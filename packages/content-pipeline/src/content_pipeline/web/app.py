"""
Salk Content Studio v2.0 — FastAPI application.

Servidor web completo para a gestora de marketing planejar e produzir conteúdo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.gzip import GZipMiddleware

from content_pipeline.web.settings_store import SettingsStore

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
    ReviewUpdate,
    VDPCreateRequest,
)
from content_pipeline.automation.copywriter import BrandCopywriter, PersonaClone
from content_pipeline.web.services import StudioService

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("content-studio")

_service: Optional[StudioService] = None


def get_service() -> StudioService:
    if _service is None:
        raise RuntimeError("Service not initialized")
    return _service


# Notification & Activity Log store
notifications_store: list = []
activity_log_store: list = []
notification_id_counter: int = 0
activity_id_counter: int = 0


def _create_notification(title: str, message: str, category: str = "info", piece_id: str = None):
    """Create a notification and store it."""
    global notification_id_counter
    notification_id_counter += 1
    notif = {
        "id": notification_id_counter,
        "title": title,
        "message": message,
        "category": category,  # info, success, warning, error, review, publish
        "piece_id": piece_id,
        "read": False,
        "created_at": datetime.now().isoformat(),
    }
    notifications_store.insert(0, notif)
    # Keep max 200 notifications
    if len(notifications_store) > 200:
        notifications_store[:] = notifications_store[:200]
    return notif


def _log_activity(action: str, details: str, actor: str = "system", piece_id: str = None):
    """Log an activity."""
    global activity_id_counter
    activity_id_counter += 1
    entry = {
        "id": activity_id_counter,
        "action": action,
        "details": details,
        "actor": actor,
        "piece_id": piece_id,
        "timestamp": datetime.now().isoformat(),
    }
    activity_log_store.insert(0, entry)
    if len(activity_log_store) > 500:
        activity_log_store[:] = activity_log_store[:500]
    return entry


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _service

    config = None
    try:
        # Pre-load settings store and apply to env BEFORE load_config
        # This ensures API keys saved via UI are available as env vars
        _pre_root = Path.cwd()
        for _c in [Path.cwd()] + list(Path.cwd().parents):
            if (_c / "docs_user").exists() or (_c / "squads").exists():
                _pre_root = _c
                break
        _pre_store = SettingsStore(_pre_root / "output" / "studio")
        _pre_store.apply_to_env()
        logger.info("Pre-loaded %d settings from store", len(_pre_store._cache))

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

    # Startup diagnostics
    app.state.start_time = time.time()
    logger.info("Salk Content Studio v2.0 starting...")
    logger.info(f"Static files: {os.path.exists(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))}")
    if _service and hasattr(_service, 'settings'):
        configured = sum(1 for k in ["OPENROUTER_API_KEY", "FAL_API_KEY", "ELEVENLABS_API_KEY"] if _service.settings.get(k))
        logger.info(f"API keys configured: {configured}/3")
    logger.info("Server ready.")

    yield
    _service = None



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
    render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
    if render_hostname:
        allowed_origins.append(f"https://{render_hostname}")
    allowed_origins.append("https://studio.salkmedical.com")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip compression for responses >= 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Rate limiting (slowapi)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Track server start time
app.state.start_time = time.time()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    if not request.url.path.startswith(("/static", "/assets", "/output")):
        logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.3f}s)")
    return response


# --- Mount static asset directories (must be at module level, not in lifespan) ---
_project_root = Path.cwd()
for _candidate in [Path.cwd()] + list(Path.cwd().parents):
    if (_candidate / "docs_user").exists() or (_candidate / "squads").exists():
        _project_root = _candidate
        break

logger.info("Project root: %s", _project_root)

_product_dir = _project_root / "docs_user" / "imagem_produtos"
if _product_dir.exists():
    app.mount("/assets/produtos", StaticFiles(directory=str(_product_dir)), name="produtos")
    logger.info("Mounted /assets/produtos → %s (%d categories)", _product_dir, len(list(_product_dir.iterdir())))
else:
    logger.warning("Product images dir NOT FOUND: %s", _product_dir)

_logos_dir = _project_root / "docs_user" / "logomarcas"
if not _logos_dir.exists():
    _logos_dir = _project_root / "docs_user" / "logos"
if _logos_dir.exists():
    app.mount("/assets/logos", StaticFiles(directory=str(_logos_dir)), name="logos")
    logger.info("Mounted /assets/logos → %s", _logos_dir)
else:
    logger.warning("Logos dir NOT FOUND: %s", _logos_dir)

_output_dir = _project_root / "output"
_output_dir.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(_output_dir)), name="output")


# --- Thumbnail generation endpoint ---
_thumbs_dir = _output_dir / "thumbs"
_thumbs_dir.mkdir(parents=True, exist_ok=True)


def _generate_thumbnail_sync(original: Path, thumb_path: Path, w: int) -> None:
    """Generate thumbnail — runs in thread pool to avoid blocking event loop."""
    from PIL import Image
    with Image.open(original) as im:
        ratio = w / im.width
        new_h = max(1, int(im.height * ratio))
        im_resized = im.resize((w, new_h), Image.LANCZOS)
        if im_resized.mode in ("RGBA", "P"):
            im_resized.save(str(thumb_path), "PNG", optimize=True)
        else:
            im_resized.save(str(thumb_path), "JPEG", quality=80, optimize=True)


@app.get("/api/assets/thumb/{category}/{filename}")
async def serve_thumbnail(category: str, filename: str, w: int = 200):
    """Generate and serve cached thumbnail for product images."""
    import asyncio
    from starlette.responses import FileResponse
    w = max(32, min(w, 800))
    thumb_subdir = _thumbs_dir / f"w{w}" / category
    thumb_subdir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_subdir / filename
    if not thumb_path.exists():
        original = _project_root / "docs_user" / "imagem_produtos" / category / filename
        if not original.exists():
            raise HTTPException(404, "Imagem não encontrada")
        try:
            await asyncio.to_thread(_generate_thumbnail_sync, original, thumb_path, w)
        except Exception as e:
            logger.warning("Thumbnail generation failed for %s/%s: %s", category, filename, e)
            return FileResponse(str(original))
    content_type = "image/png" if filename.lower().endswith(".png") else "image/jpeg"
    return FileResponse(str(thumb_path), media_type=content_type,
                        headers={"Cache-Control": "public, max-age=604800"})


# --- Fallback asset serving via API route (if StaticFiles mount failed at startup) ---
@app.get("/assets/produtos/{category}/{filename}")
async def serve_product_image(category: str, filename: str):
    """Fallback: serve product images if StaticFiles mount didn't happen."""
    file_path = _project_root / "docs_user" / "imagem_produtos" / category / filename
    if not file_path.exists():
        raise HTTPException(404, "Imagem não encontrada")
    from starlette.responses import FileResponse
    return FileResponse(str(file_path),
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/assets/logos/{brand}/{filename}")
async def serve_logo_image(brand: str, filename: str):
    """Fallback: serve logo images if StaticFiles mount didn't happen."""
    for logos_base in [_project_root / "docs_user" / "logomarcas", _project_root / "docs_user" / "logos"]:
        file_path = logos_base / brand / filename
        if file_path.exists():
            from starlette.responses import FileResponse
            return FileResponse(str(file_path))
    raise HTTPException(404, "Logo não encontrado")


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    detail = str(exc) if os.getenv("STUDIO_DEBUG") else "Internal server error"
    return JSONResponse(
        status_code=500,
        content={"detail": detail, "type": type(exc).__name__},
    )


# =========================================================================
# ROOT & HEALTH
# =========================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve o frontend (volume mount prioritario, embedded fallback)."""
    # Prioridade: volume mount > embedded
    candidates = [
        Path("/app/frontend") / "index.html",
        Path(__file__).parent / "static" / "index.html",
    ]
    for html_path in candidates:
        if html_path.exists():
            return HTMLResponse(
                html_path.read_text(encoding="utf-8"),
                headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
            )
    return JSONResponse({
        "service": "Salk Content Studio API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
    })


@app.get("/api/health")
async def health():
    """Comprehensive health check."""
    checks = {}

    # Service status
    if _service is None:
        return {
            "status": "degraded",
            "checks": {"service": False},
            "detail": "Service initializing",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
        }

    # Check API keys via service settings
    api_keys = {
        "OPENROUTER_API_KEY": bool(_service.settings.get("OPENROUTER_API_KEY")),
        "FAL_API_KEY": bool(_service.settings.get("FAL_API_KEY")),
        "ELEVENLABS_API_KEY": bool(_service.settings.get("ELEVENLABS_API_KEY")),
        "MINIMAX_API_KEY": bool(_service.settings.get("MINIMAX_API_KEY")),
    }
    checks["api_keys"] = api_keys
    checks["api_keys_configured"] = sum(1 for v in api_keys.values() if v)

    # Check data files
    import pathlib
    data_dir = pathlib.Path(__file__).parent.parent.parent.parent.parent / "squads" / "content-production" / "data"
    data_files_ok = data_dir.exists()
    checks["data_directory"] = str(data_dir)
    checks["data_directory_exists"] = data_files_ok

    # System info
    import sys
    checks["version"] = "2.0.0"
    checks["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks["uptime_seconds"] = round(time.time() - app.state.start_time, 1) if hasattr(app.state, 'start_time') else 0
    checks["notifications_count"] = len(notifications_store)
    checks["pieces_count"] = len(_service.pieces) if hasattr(_service, 'pieces') else 0
    checks["preview_mode"] = _service.preview_mode
    checks["database_backend"] = getattr(_service, "_db_backend", "sqlite")

    overall = "healthy" if checks["api_keys_configured"] >= 1 and data_files_ok else "degraded"

    return {
        "status": overall,
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
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

    # --- Geração de Imagem ---
    fal_key = svc.settings.get("FAL_API_KEY")
    results["fal.ai (NB2)"] = {
        "configured": bool(fal_key),
        "status": "ready" if fal_key else "not_configured",
    }

    gemini_key = svc.settings.get("GOOGLE_API_KEY")
    results["gemini"] = {
        "configured": bool(gemini_key),
        "status": "ready" if gemini_key else "not_configured",
    }

    # --- LLM ---
    or_key = svc.settings.get("OPENROUTER_API_KEY")
    results["openrouter"] = {
        "configured": bool(or_key),
        "status": "ready" if or_key else "not_configured",
    }

    # --- Video & Animação ---
    grok_key = svc.settings.get("GROK_API_KEY")
    results["grok"] = {
        "configured": bool(grok_key),
        "status": "ready" if grok_key else "not_configured",
    }

    minimax_key = svc.settings.get("MINIMAX_API_KEY")
    results["minimax"] = {
        "configured": bool(minimax_key),
        "status": "ready" if minimax_key else "not_configured",
    }

    pika_key = svc.settings.get("PIKA_API_KEY")
    results["pika"] = {
        "configured": bool(pika_key),
        "status": "ready" if pika_key else "not_configured",
    }

    runway_key = svc.settings.get("RUNWAY_API_KEY")
    results["runway"] = {
        "configured": bool(runway_key),
        "status": "ready" if runway_key else "not_configured",
    }

    results["kling"] = {
        "configured": svc.kling_client.configured if hasattr(svc, "kling_client") else False,
        "status": "ready" if (hasattr(svc, "kling_client") and svc.kling_client.configured) else "not_configured",
    }

    results["veo3"] = {
        "configured": svc.veo3_client.configured if hasattr(svc, "veo3_client") else False,
        "status": "ready" if (hasattr(svc, "veo3_client") and svc.veo3_client.configured) else "not_configured",
        "mode": svc.veo3_client.mode if hasattr(svc, "veo3_client") else "not_configured",
    }

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


@app.get("/api/settings/test/{platform}")
async def test_platform_connection(platform: str, user: dict = Depends(require_auth)):
    """Teste real de conexao com uma plataforma especifica (Story 6.4)."""
    import httpx

    svc = get_service()
    start = time.time()
    timeout = 10.0

    platform_tests = {
        "instagram": {
            "key_name": "INSTAGRAM_ACCESS_TOKEN",
            "url": "https://graph.instagram.com/me",
            "params_fn": lambda key: {"access_token": key},
            "headers_fn": lambda key: {},
        },
        "facebook": {
            "key_name": "FACEBOOK_ACCESS_TOKEN",
            "url": "https://graph.facebook.com/me",
            "params_fn": lambda key: {"access_token": key},
            "headers_fn": lambda key: {},
        },
        "linkedin": {
            "key_name": "LINKEDIN_ACCESS_TOKEN",
            "url": "https://api.linkedin.com/v2/me",
            "params_fn": lambda key: {},
            "headers_fn": lambda key: {"Authorization": f"Bearer {key}"},
        },
        "youtube": {
            "key_name": "YOUTUBE_API_KEY",
            "url": "https://www.googleapis.com/youtube/v3/channels",
            "params_fn": lambda key: {"mine": "true", "part": "id", "key": key},
            "headers_fn": lambda key: {},
        },
    }

    test_config = platform_tests.get(platform)
    if not test_config:
        raise HTTPException(404, f"Plataforma desconhecida: {platform}")

    api_key = svc.settings.get(test_config["key_name"]) or os.environ.get(test_config["key_name"], "")
    if not api_key:
        return {
            "ok": False,
            "error": f"Chave {test_config['key_name']} nao configurada",
            "latency_ms": 0,
            "platform": platform,
        }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                test_config["url"],
                params=test_config["params_fn"](api_key),
                headers=test_config["headers_fn"](api_key),
            )
        latency = int((time.time() - start) * 1000)
        if resp.status_code < 400:
            return {"ok": True, "error": None, "latency_ms": latency, "platform": platform}
        else:
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                "latency_ms": latency,
                "platform": platform,
            }
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return {"ok": False, "error": str(e)[:200], "latency_ms": latency, "platform": platform}


# =========================================================================
# INTEGRATIONS CRUD (Story 7.2) — API keys configuráveis via UI
# =========================================================================

INTEGRATION_PLATFORMS = {
    "instagram": "INSTAGRAM_ACCESS_TOKEN",
    "facebook": "FACEBOOK_ACCESS_TOKEN",
    "linkedin": "LINKEDIN_ACCESS_TOKEN",
    "youtube": "YOUTUBE_ACCESS_TOKEN",
}

PLATFORM_LABELS = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "youtube": "YouTube",
}

PLATFORM_EXTRA_FIELDS = {
    "instagram": ["page_id"],
    "facebook": ["page_id"],
    "linkedin": ["org_id"],
    "youtube": ["channel_id"],
}


def _mask_key(key: str | None) -> str | None:
    """Mask API key: ****last4."""
    if not key:
        return None
    return "****" + key[-4:] if len(key) > 4 else "****"


@app.get("/api/settings/integrations")
async def get_integrations(user: dict = Depends(require_auth)):
    """Lista todas as integracoes com keys mascaradas (Story 7.2)."""
    svc = get_service()
    integrations = {}
    for plat, env_key in INTEGRATION_PLATFORMS.items():
        raw_key = svc.settings.get(env_key)
        integrations[plat] = {
            "label": PLATFORM_LABELS[plat],
            "configured": bool(raw_key),
            "key_masked": _mask_key(raw_key) if raw_key else None,
            "status": "configured" if raw_key else "not_configured",
            "extra_fields": PLATFORM_EXTRA_FIELDS.get(plat, []),
        }
        for field in PLATFORM_EXTRA_FIELDS.get(plat, []):
            integrations[plat][field] = svc.settings.get(f"{plat.upper()}_{field.upper()}", "")
    return {"integrations": integrations}


@app.put("/api/settings/integrations/{platform}")
async def save_integration(platform: str, req: Request, user: dict = Depends(require_auth)):
    """Salva/atualiza credenciais de uma plataforma (Story 7.2)."""
    if platform not in INTEGRATION_PLATFORMS:
        raise HTTPException(404, f"Plataforma desconhecida: {platform}")

    svc = get_service()
    data = await req.json()
    api_key = data.get("api_key", "").strip()
    extra = data.get("extra", {})

    if not api_key:
        raise HTTPException(422, "API key nao pode ser vazia")

    # Save main key
    settings_to_save = {INTEGRATION_PLATFORMS[platform]: api_key}

    # Save extra fields
    for field in PLATFORM_EXTRA_FIELDS.get(platform, []):
        if field in extra and extra[field]:
            settings_to_save[f"{platform.upper()}_{field.upper()}"] = str(extra[field]).strip()

    svc.settings.set_many(settings_to_save)
    svc.reload_settings()

    return {
        "ok": True,
        "platform": platform,
        "status": "saved",
        "key_masked": _mask_key(api_key),
    }


@app.delete("/api/settings/integrations/{platform}")
async def delete_integration(platform: str, user: dict = Depends(require_auth)):
    """Remove credenciais de uma plataforma (Story 7.2)."""
    if platform not in INTEGRATION_PLATFORMS:
        raise HTTPException(404, f"Plataforma desconhecida: {platform}")

    svc = get_service()
    env_key = INTEGRATION_PLATFORMS[platform]

    # Remove from store
    svc.settings.set(env_key, "")
    for field in PLATFORM_EXTRA_FIELDS.get(platform, []):
        svc.settings.set(f"{platform.upper()}_{field.upper()}", "")

    svc.settings._save()
    svc.reload_settings()

    return {"ok": True, "platform": platform, "status": "removed"}


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
    """Retorna dict completo de personas (com chaves) para edição."""
    svc = get_service()
    full = svc.load_buyer_personas_full()
    if isinstance(full, dict) and "personas" in full:
        return full["personas"]
    return svc.load_buyer_personas()


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
# DATA — Endpoints de ESCRITA (PUT) para edição via UI
# =========================================================================

@app.put("/api/data/platform-specs")
async def save_platform_specs(request: Request):
    data = await request.json()
    get_service().save_platform_specs(data)
    return {"ok": True, "message": "Platform specs atualizados"}


@app.put("/api/data/buyer-personas")
async def save_buyer_personas(request: Request):
    data = await request.json()
    get_service().save_buyer_personas(data)
    return {"ok": True, "message": "Buyer personas atualizados — pipeline re-calibrado"}


@app.put("/api/data/hashtag-bank")
async def save_hashtag_bank(request: Request):
    data = await request.json()
    get_service().save_hashtag_bank(data)
    return {"ok": True, "message": "Banco de hashtags atualizado"}


@app.put("/api/data/editorial-template")
async def save_editorial_template(request: Request):
    data = await request.json()
    get_service().save_editorial_template(data)
    return {"ok": True, "message": "Template editorial atualizado"}


@app.put("/api/data/prohibited-terms")
async def save_prohibited_terms(request: Request):
    data = await request.json()
    get_service().save_prohibited_terms(data)
    return {"ok": True, "message": "Termos proibidos atualizados — compliance re-calibrado"}


@app.put("/api/data/brand-guidelines")
async def save_brand_guidelines(request: Request):
    data = await request.json()
    get_service().save_brand_guidelines(data)
    return {"ok": True, "message": "Diretrizes de marca atualizadas"}


@app.put("/api/data/brandbook/{brand}")
async def save_brandbook(brand: str, request: Request):
    data = await request.json()
    get_service().save_brandbook(brand, data)
    return {"ok": True, "message": f"Brandbook '{brand}' atualizado — prompts re-calibrados"}


@app.put("/api/data/claims-bank")
async def save_claims_bank(request: Request):
    data = await request.json()
    get_service().save_claims_bank(data)
    return {"ok": True, "message": "Claims bank atualizado"}


@app.get("/api/data/copywriter-config")
async def get_copywriter_config():
    return get_service().load_copywriter_config()


@app.put("/api/data/copywriter-config")
async def save_copywriter_config(request: Request):
    data = await request.json()
    get_service().save_copywriter_config(data)
    return {"ok": True, "message": "Copywriter config atualizado — prompts de copy re-calibrados"}


@app.get("/api/data/image-generation-config")
async def get_image_generation_config():
    return get_service().load_image_generation_config()


@app.put("/api/data/image-generation-config")
async def save_image_generation_config(request: Request):
    data = await request.json()
    get_service().save_image_generation_config(data)
    return {"ok": True, "message": "Image generation config atualizado — prompts NB2 re-calibrados"}


@app.get("/api/data/content-strategy-config")
async def get_content_strategy_config():
    return get_service().load_content_strategy_config()


@app.put("/api/data/content-strategy-config")
async def save_content_strategy_config(request: Request):
    data = await request.json()
    get_service().save_content_strategy_config(data)
    return {"ok": True, "message": "Content strategy config atualizado — orquestrador re-calibrado"}


@app.get("/api/data/atomization-config")
async def get_atomization_config():
    return get_service().load_atomization_config()


@app.put("/api/data/atomization-config")
async def save_atomization_config(request: Request):
    data = await request.json()
    get_service().save_atomization_config(data)
    return {"ok": True, "message": "Atomization config atualizado — derivativos re-calibrados"}


@app.get("/api/data/disaster-check-config")
async def get_disaster_check_config():
    return get_service().load_disaster_check_config()


@app.put("/api/data/disaster-check-config")
async def save_disaster_check_config(request: Request):
    data = await request.json()
    get_service().save_disaster_check_config(data)
    return {"ok": True, "message": "Disaster check config atualizado — quality gate re-calibrado"}


@app.get("/api/data/briefing-config")
async def get_briefing_config():
    return get_service().load_briefing_config()


@app.put("/api/data/briefing-config")
async def save_briefing_config(request: Request):
    data = await request.json()
    get_service().save_briefing_config(data)
    return {"ok": True, "message": "Briefing config atualizado — Atlas re-calibrado"}


@app.post("/api/data/invalidate-cache")
async def invalidate_all_caches():
    get_service().invalidate_all_caches()
    return {"ok": True, "message": "Todos os caches invalidados — dados recarregados do disco"}


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


@app.post("/api/uploads")
async def upload_file(file: UploadFile = File(...), purpose: str = Query("reference"), user: dict = Depends(require_auth)):
    """Upload a reference file (image/video) for use in content generation."""
    allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm"}
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in allowed_ext:
        raise HTTPException(400, f"Tipo de arquivo nao suportado: {ext}. Permitidos: {', '.join(allowed_ext)}")
    max_size = 50 * 1024 * 1024  # 50MB
    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(400, "Arquivo excede o limite de 50MB")

    upload_dir = _project_root / "output" / "uploads" / purpose
    upload_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest = upload_dir / safe_name
    dest.write_bytes(contents)

    url = f"/output/uploads/{purpose}/{safe_name}"
    size_kb = round(len(contents) / 1024, 1)
    return {"url": url, "path": str(dest), "name": file.filename, "size_kb": size_kb, "purpose": purpose}


@app.get("/api/uploads")
async def list_uploads(purpose: str = Query("")):
    """List uploaded reference files."""
    base = _project_root / "output" / "uploads"
    if not base.exists():
        return []
    results = []
    search_dirs = [base / purpose] if purpose else [d for d in base.iterdir() if d.is_dir()]
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm"}:
                results.append({
                    "url": f"/output/uploads/{d.name}/{f.name}",
                    "path": str(f),
                    "name": f.name,
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "purpose": d.name,
                    "is_video": f.suffix.lower() in {".mp4", ".mov", ".webm"},
                })
    return results


@app.delete("/api/uploads/{purpose}/{filename}")
async def delete_upload(purpose: str, filename: str, user: dict = Depends(require_auth)):
    """Delete an uploaded file."""
    # Check path traversal FIRST
    if ".." in purpose or ".." in filename:
        raise HTTPException(400, "Caminho invalido")
    file_path = _project_root / "output" / "uploads" / purpose / filename
    if not file_path.exists():
        raise HTTPException(404, "Arquivo nao encontrado")
    file_path.unlink()
    # Also remove tag metadata if exists
    meta_path = file_path.with_suffix(file_path.suffix + ".meta.json")
    if meta_path.exists():
        meta_path.unlink()
    return {"status": "deleted", "file": filename}


@app.get("/api/assets/tags/{purpose}/{filename}")
async def get_asset_tags(purpose: str, filename: str):
    """Get tags/metadata for an uploaded asset."""
    meta_path = _project_root / "output" / "uploads" / purpose / f"{filename}.meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"tags": [], "description": "", "brand": "", "product": ""}


@app.put("/api/assets/tags/{purpose}/{filename}")
async def update_asset_tags(purpose: str, filename: str, request: Request):
    """Update tags/metadata for an uploaded asset."""
    data = await request.json()
    file_path = _project_root / "output" / "uploads" / purpose / filename
    if not file_path.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    meta_path = _project_root / "output" / "uploads" / purpose / f"{filename}.meta.json"
    existing = {}
    if meta_path.exists():
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
    existing.update({
        "tags": data.get("tags", existing.get("tags", [])),
        "description": data.get("description", existing.get("description", "")),
        "brand": data.get("brand", existing.get("brand", "")),
        "product": data.get("product", existing.get("product", "")),
        "updated_at": datetime.now().isoformat(),
    })
    meta_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return existing


@app.get("/api/assets/search")
async def search_assets(q: str = Query(""), tag: str = Query(""), brand: str = Query(""), purpose: str = Query("")):
    """Search uploaded assets by name, tag, or brand."""
    base = _project_root / "output" / "uploads"
    if not base.exists():
        return []
    results = []
    q_lower = q.lower()
    search_dirs = [base / purpose] if purpose else [d for d in base.iterdir() if d.is_dir()]
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm"}:
                continue
            # Load metadata if exists
            meta_path = f.parent / f"{f.name}.meta.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Apply filters
            if q_lower and q_lower not in f.name.lower() and q_lower not in meta.get("description", "").lower():
                continue
            if tag and tag not in meta.get("tags", []):
                continue
            if brand and meta.get("brand", "") != brand:
                continue

            results.append({
                "url": f"/output/uploads/{d.name}/{f.name}",
                "path": str(f),
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "purpose": d.name,
                "is_video": f.suffix.lower() in {".mp4", ".mov", ".webm"},
                "tags": meta.get("tags", []),
                "description": meta.get("description", ""),
                "brand": meta.get("brand", ""),
                "product": meta.get("product", ""),
            })
    return results


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
async def create_piece(request: Request, user: dict = Depends(require_auth)):
    try:
        data = await request.json()
        result = get_service().create_piece(data)
        _create_notification("Peca criada", f"Nova peca: {data.get('title', 'Sem titulo')}", "success", piece_id=str(result.get("id", "") if isinstance(result, dict) else ""))
        _log_activity("piece_created", f"Peca criada: {data.get('title', '')}", piece_id=str(result.get("id", "") if isinstance(result, dict) else ""))
        return result
    except Exception as e:
        logger.error("Erro ao criar peca: %s", e, exc_info=True)
        raise HTTPException(500, f"Erro ao criar peca: {str(e)}")


@app.put("/api/production/pieces/{piece_id}/stage")
async def update_piece_stage(piece_id: str, req: PieceStageUpdate):
    svc = get_service()
    result = svc.update_piece_stage(piece_id, req.stage, req.notes)
    if result is None:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    _create_notification("Estagio atualizado", f"Peca movida para: {req.stage}", "info", piece_id=piece_id)
    _log_activity("stage_changed", f"Peca {piece_id} movida para {req.stage}", piece_id=piece_id)
    return result


@app.put("/api/production/pieces/{piece_id}")
async def update_piece(piece_id: str, request: Request, user: dict = Depends(require_auth)):
    svc = get_service()
    data = await request.json()
    result = svc.update_piece(piece_id, data)
    if result is None:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    return result


@app.delete("/api/production/pieces/{piece_id}")
async def delete_piece(piece_id: str, user: dict = Depends(require_auth)):
    svc = get_service()
    if not svc.delete_piece(piece_id):
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    return {"status": "deleted"}


@app.post("/api/production/pieces/{piece_id}/generate-copy")
@limiter.limit("10/minute")
async def generate_copy_for_piece(piece_id: str, request: Request, user: dict = Depends(require_auth)):
    """Gera copy para uma peca existente e salva automaticamente."""
    svc = get_service()
    piece = svc.get_piece(piece_id)
    if not piece:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    data = await request.json()
    briefing = data.get("briefing", "")
    # Extrair objetivo das notes ou do titulo
    import json as _json
    notes_raw = piece.get("notes", "")
    objective = ""
    try:
        notes_obj = _json.loads(notes_raw) if notes_raw else {}
        objective = notes_obj.get("objective", "")
    except (ValueError, TypeError):
        pass
    # Contexto = titulo + objetivo + notas do usuario
    context_parts = []
    if piece.get("title"):
        context_parts.append(f"Titulo: {piece['title']}")
    if objective:
        context_parts.append(f"Objetivo/Tema: {objective}")
    piece_context = ". ".join(context_parts)

    if not briefing:
        # Gerar briefing com contexto
        ab = svc.auto_briefing
        br = await ab.generate(
            product=piece.get("product", ""),
            brand=piece.get("brand", "salk"),
            pillar=piece.get("pillar", ""),
            platform=piece.get("platform", "instagram"),
            context=piece_context,
        )
        briefing = br.get("briefing_text", "")
    # Gerar copy
    cw = BrandCopywriter(svc.llm_client, brand=piece.get("brand", "salk"))
    copy_result = await cw.write_copy(
        briefing=briefing,
        platform=piece.get("platform", "instagram"),
        format_type=piece.get("format", "post"),
        product=piece.get("product", ""),
        objective=piece_context,
    )
    # Parsear copy para extrair headline, hashtags, CTA
    raw_copy = copy_result.get("copy_text", "")
    lines = [l for l in raw_copy.split("\n") if l.strip()]
    headline = ""
    hashtags = []
    cta = ""
    body_lines = []

    for line in lines:
        stripped = line.strip()
        # Linha de hashtags (começa com # e tem várias)
        if stripped.startswith("#") and stripped.count("#") >= 2 and not stripped.startswith("##"):
            hashtags = [t.strip() for t in stripped.split() if t.startswith("#")]
            continue
        # Primeira linha curta = headline
        if not headline and len(stripped) < 100 and not stripped.startswith("http"):
            headline = stripped.lstrip("#").lstrip("*").rstrip("*").strip()
            continue
        body_lines.append(line)

    # Tentar detectar CTA (última linha antes das hashtags que parece CTA)
    cta_keywords = ["saiba mais", "converse", "consulte", "conheça", "fale com", "acesse", "solicite", "confira", "agende", "faca parte", "descubra"]
    for bl in reversed(body_lines):
        if any(kw in bl.lower() for kw in cta_keywords):
            cta = bl.strip()
            body_lines.remove(bl)
            break

    clean_copy = "\n".join(body_lines).strip()

    # Salvar na peca e avancar stage
    update_data = {
        "copy_text": raw_copy,
        "hashtags": hashtags if hashtags else [],
    }
    # Salvar headline e CTA no notes JSON
    try:
        notes_obj = _json.loads(piece.get("notes", "") or "{}") if piece.get("notes") else {}
    except (ValueError, TypeError):
        notes_obj = {}
    if headline:
        notes_obj["headline"] = headline
    if cta:
        notes_obj["cta"] = cta
    update_data["notes"] = _json.dumps(notes_obj)

    if piece.get("stage") == "briefing":
        update_data["stage"] = "copy"
    svc.update_piece(piece_id, update_data)
    return {
        **copy_result,
        "piece_id": piece_id,
        "stage": update_data.get("stage", piece.get("stage")),
        "headline": headline,
        "hashtags": hashtags,
        "cta": cta,
    }


@app.post("/api/production/pieces/{piece_id}/generate-prompt")
@limiter.limit("10/minute")
async def generate_prompt_for_piece(piece_id: str, request: Request, user: dict = Depends(require_auth)):
    """Gera prompt NB2 para uma peca existente e salva em notes."""
    svc = get_service()
    piece = svc.get_piece(piece_id)
    if not piece:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")
    data = await request.json()
    # Extrair contexto do briefing e objetivo dos notes da peca
    import json as _json_parse
    _existing = piece.get("notes", "")
    try:
        _notes = _json_parse.loads(_existing) if _existing else {}
    except (ValueError, TypeError):
        _notes = {}
    _briefing = _notes.get("briefing", "")
    _objective = _notes.get("objective", piece.get("title", ""))
    result = await svc.auto_prompt.generate_with_llm(
        product=piece.get("product", "lev"),
        brand=piece.get("brand", "salk"),
        concept=data.get("concept", ""),
        briefing=_briefing,
        objective=_objective,
    )
    # Salvar prompt em notes (JSON)
    import json as _json
    existing_notes = piece.get("notes", "")
    try:
        notes_data = _json.loads(existing_notes) if existing_notes else {}
    except (ValueError, TypeError):
        notes_data = {"original_notes": existing_notes}
    notes_data["nb2_prompt"] = result.get("positive_prompt", result.get("prompt", result.get("nb2_prompt", "")))
    if result.get("negative_prompt"):
        notes_data["nb2_negative"] = result.get("negative_prompt")
    update_data = {"notes": _json.dumps(notes_data)}
    if piece.get("stage") in ("briefing", "copy"):
        update_data["stage"] = "visual"
    svc.update_piece(piece_id, update_data)
    return {**result, "piece_id": piece_id, "stage": update_data.get("stage", piece.get("stage"))}


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
    result = get_service().create_review(req.model_dump())
    _create_notification("Review criada", "Nova review pendente", "review")
    _log_activity("review_created", "Review criada para avaliacao")
    return result


@app.put("/api/reviews/{review_id}")
async def update_review(review_id: str, req: ReviewUpdate):
    svc = get_service()
    result = svc.update_review(review_id, req.verdict, req.comments)
    if result is None:
        raise HTTPException(404, f"Review não encontrado: {review_id}")
    # Stage update already handled inside svc.update_review()
    _create_notification("Review atualizada", f"Veredito: {req.verdict or 'N/A'}", "review")
    _log_activity("review_updated", f"Review {review_id} atualizada: {req.verdict or ''}")
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


@app.post("/api/calendar/{week_id}/auto-fill")
async def auto_fill_calendar(week_id: str, brand: str = "salk", user: dict = Depends(require_auth)):
    """Preenche slots do calendário automaticamente (pilares, produtos, personas)."""
    svc = get_service()
    return svc.auto_fill_calendar(week_id, brand)


@app.post("/api/calendar/{week_id}/produce")
async def produce_week(week_id: str, request: Request, user: dict = Depends(require_auth)):
    """Produz conteúdo para todos os slots da semana (briefings, copy, prompts, atomização)."""
    svc = get_service()
    data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    return await svc.produce_week(
        week_id=week_id,
        brand=data.get("brand", "salk"),
        generate_briefing=data.get("generate_briefing", True),
        generate_copy=data.get("generate_copy", True),
        generate_prompt=data.get("generate_prompt", True),
        atomize=data.get("atomize", True),
    )


@app.post("/api/calendar/{week_id}/generate-full")
async def generate_full_week(week_id: str, brand: str = "salk", user: dict = Depends(require_auth)):
    """Fluxo completo: gera calendário + auto-fill + produção de toda a semana."""
    svc = get_service()
    return await svc.generate_full_week(week_id, brand)


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
    # Read from persistent budget tracker instead of in-memory log
    if hasattr(svc, "budget_tracker") and svc.budget_tracker is not None:
        summary = svc.budget_tracker.get_month_summary()
        detail = summary.get("by_category_detail", {})
        llm_detail = detail.get("LLM", {"total_usd": 0, "count": 0})
        return {
            "total_calls": llm_detail.get("count", 0),
            "total_cost_usd": llm_detail.get("total_usd", 0),
            "by_task": {},
            "by_model": {},
        }
    return {"total_calls": 0, "total_cost_usd": 0, "by_task": {}, "by_model": {}}


# =========================================================================
# VIDEO PIPELINE
# =========================================================================

@app.get("/api/video/status")
async def video_status(user: dict = Depends(require_auth)):
    svc = get_service()
    settings = svc.settings_store if hasattr(svc, "settings_store") else None
    return {
        "kling_configured": hasattr(svc, "kling_client") and svc.kling_client is not None and svc.kling_client.configured,
        "veo3_configured": hasattr(svc, "veo3_client") and svc.veo3_client is not None and svc.veo3_client.configured,
        "veo3_mode": svc.veo3_client.mode if hasattr(svc, "veo3_client") and svc.veo3_client else "not_configured",
        "minimax_configured": hasattr(svc, "minimax_client") and svc.minimax_client is not None and svc.minimax_client.configured,
        "grok_configured": bool(settings and settings.get("GROK_API_KEY")) if settings else bool(os.getenv("GROK_API_KEY")),
        "pika_configured": bool(settings and settings.get("PIKA_API_KEY")) if settings else bool(os.getenv("PIKA_API_KEY")),
        "runway_configured": bool(settings and settings.get("RUNWAY_API_KEY")) if settings else bool(os.getenv("RUNWAY_API_KEY")),
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
    if not svc.veo3_client or not svc.veo3_client.configured:
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
    if not svc.veo3_client or not svc.veo3_client.configured:
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
# VIDEO — Kling 3.0 Pro
# =========================================================================

@app.post("/api/video/kling/i2v")
async def kling_image_to_video(request: Request, user: dict = Depends(require_auth)):
    """Gera video a partir de imagem via Kling 3.0 Pro."""
    svc = get_service()
    data = await request.json()
    if not svc.kling_client or not svc.kling_client.api_key:
        raise HTTPException(503, "Kling nao configurado. Adicione KLING_API_KEY nas configuracoes.")
    result = await svc.kling_client.image_to_video(
        image_path=data.get("image_path", ""),
        prompt=data.get("prompt", ""),
        duration=data.get("duration", 5),
        aspect_ratio=data.get("aspect_ratio", "9:16"),
    )
    return result.to_dict() if hasattr(result, 'to_dict') else result


@app.post("/api/video/kling/t2v")
async def kling_text_to_video(request: Request, user: dict = Depends(require_auth)):
    """Gera video a partir de texto via Kling 3.0 Pro."""
    svc = get_service()
    data = await request.json()
    if not svc.kling_client or not svc.kling_client.api_key:
        raise HTTPException(503, "Kling nao configurado. Adicione KLING_API_KEY nas configuracoes.")
    result = await svc.kling_client.text_to_video(
        prompt=data.get("prompt", ""),
        duration=data.get("duration", 5),
        aspect_ratio=data.get("aspect_ratio", "16:9"),
    )
    return result.to_dict() if hasattr(result, 'to_dict') else result


# =========================================================================
# VIDEO — ElevenLabs TTS
# =========================================================================

@app.get("/api/video/voices")
async def list_voices(user: dict = Depends(require_auth)):
    """Lista vozes disponiveis no ElevenLabs."""
    svc = get_service()
    if not svc.tts_client:
        return {"voices": [], "configured": False}
    voices = await svc.tts_client.get_voices()
    return {"voices": voices, "configured": svc.tts_client.configured}


@app.post("/api/video/tts")
async def generate_tts(request: Request, user: dict = Depends(require_auth)):
    """Gera narracao via ElevenLabs TTS."""
    svc = get_service()
    data = await request.json()
    if not svc.tts_client or not svc.tts_client.api_key:
        raise HTTPException(503, "ElevenLabs nao configurado. Adicione ELEVENLABS_API_KEY nas configuracoes.")
    result = await svc.tts_client.generate(
        text=data.get("text", ""),
        voice_id=data.get("voice_id", "") or None,
        output_path=data.get("output_path", "") or None,
    )
    return result.to_dict() if hasattr(result, 'to_dict') else result


# =========================================================================
# VIDEO — Assembly (FFmpeg)
# =========================================================================

@app.post("/api/video/assemble")
async def assemble_video(request: Request, user: dict = Depends(require_auth)):
    """Monta video final: clip + narracao + musica + legendas."""
    svc = get_service()
    data = await request.json()
    if not svc.video_assembler or not svc.video_assembler.available:
        raise HTTPException(503, "FFmpeg nao disponivel no servidor.")
    result = await asyncio.to_thread(
        svc.video_assembler.assemble,
        video_path=data.get("video_path", ""),
        narration_path=data.get("audio_path", "") or None,
        subtitle_text=data.get("subtitle_text", "") or None,
        bgm_path=data.get("bgm_path", "") or None,
        output_name=data.get("output_name", "") or None,
        bgm_volume=data.get("bgm_volume", 0.15),
    )
    return result.to_dict() if hasattr(result, 'to_dict') else result


# =========================================================================
# VIDEO EDITOR — Edicao inteligente com FFmpeg + instrucoes naturais
# =========================================================================

@app.get("/api/video/editor/files")
async def list_editor_videos(user: dict = Depends(require_auth)):
    """Lista videos disponiveis para edicao (output/ + uploads/)."""
    svc = get_service()
    videos = []
    out = svc.config.output_dir
    search_dirs = [
        (out / "video", "gerado"),
        (out / "uploads" / "video", "upload"),
        (out / "video" / "final", "editado"),
        (out / "video" / "editor", "editado"),
        (out / "femipa", "femipa"),
    ]
    # Also scan all subdirs of output for mp4 files
    if out.exists():
        for sub in out.iterdir():
            if sub.is_dir() and sub.name not in ("video", "uploads", "femipa", "studio", "generated", "logs"):
                search_dirs.append((sub, sub.name))
    seen = set()
    for dir_path, source in search_dirs:
        if not dir_path.exists():
            continue
        for f in dir_path.iterdir():
            if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm") and f.name not in seen:
                seen.add(f.name)
                videos.append({
                    "name": f.name,
                    "path": str(f),
                    "url": f"/output/{f.relative_to(out)}" if str(f).startswith(str(out)) else "",
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                    "source": source,
                })
    return {"videos": sorted(videos, key=lambda v: v["name"])}


@app.get("/api/video/editor/audio")
async def list_editor_audio(user: dict = Depends(require_auth)):
    """Lista arquivos de audio disponiveis (narracoes, musicas)."""
    svc = get_service()
    audio_files = []
    out = svc.config.output_dir
    search_dirs = [
        (out / "video" / "audio", "narracao"),
        (out / "uploads" / "audio", "upload"),
        (out / "audio", "audio"),
    ]
    seen = set()
    for dir_path, source in search_dirs:
        if not dir_path.exists():
            continue
        for f in dir_path.iterdir():
            if f.suffix.lower() in (".mp3", ".wav", ".aac", ".ogg", ".m4a") and f.name not in seen:
                seen.add(f.name)
                audio_files.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                    "source": source,
                })
    return {"audio": sorted(audio_files, key=lambda a: a["name"])}


@app.post("/api/video/editor/analyze")
async def analyze_video(request: Request, user: dict = Depends(require_auth)):
    """Analisa video com ffprobe — retorna duracao, resolucao, codec, audio."""
    import json as _json
    import shutil
    import subprocess as _sp

    data = await request.json()
    video_path = data.get("video_path", "")
    if not video_path or not Path(video_path).exists():
        raise HTTPException(404, "Video nao encontrado")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise HTTPException(503, "ffprobe nao disponivel")

    try:
        result = _sp.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", video_path],
            capture_output=True, text=True, timeout=15,
        )
        info = _json.loads(result.stdout)
        fmt = info.get("format", {})
        streams = info.get("streams", [])

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        return {
            "duration": round(float(fmt.get("duration", 0)), 2),
            "size_mb": round(int(fmt.get("size", 0)) / (1024 * 1024), 2),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "codec": video_stream.get("codec_name", "unknown"),
            "fps": round(int(video_stream.get("r_frame_rate", "0/1").split("/")[0]) / max(int(video_stream.get("r_frame_rate", "0/1").split("/")[1]), 1), 1) if "/" in str(video_stream.get("r_frame_rate", "")) else float(video_stream.get("r_frame_rate", 0)),
            "has_audio": audio_stream is not None,
            "audio_codec": audio_stream.get("codec_name", "") if audio_stream else "",
            "bitrate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000),
        }
    except Exception as e:
        raise HTTPException(500, f"Erro ao analisar video: {str(e)}")


@app.post("/api/video/editor/execute")
async def execute_video_edit(request: Request, user: dict = Depends(require_auth)):
    """
    Executa edicao de video via FFmpeg com instrucoes em linguagem natural.

    Recebe instrucoes do usuario, converte em comando FFmpeg via LLM,
    executa e retorna o resultado.
    """
    import shutil
    import subprocess as _sp
    import time as _time

    svc = get_service()
    data = await request.json()

    video_path = data.get("video_path", "")
    instruction = data.get("instruction", "")
    audio_path = data.get("audio_path", "")
    extra_context = data.get("context", "")

    if not video_path or not Path(video_path).exists():
        raise HTTPException(404, "Video nao encontrado")
    if not instruction.strip():
        raise HTTPException(400, "Instrucao obrigatoria")

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise HTTPException(503, "FFmpeg nao disponivel")

    # --- Analisar video ---
    ffprobe = shutil.which("ffprobe")
    video_info = ""
    if ffprobe:
        try:
            import json as _json
            probe = _sp.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", video_path],
                capture_output=True, text=True, timeout=10,
            )
            info = _json.loads(probe.stdout)
            fmt = info.get("format", {})
            vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
            video_info = (
                f"Duracao: {fmt.get('duration', '?')}s, "
                f"Resolucao: {vs.get('width', '?')}x{vs.get('height', '?')}, "
                f"Codec: {vs.get('codec_name', '?')}, "
                f"FPS: {vs.get('r_frame_rate', '?')}, "
                f"Audio: {'sim' if any(s.get('codec_type') == 'audio' for s in info.get('streams', [])) else 'nao'}"
            )
        except Exception:
            video_info = "Nao foi possivel analisar o video"

    # --- Gerar comando FFmpeg via LLM ---
    output_dir = svc.config.output_dir / "video" / "editor"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(_time.time())
    output_path = output_dir / f"edit_{timestamp}.mp4"

    system_prompt = f"""Voce e um especialista em edicao de video com FFmpeg.
O usuario quer editar um video e deu instrucoes em linguagem natural.
Converta as instrucoes em UM UNICO comando FFmpeg valido.

REGRAS:
- Responda APENAS com o comando FFmpeg, sem explicacoes
- Use o path do ffmpeg: {ffmpeg_bin}
- Video de entrada: {video_path}
- Output DEVE ser: {output_path}
- Sempre use -y para sobrescrever
- Use -movflags +faststart para web
- Codec video: libx264 -preset medium -crf 23
- Codec audio: aac -b:a 192k
- Se houver audio adicional: {audio_path or 'nenhum fornecido'}
- Info do video: {video_info}
- NAO use filtros complexos a menos que necessario
- Para fade use: fade=t=in:st=0:d=0.5,fade=t=out:st=<calc>:d=1
- Para cortar use: -ss <inicio> -t <duracao>
- Para texto/legenda use: drawtext=text='...':fontsize=24:fontcolor=white:x=(w-text_w)/2:y=h-50
{f'- Contexto adicional: {extra_context}' if extra_context else ''}"""

    user_prompt = f"Instrucao do usuario: {instruction}"

    # Tentar via OpenRouter
    or_key = svc.settings.get("OPENROUTER_API_KEY")
    ffmpeg_command = ""

    if or_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {or_key}"},
                    json={
                        "model": "anthropic/claude-sonnet-4",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "max_tokens": 1000,
                        "temperature": 0,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Limpar — extrair apenas o comando
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith(ffmpeg_bin) or line.startswith("ffmpeg"):
                        ffmpeg_command = line
                        break
                if not ffmpeg_command and content.startswith(ffmpeg_bin):
                    ffmpeg_command = content.split("\n")[0]
                if not ffmpeg_command:
                    # Se LLM retornou bloco de codigo
                    import re
                    code_match = re.search(r"```(?:bash|sh)?\s*\n(.+?)```", content, re.DOTALL)
                    if code_match:
                        for line in code_match.group(1).strip().split("\n"):
                            if "ffmpeg" in line:
                                ffmpeg_command = line.strip()
                                break
                if not ffmpeg_command:
                    ffmpeg_command = content.strip().split("\n")[0]
        except Exception as e:
            return {
                "success": False,
                "error": f"Erro ao gerar comando via LLM: {str(e)}",
                "ffmpeg_command": "",
            }
    else:
        return {
            "success": False,
            "error": "OpenRouter API Key nao configurada. Va em Configuracoes para ativar.",
            "ffmpeg_command": "",
        }

    # Validacao de seguranca — bloquear comandos perigosos
    dangerous = ["rm ", "del ", "format ", "mkfs", "|", "&&", ";", "`"]
    if any(d in ffmpeg_command.lower() for d in dangerous):
        return {
            "success": False,
            "error": "Comando bloqueado por seguranca",
            "ffmpeg_command": ffmpeg_command,
        }

    # --- Executar FFmpeg ---
    start = _time.monotonic()
    try:
        import shlex
        # No Windows, shell=True com o comando completo
        result = await asyncio.to_thread(
            _sp.run, ffmpeg_command, shell=True,
            capture_output=True, text=True, timeout=300,
        )
        elapsed = _time.monotonic() - start

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr[:800] if result.stderr else "FFmpeg retornou erro",
                "ffmpeg_command": ffmpeg_command,
                "elapsed_seconds": round(elapsed, 1),
            }

        if not output_path.exists():
            return {
                "success": False,
                "error": "Arquivo de saida nao foi gerado",
                "ffmpeg_command": ffmpeg_command,
                "elapsed_seconds": round(elapsed, 1),
            }

        size_mb = round(output_path.stat().st_size / (1024 * 1024), 2)
        # URL relativa para output
        try:
            rel = output_path.relative_to(svc.config.output_dir)
            url = f"/output/{rel}"
        except ValueError:
            url = ""

        return {
            "success": True,
            "output_path": str(output_path),
            "output_url": url,
            "size_mb": size_mb,
            "ffmpeg_command": ffmpeg_command,
            "elapsed_seconds": round(elapsed, 1),
        }

    except _sp.TimeoutExpired:
        return {
            "success": False,
            "error": "FFmpeg timeout (>5 min)",
            "ffmpeg_command": ffmpeg_command,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "ffmpeg_command": ffmpeg_command,
        }


# =========================================================================
# VIDEO — Complete Pipeline
# =========================================================================

@app.post("/api/video/pipeline")
async def video_pipeline(request: Request, user: dict = Depends(require_auth)):
    """Pipeline completo: gera video + narracao + montagem."""
    svc = get_service()
    data = await request.json()
    results = {"steps": [], "errors": []}

    # Step 1: Generate video clip
    video_result = None
    engine = data.get("engine", "veo3")
    try:
        if engine == "kling" and svc.kling_client and svc.kling_client.configured:
            if data.get("image_path"):
                video_result = await svc.kling_client.image_to_video(
                    image_path=data["image_path"],
                    prompt=data.get("prompt", ""),
                    duration=data.get("duration", 5),
                    aspect_ratio=data.get("aspect_ratio", "9:16"),
                )
            else:
                video_result = await svc.kling_client.text_to_video(
                    prompt=data.get("prompt", ""),
                    duration=data.get("duration", 5),
                    aspect_ratio=data.get("aspect_ratio", "16:9"),
                )
            results["steps"].append({"step": "video", "engine": "kling", "status": "ok"})
        elif engine == "minimax" and svc.minimax_client and svc.minimax_client.configured:
            video_result = await svc.minimax_client.image_to_video(
                image_path=data.get("image_path", ""),
                prompt=data.get("prompt", ""),
            )
            results["steps"].append({"step": "video", "engine": "minimax", "status": "ok"})
        elif engine == "veo3" and svc.veo3_client and svc.veo3_client.configured:
            if data.get("image_path"):
                video_result = await svc.veo3_client.image_to_video(
                    image_path=data["image_path"],
                    prompt=data.get("prompt", ""),
                    aspect_ratio=data.get("aspect_ratio", "9:16"),
                )
            else:
                video_result = await svc.veo3_client.text_to_video(
                    prompt=data.get("prompt", ""),
                    aspect_ratio=data.get("aspect_ratio", "16:9"),
                )
            results["steps"].append({"step": "video", "engine": "veo3", "status": "ok"})
        elif engine in ("grok", "pika", "runway"):
            results["errors"].append(f"Engine '{engine}' — cliente em desenvolvimento. Configure a API key em Configuracoes para ativar quando disponivel.")
        else:
            results["errors"].append(f"Engine '{engine}' nao configurado. Verifique a API key em Configuracoes.")
    except Exception as e:
        results["errors"].append(f"Erro gerando video: {str(e)}")

    # Convert video result to dict for downstream use
    video_dict = video_result.to_dict() if video_result and hasattr(video_result, 'to_dict') else video_result
    results["video"] = video_dict

    # Step 2: Generate narration (if script provided)
    narration_result = None
    narration_dict = None
    if data.get("narration_text") and svc.tts_client and svc.tts_client.api_key:
        try:
            narration_result = await svc.tts_client.generate(
                text=data["narration_text"],
                voice_id=data.get("voice_id", ""),
            )
            narration_dict = narration_result.to_dict() if hasattr(narration_result, 'to_dict') else narration_result
            results["steps"].append({"step": "narration", "status": "ok"})
        except Exception as e:
            results["errors"].append(f"Erro gerando narracao: {str(e)}")

    results["narration"] = narration_dict

    # Step 3: Assembly (if video + narration available)
    narration_audio = getattr(narration_result, 'audio_path', '') if narration_result else ''
    video_output = video_dict.get("video_path", "") or video_dict.get("output_path", "") if video_dict else ''
    if video_output and narration_audio and svc.video_assembler and svc.video_assembler.available:
        try:
            assembly_result = await asyncio.to_thread(
                svc.video_assembler.assemble,
                video_path=video_output,
                narration_path=narration_audio or None,
                subtitle_text=data.get("narration_text", "") or None,
                bgm_path=data.get("bgm_path", "") or None,
                output_name=data.get("final_output_name", "") or None,
            )
            results["steps"].append({"step": "assembly", "status": "ok"})
            results["final_video"] = assembly_result.to_dict() if hasattr(assembly_result, 'to_dict') else assembly_result
        except Exception as e:
            results["errors"].append(f"Erro na montagem: {str(e)}")

    results["total_cost_usd"] = sum(
        r.get("cost_usd", 0) for r in [video_dict, narration_dict] if r and isinstance(r, dict)
    )

    return results


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
# AUTOMATION — Pipeline Completo (Briefing → Copy → Prompt em sequencia)
# =========================================================================

@app.post("/api/automation/produce-piece")
@limiter.limit("5/minute")
async def produce_single_piece(request: Request, user: dict = Depends(require_auth)):
    """Pipeline completo: cria peca + briefing + copy + prompt NB2 em um clique."""
    svc = get_service()
    data = await request.json()
    import json as _json

    brand = data.get("brand", "salk")
    product = data.get("product", "")
    platform = data.get("platform", "instagram")
    pillar = data.get("pillar", "produto")
    format_type = data.get("format", "post")
    objective = data.get("objective", "")

    # Inferir produto se nao especificado (sugestao, nao obrigatorio)
    # Pilares institucionais NUNCA inferem produto — NB2 gera em modo prompt-only
    inferred_product = ""
    institutional_pillars = ("datas_comemorativas", "institucional")
    if not product and pillar not in institutional_pillars:
        inferred_product = svc.auto_prompt.infer_product(
            objective=objective, pillar=pillar, title=data.get("title", ""),
        )
        if inferred_product:
            product = inferred_product
            logger.info("Product inferred from context: %s", product)
    elif not product and pillar in institutional_pillars:
        logger.info("Pillar '%s' is institutional — no product inference, NB2 prompt-only", pillar)

    logger.info(
        "produce_single_piece: brand=%s, product=%s (inferred=%s), pillar=%s, platform=%s, objective=%s",
        brand, product, inferred_product or "no", pillar, platform, objective,
    )
    result = {"steps": [], "errors": [], "product_inferred": inferred_product or None}

    # Contexto para briefing e copy
    title = data.get("title", f"{pillar.title()} — {product.upper() or brand.upper()} ({platform})")
    context_parts = []
    if title:
        context_parts.append(f"Titulo: {title}")
    if objective:
        context_parts.append(f"Objetivo/Tema: {objective}")
    piece_context = ". ".join(context_parts)

    # Step 1: Create piece
    piece_data = {
        "title": title,
        "brand": brand, "product": product, "pillar": pillar,
        "platform": platform, "format": format_type, "stage": "briefing",
        "persona_target": data.get("persona_target", ""),
    }
    piece = svc.create_piece(piece_data)
    piece_id = piece.get("id", "")
    result["piece_id"] = piece_id
    result["steps"].append({"step": "create_piece", "status": "ok"})

    # Step 2: Briefing
    try:
        br = await svc.auto_briefing.generate(
            product=product, brand=brand, pillar=pillar, platform=platform,
            context=piece_context,
        )
        briefing_text = br.get("briefing_text", "")
        result["briefing"] = briefing_text
        result["steps"].append({"step": "briefing", "status": "ok"})
    except Exception as e:
        logger.error("produce_single_piece briefing error: %s", e, exc_info=True)
        result["errors"].append(f"Briefing: {e}")
        briefing_text = data.get("briefing", f"Post {pillar} {'sobre ' + product if product else 'institucional'} para {platform}. {objective}")

    # Step 3: Copy
    try:
        # Load prohibited terms and claims for the copywriter
        prohibited = []
        try:
            bb = svc.load_brandbook(brand)
            prohibited = bb.get("prohibited_tones", []) + bb.get("visual_rules", {}).get("proibido", [])
        except Exception:
            pass

        claims_for_copy = []
        try:
            cb = svc.load_claims_bank()
            if product:
                claims_for_copy = [c for c in cb.get("products", {}).get(product.lower(), {}).get("claims", []) if c.get("status") == "aprovado"]
            else:
                # Get institutional claims
                claims_for_copy = cb.get("institutional", {}).get("claims", [])[:10]
        except Exception:
            pass

        cw = BrandCopywriter(svc.llm_client, brand=brand)
        copy_result = await cw.write_copy(
            briefing=briefing_text, platform=platform, format_type=format_type,
            product=product, objective=piece_context,
            prohibited_terms=prohibited, approved_claims=claims_for_copy,
        )
        copy_text = copy_result.get("copy_text", "")
        result["copy"] = copy_result
        result["steps"].append({"step": "copy", "status": "ok"})
        svc.update_piece(piece_id, {"copy_text": copy_text, "stage": "copy"})
    except Exception as e:
        logger.error("produce_single_piece copy error: %s", e, exc_info=True)
        result["errors"].append(f"Copy: {e}")
        copy_text = ""

    # Step 4: NB2 Prompt (com contexto do briefing e objetivo)
    try:
        prompt_result = await svc.auto_prompt.generate_with_llm(
            product=product, brand=brand,
            concept=data.get("concept", ""),
            briefing=briefing_text,
            objective=objective,
        )
        nb2_prompt = prompt_result.get("positive_prompt", prompt_result.get("prompt", prompt_result.get("nb2_prompt", "")))
        nb2_negative = prompt_result.get("negative_prompt", "")
        result["nb2_prompt"] = nb2_prompt
        result["nb2_negative"] = nb2_negative
        result["steps"].append({"step": "nb2_prompt", "status": "ok"})
        notes_data = {"briefing": briefing_text, "nb2_prompt": nb2_prompt, "nb2_negative": nb2_negative, "objective": objective}
        svc.update_piece(piece_id, {"notes": _json.dumps(notes_data), "stage": "visual"})
    except Exception as e:
        logger.error("produce_single_piece nb2_prompt error: %s", e, exc_info=True)
        result["errors"].append(f"NB2 Prompt: {e}")

    result["total_steps"] = len(result["steps"])
    logger.info(
        "produce_single_piece complete: piece_id=%s, steps=%d, errors=%d",
        result.get("piece_id"), len(result["steps"]), len(result["errors"]),
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
    product = data.get("product", "")
    objective = data.get("objective", "")
    briefing = data.get("briefing", "")

    # Se não tem briefing mas tem produto/objetivo, gerar briefing automaticamente
    if not briefing and (product or objective):
        context_parts = []
        if product:
            context_parts.append(f"Produto: {product}")
        if objective:
            context_parts.append(f"Objetivo/Tema: {objective}")
        content_type = data.get("content_type", "")
        if content_type:
            context_parts.append(f"Tipo: {content_type}")
        piece_context = ". ".join(context_parts)
        ab = svc.auto_briefing
        br = await ab.generate(
            product=product,
            brand=brand,
            pillar=data.get("pillar", "produto"),
            platform=data.get("platform", "instagram"),
            context=piece_context,
        )
        briefing = br.get("briefing_text", "")

    cw = BrandCopywriter(svc.llm_client, brand=brand)
    result = await cw.write_copy(
        briefing=briefing,
        platform=data.get("platform", "instagram"),
        format_type=data.get("format_type", "post"),
        max_chars=data.get("max_chars", 2200),
        product=product,
        objective=objective,
    )

    # Parsear copy para extrair headline, hashtags, CTA
    import json as _json
    raw_copy = result.get("copy_text", "")
    lines = [l for l in raw_copy.split("\n") if l.strip()]
    headline = ""
    hashtags = []
    cta = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") and stripped.count("#") >= 2 and not stripped.startswith("##"):
            hashtags = [t.strip() for t in stripped.split() if t.startswith("#")]
            continue
        if not headline and len(stripped) < 100 and not stripped.startswith("http"):
            headline = stripped.lstrip("#").lstrip("*").rstrip("*").strip()
            continue

    cta_keywords = ["saiba mais", "converse", "consulte", "conheça", "fale com", "acesse", "solicite", "confira", "agende", "faca parte", "descubra"]
    for line in reversed(lines):
        if any(kw in line.lower() for kw in cta_keywords):
            cta = line.strip()
            break

    result["headline"] = headline
    result["hashtags"] = hashtags
    result["cta"] = cta
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
    from content_pipeline.automation.copywriter import get_brand_copywriters
    return {k: {"name": v["name"]} for k, v in get_brand_copywriters().items()}


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
# IMAGE GENERATION (fal.ai NB2)
# =========================================================================

@app.post("/api/automation/generate-image")
@limiter.limit("10/minute")
async def generate_image(request: Request, user: dict = Depends(require_auth)):
    """Gera imagem via fal.ai NB2 (padrão para tudo)."""
    svc = get_service()
    if not svc.image_generator or not svc.image_generator.configured:
        raise HTTPException(400, "FAL_API_KEY não configurada. Vá em Configurações.")
    data = await request.json()
    product = data.get("product", "") or data.get("product_type", "")
    result = await svc.image_generator.generate_image(
        prompt=data.get("prompt", ""),
        width=data.get("width", 1080),
        height=data.get("height", 1350),
        negative_prompt=data.get("negative_prompt", "text, logo, watermark, blurry, low quality"),
        model=data.get("model", "nb2"),
        format_preset=data.get("format_preset", ""),
        product=product,
    )
    model_used = result.model_used or "nb2"
    _create_notification("Imagem gerada", f"Imagem gerada via {model_used.upper()}", "success")
    _log_activity("image_generated", f"Imagem gerada via {model_used}/fal.ai")
    return result.to_dict()


@app.post("/api/production/pieces/{piece_id}/generate-image")
@limiter.limit("10/minute")
async def generate_image_for_piece(piece_id: str, request: Request, user: dict = Depends(require_auth)):
    """Gera imagem para uma peça existente usando o prompt NB2 salvo."""
    import json as _json
    svc = get_service()
    if not svc.image_generator or not svc.image_generator.configured:
        raise HTTPException(400, "FAL_API_KEY não configurada. Vá em Configurações.")
    piece = svc.get_piece(piece_id)
    if not piece:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")

    data = await request.json()
    # Extrair prompt NB2 das notes da peça
    notes = piece.get("notes", "")
    try:
        notes_data = _json.loads(notes) if notes else {}
    except (ValueError, TypeError):
        notes_data = {}
    prompt = data.get("prompt") or notes_data.get("nb2_prompt", "") or notes_data.get("positive_prompt", "")
    negative = data.get("negative_prompt") or notes_data.get("nb2_negative", "") or "text, logo, watermark, blurry, low quality"
    if not prompt:
        raise HTTPException(400, "Nenhum prompt NB2 disponível. Gere o prompt primeiro.")

    # Inferir produto se peça não tem (para ativar NB2)
    product = piece.get("product", "")
    if not product:
        product = svc.auto_prompt.infer_product(
            objective=notes_data.get("objective", ""),
            title=piece.get("title", ""),
            pillar=piece.get("pillar", ""),
        )
        if product:
            logger.info("Image gen: product inferred as '%s' for piece %s", product, piece_id)

    # Determinar dimensões baseado na plataforma
    platform = piece.get("platform", "instagram")
    fmt = piece.get("format", "post")
    format_preset = "feed"
    if "stories" in platform or "reels" in platform or fmt in ("reel", "story"):
        format_preset = "stories"
    elif fmt == "carousel":
        format_preset = "square"

    result = await svc.image_generator.generate_image(
        prompt=prompt,
        format_preset=format_preset,
        negative_prompt=negative,
        product=product,  # usa inferido se peça não tinha
        model=data.get("model", "nb2"),
    )

    if result.success:
        # Salvar image_url nas notes e avançar stage
        notes_data["image_url"] = result.image_url
        notes_data["image_path"] = result.image_path
        notes_data["image_cost_usd"] = result.cost_usd
        update_data = {"notes": _json.dumps(notes_data)}
        if piece.get("stage") in ("briefing", "copy", "visual"):
            update_data["stage"] = "review"
        svc.update_piece(piece_id, update_data)

    return {**result.to_dict(), "piece_id": piece_id}


# =========================================================================
# VIDEO ANIMATION (Minimax/Kling/Veo3)
# =========================================================================

@app.post("/api/automation/animate-image")
@limiter.limit("5/minute")
async def animate_image(request: Request, user: dict = Depends(require_auth)):
    """Anima imagem estática em vídeo de 6s."""
    svc = get_service()
    if not svc.video_animator or not svc.video_animator.configured:
        raise HTTPException(400, "Nenhum engine de vídeo configurado (Minimax, Kling ou Veo3)")
    data = await request.json()
    result = await svc.video_animator.animate(
        image_path=data.get("image_path", ""),
        prompt=data.get("prompt", "Subtle camera movement, cinematic lighting"),
        duration=data.get("duration", 6),
        engine=data.get("engine", "auto"),
    )
    return result.to_dict()


@app.post("/api/production/pieces/{piece_id}/animate")
@limiter.limit("5/minute")
async def animate_piece_image(piece_id: str, request: Request, user: dict = Depends(require_auth)):
    """Anima a imagem de uma peça existente para vídeo."""
    import json as _json
    svc = get_service()
    if not svc.video_animator or not svc.video_animator.configured:
        raise HTTPException(400, "Nenhum engine de vídeo configurado")
    piece = svc.get_piece(piece_id)
    if not piece:
        raise HTTPException(404, f"Peça não encontrada: {piece_id}")

    notes = piece.get("notes", "")
    try:
        notes_data = _json.loads(notes) if notes else {}
    except (ValueError, TypeError):
        notes_data = {}

    image_path = notes_data.get("image_path", "")
    if not image_path:
        raise HTTPException(400, "Peça não tem imagem gerada. Gere a imagem primeiro.")

    data = await request.json()
    result = await svc.video_animator.animate(
        image_path=image_path,
        prompt=data.get("prompt", "Subtle camera dolly forward, cinematic lighting shift"),
        duration=data.get("duration", 6),
        engine=data.get("engine", "auto"),
    )

    if result.success:
        notes_data["video_url"] = result.video_url
        notes_data["video_path"] = result.video_path
        notes_data["video_cost_usd"] = result.cost_usd
        notes_data["video_engine"] = result.engine
        svc.update_piece(piece_id, {"notes": _json.dumps(notes_data)})

    return {**result.to_dict(), "piece_id": piece_id}


@app.get("/api/automation/video-engines")
async def list_video_engines():
    """Lista engines de vídeo disponíveis."""
    svc = get_service()
    return {
        "engines": svc.video_animator.available_engines() if svc.video_animator else [],
        "image_generator": svc.image_generator.configured if svc.image_generator else False,
    }


# =========================================================================
# A/B TEST PIPELINE — Geração em massa de variações
# =========================================================================

@app.post("/api/automation/ab-test")
@limiter.limit("2/minute")
async def run_ab_test(request: Request, background_tasks: BackgroundTasks, user: dict = Depends(require_auth)):
    """Pipeline A/B test: gera N variações completas (briefing+copy+prompt+imagem)."""
    import json as _json
    svc = get_service()
    data = await request.json()

    product = data.get("product", "")
    brand = data.get("brand", "salk")
    num_variations = min(data.get("num_variations", 5), 20)
    platforms = data.get("platforms", ["instagram"])
    concept = data.get("concept", "")
    pillar = data.get("pillar", "produto")
    generate_images = data.get("generate_images", True) and svc.image_generator.configured
    generate_videos = data.get("generate_videos", False) and svc.video_animator.configured

    # Conceitos visuais para variações
    concepts = [
        "dramatic_studio", "clinical_modern", "premium_clean",
        "warm_ambient", "hero_closeup", "environment_wide",
        "tech_detail", "action_use", "atmospheric_mood",
        "minimalist_white", "dark_contrast", "golden_hour",
        "architectural", "reflection_glass", "depth_of_field",
        "symmetry", "silhouette_backlit", "macro_detail",
        "editorial_spread", "brand_lifestyle",
    ]

    results = {"piece_ids": [], "errors": [], "variations": [], "total_cost_usd": 0}

    for i in range(num_variations):
        variation_concept = concepts[i % len(concepts)] if not concept else f"{concept}_v{i+1}"
        platform = platforms[i % len(platforms)]
        variation = {"index": i + 1, "concept": variation_concept, "platform": platform, "steps": []}

        try:
            # Step 1: Briefing
            br = await svc.auto_briefing.generate(
                product=product, brand=brand, pillar=pillar, platform=platform,
            )
            briefing_text = br.get("briefing_text", "")
            variation["steps"].append("briefing")

            # Step 2: Copy
            cw = BrandCopywriter(svc.llm_client, brand=brand)
            copy_result = await cw.write_copy(
                briefing=briefing_text, platform=platform, format_type="post",
            )
            copy_text = copy_result.get("copy_text", "")
            variation["steps"].append("copy")
            variation["copywriter"] = copy_result.get("copywriter", "")

            # Step 3: NB2 Prompt
            prompt_result = await svc.auto_prompt.generate_prompt(
                product=product or "lev", brand=brand,
                concept=variation_concept, platform=platform,
            )
            nb2_prompt = prompt_result.get("positive_prompt", prompt_result.get("prompt", prompt_result.get("nb2_prompt", "")))
            nb2_negative = prompt_result.get("negative_prompt", "")
            variation["steps"].append("prompt")

            # Step 4: Create piece
            piece_data = {
                "title": f"A/B #{i+1}: {variation_concept.replace('_', ' ').title()} — {product.upper() or brand.upper()} ({platform})",
                "brand": brand, "product": product, "pillar": pillar,
                "platform": platform, "format": "post",
                "stage": "visual" if not generate_images else "review",
                "copy_text": copy_text,
                "notes": _json.dumps({
                    "briefing": briefing_text,
                    "nb2_prompt": nb2_prompt,
                    "ab_test": True,
                    "variation_index": i + 1,
                    "variation_concept": variation_concept,
                    "copywriter": copy_result.get("copywriter", ""),
                    "cost_usd": copy_result.get("cost_usd", 0) + br.get("cost_usd", 0),
                }),
            }
            piece = svc.create_piece(piece_data)
            piece_id = piece.get("id", "")
            results["piece_ids"].append(piece_id)
            variation["piece_id"] = piece_id
            variation["steps"].append("piece_created")

            # Step 5: Image (if fal.ai configured)
            img_result = None
            if generate_images and nb2_prompt and svc.image_generator and svc.image_generator.configured:
                img_result = await svc.image_generator.generate_image(
                    prompt=nb2_prompt,
                    format_preset="feed",
                    negative_prompt="text, logo, watermark, blurry, low quality, medical equipment other than the target product",
                    product=data.get("product", ""),
                    model="nb2",
                )
                if img_result.success:
                    notes = _json.loads(piece_data["notes"])
                    notes["image_url"] = img_result.image_url
                    notes["image_path"] = img_result.image_path
                    notes["image_cost_usd"] = img_result.cost_usd
                    svc.update_piece(piece_id, {"notes": _json.dumps(notes), "stage": "review"})
                    variation["steps"].append("image")
                    variation["image_url"] = img_result.image_url
                    results["total_cost_usd"] += img_result.cost_usd

            # Step 6: Video animation (if configured and requested)
            if generate_videos and img_result and img_result.success and svc.video_animator and svc.video_animator.configured:
                vid_result = await svc.video_animator.animate(
                    image_path=img_result.image_path,
                    prompt=f"Subtle camera dolly forward, cinematic lighting on {product}",
                    duration=6,
                )
                if vid_result.success:
                    notes = _json.loads(svc.get_piece(piece_id).get("notes", "{}"))
                    notes["video_url"] = vid_result.video_url
                    notes["video_path"] = vid_result.video_path
                    notes["video_cost_usd"] = vid_result.cost_usd
                    svc.update_piece(piece_id, {"notes": _json.dumps(notes)})
                    variation["steps"].append("video")
                    results["total_cost_usd"] += vid_result.cost_usd

            results["total_cost_usd"] += copy_result.get("cost_usd", 0) + br.get("cost_usd", 0)

        except Exception as e:
            logger.error("Erro na variação %d: %s", i + 1, e, exc_info=True)
            results["errors"].append(f"Variação {i+1}: {str(e)}")
            variation["error"] = str(e)

        results["variations"].append(variation)

    results["total_variations"] = len(results["piece_ids"])
    results["total_cost_usd"] = round(results["total_cost_usd"], 4)
    return results


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
    result_dict = result.to_dict()
    result_dict["preview"] = publisher.preview_mode
    if publisher.preview_mode:
        _create_notification("Simulacao de publicacao", f"Preview: conteudo simulado em {platform}", "publish")
        _log_activity("publish_preview", f"Preview simulado em {platform}", piece_id=data.get("piece_id", ""))
    else:
        _create_notification("Publicacao realizada", f"Conteudo publicado em {platform}", "publish")
        _log_activity("published", f"Conteudo publicado em {platform}", piece_id=data.get("piece_id", ""))
    return result_dict


@app.get("/api/publish/status")
async def publishers_status(user: dict = Depends(require_auth)):
    """Status de todos os publishers — granular per-platform."""
    svc = get_service()
    platforms = {}
    for name, pub in svc.publishers.items():
        platforms[name] = {
            "configured": pub.configured,
            "connected": pub.configured and not pub.preview_mode,
            "preview_mode": pub.preview_mode,
            "status": "connected" if (pub.configured and not pub.preview_mode) else ("preview" if pub.configured else "not_configured"),
        }
    return {
        "platforms": platforms,
        "preview_mode": svc.preview_mode,
        "any_connected": any(p["connected"] for p in platforms.values()),
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
async def feedback_recommendations(brand: str = "", user: dict = Depends(require_auth)):
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


@app.get("/api/report/weekly/download")
async def weekly_report_download(
    week_id: str = "", brand: str = "", user: dict = Depends(require_auth),
):
    """Download relatorio semanal como HTML file (para print-to-PDF)."""
    svc = get_service()
    html = svc.weekly_report.generate_html(week_id=week_id, brand=brand)
    # Add print-optimized CSS and auto-print script
    print_html = html.replace(
        "</style>",
        """
        @media print {
            body { margin: 20px; }
            .summary-grid { grid-template-columns: repeat(4, 1fr); }
            .no-print { display: none; }
        }
        @page { margin: 1.5cm; size: A4; }
        </style>"""
    )
    from starlette.responses import Response
    filename = f"relatorio-semanal-{week_id or 'atual'}-{brand or 'todas'}.html"
    return Response(
        content=print_html,
        media_type="text/html",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )


# =========================================================================
# FRONTEND STATIC FILES (SPA) — Render single-service deployment
# =========================================================================

# Serve frontend static files if the built frontend directory exists.
# API routes above take precedence; this catch-all handles SPA client-side routing.
frontend_dir = None
_candidates = [
    Path("/app/frontend"),  # Docker volume mount (PRIORITY — always up-to-date via git pull)
    Path(__file__).parent / "static",  # Embedded in package (fallback)
    Path(__file__).parent.parent.parent.parent.parent / "content-studio-frontend",
    Path.cwd() / "frontend",
    Path.cwd() / "packages" / "content-studio-frontend",
    Path.cwd().parent / "content-studio-frontend",
]
for _c in _candidates:
    if _c.exists():
        frontend_dir = _c
        break

# =========================================================================
# NOTIFICATIONS & ACTIVITY LOG
# =========================================================================


@app.get("/api/notifications")
async def get_notifications(unread_only: bool = False, category: str = None, limit: int = 50):
    items = notifications_store
    if unread_only:
        items = [n for n in items if not n["read"]]
    if category:
        items = [n for n in items if n["category"] == category]
    return {
        "notifications": items[:limit],
        "total": len(notifications_store),
        "unread": sum(1 for n in notifications_store if not n["read"]),
    }


@app.put("/api/notifications/{notif_id}/read")
async def mark_notification_read(notif_id: int):
    for n in notifications_store:
        if n["id"] == notif_id:
            n["read"] = True
            return {"status": "ok"}
    return {"status": "not_found"}


@app.put("/api/notifications/read-all")
async def mark_all_notifications_read():
    for n in notifications_store:
        n["read"] = True
    return {"status": "ok", "count": len(notifications_store)}


@app.delete("/api/notifications/{notif_id}")
async def delete_notification(notif_id: int):
    global notifications_store
    notifications_store = [n for n in notifications_store if n["id"] != notif_id]
    return {"status": "deleted"}


@app.get("/api/activity")
async def get_activity_log(limit: int = 100, piece_id: str = None, action: str = None):
    items = activity_log_store
    if piece_id:
        items = [a for a in items if a["piece_id"] == piece_id]
    if action:
        items = [a for a in items if a["action"] == action]
    return {
        "activities": items[:limit],
        "total": len(activity_log_store),
    }


# =========================================================================
# DEPLOY — git pull via HTTP (substitui SSH quando porta bloqueada)
# =========================================================================

@app.post("/api/deploy")
async def deploy_pull(user: dict = Depends(require_auth)):
    """Executa git pull no repositório do servidor."""
    import subprocess

    # Detectar diretório do repo (container ou host)
    repo_candidates = [
        Path("/app"),                              # dentro do container Docker
        Path("/opt/content-studio/repo-new"),      # host direto
        Path(__file__).resolve().parents[5],       # relativo ao código
    ]
    repo_dir = None
    for candidate in repo_candidates:
        if (candidate / ".git").exists():
            repo_dir = candidate
            break

    if not repo_dir:
        raise HTTPException(status_code=500, detail="Repositório git não encontrado no servidor")

    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "repo_dir": str(repo_dir),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git pull timeout (60s)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FRONTEND STATIC FILES — MUST be last (catch-all mount)
# =========================================================================

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
