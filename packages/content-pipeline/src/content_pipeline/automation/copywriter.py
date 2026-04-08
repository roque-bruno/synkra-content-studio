"""
Squad Copywriters por Marca — Agentes especializados com brandbook individual.

Cada marca tem seu copywriter com tom, vocabulario e regras proprias.
Usa LLM intermediario (Haiku) via OpenRouter.

Inclui Persona Clones: simulacao de buyer personas para testar copy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


def _load_copywriter_config(data_dir: Optional[Path] = None) -> dict:
    """Carrega copywriter-config.yaml do data dir."""
    if data_dir:
        path = data_dir / "copywriter-config.yaml"
        if path.exists():
            try:
                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception as e:
                logger.warning("Falha ao carregar copywriter-config.yaml: %s — usando fallback", e)
    return {}


# Referência global carregada sob demanda
_CONFIG_CACHE: Optional[dict] = None
_CONFIG_DATA_DIR: Optional[Path] = None


def _get_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _load_copywriter_config(_CONFIG_DATA_DIR)
    return _CONFIG_CACHE


def init_copywriter_config(data_dir: Path) -> None:
    """Inicializa o data_dir para carregamento do YAML. Chamado no startup."""
    global _CONFIG_DATA_DIR, _CONFIG_CACHE
    _CONFIG_DATA_DIR = data_dir
    _CONFIG_CACHE = None


def get_brand_copywriters() -> dict:
    cfg = _get_config()
    return cfg.get("brand_copywriters", {})


def get_persona_clones() -> dict:
    cfg = _get_config()
    return cfg.get("persona_clones", {})


class BrandCopywriter:
    """Copywriter especializado por marca."""

    def __init__(self, llm_client, brand: str = "salk", brandbook_loader=None):
        self.llm = llm_client
        self.brand = brand
        copywriters = get_brand_copywriters()
        self._config = copywriters.get(brand, copywriters.get("salk", {"name": "Copy", "system": ""}))
        self._brandbook = None
        if brandbook_loader:
            try:
                self._brandbook = brandbook_loader(brand)
            except Exception:
                pass

    def _build_brandbook_context(self, product: str = "") -> str:
        """Extrai contexto relevante do brandbook para enriquecer o prompt de copy."""
        if not self._brandbook:
            return ""
        bb = self._brandbook
        parts = []

        # Tom de voz
        tone = bb.get("tone_of_voice", {})
        if tone:
            parts.append(f"TOM DE VOZ DA MARCA: {tone.get('primary', '')}")
            if tone.get("adjectives"):
                parts.append(f"Adjetivos da marca: {', '.join(tone['adjectives'])}")
            if tone.get("cta_style"):
                parts.append(f"Estilo de CTA: {tone['cta_style']}")

        # Tagline
        if bb.get("tagline"):
            parts.append(f"Tagline: {bb['tagline']}")

        # Produto especifico
        if product:
            products = bb.get("products", [])
            for p in products:
                if p.get("id", "").lower() == product.lower() or p.get("name", "").lower() == product.lower():
                    parts.append(f"PRODUTO {p['name']}: {p.get('type', '')}. Status: {p.get('status', 'ATIVO')}")
                    if p.get("special_rules"):
                        parts.append(f"Regras do produto: {'; '.join(p['special_rules'])}")
                    break

        # Personas-alvo
        personas = bb.get("target_personas", [])
        if personas:
            persona_lines = []
            for p in personas[:4]:
                concerns = ", ".join(p.get("concerns", []))
                persona_lines.append(f"  - {p.get('name', '')}: {p.get('role', '')} (preocupacoes: {concerns})")
            parts.append("PUBLICO-ALVO:\n" + "\n".join(persona_lines))

        # Pilares de conteudo
        pillars = bb.get("content_pillars", [])
        if pillars:
            pillar_lines = [f"  - {p['name']} ({p.get('percentage', '')}%): {p.get('description', '')}" for p in pillars[:5]]
            parts.append("PILARES DE CONTEUDO:\n" + "\n".join(pillar_lines))

        if not parts:
            return ""
        return "\nCONTEXTO DA MARCA (brandbook):\n" + "\n".join(parts) + "\n"

    async def write_copy(
        self,
        briefing: str,
        platform: str = "instagram",
        format_type: str = "post",
        max_chars: int = 2200,
        product: str = "",
        objective: str = "",
        prohibited_terms: list | None = None,
        approved_claims: list | None = None,
    ) -> dict:
        """Gera copy baseado em briefing."""
        if prohibited_terms is None:
            prohibited_terms = []
        if approved_claims is None:
            approved_claims = []
        # Enriquecer com brandbook
        brandbook_context = self._build_brandbook_context(product)

        product_note = f"\nPRODUTO PRINCIPAL: {product} (mencione pelo nome no texto)\n" if product else "\nNENHUM PRODUTO SELECIONADO — conteudo INSTITUCIONAL. NAO mencione nenhum produto especifico.\n"
        objective_note = f"\nOBJETIVO/TEMA DA PECA: {objective}\nIMPORTANTE: o copy DEVE ser sobre este tema especifico. NAO ignore o objetivo.\n" if objective else ""

        # Merge prohibited terms do brandbook
        all_prohibited = list(prohibited_terms or [])
        if self._brandbook and self._brandbook.get("prohibited_terms"):
            all_prohibited.extend(self._brandbook["prohibited_terms"])
        # Deduplicate
        all_prohibited = list(dict.fromkeys(all_prohibited))

        prohibited_block = ""
        if all_prohibited:
            prohibited_block = f"\nTERMOS PROIBIDOS (NUNCA usar):\n{', '.join(all_prohibited[:40])}\n"

        claims_block = ""
        if approved_claims:
            claims_block = f"\nCLAIMS APROVADOS (use SOMENTE estes dados tecnicos — NAO invente nenhum dado):\n"
            for c in approved_claims[:15]:
                cid = c.get('id', '') or c.get('claim_id', '')
                ctxt = c.get('claim', '') or c.get('texto', '')
                claims_block += f"- [{cid}] {ctxt}\n"

        prompt = f"""Escreva o copy FINAL para {platform} ({format_type}).
{brandbook_context}{product_note}{objective_note}{prohibited_block}{claims_block}
BRIEFING:
{briefing}

REGRAS OBRIGATORIAS:
- Responda SOMENTE com o texto final pronto para publicar
- NAO inclua preambulos como "Aqui esta" ou "Segue o copy"
- NAO use separadores como --- ou ***
- Maximo {max_chars} caracteres
- Comece direto com a headline
- Termine com hashtags relevantes (na ultima linha, sem separador)
- Inclua CTA consultivo sutil (nao agressivo)
- Se houver produto especifico, MENCIONE pelo nome e destaque beneficios reais
- Se houver objetivo/tema, o copy DEVE abordar esse tema (ex: Pascoa, lancamento, etc.)
- NAO invente dados tecnicos, especificacoes ou estatisticas — use APENAS informacoes do briefing e claims aprovados
- NAO invente numeros como "reducao de 40%", "Ra 99", "multas de R$ 50 mil" sem fonte
- NAO invente datas comemorativas, eventos ou efemerides que NAO estejam no briefing
- Se o briefing NAO menciona uma data comemorativa, NAO crie uma — foque no produto/tema
- ZERO EMOJIS no texto — nenhum emoji em nenhuma parte (nem headline, nem corpo, nem CTA, nem hashtags)
- Evite frases genericas que servem para qualquer empresa (ex: "transformando vidas", "inovacao que transforma")
- Use linguagem ESPECIFICA da Salk Medical e do universo hospitalar
- Se houver claims aprovados acima, UTILIZE-OS no texto — eles sao diferencial real"""

        result = await self.llm.complete(
            task="copy",
            prompt=prompt,
            system_prompt=self._config["system"],
        )

        copy_text = result.get("text", "")

        # Enforce character limit
        if len(copy_text) > max_chars:
            # Truncate at last complete sentence before limit
            truncated = copy_text[:max_chars]
            last_period = truncated.rfind('.')
            last_newline = truncated.rfind('\n')
            cut_point = max(last_period, last_newline)
            if cut_point > max_chars // 2:
                copy_text = truncated[:cut_point + 1]

        # Basic compliance check
        _prohibited_phrases = ["o melhor", "o unico", "garante", "100% seguro", "infalivel", "elimina riscos"]
        warnings = []
        for phrase in _prohibited_phrases:
            if phrase.lower() in copy_text.lower():
                warnings.append(f"Termo proibido detectado: '{phrase}'")

        return {
            "copy_text": copy_text,
            "copywriter": self._config["name"],
            "brand": self.brand,
            "platform": platform,
            "model_used": result.get("model", ""),
            "cost_usd": result.get("cost_usd", 0),
            "warnings": warnings,
        }

    async def rewrite(self, original: str, feedback: str) -> dict:
        """Reescreve copy com feedback."""
        prompt = f"""Reescreva o copy abaixo incorporando o feedback:

COPY ORIGINAL:
{original}

FEEDBACK:
{feedback}

Mantenha o mesmo formato (headline, corpo, CTA, hashtags)."""

        result = await self.llm.complete(
            task="copy",
            prompt=prompt,
            system_prompt=self._config["system"],
        )

        return {
            "copy_text": result.get("text", ""),
            "copywriter": self._config["name"],
            "brand": self.brand,
            "model_used": result.get("model", ""),
            "cost_usd": result.get("cost_usd", 0),
        }


class PersonaClone:
    """Simulacao de buyer persona para testar copy."""

    def __init__(self, llm_client, persona_id: str = "eng_clinica"):
        self.llm = llm_client
        self.persona_id = persona_id
        clones = get_persona_clones()
        self._config = clones.get(persona_id, clones.get("eng_clinica", {"name": "Persona", "system": ""}))

    async def evaluate(self, copy_text: str, brand: str = "salk") -> dict:
        """
        Avalia copy do ponto de vista da persona.

        Returns:
            dict com score (1-10), feedback, would_engage (bool)
        """
        prompt = f"""Avalie o seguinte copy de conteudo da marca {brand}:

---
{copy_text}
---

Responda em formato:
SCORE: (1-10)
ENGAJARIA: (sim/nao)
PONTOS_FORTES: (lista)
PONTOS_FRACOS: (lista)
SUGESTAO: (uma frase)"""

        result = await self.llm.complete(
            task="persona_test",
            prompt=prompt,
            system_prompt=self._config["system"],
        )

        return {
            "persona": self._config["name"],
            "persona_id": self.persona_id,
            "evaluation": result.get("text", ""),
            "model_used": result.get("model", ""),
            "cost_usd": result.get("cost_usd", 0),
        }

    @staticmethod
    def list_personas() -> list[dict]:
        """Lista personas disponiveis."""
        return [
            {"id": k, "name": v["name"]}
            for k, v in get_persona_clones().items()
        ]
