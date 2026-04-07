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
        "surgical light", "operating light", "ceiling mounted light", "surgical lamp",
        "operating table", "surgical table", "examination table",
        "medical monitor", "patient monitor", "display screen",
        "pendant", "ceiling mount arm", "articulating arm",
        "medical equipment", "hospital equipment", "medical device",
        "competing medical equipment", "other brand equipment",
        "people faces", "identifiable patients", "blood", "graphic medical content",
        "blue monochrome", "cyan tint", "teal color", "neon blue", "blue cast",
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
        "description": "Foco cirurgico de teto LED — luz concentrada no campo",
        "must_include": "visible ceiling area for ceiling-mounted equipment, surgical field below",
        "never_include": "scattered light, diffused glow, lateral rays, other ceiling lights",
        "preferred_techniques": ["dramatic_studio", "hero_shot"],
        "preferred_lighting": ["dramatic_rim", "high_contrast"],
        "extra_negatives": MANDATORY_NEGATIVES["lev_specific"],
    },
    "kratus": {
        "description": "Mesa cirurgica robusta com posicoes ajustaveis",
        "must_include": "clean floor area in center for surgical table, wide room",
        "never_include": "other surgical tables, examination couch, gurney, stretcher",
        "preferred_techniques": ["hero_shot", "environmental"],
        "preferred_lighting": ["clinical_bright", "soft_diffused"],
        "extra_negatives": [],
    },
    "ostus": {
        "description": "Serra cirurgica eletrica para ortopedia",
        "must_include": "sterile instrument area, draped surgical surface, precision context",
        "never_include": "other power tools, hand saw, competing surgical instruments",
        "preferred_techniques": ["detail_macro", "hero_shot"],
        "preferred_lighting": ["clinical_bright", "high_contrast"],
        "extra_negatives": [],
    },
    "kronus": {
        "description": "Suporte pendente de teto biarticulado para equipamentos",
        "must_include": "visible ceiling with mounting rails, upper wall area, gas panels",
        "never_include": "floor-standing rack, wall TV bracket, consumer monitor arm",
        "preferred_techniques": ["hero_shot", "environmental"],
        "preferred_lighting": ["soft_diffused", "clinical_bright"],
        "extra_negatives": [],
    },
}

# Perspectiva da camera por tipo de produto
PRODUCT_SCENE_HINTS = {
    "lev": {
        "perspective": "camera at bed level looking UPWARD toward ceiling, showing ceiling and upper walls",
        "spatial": "tall room, high ceiling prominent, vertical emphasis, space for ceiling-mounted light",
    },
    "kratus": {
        "perspective": "camera at waist height, slightly elevated, looking toward center of room",
        "spatial": "wide room, clean floor prominent, horizontal emphasis, space for table in center",
    },
    "ostus": {
        "perspective": "camera at table height, close-up perspective, sterile instrument context",
        "spatial": "tight clinical framing, draped surfaces, precision instrument environment",
    },
    "kronus": {
        "perspective": "camera at standing height looking slightly upward toward ceiling area",
        "spatial": "vertical space, ceiling and upper walls visible, mounting infrastructure context",
    },
}

# Inferencia de produto por keywords
PRODUCT_INFERENCE_MAP = {
    "iluminacao": "lev", "iluminação": "lev", "foco": "lev", "luz": "lev",
    "led": "lev", "surgical light": "lev", "visibilidade": "lev", "lev": "lev",
    "mesa": "kratus", "table": "kratus", "posicionamento": "kratus",
    "paciente": "kratus", "ergonomia": "kratus", "kratus": "kratus",
    "serra": "ostus", "saw": "ostus", "corte": "ostus", "ortopedia": "ostus",
    "osso": "ostus", "osteotomia": "ostus", "ostus": "ostus",
    "suporte": "kronus", "pendente": "kronus", "monitor": "kronus",
    "braço": "kronus", "articulado": "kronus", "kronus": "kronus",
}
HERO_PRODUCT = "lev"  # Produto principal da marca


class AutoPromptNB2:
    """Gerador de prompts NB2 com arquitetura de 8 dimensoes."""

    def __init__(self, llm_client=None, brandbook_loader=None):
        self.llm = llm_client
        self._load_brandbook = brandbook_loader

    @staticmethod
    def infer_product(objective: str = "", pillar: str = "", title: str = "", context: str = "") -> str:
        """Sugere produto com base no contexto. Retorna key ou '' se institucional."""
        text = f"{objective} {pillar} {title} {context}".lower()
        for keyword, product in PRODUCT_INFERENCE_MAP.items():
            if keyword in text:
                return product
        # Pilares que tipicamente envolvem produto
        if pillar in ("produto",):
            return HERO_PRODUCT
        # Institucional, educacional sem keyword de produto = sem produto (FLUX)
        return ""

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

        system = f"""Voce e Apex, diretor de fotografia especializado em ambientes hospitalares.
Voce cria prompts para geracao de imagem. O produto sera inserido DEPOIS via upload separado.
Seu prompt descreve SOMENTE o cenario/ambiente VAZIO — SEM nenhum equipamento medico.

=== REGRA #1 (MAIS IMPORTANTE DE TODAS) ===
ZERO EQUIPAMENTOS MEDICOS no prompt. Isso inclui:
- NENHUM foco cirurgico, luminaria cirurgica, surgical light
- NENHUMA mesa cirurgica, operating table, surgical table
- NENHUM monitor, display, tela
- NENHUM pendente, braço articulado, ceiling mount
- NENHUM equipamento de qualquer tipo no centro da cena
O CENTRO DA IMAGEM deve estar VAZIO — e onde o produto real sera inserido depois.

=== REGRA #2: FOTORREALISMO ===
- Fotografia REAL com camera DSLR, ISO, abertura — como foto de catalogo Stryker/Getinge
- NUNCA render 3D, ilustracao, cartoon, estetica digital
- Materiais REAIS: aco inox escovado, piso epoxi claro, paredes brancas, azulejos, cortinas cirurgicas

=== REGRA #3: CORES REALISTAS ===
- Paleta QUENTE e NEUTRA: brancos, cinzas claros, tons de creme, aco inox prateado
- Toques SUTIS de azul cirurgico (campos, aventais) — nunca dominante
- PROIBIDO: monocromatico azul, azul neon, ciano dominante, teal, tons frios saturados
- A imagem deve parecer uma foto REAL de hospital, nao um cenario de filme sci-fi

=== REGRA #4: COMPOSICAO ===
- CENTRO VAZIO: o ponto focal da imagem deve ser um espaco limpo onde o produto sera colocado
- Angulo levemente baixo (3/4) para dar imponencia ao espaco vazio central
- Profundidade de campo: fundo levemente desfocado, centro nitido

=== REGRA #5: CENARIO ===
- SEMPRE ambiente hospitalar/cirurgico REAL: centro cirurgico, sala de exames, UTI
- Para datas comemorativas: o AMBIENTE HOSPITALAR onde o profissional trabalha
- NUNCA: laboratorio de tecnologia, escritorio, fabrica, cenario sci-fi, corredor vazio
- Detalhes de contexto: portas de aco, paineis de gases medicinais, piso epoxi, teto com luminárias fluorescentes comuns

=== REGRA #6: SEM TEXTO ===
Nenhuma palavra, letra, numero, placa, tela legivel, label na imagem.

Produto sendo fotografado: {product or 'equipamento cirurgico Salk Medical'} ({brand})
{f'Contexto do produto: {product_rules.get("must_include", "")}' if product_rules.get("must_include") else ''}
{f'NUNCA incluir: {product_rules.get("never_include", "")}' if product_rules.get("never_include") else ''}

LEMBRE: o prompt descreve o AMBIENTE. O produto NAO aparece no prompt. O centro fica VAZIO.
"""
        # Scene hints por produto (perspectiva, espacialidade)
        scene_hints = PRODUCT_SCENE_HINTS.get(product_key, {})
        if scene_hints:
            system += f"""
=== PERSPECTIVA ESPECIFICA PARA {product.upper()} ===
- Camera: {scene_hints['perspective']}
- Espacialidade: {scene_hints['spatial']}
"""
        elif not product:
            system += """
=== CONTEUDO INSTITUCIONAL (sem produto especifico) ===
- A imagem deve refletir o TEMA/OBJETIVO do conteudo (ex: Dia da Engenharia, Dia do Medico, etc.)
- Contexto HOSPITALAR ou de SAUDE, mas adaptado ao tema
- Pode mostrar o AMBIENTE completo, perspectiva livre, pessoas desfocadas ao fundo se fizer sentido
- Foco em transmitir profissionalismo, tecnologia, inovacao, humanidade
- Se o tema for uma data comemorativa, capture a essencia dessa profissao/data no contexto hospitalar
"""

        # Contexto rico do briefing e objetivo
        context_block = ""
        if briefing:
            context_block += f"\nBRIEFING DO CONTEUDO:\n{briefing[:500]}\n"
        if objective:
            context_block += f"\nOBJETIVO/TEMA: {objective}\n"

        if product:
            user_prompt = f"""Crie um prompt de cenario hospitalar para inserir o produto {product}.
{context_block}
Conceito: {concept or 'centro cirurgico premium, vazio no centro, pronto para inserir produto'}
Formato: {format_type}

CRITICO — O prompt descreve SOMENTE o ambiente/cenario:
- Descreva a SALA (paredes, piso, teto, portas, iluminacao do teto)
- Descreva a ATMOSFERA (luz, sombras, reflexos no aco inox)
- Descreva MATERIAIS (aco escovado, epoxi, azulejo, vidro)
- NAO descreva NENHUM equipamento medico (nem foco, nem mesa, nem monitor, nem pendente)
- O CENTRO da imagem deve ser um espaco VAZIO e LIMPO
- Cores QUENTES e NEUTRAS (branco, cinza, creme, prata) — NUNCA azul dominante

TERMINAR o prompt com: "professional DSLR photography, Canon EOS R5, 24-70mm f/2.8, photorealistic, warm neutral tones, no text, no writing, no labels, no medical equipment, empty center"
"""
        else:
            user_prompt = f"""Crie um prompt para imagem institucional da Salk Medical.
{context_block}
Conceito: {concept or 'conteudo institucional premium'}
Formato: {format_type}

CONTEXTO DA MARCA: Salk Medical fabrica equipamentos cirurgicos (focos, mesas, serras, suportes).
O publico-alvo sao ENGENHEIROS CLINICOS — profissionais que gerenciam, instalam e mantem equipamentos em hospitais.

O prompt DEVE refletir o TEMA/OBJETIVO acima. Exemplos:
- "Dia da Engenharia" → engenheiro clinico inspecionando sala cirurgica, checklist tecnico, manutencao preventiva de equipamentos, ferramentas de precisao sobre mesa de aco inox
- "Dia do Medico" → ambiente cirurgico premium, equipe medica desfocada, atmosfera de excelencia
- "Inovacao" → sala cirurgica moderna, tecnologia de ponta, design clean e futurista

REGRAS:
- A imagem deve contar uma HISTORIA relacionada ao tema, nao ser uma sala vazia
- Pode incluir PESSOAS desfocadas ou silhuetas se fizer sentido para o tema
- Cores QUENTES e NEUTRAS — NUNCA azul monocromatico dominante
- Nao descreva equipamentos medicos especificos de concorrentes
- Contexto sempre HOSPITALAR/CIRURGICO, focado no universo da engenharia clinica

TERMINAR com: "professional DSLR photography, Canon EOS R5, 24-70mm f/2.8, photorealistic, warm neutral tones, no text, no writing, no labels"
"""

        user_prompt += """
Responda EXATAMENTE neste formato:
POSITIVE: (prompt em ingles)
NEGATIVE: (prompt negativo em ingles)"""

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

        # Garantir qualidade fotorrealista, cores neutras e anti-texto no positivo
        quality_suffix = "professional DSLR photography, photorealistic, warm neutral tones, no text, no writing, no labels, no medical equipment, empty center composition"
        if positive and "no text" not in positive.lower():
            positive = positive.rstrip(".," ) + ", " + quality_suffix
        # Remover termos proibidos que o LLM pode ter incluido
        for banned in ["surgical light", "operating light", "surgical lamp", "operating table",
                       "surgical table", "medical monitor", "patient monitor", "pendant light",
                       "ceiling mounted light", "overhead surgical"]:
            positive = positive.replace(banned, "").replace("  ", " ")

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
