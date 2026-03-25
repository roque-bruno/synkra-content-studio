"""
Salk Content Studio v2.0 — FastAPI application.

Servidor web completo para a gestora de marketing planejar e produzir conteúdo.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from content_pipeline.web.auth import (
    LoginRequest,
    authenticate,
    require_auth,
)
from content_pipeline.web.models import (
    CalendarWeek,
    ComplianceCheckRequest,
    CopyDraft,
    GenerateRequest,
    PerformanceEntry,
    PieceStageUpdate,
    ProductionPiece,
    PromptPreviewRequest,
    ReviewItem,
    VDPCreateRequest,
)
from content_pipeline.automation.copywriter import BrandCopywriter, PersonaClone
from content_pipeline.web.services import StudioService

logger = logging.getLogger(__name__)

_service: Optional[StudioService] = None


def get_service() -> StudioService:
    if _service is None:
        raise RuntimeError("Service not initialized")
    return _service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service

    config = None
    try:
        from content_pipeline.config import load_config
        config = load_config()
        _service = StudioService(config, preview_mode=False)
        logger.info("Content Studio v2.0 — MODO PRODUCAO")
    except Exception as exc:
        logger.warning("Config completa indisponível (%s) — tentando modo preview", exc)
        from content_pipeline.config import (
            GeminiConfig,
            NB2Config,
            PipelineConfig,
        )

        project_root = Path.cwd()
        for candidate in [Path.cwd()] + list(Path.cwd().parents):
            if (candidate / "docs_user").exists() or (candidate / "squads").exists():
                project_root = candidate
                break
        config = PipelineConfig(
            project_root=project_root,
            assets_dir=project_root / "docs_user",
            output_dir=project_root / "output",
            vdp_dir=project_root / "squads" / "content-production" / "output",
            logs_dir=project_root / "output" / "logs",
            gemini=GeminiConfig(api_key="preview"),
            nb2=NB2Config(),
        )
        try:
            _service = StudioService(config, preview_mode=True)
            logger.info("Content Studio v2.0 — MODO PREVIEW (sem API key)")
        except Exception as exc2:
            logger.error("Falha ao inicializar StudioService: %s", exc2)
            _service = None

    if config and _service:
        try:
            _mount_static_dirs(app, config)
        except Exception as exc:
            logger.warning("Falha ao montar diretórios estáticos: %s", exc)
    yield
    _service = None


def _mount_static_dirs(app: FastAPI, config) -> None:
    product_dir = config.product_images_dir
    if product_dir.exists():
        app.mount(
            "/assets/produtos",
            StaticFiles(directory=str(product_dir)),
            name="produtos",
        )

    logos_dir = config.assets_dir / "logomarcas"
    if not logos_dir.exists():
        logos_dir = config.assets_dir / "logos"
    if logos_dir.exists():
        app.mount(
            "/assets/logos",
            StaticFiles(directory=str(logos_dir)),
            name="logos",
        )

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/output",
        StaticFiles(directory=str(output_dir)),
        name="output",
    )


# --- App ---

app = FastAPI(
    title="Salk Content Studio",
    description="Sistema de Produção de Conteúdo v2.0 — Manager Grupo",
    version="2.0.0",
    lifespan=lifespan,
)

# Parse CORS origins from env or use defaults
_default_origins = [
    "https://studio.salk.com",
    "http://localhost:8080",
    "http://localhost:3000",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:3000",
]
_env_origins = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in _env_origins.split(",") if o.strip()] if _env_origins else _default_origins
# In production, Render sets RENDER=true
if os.getenv("RENDER"):
    allowed_origins.append("https://*.onrender.com")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (slowapi)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# =========================================================================
# ROOT & HEALTH
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve o frontend embutido (fallback para dev local)."""
    # Tenta frontend embutido (modo dev / compatibilidade)
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return JSONResponse({
        "service": "Salk Content Studio API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "frontend": "https://studio.salk.com",
    })


@app.get("/api/health")
async def health():
    if _service is None:
        return {"status": "degraded", "version": "2.0.0", "detail": "Service initializing"}
    db_backend = getattr(_service, "_db_backend", "sqlite")
    return {
        "status": "ok",
        "version": "2.0.0",
        "preview_mode": _service.preview_mode,
        "api_key_configured": not _service.preview_mode,
        "database_backend": db_backend,
        "allowed_origins": allowed_origins,
    }


# =========================================================================
# SETTINGS — Configurações e chaves API
# =========================================================================

@app.get("/api/settings")
async def get_settings(user: dict = Depends(require_auth)):
    """Retorna status de todas as configurações (valores mascarados)."""
    svc = get_service()
    return {
        "status": svc.settings.get_status(),
        "values": svc.settings.get_masked(),
        "groups": svc.settings.get_groups(),
        "definitions": svc.settings.get_definitions(),
        "preview_mode": svc.preview_mode,
    }


@app.put("/api/settings")
async def save_settings(req: Request, user: dict = Depends(require_auth)):
    """Salva configurações e recarrega clientes."""
    svc = get_service()
    data = await req.json()
    settings = data.get("settings", {})

    # Filtrar valores vazios e placeholders
    clean = {}
    for k, v in settings.items():
        if v and "•" not in v:  # ignorar valores mascarados não editados
            clean[k] = v.strip()

    if clean:
        svc.settings.set_many(clean)
        result = svc.reload_settings()
        return {
            "saved": len(clean),
            "keys_updated": list(clean.keys()),
            **result,
        }

    return {"saved": 0, "status": "no_changes"}


@app.get("/api/settings/test")
async def test_connections(user: dict = Depends(require_auth)):
    """Testa conectividade com os serviços configurados."""
    svc = get_service()
    results = {}

    # OpenRouter
    or_key = svc.settings.get("OPENROUTER_API_KEY")
    results["openrouter"] = {
        "configured": bool(or_key),
        "status": "ready" if or_key else "not_configured",
    }

    # Gemini
    gemini_key = svc.settings.get("GOOGLE_API_KEY")
    results["gemini"] = {
        "configured": bool(gemini_key),
        "status": "ready" if gemini_key else "not_configured",
    }

    # Kling
    results["kling"] = {
        "configured": svc.kling_client.configured if hasattr(svc, "kling_client") else False,
        "status": "ready" if (hasattr(svc, "kling_client") and svc.kling_client.configured) else "not_configured",
    }

    # Veo 3
    results["veo3"] = {
        "configured": svc.veo3_client.configured if hasattr(svc, "veo3_client") else False,
        "status": "ready" if (hasattr(svc, "veo3_client") and svc.veo3_client.configured) else "not_configured",
        "mode": svc.veo3_client.mode if hasattr(svc, "veo3_client") else "not_configured",
    }

    # ElevenLabs
    results["elevenlabs"] = {
        "configured": svc.tts_client.configured if hasattr(svc, "tts_client") else False,
        "status": "ready" if (hasattr(svc, "tts_client") and svc.tts_client.configured) else "not_configured",
    }

    # Database
    db_backend = getattr(svc, "_db_backend", "sqlite")
    results["database"] = {
        "configured": True,
        "status": "ready",
        "backend": db_backend,
    }

    # Publishers
    for name, pub in svc.publishers.items():
        results[name] = {
            "configured": pub.configured,
            "status": "ready" if pub.configured else "not_configured",
        }

    configured_count = sum(1 for r in results.values() if r["configured"])
    return {
        "services": results,
        "total": len(results),
        "configured": configured_count,
        "preview_mode": svc.preview_mode,
        "database_backend": db_backend,
    }


# =========================================================================
# AUTH
# =========================================================================

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    token = authenticate(req.username, req.password)
    if token is None:
        raise HTTPException(401, "Credenciais inválidas")
    return {"token": token, "username": req.username, "expires_in": 86400}


@app.get("/api/auth/me")
async def auth_me(user: dict = Depends(require_auth)):
    return {"username": user.get("sub", ""), "authenticated": True}


# =========================================================================
# DASHBOARD
# =========================================================================

@app.get("/api/dashboard")
async def dashboard(user: dict = Depends(require_auth)):
    svc = get_service()
    stats = svc.get_dashboard_stats()
    recent = svc.get_recent_log(limit=10)
    return {"stats": stats, "recent_log": recent}


# =========================================================================
# DATA FILES — Referência YAML
# =========================================================================

@app.get("/api/data/platform-specs")
async def get_platform_specs():
    return get_service().load_platform_specs()


@app.get("/api/data/buyer-personas")
async def get_buyer_personas():
    return get_service().load_buyer_personas()


@app.get("/api/data/hashtag-bank")
async def get_hashtag_bank():
    return get_service().load_hashtag_bank()


@app.get("/api/data/hashtags/{brand}")
async def get_hashtags_for_brand(brand: str, platform: str = "instagram"):
    return get_service().get_hashtags_for_brand(brand, platform)


@app.get("/api/data/editorial-template")
async def get_editorial_template():
    return get_service().load_editorial_template()


@app.get("/api/data/prohibited-terms")
async def get_prohibited_terms():
    return get_service().load_prohibited_terms()


@app.get("/api/data/brand-guidelines")
async def get_brand_guidelines():
    return get_service().load_brand_guidelines()


@app.get("/api/data/brandbooks")
async def list_brandbooks():
    return get_service().list_brandbooks()


@app.get("/api/data/brandbook/{brand}")
async def get_brandbook(brand: str):
    svc = get_service()
    bb = svc.load_brandbook(brand)
    if bb is None:
        raise HTTPException(404, f"Brandbook não encontrado: {brand}")
    return bb


# =========================================================================
# ASSETS — Produtos, logos, claims
# =========================================================================

@app.get("/api/assets/products")
async def list_products():
    return get_service().scan_product_images()


@app.get("/api/assets/logos")
async def list_logos():
    return get_service().scan_logos()


@app.get("/api/assets/claims")
async def list_claims():
    return get_service().load_claims_bank()


@app.get("/api/assets/brands")
async def get_brands():
    return get_service().load_brand_guidelines()


# =========================================================================
# VDPs
# =========================================================================

@app.get("/api/vdp")
async def list_vdps():
    return get_service().list_vdps()


@app.get("/api/vdp/detail")
async def get_vdp(path: str = Query(...)):
    svc = get_service()
    detail = svc.load_vdp(path)
    if detail is None:
        raise HTTPException(404, f"VDP não encontrado: {path}")
    return detail


@app.post("/api/vdp/create")
async def create_vdp(req: VDPCreateRequest):
    svc = get_service()
    return svc.create_vdp(req.model_dump())


@app.get("/api/vdp/presets")
async def get_presets():
    return get_service().get_presets()


@app.post("/api/vdp/preview-prompt")
async def preview_prompt(req: PromptPreviewRequest):
    svc = get_service()
    return svc.preview_prompt(
        product_type=req.product_type,
        scene_description=req.scene_description,
        lighting_preset=req.lighting_preset,
        camera_preset=req.camera_preset,
        surface_preset=req.surface_preset,
        style=req.style,
        mood=req.mood,
        is_lev=req.is_lev,
        width=req.width,
        height=req.height,
    )


# =========================================================================
# STUDIO / GENERATION
# =========================================================================

@app.post("/api/studio/generate")
@limiter.limit("10/minute")
async def generate_nb2(request: Request, req: GenerateRequest):
    svc = get_service()

    if svc.preview_mode:
        return JSONResponse(
            status_code=503,
            content={
                "error": "preview_mode",
                "message": (
                    "Modo Preview — geração desabilitada. "
                    "Configure GOOGLE_API_KEY no arquivo .env para habilitar."
                ),
            },
        )

    orchestrator = svc.orchestrator
    if orchestrator is None:
        raise HTTPException(500, "Orchestrator não inicializado")

    vdp_path = Path(req.vdp_path)
    if not vdp_path.is_absolute():
        vdp_path = svc.config.project_root / vdp_path

    try:
        result = await asyncio.to_thread(
            orchestrator.run_single,
            vdp_path,
            output_subdir=req.output_subdir,
        )
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "success": result.success,
        "produto": result.vdp.produto,
        "attempts": result.attempts,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "output_path": str(result.output_path) if result.output_path else "",
        "output_url": (
            f"/output/nb2/{req.output_subdir}/{result.output_path.name}"
            if result.output_path
            else ""
        ),
        "error": result.error or "",
    }


@app.get("/api/studio/history")
async def generation_history():
    svc = get_service()
    nb2_dir = svc.config.output_dir / "nb2"

    if not nb2_dir.exists():
        return []

    history = []
    import json

    for meta_file in sorted(nb2_dir.rglob("*.meta.json"), reverse=True):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            img_name = meta.get("output", {}).get("file", "")
            rel_path = meta_file.parent.relative_to(svc.config.output_dir)
            meta["image_url"] = f"/output/{str(rel_path).replace(chr(92), '/')}/{img_name}"
            meta["meta_file"] = meta_file.name
            history.append(meta)
        except Exception:
            continue

    return history[:50]


# =========================================================================
# PRODUCTION BOARD (Tempo) — Kanban
# =========================================================================

@app.get("/api/production/pieces")
async def list_pieces(stage: str = "", brand: str = ""):
    return get_service().list_pieces(stage=stage, brand=brand)


@app.post("/api/production/pieces")
async def create_piece(req: ProductionPiece):
    return get_service().create_piece(req.model_dump())


@app.put("/api/production/pieces/{piece_id}/stage")
async def update_piece_stage(piece_id: str, req: PieceStageUpdate):
    svc = get_service()
    result = svc.update_piece_stage(piece_id, req.stage, req.notes)
    if result is None:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    return result


@app.put("/api/production/pieces/{piece_id}")
async def update_piece(piece_id: str, req: ProductionPiece):
    svc = get_service()
    result = svc.update_piece(piece_id, req.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    return result


@app.delete("/api/production/pieces/{piece_id}")
async def delete_piece(piece_id: str):
    svc = get_service()
    if not svc.delete_piece(piece_id):
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    return {"status": "deleted"}


# =========================================================================
# COMPLIANCE (Shield)
# =========================================================================

@app.post("/api/compliance/check")
async def check_compliance(req: ComplianceCheckRequest):
    return get_service().check_compliance(req.text, req.brand, req.product)


@app.post("/api/compliance/check-prompt")
async def check_prompt_compliance(req: ComplianceCheckRequest):
    """Valida prompt NB2 contra brandbook (Design System como cabresto)."""
    svc = get_service()
    brand = req.brand or "salk"
    result = svc.brand_enforcer.validate(req.text, brand, context="prompt")
    return result.to_dict()


@app.get("/api/compliance/prompt-constraints/{brand}")
async def get_prompt_constraints(brand: str):
    """Retorna constraints do brandbook para injetar em prompts NB2."""
    svc = get_service()
    constraints = svc.brand_enforcer.get_prompt_constraints(brand)
    return {"brand": brand, "constraints": constraints}


# =========================================================================
# REVIEW QUEUE (Lens)
# =========================================================================

@app.get("/api/reviews")
async def list_reviews(verdict: str = ""):
    return get_service().list_reviews(verdict=verdict)


@app.post("/api/reviews")
async def create_review(req: ReviewItem):
    return get_service().create_review(req.model_dump())


@app.put("/api/reviews/{review_id}")
async def update_review(review_id: str, req: ReviewItem):
    svc = get_service()
    result = svc.update_review(review_id, req.verdict, req.comments)
    if result is None:
        raise HTTPException(404, f"Review não encontrado: {review_id}")
    return result


# =========================================================================
# PERFORMANCE (Pulse)
# =========================================================================

@app.get("/api/metrics")
async def list_metrics():
    return get_service().list_metrics()


@app.get("/api/metrics/summary")
async def get_metrics_summary():
    return get_service().get_performance_summary()


@app.post("/api/metrics")
async def save_metric(req: PerformanceEntry):
    return get_service().save_metric(req.model_dump())


# =========================================================================
# CALENDAR v2
# =========================================================================

@app.get("/api/calendar")
async def list_calendars():
    return get_service().list_calendars()


@app.get("/api/calendar/{week_id}")
async def get_calendar(week_id: str):
    svc = get_service()
    cal = svc.load_calendar(week_id)
    if cal is None:
        return {"week_id": week_id, "slots": []}
    return cal


@app.post("/api/calendar/{week_id}")
async def save_calendar(week_id: str, data: CalendarWeek):
    svc = get_service()
    svc.save_calendar(week_id, data.model_dump())
    return {"status": "saved", "week_id": week_id}


@app.post("/api/calendar/{week_id}/generate")
async def generate_calendar(week_id: str, brand: str = "salk"):
    svc = get_service()
    return svc.generate_calendar_from_template(week_id, brand)


# =========================================================================
# BUDGET TRACKER
# =========================================================================

@app.get("/api/budget/summary")
async def budget_summary(user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "budget_tracker") or svc.budget_tracker is None:
        return {"month": "", "total_usd": 0, "limit_usd": 349, "percentage_used": 0, "by_category": {}}
    return svc.budget_tracker.get_month_summary()


@app.get("/api/budget/daily")
async def budget_daily(user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "budget_tracker") or svc.budget_tracker is None:
        return []
    return svc.budget_tracker.get_daily_breakdown()


@app.get("/api/budget/recent")
async def budget_recent(user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "budget_tracker") or svc.budget_tracker is None:
        return []
    return svc.budget_tracker.get_recent(limit=30)


# =========================================================================
# JOURNEY LOG
# =========================================================================

@app.get("/api/journey")
async def journey_entries(
    phase: str = "", agent: str = "", result: str = "",
    limit: int = 50, user: dict = Depends(require_auth),
):
    svc = get_service()
    if not hasattr(svc, "journey_log") or svc.journey_log is None:
        return []
    return svc.journey_log.query(
        phase=phase or None, agent=agent or None,
        result=result or None, limit=limit,
    )


@app.get("/api/journey/stats")
async def journey_stats(user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "journey_log") or svc.journey_log is None:
        return {"total_entries": 0, "by_result": {}, "by_phase": {}, "by_agent": {}}
    return svc.journey_log.get_stats()


@app.get("/api/journey/piece/{piece_id}")
async def journey_piece(piece_id: str, user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "journey_log") or svc.journey_log is None:
        return []
    return svc.journey_log.get_piece_journey(piece_id)


# =========================================================================
# LLM (OpenRouter)
# =========================================================================

@app.get("/api/llm/models")
async def llm_models(user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "llm_client") or svc.llm_client is None:
        return []
    return svc.llm_client.get_available_models()


@app.get("/api/llm/usage")
async def llm_usage(user: dict = Depends(require_auth)):
    svc = get_service()
    if not hasattr(svc, "llm_client") or svc.llm_client is None:
        return {"total_calls": 0, "total_cost_usd": 0}
    return svc.llm_client.get_usage_summary()


# =========================================================================
# VIDEO PIPELINE
# =========================================================================

@app.get("/api/video/status")
async def video_status(user: dict = Depends(require_auth)):
    svc = get_service()
    return {
        "kling_configured": hasattr(svc, "kling_client") and svc.kling_client is not None and svc.kling_client.configured,
        "veo3_configured": hasattr(svc, "veo3_client") and svc.veo3_client is not None and svc.veo3_client.configured,
        "veo3_mode": svc.veo3_client.mode if hasattr(svc, "veo3_client") and svc.veo3_client else "not_configured",
        "elevenlabs_configured": hasattr(svc, "tts_client") and svc.tts_client is not None and svc.tts_client.configured,
        "ffmpeg_available": hasattr(svc, "video_assembler") and svc.video_assembler is not None and svc.video_assembler.available,
    }


# =========================================================================
# VIDEO — Veo 3 (Google DeepMind)
# =========================================================================

@app.get("/api/video/veo3/models")
async def veo3_models(user: dict = Depends(require_auth)):
    """Lista modelos Veo disponíveis."""
    from content_pipeline.video.veo3_client import Veo3Client
    return Veo3Client.list_models()


@app.post("/api/video/veo3/t2v")
@limiter.limit("10/minute")
async def veo3_text_to_video(request: Request, user: dict = Depends(require_auth)):
    """Gera vídeo a partir de texto via Veo 3."""
    svc = get_service()
    if not svc.veo3_client.configured:
        raise HTTPException(400, "Veo 3 não configurado — adicione GOOGLE_API_KEY nas configurações")
    data = await request.json()
    result = await svc.veo3_client.text_to_video(
        prompt=data.get("prompt", ""),
        duration=data.get("duration", 5),
        aspect_ratio=data.get("aspect_ratio", "9:16"),
        resolution=data.get("resolution", "720p"),
        model=data.get("model", "veo-3.0-generate-preview"),
        negative_prompt=data.get("negative_prompt", "text, watermark, logo, blurry, distorted"),
        generate_audio=data.get("generate_audio", False),
        person_generation=data.get("person_generation", "dont_allow"),
    )
    return result.to_dict()


@app.post("/api/video/veo3/i2v")
@limiter.limit("10/minute")
async def veo3_image_to_video(request: Request, user: dict = Depends(require_auth)):
    """Gera vídeo a partir de imagem via Veo 3."""
    svc = get_service()
    if not svc.veo3_client.configured:
        raise HTTPException(400, "Veo 3 não configurado — adicione GOOGLE_API_KEY nas configurações")
    data = await request.json()
    image_path = data.get("image_path", "")
    if not image_path:
        raise HTTPException(400, "image_path é obrigatório para Image-to-Video")
    result = await svc.veo3_client.image_to_video(
        image_path=image_path,
        prompt=data.get("prompt", ""),
        duration=data.get("duration", 5),
        aspect_ratio=data.get("aspect_ratio", "9:16"),
        resolution=data.get("resolution", "720p"),
        model=data.get("model", "veo-3.0-generate-preview"),
        negative_prompt=data.get("negative_prompt", "text, watermark, logo, blurry, distorted"),
        generate_audio=data.get("generate_audio", False),
        person_generation=data.get("person_generation", "dont_allow"),
    )
    return result.to_dict()


# =========================================================================
# AUTOMATION — Auto-Briefing (Atlas)
# =========================================================================

@app.post("/api/automation/briefing")
@limiter.limit("10/minute")
async def generate_briefing(request: Request, user: dict = Depends(require_auth)):
    """Gera briefing automatico para um slot do calendario."""
    svc = get_service()
    data = await request.json()
    result = await svc.auto_briefing.generate(
        brand=data.get("brand", "salk"),
        platform=data.get("platform", "instagram"),
        pillar=data.get("pillar", "produto"),
        product=data.get("product", ""),
        persona=data.get("persona", ""),
        day=data.get("day", ""),
        context=data.get("context", ""),
    )
    return result


@app.post("/api/automation/briefing/batch")
async def generate_briefing_batch(req: Request, user: dict = Depends(require_auth)):
    """Gera briefings para multiplos slots."""
    svc = get_service()
    data = await req.json()
    slots = data.get("slots", [])
    results = await svc.auto_briefing.generate_batch(slots)
    return {"count": len(results), "briefings": results}


@app.post("/api/automation/briefing/smart")
@limiter.limit("10/minute")
async def generate_smart_briefing(request: Request, user: dict = Depends(require_auth)):
    """Gera briefing inteligente usando dados de performance anteriores (self-learning)."""
    svc = get_service()
    data = await request.json()
    result = await svc.generate_smart_briefing(
        brand=data.get("brand", "salk"),
        platform=data.get("platform", "instagram"),
        pillar=data.get("pillar", "produto"),
        product=data.get("product", ""),
        persona=data.get("persona", ""),
        day=data.get("day", ""),
    )
    return result


# =========================================================================
# AUTOMATION — Copywriter (Squad)
# =========================================================================

@app.post("/api/automation/copy/write")
@limiter.limit("10/minute")
async def write_copy(request: Request, user: dict = Depends(require_auth)):
    """Gera copy com copywriter especializado da marca."""
    svc = get_service()
    data = await request.json()
    brand = data.get("brand", "salk")
    cw = BrandCopywriter(svc.llm_client, brand=brand)
    result = await cw.write_copy(
        briefing=data.get("briefing", ""),
        platform=data.get("platform", "instagram"),
        format_type=data.get("format_type", "post"),
        max_chars=data.get("max_chars", 2200),
    )
    return result


@app.post("/api/automation/copy/rewrite")
async def rewrite_copy(req: Request, user: dict = Depends(require_auth)):
    """Reescreve copy com feedback."""
    svc = get_service()
    data = await req.json()
    brand = data.get("brand", "salk")
    cw = BrandCopywriter(svc.llm_client, brand=brand)
    result = await cw.rewrite(
        original=data.get("original", ""),
        feedback=data.get("feedback", ""),
    )
    return result


@app.get("/api/automation/copy/copywriters")
async def list_copywriters():
    """Lista copywriters disponiveis por marca."""
    from content_pipeline.automation.copywriter import BRAND_COPYWRITERS
    return {k: {"name": v["name"]} for k, v in BRAND_COPYWRITERS.items()}


# =========================================================================
# AUTOMATION — Persona Clones (Teste de Copy)
# =========================================================================

@app.post("/api/automation/persona/evaluate")
async def persona_evaluate(req: Request, user: dict = Depends(require_auth)):
    """Avalia copy do ponto de vista de uma buyer persona."""
    svc = get_service()
    data = await req.json()
    persona_id = data.get("persona_id", "eng_clinica")
    clone = PersonaClone(svc.llm_client, persona_id=persona_id)
    result = await clone.evaluate(
        copy_text=data.get("copy_text", ""),
        brand=data.get("brand", "salk"),
    )
    return result


@app.get("/api/automation/persona/list")
async def list_personas():
    """Lista personas disponiveis para teste."""
    return PersonaClone.list_personas()


# =========================================================================
# AUTOMATION — Auto-Prompt NB2 (Apex)
# =========================================================================

@app.post("/api/automation/prompt/generate")
@limiter.limit("10/minute")
async def generate_prompt(request: Request, user: dict = Depends(require_auth)):
    """Gera prompt NB2 com arquitetura de 8 dimensoes."""
    svc = get_service()
    data = await request.json()
    result = await svc.auto_prompt.generate_prompt(
        product=data.get("product", "lev"),
        brand=data.get("brand", "salk"),
        concept=data.get("concept", ""),
        technique=data.get("technique", "dramatic_studio"),
        lighting=data.get("lighting", "dramatic_rim"),
        scene=data.get("scene", "studio_neutro"),
        composition=data.get("composition", "central_hero"),
        atmosphere=data.get("atmosphere", "premium_tech"),
        format_type=data.get("format_type", "square_social"),
        custom_notes=data.get("custom_notes", ""),
    )
    return result


@app.post("/api/automation/prompt/generate-creative")
async def generate_creative_prompt(req: Request, user: dict = Depends(require_auth)):
    """Gera prompt NB2 criativo via LLM dentro das restricoes."""
    svc = get_service()
    data = await req.json()
    result = await svc.auto_prompt.generate_with_llm(
        product=data.get("product", "lev"),
        brand=data.get("brand", "salk"),
        concept=data.get("concept", ""),
        format_type=data.get("format_type", "square_social"),
    )
    return result


@app.get("/api/automation/prompt/dimensions")
async def list_prompt_dimensions():
    """Lista dimensoes e opcoes do auto-prompt."""
    from content_pipeline.automation.auto_prompt import AutoPromptNB2
    return {
        "dimensions": AutoPromptNB2.list_dimensions(),
        "products": AutoPromptNB2.list_products(),
    }


# =========================================================================
# AUTOMATION — Disaster Check (Quality Gate Visual)
# =========================================================================

@app.post("/api/automation/disaster-check")
async def disaster_check(req: Request, user: dict = Depends(require_auth)):
    """Executa disaster check em imagem gerada."""
    svc = get_service()
    data = await req.json()
    result = await svc.disaster_check.check_image(
        image_path=data.get("image_path", ""),
        product=data.get("product", ""),
        brand=data.get("brand", "salk"),
        format_target=data.get("format_target", "square_social"),
        manual_overrides=data.get("manual_overrides"),
    )
    return result.to_dict()


@app.post("/api/automation/disaster-check/batch")
async def disaster_check_batch(req: Request, user: dict = Depends(require_auth)):
    """Disaster check em batch."""
    svc = get_service()
    data = await req.json()
    items = data.get("items", [])
    results = await svc.disaster_check.check_batch(items)
    return {"count": len(results), "results": results}


@app.get("/api/automation/disaster-check/checklist")
async def disaster_checklist():
    """Retorna checklist completo do disaster check."""
    from content_pipeline.automation.disaster_check import DisasterCheck
    return DisasterCheck.get_checklist()


# =========================================================================
# AUTOMATION — Atomizacao Semantica (Nova)
# =========================================================================

@app.post("/api/automation/atomize")
async def atomize_content(req: Request, user: dict = Depends(require_auth)):
    """Atomiza conteudo master em derivativos por plataforma."""
    svc = get_service()
    data = await req.json()
    result = await svc.atomizer.atomize(
        master_content=data.get("master_content", ""),
        master_type=data.get("master_type", "post_unico"),
        brand=data.get("brand", "salk"),
        target_platforms=data.get("target_platforms"),
        context=data.get("context", ""),
    )
    return result


@app.post("/api/automation/atomize/suggest")
async def suggest_derivatives(req: Request):
    """Sugere derivativos possiveis para um tipo de master."""
    svc = get_service()
    data = await req.json()
    result = await svc.atomizer.suggest_derivatives(
        master_type=data.get("master_type", "post_unico"),
    )
    return result


@app.get("/api/automation/atomize/platforms")
async def list_atomize_platforms():
    """Lista plataformas e formatos disponiveis."""
    from content_pipeline.automation.atomizer import SemanticAtomizer
    return {
        "master_types": SemanticAtomizer.list_master_types(),
        "platforms": SemanticAtomizer.list_platforms(),
    }


# =========================================================================
# PUBLISHERS — Publicacao em redes sociais
# =========================================================================

@app.post("/api/publish/{platform}")
async def publish_content(platform: str, req: Request, user: dict = Depends(require_auth)):
    """Publica conteudo em uma plataforma especifica."""
    svc = get_service()
    publisher = svc.publishers.get(platform)
    if publisher is None:
        raise HTTPException(404, f"Plataforma nao encontrada: {platform}")
    data = await req.json()
    result = await publisher.publish(
        content=data.get("content", ""),
        media_paths=data.get("media_paths"),
        media_urls=data.get("media_urls"),
        schedule_time=data.get("schedule_time"),
        **{k: v for k, v in data.items() if k not in ("content", "media_paths", "media_urls", "schedule_time")},
    )
    return result.to_dict()


@app.get("/api/publish/status")
async def publishers_status(user: dict = Depends(require_auth)):
    """Status de todos os publishers."""
    svc = get_service()
    return {
        name: {"configured": pub.configured, "preview_mode": pub.preview_mode}
        for name, pub in svc.publishers.items()
    }


# =========================================================================
# METRICS COLLECTOR — Coleta automatica
# =========================================================================

@app.post("/api/metrics/collect")
async def collect_metrics(user: dict = Depends(require_auth)):
    """Coleta metricas de todos os posts pendentes (48h+)."""
    svc = get_service()
    result = await svc.metrics_collector.collect_pending()
    return result


@app.post("/api/metrics/collect/{platform}/{post_id}")
async def collect_single_metrics(platform: str, post_id: str, user: dict = Depends(require_auth)):
    """Coleta metricas de um post especifico."""
    svc = get_service()
    result = await svc.metrics_collector.collect_single(platform, post_id)
    return result


@app.get("/api/metrics/collector-status")
async def collector_status(user: dict = Depends(require_auth)):
    """Status do coletor de metricas."""
    svc = get_service()
    return svc.metrics_collector.get_collection_status()


# =========================================================================
# BATCH APPROVAL — Aprovacao em lote
# =========================================================================

@app.get("/api/approval/pending")
async def get_pending_approval(
    week_id: str = "", brand: str = "", user: dict = Depends(require_auth),
):
    """Lista pecas pendentes de aprovacao."""
    svc = get_service()
    return svc.batch_approval.get_pending_batch(week_id=week_id, brand=brand)


@app.post("/api/approval/approve")
async def approve_batch(req: Request, user: dict = Depends(require_auth)):
    """Aprova multiplas pecas de uma vez."""
    svc = get_service()
    data = await req.json()
    return svc.batch_approval.approve_batch(
        piece_ids=data.get("piece_ids", []),
        approver=user.get("sub", "gestora"),
        notes=data.get("notes", ""),
    )


@app.post("/api/approval/reject")
async def reject_pieces(req: Request, user: dict = Depends(require_auth)):
    """Rejeita pecas individuais com feedback."""
    svc = get_service()
    data = await req.json()
    return svc.batch_approval.reject_pieces(
        rejections=data.get("rejections", []),
        reviewer=user.get("sub", "gestora"),
    )


@app.get("/api/approval/summary")
async def approval_summary(week_id: str = "", user: dict = Depends(require_auth)):
    """Resumo de aprovacoes."""
    svc = get_service()
    return svc.batch_approval.get_approval_summary(week_id=week_id)


# =========================================================================
# FEEDBACK LOOP — Performance → Briefings
# =========================================================================

@app.get("/api/feedback/analysis")
async def feedback_analysis(brand: str = "", user: dict = Depends(require_auth)):
    """Analisa performance e gera insights."""
    svc = get_service()
    return svc.feedback_loop.analyze_performance(brand=brand)


@app.get("/api/feedback/recommendations")
async def feedback_recommendations(brand: str = "salk", user: dict = Depends(require_auth)):
    """Recomendacoes para proximos briefings baseado em dados."""
    svc = get_service()
    return svc.feedback_loop.get_briefing_recommendations(brand=brand)


# =========================================================================
# REPORT — Relatorio semanal
# =========================================================================

@app.get("/api/report/weekly")
async def weekly_report_data(
    week_id: str = "", brand: str = "", user: dict = Depends(require_auth),
):
    """Dados do relatorio semanal (JSON)."""
    svc = get_service()
    return svc.weekly_report.generate(week_id=week_id, brand=brand)


@app.get("/api/report/weekly/html", response_class=HTMLResponse)
async def weekly_report_html(
    week_id: str = "", brand: str = "", user: dict = Depends(require_auth),
):
    """Relatorio semanal em HTML (pode ser impresso como PDF)."""
    svc = get_service()
    html = svc.weekly_report.generate_html(week_id=week_id, brand=brand)
    return HTMLResponse(html)


# =========================================================================
# FRONTEND STATIC FILES (SPA) — Render single-service deployment
# =========================================================================

# Serve frontend static files if the built frontend directory exists.
# API routes above take precedence; this catch-all handles SPA client-side routing.
frontend_dir = None
_candidates = [
    Path("/app/frontend"),  # Docker container layout
    Path(__file__).parent.parent.parent.parent.parent / "content-studio-frontend",
    Path.cwd() / "frontend",
    Path.cwd() / "packages" / "content-studio-frontend",
    Path.cwd().parent / "content-studio-frontend",
]
for _c in _candidates:
    if _c.exists():
        frontend_dir = _c
        break

if frontend_dir and frontend_dir.exists():
    logger.info("Frontend found at %s — mounting static files", frontend_dir)
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    logger.info("No frontend directory found — API-only mode")


# =========================================================================
# MODULE EXECUTION
# =========================================================================

def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn

    print(f"\n  Salk Content Studio v2.0")
    print(f"  http://{host}:{port}")
    print(f"  Ctrl+C para parar\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
