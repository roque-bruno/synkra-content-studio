"""
Services — camada de negócio do Content Studio v2.0.

Singleton-friendly: instanciado uma vez no startup do FastAPI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from content_pipeline.config import PipelineConfig
from content_pipeline.nb2.prompt_builder import (
    CAMERA_PRESETS,
    LIGHTING_PRESETS,
    SURFACE_PRESETS,
    PromptBuilder,
)
from content_pipeline.nb2.vdp_loader import VDPLoader, VDPSpec
from content_pipeline.brand_enforcer import BrandEnforcer
from content_pipeline.llm.budget_tracker import BudgetTracker
from content_pipeline.llm.journey_log import JourneyLog
from content_pipeline.llm.openrouter import OpenRouterClient
from content_pipeline.output.manager import OutputManager
from content_pipeline.video.assembler import VideoAssembler
from content_pipeline.video.elevenlabs_tts import ElevenLabsTTS
from content_pipeline.video.kling_client import KlingClient
from content_pipeline.video.veo3_client import Veo3Client
from content_pipeline.publishers.base import PublisherBase
from content_pipeline.publishers.instagram import InstagramPublisher
from content_pipeline.publishers.linkedin import LinkedInPublisher
from content_pipeline.publishers.facebook import FacebookPublisher
from content_pipeline.publishers.youtube import YouTubePublisher
from content_pipeline.publishers.metrics_collector import MetricsCollector
from content_pipeline.publishers.batch_approval import BatchApproval
from content_pipeline.publishers.feedback_loop import FeedbackLoop
from content_pipeline.publishers.report_pdf import WeeklyReport
from content_pipeline.automation.auto_briefing import AutoBriefing
from content_pipeline.automation.auto_prompt import AutoPromptNB2
from content_pipeline.automation.atomizer import SemanticAtomizer
from content_pipeline.automation.copywriter import BrandCopywriter, PersonaClone
from content_pipeline.automation.disaster_check import DisasterCheck
from content_pipeline.automation.image_generator import FalImageGenerator
from content_pipeline.automation.video_animator import VideoAnimator
from content_pipeline.automation.keyframe_processor import KeyframeProcessor
from content_pipeline.automation.week_orchestrator import WeekOrchestrator
from content_pipeline.video.minimax_client import MinimaxClient
from content_pipeline.web.database import StudioDatabase
from content_pipeline.web.settings_store import SettingsStore

# Type alias — SupabaseDatabase tem a mesma interface que StudioDatabase
DatabaseBackend = StudioDatabase  # será substituído em runtime se Supabase configurado

logger = logging.getLogger(__name__)


def _extract_claim_phrases(claim_text: str) -> list[str]:
    """Extract key technical phrases from a claim for fuzzy matching."""
    # Return the full claim and significant subphrases (3+ words)
    phrases = [claim_text]
    words = claim_text.split()
    if len(words) >= 4:
        # Also match on the first 4 words (e.g. "índice de reprodução de")
        phrases.append(" ".join(words[:4]))
    # Match specific numeric patterns in the claim
    import re
    numbers = re.findall(r'\d+[\.,]?\d*\s*\w+', claim_text)
    phrases.extend(numbers)
    return [p for p in phrases if len(p) > 5]


class StudioService:
    """Serviço central do Content Studio v2.0."""

    def __init__(self, config: PipelineConfig, preview_mode: bool = True) -> None:
        self.config = config
        self.preview_mode = preview_mode
        self.vdp_loader = VDPLoader()
        self.prompt_builder = PromptBuilder()
        self.output_manager = OutputManager(
            base_dir=config.output_dir,
            quality=config.nb2.output_quality,
        )
        self._orchestrator = None

        # Diretório de dados do studio (persistência local)
        self._studio_dir = config.output_dir / "studio"
        self._studio_dir.mkdir(parents=True, exist_ok=True)

        # Settings Store (chaves API persistidas)
        self.settings = SettingsStore(self._studio_dir)
        self.settings.apply_to_env()

        # Database — Supabase (se configurado) ou SQLite (fallback)
        self.db = self._init_database()

        # Inicializar todos os subsistemas
        self._init_subsystems(config)

        # Cache de dados YAML (carregados uma vez)
        self._platform_specs_cache: Optional[dict] = None
        self._buyer_personas_cache: Optional[list] = None
        self._hashtag_bank_cache: Optional[dict] = None
        self._editorial_template_cache: Optional[dict] = None
        self._prohibited_terms_cache: Optional[dict] = None
        self._brand_guidelines_cache: Optional[dict] = None
        self._brandbooks_cache: dict[str, dict] = {}

    def _init_database(self):
        """Inicializa banco: Supabase se configurado, senão SQLite local."""
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_SERVICE_KEY")

        if supabase_url and supabase_key:
            try:
                from content_pipeline.web.database_supabase import SupabaseDatabase
                db = SupabaseDatabase(url=supabase_url, key=supabase_key)
                logger.info("Database: Supabase (PostgreSQL) ✓")
                self._db_backend = "supabase"
                return db
            except Exception as e:
                logger.warning("Supabase indisponível (%s) — fallback para SQLite", e)

        db = StudioDatabase(self._studio_dir / "studio.db")
        db.migrate_from_json(self._studio_dir)
        logger.info("Database: SQLite local ✓")
        self._db_backend = "sqlite"
        return db

    def _init_subsystems(self, config: PipelineConfig) -> None:
        """Inicializa todos os subsistemas com as chaves atuais."""
        # Brand Enforcer (Design System como cabresto)
        brandbooks_dir = self._data_dir() / "brandbooks"
        self.brand_enforcer = BrandEnforcer(brandbooks_dir)

        # Budget Tracker
        self.budget_tracker = BudgetTracker(self._studio_dir / "budget.db")

        # Journey Log
        self.journey_log = JourneyLog(self._studio_dir / "journey.db")

        # LLM Client (OpenRouter)
        self.llm_client = OpenRouterClient(budget_tracker=self.budget_tracker)

        # Video Pipeline
        video_dir = config.output_dir / "video"
        self.kling_client = KlingClient(
            output_dir=video_dir / "kling",
            budget_tracker=self.budget_tracker,
        )
        self.veo3_client = Veo3Client(
            output_dir=video_dir / "veo3",
            budget_tracker=self.budget_tracker,
        )
        self.tts_client = ElevenLabsTTS(
            output_dir=video_dir / "audio",
            budget_tracker=self.budget_tracker,
        )
        self.video_assembler = VideoAssembler(output_dir=video_dir / "final")
        self.minimax_client = MinimaxClient(
            output_dir=video_dir / "minimax",
            budget_tracker=self.budget_tracker,
        )

        # Image Generation (fal.ai NB2 + FLUX)
        self.image_generator = FalImageGenerator(
            output_dir=config.output_dir / "generated",
            product_images_dir=config.product_images_dir,
            base_url=os.getenv("PUBLIC_BASE_URL", "https://studio.salkmedical.com"),
            budget_tracker=self.budget_tracker,
        )

        # Video Animator (facade)
        self.video_animator = VideoAnimator(
            minimax_client=self.minimax_client,
            kling_client=self.kling_client,
            veo3_client=self.veo3_client,
        )

        # Keyframe Processor
        self.keyframe_processor = KeyframeProcessor(
            image_generator=self.image_generator,
            output_dir=config.output_dir / "keyframes",
        )

        # Automation agents
        self.auto_briefing = AutoBriefing(
            llm_client=self.llm_client,
            brandbooks_loader=self.load_brandbook,
            claims_loader=self.load_claims_bank,
        )
        self.auto_prompt = AutoPromptNB2(
            llm_client=self.llm_client,
            brandbook_loader=self.load_brandbook,
        )
        self.disaster_check = DisasterCheck(
            llm_client=self.llm_client,
            brandbook_loader=self.load_brandbook,
        )
        self.atomizer = SemanticAtomizer(llm_client=self.llm_client)

        # Week Orchestrator (produção automatizada da semana)
        self.week_orchestrator = WeekOrchestrator(
            auto_briefing=self.auto_briefing,
            auto_prompt=self.auto_prompt,
            copywriter_factory=lambda brand: BrandCopywriter(self.llm_client, brand),
            atomizer=self.atomizer,
            db=self.db,
            brandbook_loader=self.load_brandbook,
        )

        # Atualizar preview_mode baseado em chaves disponíveis (antes dos publishers)
        has_gemini = bool(self.settings.get("GOOGLE_API_KEY"))
        if has_gemini and self.preview_mode:
            self.preview_mode = False
            logger.info("Gemini API key detectada — modo produção ativado")

        # Publishers (usam o preview_mode já atualizado)
        preview = self.preview_mode
        self.publishers: dict[str, PublisherBase] = {
            "instagram": InstagramPublisher(preview_mode=preview),
            "linkedin": LinkedInPublisher(preview_mode=preview),
            "facebook": FacebookPublisher(preview_mode=preview),
            "youtube": YouTubePublisher(preview_mode=preview),
        }
        self.metrics_collector = MetricsCollector(
            publishers=self.publishers, db=self.db,
        )
        self.batch_approval = BatchApproval(
            db=self.db, brand_enforcer=self.brand_enforcer,
        )
        self.feedback_loop = FeedbackLoop(
            db=self.db, journey_log=self.journey_log,
        )
        self.weekly_report = WeeklyReport(
            db=self.db,
            budget_tracker=self.budget_tracker,
            feedback_loop=self.feedback_loop,
        )

    def reload_settings(self) -> dict:
        """Recarrega settings e reinicializa clientes que dependem de API keys."""
        self.settings.apply_to_env()
        self._init_subsystems(self.config)
        return {"status": "reloaded", "preview_mode": self.preview_mode}

    async def generate_smart_briefing(
        self,
        brand: str,
        platform: str,
        pillar: str,
        product: str = "",
        persona: str = "",
        day: str = "",
    ) -> dict:
        """Gera briefing inteligente usando feedback de performance anterior."""
        # 1. Get recommendations from feedback loop
        recommendations = self.feedback_loop.get_briefing_recommendations(brand)

        # 2. Build enriched context from recommendations
        context_parts: list[str] = []
        if recommendations.get("insights"):
            context_parts.append("INSIGHTS DE PERFORMANCE ANTERIOR:")
            for insight in recommendations["insights"][:5]:
                context_parts.append(f"- {insight}")
        if recommendations.get("best_formats"):
            context_parts.append(
                f"FORMATOS COM MELHOR PERFORMANCE: {', '.join(recommendations['best_formats'][:3])}"
            )
        if recommendations.get("best_pillars"):
            context_parts.append(
                f"PILARES COM MELHOR ENGAJAMENTO: {', '.join(recommendations['best_pillars'][:3])}"
            )
        if recommendations.get("avoid"):
            context_parts.append("EVITAR:")
            for item in recommendations["avoid"][:3]:
                context_parts.append(f"- {item}")

        enriched_context = "\n".join(context_parts) if context_parts else ""

        # 3. Generate briefing with enriched context
        result = await self.auto_briefing.generate(
            brand=brand,
            platform=platform,
            pillar=pillar,
            product=product,
            persona=persona,
            day=day,
            context=enriched_context,
        )

        # 4. Tag the result
        result["smart_mode"] = True
        result["recommendations_used"] = bool(context_parts)
        result["recommendation_count"] = len(context_parts)

        return result

    @property
    def orchestrator(self):
        if self._orchestrator is None and not self.preview_mode:
            from content_pipeline.pipeline.orchestrator import PipelineOrchestrator
            self._orchestrator = PipelineOrchestrator(self.config)
        return self._orchestrator

    def _data_dir(self) -> Path:
        # Procurar squads/content-production/data a partir do project_root
        # ou subindo até o monorepo root (onde .git está)
        candidates = [
            self.config.project_root / "squads" / "content-production" / "data",
        ]
        # Subir até encontrar o diretório squads (monorepo root)
        for parent in self.config.project_root.parents:
            candidates.append(parent / "squads" / "content-production" / "data")
            if (parent / ".git").exists():
                break
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]  # fallback

    def _load_yaml(self, filename: str) -> dict | list:
        path = self._data_dir() / filename
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # =========================================================================
    # DADOS YAML — Referência (todos os data files do squad)
    # =========================================================================

    def load_platform_specs(self) -> dict:
        if self._platform_specs_cache is None:
            self._platform_specs_cache = self._load_yaml("platform-specs.yaml")
        return self._platform_specs_cache

    def load_buyer_personas(self) -> list:
        if self._buyer_personas_cache is None:
            data = self._load_yaml("buyer-personas.yaml")
            if isinstance(data, dict):
                self._buyer_personas_cache = data.get("personas", [])
            else:
                self._buyer_personas_cache = data if isinstance(data, list) else []
        return self._buyer_personas_cache

    def load_hashtag_bank(self) -> dict:
        if self._hashtag_bank_cache is None:
            self._hashtag_bank_cache = self._load_yaml("hashtag-bank.yaml")
        return self._hashtag_bank_cache

    def load_editorial_template(self) -> dict:
        if self._editorial_template_cache is None:
            self._editorial_template_cache = self._load_yaml("editorial-calendar-template.yaml")
        return self._editorial_template_cache

    def load_prohibited_terms(self) -> dict:
        if self._prohibited_terms_cache is None:
            self._prohibited_terms_cache = self._load_yaml("prohibited-terms.yaml")
        return self._prohibited_terms_cache

    def load_brand_guidelines(self) -> dict:
        if self._brand_guidelines_cache is None:
            self._brand_guidelines_cache = self._load_yaml("brand-guidelines.yaml")
        return self._brand_guidelines_cache

    def load_brandbook(self, brand: str) -> Optional[dict]:
        """Carrega brandbook YAML de uma marca específica."""
        if brand in self._brandbooks_cache:
            return self._brandbooks_cache[brand]
        path = self._data_dir() / "brandbooks" / f"{brand}.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self._brandbooks_cache[brand] = data
        return data

    def list_brandbooks(self) -> list[dict]:
        """Lista resumo de todos os brandbooks disponíveis."""
        bb_dir = self._data_dir() / "brandbooks"
        if not bb_dir.exists():
            return []
        result = []
        for f in sorted(bb_dir.glob("*.yaml")):
            bb = self.load_brandbook(f.stem)
            if bb:
                result.append({
                    "brand": bb.get("brand", f.stem),
                    "full_name": bb.get("full_name", ""),
                    "priority": bb.get("priority", 99),
                    "focus": bb.get("focus", ""),
                    "tagline": bb.get("tagline", ""),
                })
        return result

    # =========================================================================
    # ASSETS — Imagens de produto, logos, claims
    # =========================================================================

    def _supabase_storage_url(self, bucket: str, path: str) -> str:
        """Retorna URL pública do Supabase Storage."""
        from urllib.parse import quote
        supabase_url = self.settings.get("SUPABASE_URL") or ""
        return f"{supabase_url}/storage/v1/object/public/{bucket}/{quote(path, safe='/')}"

    def scan_product_images(self) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}

        # Cloud mode — Supabase Storage has priority when configured
        if self.settings.get("SUPABASE_URL"):
            result = self._scan_supabase_bucket("produtos")
            if result:
                return result

        # Local mode — serve from filesystem
        images_dir = self.config.product_images_dir
        if images_dir.exists():
            for category_dir in sorted(images_dir.iterdir()):
                if not category_dir.is_dir():
                    continue
                items = []
                for img_file in sorted(category_dir.iterdir()):
                    if img_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        items.append({
                            "name": img_file.stem,
                            "path": str(img_file.relative_to(self.config.project_root)),
                            "url": f"/assets/produtos/{category_dir.name}/{img_file.name}",
                            "thumb_url": f"/api/assets/thumb/{category_dir.name}/{img_file.name}?w=200",
                            "size_kb": round(img_file.stat().st_size / 1024, 1),
                            "category": category_dir.name,
                        })
                if items:
                    result[category_dir.name] = items

        return result

    def _scan_supabase_bucket(self, bucket: str, prefix: str = "") -> dict[str, list[dict]]:
        """Lista arquivos de um bucket do Supabase Storage."""
        import httpx
        result: dict[str, list[dict]] = {}
        supabase_url = self.settings.get("SUPABASE_URL")
        supabase_key = self.settings.get("SUPABASE_SERVICE_KEY")
        if not supabase_url or not supabase_key:
            return result
        try:
            headers = {"Authorization": f"Bearer {supabase_key}"}
            # List top-level folders
            resp = httpx.post(
                f"{supabase_url}/storage/v1/object/list/{bucket}",
                headers=headers,
                json={"prefix": prefix, "limit": 1000},
                timeout=10,
            )
            if resp.status_code != 200:
                return result
            for item in resp.json():
                name = item.get("name", "")
                if item.get("id") is None:
                    # It's a folder — list contents
                    folder_resp = httpx.post(
                        f"{supabase_url}/storage/v1/object/list/{bucket}",
                        headers=headers,
                        json={"prefix": name, "limit": 1000},
                        timeout=10,
                    )
                    if folder_resp.status_code == 200:
                        items = []
                        for f in folder_resp.json():
                            fname = f.get("name", "")
                            if any(fname.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                                fpath = f"{name}/{fname}"
                                items.append({
                                    "name": Path(fname).stem,
                                    "url": self._supabase_storage_url(bucket, fpath),
                                    "size_kb": round((f.get("metadata", {}).get("size", 0)) / 1024, 1),
                                    "category": name,
                                })
                        if items:
                            result[name] = items
                else:
                    # It's a file at root level
                    if any(name.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                        cat = "geral"
                        result.setdefault(cat, []).append({
                            "name": Path(name).stem,
                            "url": self._supabase_storage_url(bucket, name),
                            "size_kb": round((item.get("metadata", {}).get("size", 0)) / 1024, 1),
                            "category": cat,
                        })
        except Exception as e:
            logger.warning("Failed to list Supabase bucket %s: %s", bucket, e)
        return result

    def scan_logos(self) -> list[dict]:
        # Cloud mode — Supabase Storage has priority when configured
        if self.settings.get("SUPABASE_URL"):
            bucket_data = self._scan_supabase_bucket("logos")
            logos = []
            for items in bucket_data.values():
                logos.extend(items)
            if logos:
                return logos

        # Local mode — serve from filesystem
        logos_dir = self.config.assets_dir / "logomarcas"
        if not logos_dir.exists():
            logos_dir = self.config.assets_dir / "logos"

        if logos_dir.exists():
            logos = []
            for logo_file in sorted(logos_dir.rglob("*")):
                if logo_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg"):
                    rel = logo_file.relative_to(logos_dir)
                    logos.append({
                        "name": logo_file.stem,
                        "path": str(logo_file.relative_to(self.config.project_root)),
                        "url": f"/assets/logos/{str(rel).replace(chr(92), '/')}",
                        "size_kb": round(logo_file.stat().st_size / 1024, 1),
                        "category": logo_file.parent.name if logo_file.parent != logos_dir else "geral",
                    })
            return logos

        return []

    def load_claims_bank(self) -> list[dict]:
        claims_file = self._data_dir() / "claims-bank.yaml"
        if not claims_file.exists():
            return []

        data = yaml.safe_load(claims_file.read_text(encoding="utf-8"))
        claims = []

        if isinstance(data, dict):
            for product_key, product_data in data.items():
                if isinstance(product_data, list):
                    for claim in product_data:
                        if isinstance(claim, dict) and "id" in claim:
                            claims.append({
                                "claim_id": claim.get("id", ""),
                                "texto": claim.get("claim", claim.get("texto", "")),
                                "fonte": claim.get("source", claim.get("fonte", "")),
                                "status": claim.get("status", "APROVADO"),
                                "produto": product_key,
                            })
                elif isinstance(product_data, dict):
                    for claim in product_data.get("claims", []):
                        if isinstance(claim, dict):
                            claims.append({
                                "claim_id": claim.get("id", ""),
                                "texto": claim.get("claim", claim.get("texto", "")),
                                "fonte": claim.get("source", claim.get("fonte", "")),
                                "status": claim.get("status", "APROVADO"),
                                "produto": product_key,
                            })

        return claims

    # =========================================================================
    # VDPs — Listagem, detalhes, criação
    # =========================================================================

    def list_vdps(self) -> list[dict]:
        vdps = []
        vdp_base = self.config.vdp_dir

        if not vdp_base.exists():
            return vdps

        for md_file in sorted(vdp_base.rglob("*.md")):
            try:
                spec = self.vdp_loader.load(md_file)
                vdps.append(self._spec_to_summary(spec))
            except Exception as e:
                logger.debug("Ignorando %s: %s", md_file.name, e)

        return vdps

    def load_vdp(self, relative_path: str) -> Optional[dict]:
        full_path = self.config.vdp_dir / relative_path
        if not full_path.exists():
            full_path = self.config.project_root / relative_path

        if not full_path.exists():
            return None

        spec = self.vdp_loader.load(full_path)
        return self._spec_to_detail(spec)

    def create_vdp(self, data: dict) -> dict:
        """Cria novo VDP a partir dos dados do formulário."""
        output_dir = self.config.vdp_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r"[^a-z0-9]+", "-", data["produto"].lower()).strip("-")
        marca = data.get("marca", "salk").lower()
        filename = f"hero-{slug}-v1.md"

        # Evitar sobrescrever
        counter = 1
        while (output_dir / filename).exists():
            counter += 1
            filename = f"hero-{slug}-v{counter}.md"

        claims_block = ""
        if data.get("claims"):
            claims_block = "| ID | Claim | Fonte |\n|---|---|---|\n"
            all_claims = self.load_claims_bank()
            claims_map = {c["claim_id"]: c for c in all_claims}
            for cid in data["claims"]:
                c = claims_map.get(cid, {})
                claims_block += f"| {cid} | {c.get('texto', '')} | {c.get('fonte', '')} |\n"

        criterios_block = ""
        if data.get("criterios"):
            criterios_block = "\n".join(f"- {c}" for c in data["criterios"])
        else:
            criterios_block = (
                "- Produto central e dominante no frame\n"
                "- Iluminação dramática com reflexo\n"
                "- Sem texto ou logo na imagem\n"
                "- Sem equipamentos médicos concorrentes\n"
                "- Cores fiéis ao produto real"
            )

        logo_line = "Mendel Medical" if marca == "mendel" else "Salk Medical"

        content = f"""# VDP — {data['produto']}

**Produto:** {data['produto']}
**Marca:** {marca.title()}
**Conceito:** {data.get('conceito', 'Hero Shot')}
**Formato:** {data.get('formato', '1080x1350')}
**PNG Referência:** {data.get('png_referencia', '')}

---

## 1. Prompt NB2

{data.get('prompt_nb2', '')}

---

## 2. Checklist Pós-Geração

- [ ] Produto fiel ao PNG de referência
- [ ] Sem texto ou logotipo na imagem
- [ ] Sem equipamentos médicos além do produto-alvo
- [ ] Iluminação e reflexo adequados
- [ ] Cores fiéis ao produto real

---

## 3. Composição Canva

**Headline:** {data.get('canva_headline', '')}
**Logo:** {logo_line}
**Spec Line:** {data.get('canva_spec_line', '')}
**ANVISA:** {data.get('canva_anvisa', '')}
**Template:** {data.get('canva_template', 'hero-shot')}

---

## 4. Claims Regulatórios

{claims_block if claims_block else '*(Nenhum claim associado)*'}

---

## 5. Critérios de Aprovação

{criterios_block}
"""

        vdp_path = output_dir / filename
        vdp_path.write_text(content, encoding="utf-8")

        # Retornar o VDP criado
        spec = self.vdp_loader.load(vdp_path)
        return self._spec_to_detail(spec)

    def get_presets(self) -> dict:
        return {
            "camera": {k: v for k, v in CAMERA_PRESETS.items()},
            "lighting": {k: v for k, v in LIGHTING_PRESETS.items()},
            "surface": {k: v for k, v in SURFACE_PRESETS.items()},
        }

    def preview_prompt(
        self,
        product_type: str,
        scene_description: str,
        lighting_preset: str = "dramatic_three_point",
        camera_preset: str = "dramatic_studio",
        surface_preset: str = "reflective_black",
        style: str = "",
        mood: str = "",
        is_lev: bool = False,
        width: int = 1080,
        height: int = 1350,
    ) -> dict:
        prompt = self.prompt_builder.build_hero_prompt(
            product_type=product_type,
            scene_description=scene_description,
            lighting_preset=lighting_preset,
            camera_preset=camera_preset,
            surface_preset=surface_preset,
            style=style,
            mood=mood,
            is_lev=is_lev,
            width=width,
            height=height,
        )
        return {
            "prompt": prompt,
            "char_count": len(prompt),
            "presets_used": {
                "camera": camera_preset,
                "lighting": lighting_preset,
                "surface": surface_preset,
            },
        }

    # =========================================================================
    # DASHBOARD
    # =========================================================================

    def get_dashboard_stats(self) -> dict:
        summary = self.output_manager.get_output_summary()
        product_images = self.scan_product_images()
        logos = self.scan_logos()
        vdps = self.list_vdps()
        claims = self.load_claims_bank()
        pieces = self.list_pieces()

        in_production = sum(1 for p in pieces if p.get("stage") not in ("approved", "published"))
        pending_review = sum(1 for p in pieces if p.get("stage") == "review")
        approved = sum(1 for p in pieces if p.get("stage") in ("approved", "published"))
        published = sum(1 for p in pieces if p.get("stage") == "published")

        # Stage breakdown
        stages = {}
        for p in pieces:
            s = p.get("stage", "briefing")
            stages[s] = stages.get(s, 0) + 1

        # Brand breakdown
        brands = {}
        for p in pieces:
            b = p.get("brand", "salk")
            brands[b] = brands.get(b, 0) + 1

        # Platform breakdown
        platforms = {}
        for p in pieces:
            pl = p.get("platform", "")
            if pl:
                platforms[pl] = platforms.get(pl, 0) + 1

        # Calendar stats
        cal_week_ids = self.db.list_calendars() if hasattr(self.db, 'list_calendars') else []
        total_slots = 0
        filled_slots = 0
        for wid in cal_week_ids:
            cal = self.db.load_calendar(wid)
            if not cal:
                continue
            slots = cal.get("slots", [])
            total_slots += len(slots)
            filled_slots += sum(1 for s in slots if s.get("piece_id") or s.get("status") == "produced")

        # Compliance stats from prohibited terms YAML
        prohibited = self.load_prohibited_terms()
        total_rules = sum(
            len(v.get("terms", []) + v.get("items", []))
            for v in prohibited.values()
            if isinstance(v, dict)
        )

        # Reviews stats
        reviews = self.list_reviews()
        reviews_pending = sum(1 for r in reviews if r.get("verdict") == "pending")
        reviews_approved = sum(1 for r in reviews if r.get("verdict") == "approved")
        reviews_rejected = sum(1 for r in reviews if r.get("verdict") == "rejected")

        # Weekly production (pieces created in last 7 days)
        from datetime import datetime, timedelta
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        pieces_this_week = sum(1 for p in pieces if p.get("created_at", "") >= week_ago)

        return {
            "total_vdps": len(vdps),
            "images_generated": summary["nb2_images"],
            "total_size_mb": round(summary["total_size_mb"], 2),
            "compositions": summary["compositions"],
            "preview_mode": self.preview_mode,
            "products_available": sum(len(v) for v in product_images.values()),
            "logos_available": len(logos),
            "claims_available": len(claims),
            "pieces_in_production": in_production,
            "pieces_pending_review": pending_review,
            "pieces_approved": approved,
            "pieces_published": published,
            "pieces_total": len(pieces),
            "pieces_this_week": pieces_this_week,
            "stage_breakdown": stages,
            "brand_breakdown": brands,
            "platform_breakdown": platforms,
            "calendar_weeks": len(cal_week_ids),
            "calendar_total_slots": total_slots,
            "calendar_filled_slots": filled_slots,
            "compliance_rules_active": total_rules,
            "reviews_pending": reviews_pending,
            "reviews_approved": reviews_approved,
            "reviews_rejected": reviews_rejected,
        }

    def get_recent_log(self, limit: int = 20) -> list[dict]:
        log_path = self.config.output_dir / "logs" / "production-log.jsonl"
        if not log_path.exists():
            return []

        entries = []
        for line in log_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return entries[-limit:]

    # =========================================================================
    # PRODUCTION BOARD (Tempo) — Kanban de peças
    # =========================================================================

    def list_pieces(self, stage: str = "", brand: str = "") -> list[dict]:
        return self.db.list_pieces(stage=stage, brand=brand)

    def get_piece(self, piece_id: str) -> Optional[dict]:
        return self.db.get_piece(piece_id)

    def create_piece(self, data: dict) -> dict:
        return self.db.create_piece(data)

    def update_piece_stage(self, piece_id: str, stage: str, notes: str = "") -> Optional[dict]:
        return self.db.update_piece_stage(piece_id, stage, notes)

    def update_piece(self, piece_id: str, data: dict) -> Optional[dict]:
        return self.db.update_piece(piece_id, data)

    def delete_piece(self, piece_id: str) -> bool:
        return self.db.delete_piece(piece_id)

    # =========================================================================
    # COMPLIANCE (Shield) — Verificação de termos proibidos
    # =========================================================================

    def check_compliance(self, text: str, brand: str = "", product: str = "") -> dict:
        prohibited = self.load_prohibited_terms()
        violations = []
        warnings = []
        etrus_blocked = False

        text_lower = text.lower()

        # ── Iterate top-level YAML keys (produtos_bloqueados, superlativos, etc.) ──
        skip_keys = {"version", "last_updated", "owner", "severity", "safe_translations"}
        for cat_name, cat_data in prohibited.items():
            if cat_name in skip_keys or not isinstance(cat_data, dict):
                continue

            severity = cat_data.get("severity", "HIGH")
            terms = cat_data.get("terms", [])
            items = cat_data.get("items", [])

            # Handle 'terms' list (dicts with term/reason/alternative)
            for term_entry in terms:
                if isinstance(term_entry, str):
                    term = term_entry
                    reason = cat_name
                    alternative = ""
                elif isinstance(term_entry, dict):
                    term = term_entry.get("term", term_entry.get("text", ""))
                    reason = term_entry.get("reason", cat_name)
                    alternative = term_entry.get("alternative", term_entry.get("safe", ""))
                else:
                    continue

                if not term:
                    continue

                # Skip terms with bracket placeholders like "[marca X]"
                search_term = term.lower()
                if "[" in search_term:
                    # Extract the fixed part before the bracket for matching
                    fixed_part = search_term.split("[")[0].strip()
                    if not fixed_part or fixed_part not in text_lower:
                        continue
                elif search_term not in text_lower:
                    continue

                entry = {
                    "term": term,
                    "category": cat_name,
                    "severity": severity,
                    "reason": reason,
                    "alternative": alternative,
                }

                if severity == "CRITICAL":
                    violations.append(entry)
                else:
                    warnings.append(entry)

            # Handle 'items' list (plain strings, e.g. visual_prohibitions)
            for item in items:
                if isinstance(item, str) and item.lower() in text_lower:
                    entry = {
                        "term": item,
                        "category": cat_name,
                        "severity": severity,
                        "reason": cat_data.get("reference", cat_name),
                        "alternative": "",
                    }
                    if severity == "CRITICAL":
                        violations.append(entry)
                    else:
                        warnings.append(entry)

        # ── Check ETRUS (sempre crítico — redundância intencional) ──
        etrus_patterns = ["etrus", "novo foco cirúrgico", "novo foco cirurgico", "new surgical focus"]
        already_found = {v["term"].lower() for v in violations}
        for pat in etrus_patterns:
            if pat in text_lower and pat not in already_found:
                etrus_blocked = True
                violations.append({
                    "term": pat,
                    "category": "blocked_products",
                    "severity": "CRITICAL",
                    "reason": "ETRUS NÃO lançado — PROIBIDO publicar",
                    "alternative": "Use LEV",
                })
            elif pat in text_lower:
                etrus_blocked = True

        # ── Claims validation against claims-bank.yaml ──
        claims_result = self._validate_claims(text, product)

        # ── Brand Enforcer (Design System como cabresto) ──
        if brand:
            brand_result = self.brand_enforcer.validate(text, brand, context="copy")
            for v in brand_result.violations:
                violations.append({
                    "term": v.detail,
                    "category": f"brand_{v.rule}",
                    "severity": "CRITICAL" if v.severity == "BLOQUEANTE" else "HIGH",
                    "reason": v.detail,
                    "alternative": v.suggestion,
                })
            for w in brand_result.warnings:
                warnings.append({
                    "term": w.detail,
                    "category": f"brand_{w.rule}",
                    "severity": w.severity,
                    "reason": w.detail,
                    "alternative": w.suggestion,
                })

        passed = len(violations) == 0
        return {
            "passed": passed,
            "violations": violations,
            "warnings": warnings,
            "claims_valid": claims_result["valid"],
            "claims_detail": claims_result,
            "etrus_blocked": etrus_blocked,
            "terms_checked": sum(
                len(v.get("terms", []) + v.get("items", []))
                for v in prohibited.values()
                if isinstance(v, dict)
            ),
        }

    def _validate_claims(self, text: str, product: str = "") -> dict:
        """Validate technical claims in text against claims-bank.yaml."""
        claims_bank = self.load_claims_bank()
        if not claims_bank:
            return {"valid": True, "approved_used": [], "unapproved": [], "suggestions": []}

        # Flatten all approved claims from the bank
        approved_claims = {}
        for item in claims_bank:
            if isinstance(item, dict):
                cid = item.get("id", item.get("claim_id", ""))
                claim_text = item.get("claim", item.get("texto", ""))
                status = item.get("status", "APROVADO")
                prod = item.get("produto", item.get("product", ""))
                if cid and claim_text:
                    approved_claims[cid] = {
                        "claim": claim_text,
                        "status": status,
                        "product": prod,
                        "accessible": item.get("accessible", ""),
                    }

        text_lower = text.lower()
        approved_used = []
        suggestions = []

        # Check which approved claims appear in the text
        for cid, cdata in approved_claims.items():
            claim_lower = cdata["claim"].lower()
            # Check if key technical phrases from the claim appear
            if any(
                phrase in text_lower
                for phrase in _extract_claim_phrases(claim_lower)
            ):
                if cdata["status"] == "APROVADO":
                    approved_used.append(cid)
                else:
                    suggestions.append({
                        "claim_id": cid,
                        "issue": f"Claim {cid} status: {cdata['status']} (não APROVADO)",
                    })

        # Check for numeric specs that might be unapproved claims
        import re
        spec_patterns = [
            r'\d+[\.,]?\d*\s*(?:lux|klux)',
            r'\d+[\.,]?\d*\s*(?:kg|mm|cm)',
            r'(?:ra|r9|cri)\s*[=≥>]\s*\d+',
            r'ip\s*\d{2}',
            r'\d+[\.,]?\d*\s*(?:k|kelvin)',
        ]
        unapproved = []
        for pat in spec_patterns:
            matches = re.findall(pat, text_lower)
            for match in matches:
                # Check if this spec is part of any approved claim
                found_in_approved = any(
                    match in cdata["claim"].lower()
                    for cdata in approved_claims.values()
                )
                if not found_in_approved:
                    unapproved.append({
                        "spec": match,
                        "issue": "Especificação técnica não encontrada no banco de claims aprovados",
                    })

        return {
            "valid": len(unapproved) == 0,
            "approved_used": approved_used,
            "unapproved": unapproved,
            "suggestions": suggestions,
            "total_approved_claims": len(approved_claims),
        }

    # =========================================================================
    # REVIEW QUEUE (Lens) — Fila de revisão
    # =========================================================================

    def list_reviews(self, verdict: str = "") -> list[dict]:
        return self.db.list_reviews(verdict=verdict)

    def create_review(self, data: dict) -> dict:
        return self.db.create_review(data)

    def update_review(self, review_id: str, verdict: str, comments: str = "") -> Optional[dict]:
        result = self.db.update_review(review_id, verdict, comments)
        if result:
            # Se aprovado, avançar a peça
            if verdict == "approved" and result.get("piece_id"):
                self.update_piece_stage(result["piece_id"], "approved")
            elif verdict == "rejected" and result.get("piece_id"):
                self.update_piece_stage(result["piece_id"], "copy", notes="Revisão rejeitada: " + comments)
        return result

    # =========================================================================
    # PERFORMANCE (Pulse) — Métricas pós-publicação
    # =========================================================================

    def list_metrics(self) -> list[dict]:
        return self.db.list_metrics()

    def save_metric(self, data: dict) -> dict:
        return self.db.save_metric(data)

    def get_performance_summary(self) -> dict:
        summary = self.db.get_performance_summary()
        if not summary:
            return {
                "total_posts": 0,
                "total_impressions": 0,
                "total_reach": 0,
                "total_engagement": 0,
                "avg_engagement_rate": 0,
                "by_platform": {},
            }

        total_impressions = sum(v.get("total_impressions", 0) for v in summary.values())
        total_reach = sum(v.get("total_reach", 0) for v in summary.values())
        total_engagement = sum(v.get("total_engagement", 0) for v in summary.values())
        total_posts = sum(v.get("count", 0) for v in summary.values())

        return {
            "total_posts": total_posts,
            "total_impressions": total_impressions,
            "total_reach": total_reach,
            "total_engagement": total_engagement,
            "avg_engagement_rate": round(
                (total_engagement / total_reach * 100) if total_reach > 0 else 0, 2
            ),
            "by_platform": summary,
        }

    # =========================================================================
    # CALENDAR v2
    # =========================================================================

    def list_calendars(self) -> list[str]:
        return self.db.list_calendars()

    def load_calendar(self, week_id: str) -> Optional[dict]:
        return self.db.load_calendar(week_id)

    def save_calendar(self, week_id: str, data: dict) -> None:
        self.db.save_calendar(week_id, data)

    def auto_fill_calendar(self, week_id: str, brand: str = "salk") -> dict:
        """Gera calendário E preenche slots automaticamente."""
        cal = self.load_calendar(week_id)
        if not cal:
            cal = self.generate_calendar_from_template(week_id, brand)
        filled = self.week_orchestrator.auto_fill_calendar(cal, brand)
        self.save_calendar(week_id, filled)
        return filled

    async def produce_week(
        self,
        week_id: str,
        brand: str = "salk",
        generate_briefing: bool = True,
        generate_copy: bool = True,
        generate_prompt: bool = True,
        atomize: bool = True,
    ) -> dict:
        """Produz conteúdo completo para a semana (briefings, copy, prompts, atomização)."""
        cal = self.load_calendar(week_id)
        if not cal:
            cal = self.auto_fill_calendar(week_id, brand)
        return await self.week_orchestrator.produce_week(
            calendar=cal,
            generate_briefing=generate_briefing,
            generate_copy=generate_copy,
            generate_prompt=generate_prompt,
            atomize=atomize,
        )

    async def generate_full_week(self, week_id: str, brand: str = "salk") -> dict:
        """Fluxo completo: auto-fill + produção de toda a semana."""
        cal = self.generate_calendar_from_template(week_id, brand)
        filled = self.week_orchestrator.auto_fill_calendar(cal, brand)
        self.save_calendar(week_id, filled)
        return await self.week_orchestrator.produce_week(filled)

    def generate_calendar_from_template(self, week_id: str, brand: str = "salk") -> dict:
        """Gera calendário da semana baseado no template editorial."""
        template = self.load_editorial_template()

        # Tentar múltiplas chaves do template (salk_weekly_template, mendel_weekly_template, etc.)
        slots_template = (
            template.get(f"{brand}_weekly_template")
            or template.get("salk_weekly_template")
            or template.get("weekly_slots_template")
            or {}
        )

        slots = []
        day_map = {
            "segunda": "Segunda",
            "terca": "Terca",
            "quarta": "Quarta",
            "quinta": "Quinta",
            "sexta": "Sexta",
            # Fallback inglês
            "monday": "Segunda",
            "tuesday": "Terca",
            "wednesday": "Quarta",
            "thursday": "Quinta",
            "friday": "Sexta",
        }

        for day_key, day_name in day_map.items():
            day_data = slots_template.get(day_key)
            if not day_data:
                continue
            # O template pode ter {slots: [...]} ou ser diretamente uma lista
            day_slots = day_data.get("slots", day_data) if isinstance(day_data, dict) else day_data
            if isinstance(day_slots, list):
                for s in day_slots:
                    if isinstance(s, dict):
                        slots.append({
                            "id": str(uuid.uuid4())[:8],
                            "day": day_name,
                            "time": s.get("horario", s.get("time", s.get("best_time", ""))),
                            "platform": s.get("platform", ""),
                            "format": s.get("format", ""),
                            "product": "",
                            "pillar": "",
                            "brand": brand,
                            "status": "planned",
                            "piece_id": "",
                            "notes": "",
                            "persona_target": "",
                        })

        cal = {
            "week_id": week_id,
            "brand": brand,
            "year": 2026,
            "status": "draft",
            "slots": slots,
        }
        self.save_calendar(week_id, cal)
        return cal

    # =========================================================================
    # HASHTAG HELPER
    # =========================================================================

    def get_hashtags_for_brand(self, brand: str, platform: str = "instagram") -> dict:
        bank = self.load_hashtag_bank()

        # Map short brand names to YAML keys
        brand_key_map = {
            "salk": "salk_medical",
            "mendel": "mendel_medical",
            "manager": "manager_grupo",
            "dayho": "dayho",
        }
        yaml_key = brand_key_map.get(brand, brand)

        # Try mapped key first, then original, then inside "brands" dict
        brand_data = bank.get(yaml_key, bank.get(brand, {}))
        if not brand_data and "brands" in bank:
            brand_data = bank["brands"].get(yaml_key, bank["brands"].get(brand, {}))

        def _extract_tags(section) -> list:
            """Extract tags from a section that may be a list or a dict with 'tags' key."""
            if isinstance(section, list):
                return section
            if isinstance(section, dict):
                return section.get("tags", [])
            return []

        result = {
            "core": [],
            "product": [],
            "niche": [],
            "platform_specific": [],
            "usage_rules": bank.get("usage_rules", {}),
        }

        if isinstance(brand_data, dict):
            result["core"] = _extract_tags(brand_data.get("core", []))
            result["product"] = _extract_tags(
                brand_data.get("produto", brand_data.get("product", brand_data.get("tecnico", [])))
            )
            result["niche"] = _extract_tags(brand_data.get("nicho", brand_data.get("niche", [])))
            result["platform_specific"] = _extract_tags(
                brand_data.get(platform, brand_data.get(f"{platform}_tags", []))
            )

        return result

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _spec_to_summary(self, spec: VDPSpec) -> dict:
        return {
            "file_name": spec.file_path.name,
            "file_path": str(spec.file_path.relative_to(self.config.project_root))
            if str(spec.file_path).startswith(str(self.config.project_root))
            else str(spec.file_path),
            "produto": spec.produto,
            "marca": spec.marca,
            "conceito": spec.conceito,
            "formato": spec.formato,
            "png_referencia": spec.png_referencia,
            "prompt_length": len(spec.prompt_nb2),
            "claims_count": len(spec.claims),
            "criterios_count": len(spec.criterios_aprovacao),
            "is_salk": spec.is_salk,
            "is_mendel": spec.is_mendel,
            "slug": spec.product_slug,
        }

    def _spec_to_detail(self, spec: VDPSpec) -> dict:
        base = self._spec_to_summary(spec)
        base.update({
            "prompt_nb2": spec.prompt_nb2,
            "claims": [
                {"claim_id": c.claim_id, "texto": c.texto, "fonte": c.fonte}
                for c in spec.claims
            ],
            "criterios": spec.criterios_aprovacao,
            "canva_headline": spec.canva.headline,
            "canva_logo": spec.canva.logo,
            "canva_spec_line": spec.canva.spec_line,
            "canva_anvisa": spec.canva.anvisa_badge,
            "canva_template": spec.canva.template,
        })
        return base
