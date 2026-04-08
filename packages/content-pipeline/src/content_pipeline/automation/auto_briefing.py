"""
Auto-Briefing (Atlas) — Gera briefing automatico por slot do calendario.

Recebe: slot do calendario (dia, plataforma, pilar, marca, persona)
Produz: briefing completo com objetivo, mensagem-chave, CTA, tom, formato

Usa LLM barato (Flash) via OpenRouter para gerar.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Carregamento dinâmico de briefing-config.yaml
# ---------------------------------------------------------------------------
_BRIEFING_CONFIG_CACHE: Optional[dict] = None
_BRIEFING_DATA_DIR: Optional[Path] = None


def _load_briefing_config() -> dict:
    global _BRIEFING_CONFIG_CACHE
    if _BRIEFING_CONFIG_CACHE is not None:
        return _BRIEFING_CONFIG_CACHE
    if _BRIEFING_DATA_DIR:
        path = _BRIEFING_DATA_DIR / "briefing-config.yaml"
        if path.exists():
            try:
                _BRIEFING_CONFIG_CACHE = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return _BRIEFING_CONFIG_CACHE
            except Exception as e:
                logger.warning("Falha ao carregar briefing-config.yaml: %s", e)
    _BRIEFING_CONFIG_CACHE = {}
    return _BRIEFING_CONFIG_CACHE


def init_briefing_config(data_dir: Path) -> None:
    """Inicializa data_dir para carregamento do YAML."""
    global _BRIEFING_DATA_DIR, _BRIEFING_CONFIG_CACHE
    _BRIEFING_DATA_DIR = data_dir
    _BRIEFING_CONFIG_CACHE = None


def get_briefing_system_prompt() -> str:
    return _load_briefing_config().get("briefing_system_prompt", "")


class AutoBriefing:
    """Gera briefings automaticos para slots do calendario."""

    def __init__(self, llm_client, brandbooks_loader=None, claims_loader=None):
        self.llm = llm_client
        self._load_brandbook = brandbooks_loader
        self._load_claims = claims_loader

    async def generate(
        self,
        brand: str,
        platform: str,
        pillar: str,
        product: str = "",
        persona: str = "",
        day: str = "",
        context: str = "",
    ) -> dict:
        """
        Gera briefing para um slot do calendario.

        Returns:
            dict com briefing completo + metadados LLM
        """
        logger.info(
            "Generating briefing: brand=%s, product=%s, pillar=%s, platform=%s",
            brand, product, pillar, platform,
        )
        # Carregar contexto rico do brandbook
        brand_context = ""
        if self._load_brandbook:
            bb = self._load_brandbook(brand)
            if bb:
                # Info basica
                brand_context = f"Marca: {bb.get('full_name', brand)}\n"
                brand_context += f"Tagline: {bb.get('tagline', '')}\n"
                brand_context += f"Foco: {bb.get('focus', '')}\n"

                # Tom de voz completo
                tov = bb.get('tone_of_voice', {})
                if tov:
                    brand_context += f"Tom: {tov.get('primary', '')}\n"
                    brand_context += f"CTA style: {tov.get('cta_style', '')}\n"
                    prohibited = tov.get('prohibited', [])
                    if prohibited:
                        brand_context += f"Tom PROIBIDO: {', '.join(prohibited)}\n"

                # Produtos disponiveis (com tipo e regras)
                products_list = bb.get('products', [])
                active_products = [p for p in products_list if p.get('status') == 'ATIVO']
                if active_products:
                    brand_context += "\nPRODUTOS DISPONIVEIS:\n"
                    for p in active_products:
                        line = f"- {p.get('name', '')} ({p.get('type', '')})"
                        rules = p.get('special_rules', [])
                        if rules:
                            line += f" — Regras: {'; '.join(rules)}"
                        brand_context += line + "\n"

                # Personas-alvo
                personas = bb.get('target_personas', [])
                if personas:
                    brand_context += "\nPERSONAS-ALVO:\n"
                    for pers in personas:
                        brand_context += f"- {pers.get('name', '')} ({pers.get('role', '')}): preocupacoes = {', '.join(pers.get('concerns', []))}\n"

                # Pilares de conteudo
                pillars = bb.get('content_pillars', [])
                if pillars:
                    brand_context += "\nPILARES DE CONTEUDO:\n"
                    for pil in pillars:
                        brand_context += f"- {pil.get('name', '')} ({pil.get('percentage', 0)}%): {pil.get('description', '')}\n"

                # Regras visuais
                visual = bb.get('visual_rules', {})
                if visual:
                    brand_context += "\nREGRAS VISUAIS:\n"
                    for k, v in visual.items():
                        brand_context += f"- {k}: {v}\n"

        # Carregar claims aprovados relevantes
        claims_context = ""
        if self._load_claims:
            all_claims = self._load_claims()
            if all_claims:
                # Filtrar por produto se especificado
                if product:
                    relevant = [c for c in all_claims if product.lower() in c.get('produto', '').lower()]
                else:
                    relevant = all_claims[:20]  # Top 20 para institucional
                if relevant:
                    claims_context = "\nCLAIMS APROVADOS (use SOMENTE estes — NUNCA inventar):\n"
                    for c in relevant[:15]:
                        claims_context += f"- [{c.get('claim_id', '')}] {c.get('texto', '')}\n"

        prompt = f"""Crie um briefing de conteudo para:
- Marca: {brand}
- Plataforma: {platform}
- Pilar: {pillar}
- Produto: {product or 'a definir — escolha o produto MAIS RELEVANTE ao tema entre: LEV (foco cirurgico), KRATUS (mesa cirurgica), OSTUS (pendente), KRONUS (monitor). Justifique a escolha no campo produto_recomendado.'}
- Persona-alvo: {persona or 'geral'}
- Dia: {day}
{f'- Contexto/Tema: {context}' if context else ''}

{brand_context}
{claims_context}

REGRAS OBRIGATORIAS:
- O briefing deve ser ESPECIFICO e RELEVANTE ao tema/objetivo informado.
- Se uma data comemorativa foi informada no Contexto/Tema, conecte com o produto de forma natural.
- NUNCA invente datas comemorativas, eventos ou efemérides que NAO foram explicitamente informados acima.
- NUNCA invente dados tecnicos, especificacoes, numeros ou estatisticas — use SOMENTE os claims aprovados acima.
- Se nao ha data comemorativa no contexto, foque em conteudo de PRODUTO ou EDUCATIVO do pilar informado.
- Use claims reais do banco acima. Seja criativo mas preciso.

Gere o briefing completo no formato YAML especificado."""

        result = await self.llm.complete(
            task="briefing",
            prompt=prompt,
            system_prompt=get_briefing_system_prompt(),
        )

        logger.info(
            "Briefing generated: model=%s, cost=%.4f",
            result.get("model", ""), result.get("cost_usd", 0),
        )

        briefing_text = result.get("text", "")
        if not briefing_text or len(briefing_text) < 50:
            logger.warning("Briefing too short (%d chars), may be invalid", len(briefing_text))

        return {
            "briefing_text": result.get("text", ""),
            "brand": brand,
            "platform": platform,
            "pillar": pillar,
            "product": product,
            "persona": persona,
            "model_used": result.get("model", ""),
            "cost_usd": result.get("cost_usd", 0),
            "preview_mode": result.get("preview_mode", False),
        }

    async def generate_batch(self, slots: list[dict]) -> list[dict]:
        """Gera briefings para multiplos slots."""
        results = []
        for slot in slots:
            r = await self.generate(
                brand=slot.get("brand", "salk"),
                platform=slot.get("platform", "instagram"),
                pillar=slot.get("pillar", "produto"),
                product=slot.get("product", ""),
                persona=slot.get("persona_target", ""),
                day=slot.get("day", ""),
            )
            results.append(r)
        return results
