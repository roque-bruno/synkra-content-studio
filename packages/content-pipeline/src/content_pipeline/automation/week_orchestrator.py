"""
Week Orchestrator — Automação completa de produção editorial semanal.

Duas fases:
1. auto_fill_calendar(): Preenche slots do calendário automaticamente
   baseado na rotação de pilares, produtos ativos e histórico.
2. produce_week(): Gera briefings, copy, prompts NB2 e atomização
   para todos os slots de uma vez.

Resultado: gestora recebe a semana pronta para revisão.
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Rotação de pilares por marca (peso = % da semana)
PILLAR_WEIGHTS = {
    "salk": {
        "produto": 30,
        "educacional": 25,
        "cases": 20,
        "command": 15,
        "licitacoes": 10,
    },
    "mendel": {
        "produto_tecnico": 35,
        "engenharia": 30,
        "certificacoes": 20,
        "bastidores": 15,
    },
    "manager-grupo": {
        "cultura": 35,
        "inovacao": 25,
        "pessoas": 25,
        "institucional": 15,
    },
}

# Produtos ativos por marca (nunca incluir ETRUS)
ACTIVE_PRODUCTS = {
    "salk": ["lev", "kratus", "ostus", "kronus"],
    "mendel": ["lev", "kratus", "ostus", "kronus"],
    "manager-grupo": [],
    "dayho": [],
}

# Personas-alvo por pilar
PILLAR_PERSONAS = {
    "produto": ["eng_clinica", "compras", "equipe_medica"],
    "educacional": ["eng_clinica", "admin_hospitalar"],
    "cases": ["admin_hospitalar", "compras"],
    "command": ["eng_clinica", "equipe_medica"],
    "licitacoes": ["compras", "admin_hospitalar"],
    "produto_tecnico": ["eng_clinica"],
    "engenharia": ["eng_clinica"],
    "certificacoes": ["eng_clinica", "compras"],
    "bastidores": ["eng_clinica"],
}

# Técnicas preferidas por produto para prompt NB2
PRODUCT_TECHNIQUES = {
    "lev": {
        "technique": "dramatic_studio",
        "lighting": "dramatic_rim",
        "scene": "centro_cirurgico",
        "atmosphere": "premium_tech",
    },
    "kratus": {
        "technique": "hero_shot",
        "lighting": "high_contrast",
        "scene": "centro_cirurgico",
        "atmosphere": "clean_medical",
    },
    "ostus": {
        "technique": "environmental",
        "lighting": "soft_diffused",
        "scene": "centro_cirurgico",
        "atmosphere": "modern_minimal",
    },
    "kronus": {
        "technique": "detail_macro",
        "lighting": "clinical_bright",
        "scene": "centro_cirurgico",
        "atmosphere": "premium_tech",
    },
}

# Formato de imagem por formato de plataforma
FORMAT_MAP = {
    "Carousel 4:5": "square_social",
    "Reel 9:16": "portrait_story",
    "Post 1:1": "square_social",
    "Imagem 1200x627": "4k_landscape",
    "Banner": "wide_banner",
    "Texto+Imagem": "square_social",
    "PDF Carousel": "square_social",
    "Vídeo/Post": "square_social",
    "Shorts 9:16": "portrait_story",
    "Vídeo <90s": "4k_landscape",
}


class WeekOrchestrator:
    """Orquestra a produção editorial de uma semana completa."""

    def __init__(
        self,
        auto_briefing,
        auto_prompt,
        copywriter_factory,
        atomizer,
        db,
        brandbook_loader=None,
        feedback_loop=None,
    ):
        self.briefing = auto_briefing
        self.prompt = auto_prompt
        self.copywriter_factory = copywriter_factory
        self.atomizer = atomizer
        self.db = db
        self._load_brandbook = brandbook_loader
        self.feedback = feedback_loop

    # =====================================================================
    # FASE 1: Auto-fill do calendário
    # =====================================================================

    def auto_fill_calendar(
        self,
        calendar: dict,
        brand: str = "salk",
        strategy: str = "balanced",
    ) -> dict:
        """
        Preenche slots vazios do calendário automaticamente.

        Distribui pilares segundo pesos, alterna produtos,
        atribui personas-alvo relevantes.

        Args:
            calendar: Calendário com slots vazios (do generate_calendar_from_template)
            brand: Marca principal
            strategy: 'balanced' (rotação uniforme) ou 'performance' (prioriza top performers)

        Returns:
            Calendário com slots preenchidos (pilar, produto, persona_target)
        """
        slots = calendar.get("slots", [])
        if not slots:
            return calendar

        weights = PILLAR_WEIGHTS.get(brand, PILLAR_WEIGHTS.get("salk", {}))
        products = ACTIVE_PRODUCTS.get(brand, [])

        # Calcular distribuição de pilares para a semana
        total_slots = len(slots)
        pillar_distribution = self._distribute_pillars(weights, total_slots)

        # Embaralhar para não ficar previsível
        random.shuffle(pillar_distribution)

        # Ciclo de produtos (alterna uniformemente)
        product_cycle = self._product_cycle(products, total_slots)

        for i, slot in enumerate(slots):
            # Não sobrescrever slots já preenchidos
            if slot.get("pillar") and slot.get("product"):
                continue

            pillar = pillar_distribution[i] if i < len(pillar_distribution) else "produto"

            # Produto: pilares de produto usam produto real, outros podem ser vazio
            product = ""
            if pillar in ("produto", "produto_tecnico", "command") and products:
                product = product_cycle[i % len(product_cycle)]
            elif pillar in ("educacional", "cases", "licitacoes") and products:
                # Educacional/cases pode referenciar produto como contexto
                product = product_cycle[i % len(product_cycle)]

            # Persona-alvo
            personas = PILLAR_PERSONAS.get(pillar, ["eng_clinica"])
            persona = personas[i % len(personas)]

            slot["pillar"] = pillar
            slot["product"] = product
            slot["persona_target"] = persona
            slot["brand"] = brand
            slot["status"] = "planned"

        calendar["status"] = "planned"
        calendar["auto_filled"] = True
        calendar["filled_at"] = datetime.utcnow().isoformat()

        return calendar

    def _distribute_pillars(self, weights: dict, total: int) -> list[str]:
        """Distribui pilares proporcionalmente aos pesos."""
        distribution = []
        remaining = total

        # Ordenar por peso (maior primeiro)
        sorted_pillars = sorted(weights.items(), key=lambda x: x[1], reverse=True)

        for pillar, weight in sorted_pillars:
            count = max(1, round(total * weight / 100))
            count = min(count, remaining)
            distribution.extend([pillar] * count)
            remaining -= count
            if remaining <= 0:
                break

        # Se sobrou, preencher com o pilar principal
        while len(distribution) < total:
            distribution.append(sorted_pillars[0][0])

        return distribution[:total]

    def _product_cycle(self, products: list[str], total: int) -> list[str]:
        """Cria ciclo de produtos que alterna uniformemente."""
        if not products:
            return [""] * total
        cycle = []
        for i in range(total):
            cycle.append(products[i % len(products)])
        return cycle

    # =====================================================================
    # FASE 2: Produção batch — gera tudo para a semana
    # =====================================================================

    async def produce_week(
        self,
        calendar: dict,
        generate_briefing: bool = True,
        generate_copy: bool = True,
        generate_prompt: bool = True,
        atomize: bool = True,
    ) -> dict:
        """
        Produz conteúdo para todos os slots do calendário.

        Encadeia: briefing → copy → prompt NB2 → atomização
        Salva cada peça no banco.

        Args:
            calendar: Calendário com slots preenchidos (auto_fill ou manual)
            generate_briefing: Gerar briefings via Atlas
            generate_copy: Gerar copy via copywriter da marca
            generate_prompt: Gerar prompt NB2 via Apex
            atomize: Gerar derivativos via Nova

        Returns:
            Resultado com contadores e peças geradas
        """
        slots = calendar.get("slots", [])
        week_id = calendar.get("week_id", "unknown")
        brand = calendar.get("brand", "salk")

        results = {
            "week_id": week_id,
            "brand": brand,
            "total_slots": len(slots),
            "briefings_generated": 0,
            "copies_generated": 0,
            "prompts_generated": 0,
            "atomizations": 0,
            "pieces_created": 0,
            "errors": [],
            "pieces": [],
        }

        for slot in slots:
            if not slot.get("pillar"):
                continue  # Slot vazio, pular

            try:
                piece = await self._produce_slot(
                    slot=slot,
                    brand=brand,
                    week_id=week_id,
                    generate_briefing=generate_briefing,
                    generate_copy=generate_copy,
                    generate_prompt=generate_prompt,
                    atomize=atomize,
                )

                # Atualizar contadores
                if piece.get("briefing"):
                    results["briefings_generated"] += 1
                if piece.get("copy"):
                    results["copies_generated"] += 1
                if piece.get("nb2_prompt"):
                    results["prompts_generated"] += 1
                if piece.get("derivatives"):
                    results["atomizations"] += 1

                results["pieces_created"] += 1
                results["pieces"].append(piece)

                # Atualizar slot com piece_id
                slot["piece_id"] = piece.get("id", "")
                slot["status"] = "in_progress"

            except Exception as e:
                logger.error("Erro ao produzir slot %s: %s", slot.get("id"), e)
                results["errors"].append({
                    "slot_id": slot.get("id"),
                    "day": slot.get("day"),
                    "platform": slot.get("platform"),
                    "error": str(e),
                })

        # Salvar calendário atualizado
        calendar["status"] = "in_production"
        self.db.save_calendar(week_id, calendar)

        # Custo total
        results["total_cost_usd"] = sum(
            p.get("total_cost_usd", 0) for p in results["pieces"]
        )

        return results

    async def _produce_slot(
        self,
        slot: dict,
        brand: str,
        week_id: str,
        generate_briefing: bool,
        generate_copy: bool,
        generate_prompt: bool,
        atomize: bool,
    ) -> dict:
        """Produz conteúdo completo para um slot individual."""
        piece_id = str(uuid.uuid4())[:8]
        cost = 0.0
        piece = {
            "id": piece_id,
            "week_id": week_id,
            "slot_id": slot.get("id", ""),
            "day": slot.get("day", ""),
            "platform": slot.get("platform", ""),
            "format": slot.get("format", ""),
            "brand": brand,
            "product": slot.get("product", ""),
            "pillar": slot.get("pillar", ""),
            "persona_target": slot.get("persona_target", ""),
            "stage": "briefing",
            "briefing": None,
            "copy": None,
            "nb2_prompt": None,
            "derivatives": None,
            "total_cost_usd": 0,
            "created_at": datetime.utcnow().isoformat(),
        }

        # 1. BRIEFING (Atlas)
        if generate_briefing:
            briefing_result = await self.briefing.generate(
                brand=brand,
                platform=slot.get("platform", "instagram"),
                pillar=slot.get("pillar", "produto"),
                product=slot.get("product", ""),
                persona=slot.get("persona_target", ""),
                day=slot.get("day", ""),
            )
            piece["briefing"] = briefing_result.get("briefing_text", "")
            cost += briefing_result.get("cost_usd", 0)
            logger.info(
                "Briefing gerado: %s %s [%s]",
                slot.get("day"), slot.get("platform"), slot.get("pillar"),
            )

        # 2. COPY (Helena/Roberto/Carolina/Marcos)
        if generate_copy and piece.get("briefing"):
            copywriter = self.copywriter_factory(brand)
            copy_result = await copywriter.write_copy(
                briefing=piece["briefing"],
                platform=self._normalize_platform(slot.get("platform", "")),
                format_type=slot.get("format", "post"),
            )
            piece["copy"] = copy_result.get("copy_text", "")
            piece["copywriter"] = copy_result.get("copywriter", "")
            cost += copy_result.get("cost_usd", 0)
            piece["stage"] = "copy"

        # 3. PROMPT NB2 (Apex)
        if generate_prompt and slot.get("product"):
            product = slot.get("product", "lev")
            tech = PRODUCT_TECHNIQUES.get(product, PRODUCT_TECHNIQUES["lev"])
            format_type = FORMAT_MAP.get(
                slot.get("format", ""), "square_social"
            )

            prompt_result = await self.prompt.generate_prompt(
                product=product,
                brand=brand,
                concept=slot.get("pillar", ""),
                technique=tech["technique"],
                lighting=tech["lighting"],
                scene=tech["scene"],
                composition="central_hero",
                atmosphere=tech["atmosphere"],
                format_type=format_type,
            )
            piece["nb2_prompt"] = {
                "positive": prompt_result.get("positive_prompt", ""),
                "negative": prompt_result.get("negative_prompt", ""),
                "dimensions": prompt_result.get("dimensions", {}),
                "warnings": prompt_result.get("warnings", []),
            }
            cost += prompt_result.get("cost_usd", 0)
            piece["stage"] = "prompt"

        # 4. ATOMIZAÇÃO (Nova) — gera derivativos para outras plataformas
        if atomize and piece.get("copy"):
            master_type = self._infer_master_type(slot.get("format", ""))
            atom_result = await self.atomizer.atomize(
                master_content=piece["copy"],
                master_type=master_type,
                brand=brand,
                context=f"Produto: {slot.get('product', '')}, Pilar: {slot.get('pillar', '')}",
            )
            piece["derivatives"] = atom_result.get("derivatives", {})
            piece["derivatives_count"] = atom_result.get("derivatives_count", 0)
            cost += sum(
                d.get("cost_usd", 0)
                for d in (atom_result.get("derivatives", {}) or {}).values()
                if isinstance(d, dict)
            )
            piece["stage"] = "ready"

        piece["total_cost_usd"] = round(cost, 4)

        # Mapear campos para o schema do DB antes de salvar
        db_piece = {
            "id": piece["id"],
            "title": f"{slot.get('pillar', 'conteudo').title()} — {slot.get('product', '').upper() or brand.title()} ({slot.get('platform', 'instagram')})",
            "brand": brand,
            "product": piece.get("product", ""),
            "pillar": piece.get("pillar", ""),
            "platform": piece.get("platform", ""),
            "format": piece.get("format", ""),
            "stage": piece.get("stage", "briefing"),
            "persona_target": piece.get("persona_target", ""),
            "calendar_slot_id": slot.get("id", ""),
            "copy_text": piece.get("copy", ""),
            "notes": json.dumps({
                "briefing": piece.get("briefing", ""),
                "nb2_prompt": piece.get("nb2_prompt"),
                "derivatives": piece.get("derivatives"),
                "derivatives_count": piece.get("derivatives_count", 0),
                "copywriter": piece.get("copywriter", ""),
                "week_id": week_id,
                "cost_usd": piece["total_cost_usd"],
            }),
            "created_at": piece.get("created_at"),
        }

        # Salvar peça no banco
        self.db.create_piece(db_piece)

        return piece

    def _normalize_platform(self, platform: str) -> str:
        """Normaliza nome da plataforma para o formato do copywriter."""
        p = platform.lower()
        if "instagram" in p:
            return "instagram"
        if "linkedin" in p:
            return "linkedin"
        if "facebook" in p:
            return "facebook"
        if "youtube" in p:
            return "youtube"
        return "instagram"

    def _infer_master_type(self, format_str: str) -> str:
        """Infere tipo master pelo formato do slot."""
        f = format_str.lower()
        if "carousel" in f or "carrossel" in f or "pdf" in f:
            return "carrossel"
        if "reel" in f or "short" in f or "vídeo" in f or "video" in f:
            return "video_longo"
        return "post_unico"

    # =====================================================================
    # CONVENIÊNCIA: gerar semana completa (auto-fill + produção)
    # =====================================================================

    async def generate_full_week(
        self,
        week_id: str,
        brand: str = "salk",
        calendar: Optional[dict] = None,
    ) -> dict:
        """
        Fluxo completo: auto-fill + produção de toda a semana.

        1. Preenche calendário automaticamente
        2. Gera briefings, copy, prompts NB2, atomização
        3. Salva tudo no banco
        4. Retorna resultado com peças prontas para revisão

        Args:
            week_id: ID da semana (ex: 2026-W16)
            brand: Marca principal
            calendar: Calendário existente (ou None para gerar novo)

        Returns:
            Resultado completo da produção
        """
        logger.info("=== PRODUÇÃO SEMANA %s [%s] ===", week_id, brand)

        # 1. Auto-fill
        if calendar:
            filled = self.auto_fill_calendar(calendar, brand)
        else:
            # Precisa gerar o calendário template primeiro (via service)
            filled = {"week_id": week_id, "brand": brand, "slots": []}

        logger.info(
            "Calendário preenchido: %d slots", len(filled.get("slots", []))
        )

        # 2. Produzir tudo
        result = await self.produce_week(filled)

        logger.info(
            "Produção completa: %d peças, %d briefings, %d copies, %d prompts, custo $%.4f",
            result["pieces_created"],
            result["briefings_generated"],
            result["copies_generated"],
            result["prompts_generated"],
            result.get("total_cost_usd", 0),
        )

        return result
