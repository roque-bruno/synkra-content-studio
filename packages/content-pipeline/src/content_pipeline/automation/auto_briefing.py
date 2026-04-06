"""
Auto-Briefing (Atlas) — Gera briefing automatico por slot do calendario.

Recebe: slot do calendario (dia, plataforma, pilar, marca, persona)
Produz: briefing completo com objetivo, mensagem-chave, CTA, tom, formato

Usa LLM barato (Flash) via OpenRouter para gerar.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

BRIEFING_SYSTEM_PROMPT = """Voce e Atlas, o estrategista de conteudo do Manager Grupo.
Sua funcao e criar briefings de conteudo para redes sociais B2B healthcare.

REGRAS INEGOCIAVEIS:
- ETRUS esta BLOQUEADO — nunca mencionar jamais
- NUNCA prometer resultados medicos
- NUNCA usar superlativos (o melhor, o unico, garante, infalivel)
- Claims SOMENTE dos claims aprovados fornecidos abaixo — NUNCA inventar
- Tom deve seguir o brandbook da marca
- O briefing DEVE ser ESPECIFICO ao produto e tema, NUNCA generico
- Se um produto foi selecionado, o briefing DEVE mencionar specs e diferenciais reais desse produto
- Se nenhum produto foi selecionado, escolher 1-2 produtos mais relevantes ao tema/data e justificar
- claims_sugeridos DEVEM ser IDs do banco de claims (ex: LEV-01, KRATUS-03)

Formato de saida (YAML):
```yaml
objetivo: "string — especifico ao tema e produto"
mensagem_chave: "string — com diferencial tecnico real do produto"
cta: "string — consultivo, nunca vendedor"
tom: "string"
formato_visual: "string — descricao do cenario para imagem NB2"
hashtags_sugeridas: ["string"]
claims_sugeridos: ["ID do claim — ex: LEV-01"]
notas_visuais: "string — instrucoes especificas para cenario da imagem"
produto_recomendado: "string — produto escolhido e por que"
```"""


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
- Produto: {product or 'a definir — escolha o mais relevante ao tema'}
- Persona-alvo: {persona or 'geral'}
- Dia: {day}
{f'- Contexto/Tema: {context}' if context else ''}

{brand_context}
{claims_context}

IMPORTANTE: O briefing deve ser ESPECIFICO e RELEVANTE ao tema/objetivo informado.
Se o tema e uma data comemorativa, conecte com o produto de forma natural e inteligente.
Use claims reais do banco acima. Seja criativo mas preciso.

Gere o briefing completo no formato YAML especificado."""

        result = await self.llm.complete(
            task="briefing",
            prompt=prompt,
            system_prompt=BRIEFING_SYSTEM_PROMPT,
        )

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
