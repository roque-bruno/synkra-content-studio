"""
Auto-Prompt NB2 (Apex) — Gerador automatico de prompts de imagem 8 dimensoes.

Arquitetura validada pelo usuario:
1. Tecnica fotografica (hero shot, dramatic studio, etc)
2. Iluminacao (direcional, rim light, etc)
3. Cenario (ambiente hospitalar, industrial, etc)
4. Composicao (angulo, enquadramento)
5. Atmosfera (mood, color grading)
6. Detalhes tecnicos (resolucao, aspect ratio)
7. Negative prompts (obrigatorios)
8. Instrucoes de produto (NUNCA descrever o produto, so cenario)

Regras inegociaveis:
- NUNCA descrever o produto (NB2 distorce)
- NUNCA gerar equipamentos medicos alem do produto-alvo
- NUNCA pedir glow/dispersao para LEV (luz concentrada)
- NUNCA sugerir colar PNG no Canva (= wallpaper = proibido)
- Negative prompt OBRIGATORIO
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Dimensoes do prompt com opcoes pre-validadas
PROMPT_DIMENSIONS = {
    "tecnica": {
        "hero_shot": "Professional hero shot photography, product centered",
        "dramatic_studio": "Dramatic studio photography with professional lighting setup",
        "lifestyle": "Lifestyle photography in real-world usage context",
        "detail_macro": "Macro detail photography showing craftsmanship and precision",
        "environmental": "Environmental photography showing product in its natural setting",
    },
    "iluminacao": {
        "dramatic_rim": "Dramatic rim lighting with strong key light, deep shadows",
        "soft_diffused": "Soft diffused lighting, even illumination, minimal shadows",
        "high_contrast": "High contrast lighting with defined highlights and shadows",
        "natural_window": "Natural window light, soft and directional",
        "clinical_bright": "Bright clinical lighting, clean and even",
    },
    "cenario": {
        "centro_cirurgico": "Modern surgical center, clean sterile environment, stainless steel surfaces",
        "sala_exames": "Medical examination room, clinical setting, organized equipment",
        "corredor_hospital": "Modern hospital corridor, wide and clean, professional environment",
        "laboratorio": "High-tech laboratory, precision instruments, controlled environment",
        "industrial": "Industrial manufacturing floor, CNC machines, precision engineering",
        "studio_neutro": "Clean neutral photography studio, seamless background",
    },
    "composicao": {
        "central_hero": "Centered composition, product as focal point, rule of thirds",
        "angular_dramatico": "Low angle dramatic shot, emphasizing scale and importance",
        "overhead_tech": "Overhead technical view, showing layout and organization",
        "three_quarter": "Three-quarter view, showing depth and dimension",
        "detail_close": "Extreme close-up, filling frame with product detail",
    },
    "atmosfera": {
        "premium_tech": "Premium technology aesthetic, cool blue tones, professional",
        "clean_medical": "Clean medical aesthetic, whites and soft blues, sterile feel",
        "industrial_warm": "Industrial warm tones, amber accents, solid and reliable",
        "modern_minimal": "Modern minimalist, neutral palette, sophisticated",
        "dramatic_dark": "Dramatic dark mood, selective lighting, high impact",
    },
    "detalhes_tecnicos": {
        "4k_landscape": "4K resolution, 16:9 landscape, photorealistic rendering",
        "square_social": "1080x1080, square format optimized for social media",
        "portrait_story": "1080x1920, portrait format for stories/reels",
        "wide_banner": "2560x720, wide banner format for covers",
    },
}

# Negative prompts obrigatorios por categoria
MANDATORY_NEGATIVES = {
    "universal": [
        "text", "watermark", "logo", "signature", "letters", "words",
        "blurry", "low quality", "distorted", "deformed",
        "cartoon", "illustration", "painting", "sketch",
    ],
    "medical": [
        "competing medical equipment", "other brand equipment",
        "generic hospital equipment in focus", "full room with multiple devices",
        "people faces", "identifiable patients", "blood", "graphic medical content",
    ],
    "lev_specific": [
        "light rays spreading sideways", "diffused glow", "scattered light",
        "lens flare", "light bleeding", "omnidirectional light",
        "ceiling mounted fluorescent", "ambient room lighting",
    ],
}

# Regras por produto
PRODUCT_RULES = {
    "lev": {
        "must_include": "concentrated focused beam of light on surgical field",
        "never_include": "scattered light, diffused glow, lateral rays",
        "preferred_techniques": ["dramatic_studio", "hero_shot"],
        "preferred_lighting": ["dramatic_rim", "high_contrast"],
        "extra_negatives": MANDATORY_NEGATIVES["lev_specific"],
    },
    "kratus": {
        "must_include": "robust surgical table, adjustable positions visible",
        "never_include": "generic examination table, flimsy structure",
        "preferred_techniques": ["hero_shot", "environmental"],
        "preferred_lighting": ["clinical_bright", "soft_diffused"],
        "extra_negatives": [],
    },
    "ostus": {
        "must_include": "pendant surgical light system, articulating arm",
        "never_include": "standalone floor lamp, desk light",
        "preferred_techniques": ["dramatic_studio", "angular_dramatico"],
        "preferred_lighting": ["dramatic_rim", "high_contrast"],
        "extra_negatives": [],
    },
    "kronus": {
        "must_include": "medical monitor/display, clear screen, mounting system",
        "never_include": "consumer TV, laptop screen",
        "preferred_techniques": ["hero_shot", "detail_macro"],
        "preferred_lighting": ["soft_diffused", "clinical_bright"],
        "extra_negatives": [],
    },
}


class AutoPromptNB2:
    """Gerador de prompts NB2 com arquitetura de 8 dimensoes."""

    def __init__(self, llm_client=None, brandbook_loader=None):
        self.llm = llm_client
        self._load_brandbook = brandbook_loader

    async def generate_prompt(
        self,
        product: str,
        brand: str = "salk",
        concept: str = "",
        technique: str = "dramatic_studio",
        lighting: str = "dramatic_rim",
        scene: str = "studio_neutro",
        composition: str = "central_hero",
        atmosphere: str = "premium_tech",
        format_type: str = "square_social",
        custom_notes: str = "",
    ) -> dict:
        """
        Gera prompt NB2 completo com 8 dimensoes.

        REGRA CRITICA: O prompt descreve APENAS o cenario.
        O produto e inserido via upload separado no NB2.
        """
        product_key = product.lower()
        product_rules = PRODUCT_RULES.get(product_key, {})

        # Montar as 8 dimensoes
        dim_tecnica = PROMPT_DIMENSIONS["tecnica"].get(
            technique, PROMPT_DIMENSIONS["tecnica"]["dramatic_studio"]
        )
        dim_iluminacao = PROMPT_DIMENSIONS["iluminacao"].get(
            lighting, PROMPT_DIMENSIONS["iluminacao"]["dramatic_rim"]
        )
        dim_cenario = PROMPT_DIMENSIONS["cenario"].get(
            scene, PROMPT_DIMENSIONS["cenario"]["studio_neutro"]
        )
        dim_composicao = PROMPT_DIMENSIONS["composicao"].get(
            composition, PROMPT_DIMENSIONS["composicao"]["central_hero"]
        )
        dim_atmosfera = PROMPT_DIMENSIONS["atmosfera"].get(
            atmosphere, PROMPT_DIMENSIONS["atmosfera"]["premium_tech"]
        )
        dim_tecnico = PROMPT_DIMENSIONS["detalhes_tecnicos"].get(
            format_type, PROMPT_DIMENSIONS["detalhes_tecnicos"]["square_social"]
        )

        # Construir negative prompt
        negatives = (
            MANDATORY_NEGATIVES["universal"]
            + MANDATORY_NEGATIVES["medical"]
            + product_rules.get("extra_negatives", [])
        )

        # Montar prompt final
        prompt_parts = [
            dim_tecnica,
            dim_iluminacao,
            dim_cenario,
            dim_composicao,
            dim_atmosfera,
        ]

        if product_rules.get("must_include"):
            prompt_parts.append(product_rules["must_include"])

        if concept:
            prompt_parts.append(f"Concept: {concept}")

        if custom_notes:
            prompt_parts.append(custom_notes)

        prompt_parts.append(dim_tecnico)

        positive_prompt = ", ".join(prompt_parts)
        negative_prompt = ", ".join(negatives)

        result = {
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "dimensions": {
                "tecnica": technique,
                "iluminacao": lighting,
                "cenario": scene,
                "composicao": composition,
                "atmosfera": atmosphere,
                "formato": format_type,
                "negative": "auto-generated",
                "produto": f"{product} (upload separado, NAO descrito no prompt)",
            },
            "product": product,
            "brand": brand,
            "product_rules_applied": list(product_rules.keys()),
            "warnings": [],
        }

        # Validar regras do produto
        if product_rules.get("never_include"):
            for term in product_rules["never_include"].split(", "):
                if term.lower() in positive_prompt.lower():
                    result["warnings"].append(
                        f"ALERTA: Termo proibido '{term}' detectado no prompt"
                    )

        return result

    async def generate_with_llm(
        self,
        product: str,
        brand: str = "salk",
        concept: str = "",
        format_type: str = "square_social",
        briefing: str = "",
        objective: str = "",
    ) -> dict:
        """
        Usa LLM para gerar prompt criativo dentro das restricoes.

        Combina criatividade do LLM com regras inegociaveis hardcoded.
        O briefing e objetivo sao usados para gerar um cenario RELEVANTE ao conteudo.
        """
        if not self.llm:
            return await self.generate_prompt(
                product=product, brand=brand, concept=concept, format_type=format_type
            )

        product_key = product.lower()
        product_rules = PRODUCT_RULES.get(product_key, {})

        system = f"""Voce e Apex, diretor de fotografia especializado em equipamentos medico-hospitalares.
Voce cria prompts para geracao de imagem via NB2 (NanoBanana 2).

CONTEXTO DA EMPRESA:
- Salk Medical fabrica equipamentos cirurgicos REAIS: focos cirurgicos, mesas, pendentes, monitores
- O PUBLICO sao gestores hospitalares, engenheiros clinicos, medicos cirurgioes
- As imagens sao para REDES SOCIAIS de uma empresa B2B de saude

COMO FUNCIONA O NB2:
- O produto REAL (foto PNG) e inserido via upload separado
- Seu prompt descreve APENAS o cenario/ambiente onde o produto sera colocado
- A IA renderiza o produto DENTRO do cenario que voce descreve
- Voce NAO descreve o produto — ele ja existe como foto

REGRAS INEGOCIAVEIS:
1. CENARIOS DEVEM SER MEDICOS/HOSPITALARES: salas cirurgicas, centros cirurgicos, UTIs, salas de exames, corredores hospitalares modernos. NUNCA labs de tecnologia, fabricas, escritorios ou cenarios sci-fi
2. FOTORREALISMO OBRIGATORIO: fotografia profissional real, NUNCA ilustracao, render 3D, cartoon ou estetica digital/futurista
3. NUNCA descreva o produto — ele sera inserido via upload
4. NUNCA mencione outros equipamentos medicos no cenario (= concorrente no material)
5. Para datas comemorativas (Dia da Engenharia, etc): o cenario CONTINUA sendo hospitalar/cirurgico — mostre o AMBIENTE onde o profissional celebrado TRABALHA com o equipamento, NAO o ambiente generico da profissao
6. NUNCA use glow/dispersao para LEV — luz CONCENTRADA no campo cirurgico
7. NUNCA cenario vazio/abstrato sem contexto real
8. SEM TEXTO na imagem: nenhuma palavra, letra, numero, placa, tela com texto legivel
9. Prompt em INGLES
10. Descreva materiais REAIS: aco inox, pisos epoxi, paredes brancas, azulejos, cortinas cirurgicas, iluminacao fluorescente/LED de teto

ESTILO VISUAL:
- Fotografia de advertising hospitalar premium (como catálogo Stryker, Getinge, Steris)
- Iluminacao dramatica mas REALISTA (luz de teto hospitalar + accent light)
- Composicao: espaco vazio no centro para o produto ser inserido
- Cores: brancos, cinzas, azuis cirurgicos, toques de aco inox — NUNCA monocromatico azul neon

Produto: {product} ({brand})
{f'DEVE ter no cenario: {product_rules.get("must_include", "")}' if product_rules.get("must_include") else ''}
{f'NUNCA incluir: {product_rules.get("never_include", "")}' if product_rules.get("never_include") else ''}
Tecnicas preferidas: {', '.join(product_rules.get('preferred_techniques', ['dramatic_studio']))}
"""

        # Contexto rico do briefing e objetivo
        context_block = ""
        if briefing:
            context_block += f"\nBRIEFING DO CONTEUDO:\n{briefing[:500]}\n"
        if objective:
            context_block += f"\nOBJETIVO/TEMA: {objective}\n"

        user_prompt = f"""Crie um prompt NB2 para {product} da {brand}.
{context_block}
Conceito visual: {concept or 'hero shot premium em ambiente cirurgico real'}
Formato: {format_type}

IMPORTANTE: O cenario DEVE ser um ambiente medico/hospitalar REAL onde o produto {product} seria usado.
Se o tema e uma data comemorativa (ex: "Dia da Engenharia"), mostre o AMBIENTE HOSPITALAR onde o profissional celebrado trabalha — NAO um laboratorio ou escritorio generico.
Pense como um fotografo de catalogo de equipamentos medicos premium.

OBRIGATORIO no prompt: "professional medical photography, photorealistic, no text, no writing, no labels"

Responda EXATAMENTE neste formato:
POSITIVE: (prompt em ingles — cenario hospitalar/cirurgico fotorrealista, com iluminacao, materiais, atmosfera. DEVE incluir "no text, no writing, no labels" no final)
NEGATIVE: (prompt negativo em ingles)
TECNICA: (nome da tecnica fotografica)
CONCEITO: (resumo do conceito visual em 1 linha)"""

        llm_result = await self.llm.complete(
            task="copy",
            prompt=user_prompt,
            system_prompt=system,
        )

        # Extrair prompt positivo e negativo da resposta do LLM
        llm_text = llm_result.get("text", "")
        positive = ""
        negative = ""
        for line in llm_text.split("\n"):
            line_stripped = line.strip()
            if line_stripped.upper().startswith("POSITIVE:"):
                positive = line_stripped[9:].strip()
            elif line_stripped.upper().startswith("NEGATIVE:"):
                negative = line_stripped[9:].strip()

        # Garantir qualidade fotorrealista e anti-texto no positivo
        no_text_suffix = "professional medical photography, photorealistic, no text, no writing, no labels, no signs, no letters"
        if positive and "no text" not in positive.lower():
            positive = positive.rstrip(".," ) + ", " + no_text_suffix

        # Garantir negatives obrigatorios mesmo que LLM esqueca
        mandatory_neg = (
            MANDATORY_NEGATIVES["universal"]
            + MANDATORY_NEGATIVES["medical"]
            + product_rules.get("extra_negatives", [])
        )
        all_negatives = negative + ", " + ", ".join(mandatory_neg) if negative else ", ".join(mandatory_neg)

        return {
            "positive_prompt": positive or llm_text,
            "negative_prompt": all_negatives,
            "llm_generated": llm_text,
            "product": product,
            "brand": brand,
            "format": format_type,
            "model_used": llm_result.get("model", ""),
            "cost_usd": llm_result.get("cost_usd", 0),
            "warnings": [],
        }

    @staticmethod
    def list_dimensions() -> dict:
        """Lista todas as dimensoes e opcoes disponiveis."""
        return {
            dim: list(options.keys())
            for dim, options in PROMPT_DIMENSIONS.items()
        }

    @staticmethod
    def list_products() -> list[str]:
        """Lista produtos com regras especificas."""
        return list(PRODUCT_RULES.keys())
