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
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Carregamento dinâmico de image-generation-config.yaml
# ---------------------------------------------------------------------------
_IMG_CONFIG_CACHE: Optional[dict] = None
_IMG_CONFIG_DATA_DIR: Optional[Path] = None


def _load_image_gen_config() -> dict:
    global _IMG_CONFIG_CACHE
    if _IMG_CONFIG_CACHE is not None:
        return _IMG_CONFIG_CACHE
    if _IMG_CONFIG_DATA_DIR:
        path = _IMG_CONFIG_DATA_DIR / "image-generation-config.yaml"
        if path.exists():
            try:
                _IMG_CONFIG_CACHE = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return _IMG_CONFIG_CACHE
            except Exception as e:
                logger.warning("Falha ao carregar image-generation-config.yaml: %s", e)
    _IMG_CONFIG_CACHE = {}
    return _IMG_CONFIG_CACHE


def init_image_gen_config(data_dir: Path) -> None:
    """Inicializa data_dir para carregamento do YAML. Chamado no startup."""
    global _IMG_CONFIG_DATA_DIR, _IMG_CONFIG_CACHE
    _IMG_CONFIG_DATA_DIR = data_dir
    _IMG_CONFIG_CACHE = None


def get_prompt_dimensions() -> dict:
    return _load_image_gen_config().get("prompt_dimensions", {})


def get_mandatory_negatives() -> dict:
    return _load_image_gen_config().get("mandatory_negatives", {})


def get_product_rules() -> dict:
    cfg = _load_image_gen_config()
    rules = cfg.get("product_rules", {})
    negatives = cfg.get("mandatory_negatives", {})
    # Resolve extra_negatives_ref → lista real
    for product, rule in rules.items():
        ref = rule.get("extra_negatives_ref")
        if ref and isinstance(ref, str):
            rule["extra_negatives"] = negatives.get(ref, [])
        elif not rule.get("extra_negatives"):
            rule["extra_negatives"] = []
    return rules


def get_product_scene_hints() -> dict:
    return _load_image_gen_config().get("product_scene_hints", {})


def get_product_inference_map() -> dict:
    return _load_image_gen_config().get("product_inference_map", {})


def get_hero_product() -> str:
    return _load_image_gen_config().get("hero_product", "lev")


class AutoPromptNB2:
    """Gerador de prompts NB2 com arquitetura de 8 dimensoes."""

    def __init__(self, llm_client=None, brandbook_loader=None, data_dir: Optional[Path] = None):
        self.llm = llm_client
        self._load_brandbook = brandbook_loader
        self._data_dir = data_dir
        self._brand_context_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Brand Intelligence — carrega ICP + identidade de marca dos YAMLs
    # ------------------------------------------------------------------

    def _load_buyer_personas(self) -> dict:
        """Carrega buyer-personas.yaml do data dir."""
        if not self._data_dir:
            return {}
        path = self._data_dir / "buyer-personas.yaml"
        if not path.exists():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data.get("personas", data) if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("Falha ao carregar buyer-personas: %s", e)
            return {}

    def _build_brand_context(self, brand: str) -> str:
        """Constroi bloco de contexto de marca + ICP a partir dos YAMLs.

        Retorna string formatada para injecao no system prompt.
        Resultado cacheado por brand para evitar re-leitura.
        """
        if brand in self._brand_context_cache:
            return self._brand_context_cache[brand]

        sections = []

        # 1. Brandbook — identidade, tom, pilares, publico
        bb = self._load_brandbook(brand) if self._load_brandbook else None
        if bb:
            sections.append(f"MARCA: {bb.get('full_name', brand)}")
            sections.append(f"TAGLINE: {bb.get('tagline', '')}")
            tone = bb.get("tone_of_voice", {})
            if tone:
                sections.append(f"TOM DE VOZ: {tone.get('primary', '')}")
                prohibited = tone.get("prohibited", [])
                if prohibited:
                    sections.append(f"TOM PROIBIDO: {', '.join(prohibited)}")

            pillars = bb.get("content_pillars", [])
            if pillars:
                pillar_lines = [f"  - {p['name']} ({p.get('percentage', '')}%): {p.get('description', '')}" for p in pillars]
                sections.append("PILARES DE CONTEUDO:\n" + "\n".join(pillar_lines))

            personas_bb = bb.get("target_personas", [])
            if personas_bb:
                persona_lines = [f"  - {p['name']} ({p.get('role', '')}): preocupacoes = {', '.join(p.get('concerns', []))}" for p in personas_bb]
                sections.append("PUBLICO-ALVO DA MARCA:\n" + "\n".join(persona_lines))

            products = bb.get("products", [])
            active = [p for p in products if p.get("status") == "ATIVO"]
            if active:
                prod_lines = [f"  - {p['name']}: {p.get('type', '')}" for p in active]
                sections.append("PRODUTOS ATIVOS:\n" + "\n".join(prod_lines))

        # 2. Buyer Personas — ICP detalhado
        personas = self._load_buyer_personas()
        if personas:
            icp_lines = []
            for key, persona in personas.items():
                title = persona.get("title", key)
                role = persona.get("decision_role", "")
                tone_p = persona.get("tone", "")
                pains = persona.get("pain_points", [])
                keywords = persona.get("keywords", [])
                icp_lines.append(f"  {title} ({role}):")
                if tone_p:
                    icp_lines.append(f"    Tom: {tone_p}")
                if keywords:
                    icp_lines.append(f"    Palavras-chave: {', '.join(keywords[:8])}")
                if pains:
                    icp_lines.append(f"    Dores: {'; '.join(pains[:3])}")
            sections.append("ICP DETALHADO (Ideal Customer Profile):\n" + "\n".join(icp_lines))

            # Destaque do ICP primario
            eng_clinica = personas.get("engenharia_clinica")
            if eng_clinica:
                sections.append(
                    f"ICP PRIMARIO: {eng_clinica.get('title', 'Engenheiro Clinico')} — "
                    f"{eng_clinica.get('decision_role', '')}. "
                    f"Foco em: {', '.join(eng_clinica.get('keywords', [])[:6])}. "
                    f"Dores: {'; '.join(eng_clinica.get('pain_points', [])[:3])}"
                )

        context = "\n".join(sections)
        self._brand_context_cache[brand] = context
        return context

    @staticmethod
    def infer_product(objective: str = "", pillar: str = "", title: str = "", context: str = "") -> str:
        """Sugere produto com base no contexto. Retorna key ou '' se institucional."""
        text = f"{objective} {pillar} {title} {context}".lower()
        for keyword, product in get_product_inference_map().items():
            if keyword in text:
                return product
        # Pilares que tipicamente envolvem produto
        if pillar in ("produto", "awareness_produto"):
            return get_hero_product()
        # Datas comemorativas, institucional = sem produto (NB2 prompt-only)
        if pillar in ("datas_comemorativas", "institucional"):
            return ""
        # Sem keyword de produto = NB2 prompt-only
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
        product_rules = get_product_rules().get(product_key, {})

        # Montar as 8 dimensoes
        dim_tecnica = get_prompt_dimensions()["tecnica"].get(
            technique, get_prompt_dimensions()["tecnica"]["dramatic_studio"]
        )
        dim_iluminacao = get_prompt_dimensions()["iluminacao"].get(
            lighting, get_prompt_dimensions()["iluminacao"]["dramatic_rim"]
        )
        dim_cenario = get_prompt_dimensions()["cenario"].get(
            scene, get_prompt_dimensions()["cenario"]["studio_neutro"]
        )
        dim_composicao = get_prompt_dimensions()["composicao"].get(
            composition, get_prompt_dimensions()["composicao"]["central_hero"]
        )
        dim_atmosfera = get_prompt_dimensions()["atmosfera"].get(
            atmosphere, get_prompt_dimensions()["atmosfera"]["premium_tech"]
        )
        dim_tecnico = get_prompt_dimensions()["detalhes_tecnicos"].get(
            format_type, get_prompt_dimensions()["detalhes_tecnicos"]["square_social"]
        )

        # Construir negative prompt
        negatives = (
            get_mandatory_negatives()["universal"]
            + get_mandatory_negatives()["medical"]
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
        product_rules = get_product_rules().get(product_key, {})

        # ── Brand Intelligence: contexto dinamico dos YAMLs ──
        brand_ctx = self._build_brand_context(brand)

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

=== INTELIGENCIA DE MARCA (carregado automaticamente) ===
{brand_ctx}
REGRA: Toda imagem deve ser contextualizada para o UNIVERSO do ICP primario (engenharia clinica).
O cenario, a atmosfera e os detalhes visuais devem ressoar com profissionais que GERENCIAM,
INSTALAM e fazem MANUTENCAO de equipamentos em hospitais. Pense como o ICP ve o ambiente.
"""
        # Scene hints por produto (perspectiva, espacialidade)
        scene_hints = get_product_scene_hints().get(product_key, {})
        if scene_hints:
            system += f"""
=== PERSPECTIVA ESPECIFICA PARA {product.upper()} ===
- Camera: {scene_hints['perspective']}
- Espacialidade: {scene_hints['spatial']}
"""
        elif not product:
            system += """
=== CONTEUDO INSTITUCIONAL (sem produto especifico) ===
- A imagem DEVE estar em CONTEXTO HOSPITALAR/CIRURGICO — NUNCA outro ambiente
- CENARIOS VALIDOS: centro cirurgico, sala de exames, UTI, sala de equipamentos, area tecnica do hospital
- CENARIOS PROIBIDOS: corredor, elevador, lobby, recepcao, escritorio, sala de reuniao, estacionamento, area externa
- A imagem deve contar uma HISTORIA relacionada ao TEMA/OBJETIVO
- Pode incluir PESSOAS (profissionais de saude) desfocadas ou em silhueta se fizer sentido para o tema
- Foco: profissionalismo, tecnologia, inovacao, humanidade

=== REFERENCIAS POR TIPO DE DATA SAZONAL ===
- Dia da Engenharia/Engenheiro Biomedico: engenheiro clinico de jaleco inspecionando painel tecnico em sala cirurgica, ferramentas de precisao, tablet com esquema tecnico, maos ajustando equipamento
- Dia do Medico/Cirurgiao: equipe medica em sala cirurgica, atmosfera de concentracao, luz cirurgica acesa (vista de baixo), maos com luvas estereis
- Dia do Enfermeiro: profissional organizando instrumental, cuidado com paciente, ambiente limpo e acolhedor
- Hospitalar Fair/Congresso: sala de demonstracao com equipamentos, publico tecnico, ambiente de inovacao
- Retrospectiva/Institucional: panorama de centro cirurgico moderno, multiplas salas, tecnologia integrada
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

Use a INTELIGENCIA DE MARCA do system prompt para entender quem e o publico,
qual o tom da marca, e como gerar imagens que RESSOEM com o ICP.

O prompt DEVE refletir o TEMA/OBJETIVO acima. Exemplos:
- "Dia da Engenharia" → engenheiro clinico inspecionando sala cirurgica, checklist tecnico, manutencao preventiva de equipamentos, ferramentas de precisao sobre mesa de aco inox
- "Dia do Medico" → ambiente cirurgico premium, equipe medica desfocada, atmosfera de excelencia
- "Inovacao" → sala cirurgica moderna, tecnologia de ponta, design clean e futurista

REGRAS:
- A imagem deve contar uma HISTORIA relacionada ao tema, nao ser uma sala vazia
- Pode incluir PESSOAS desfocadas ou silhuetas se fizer sentido para o tema
- Cores QUENTES e NEUTRAS — NUNCA azul monocromatico dominante
- Nao descreva equipamentos medicos especificos de concorrentes
- Contexto sempre HOSPITALAR/CIRURGICO, focado no universo do ICP primario

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

        # --- FIX 3: Validacao pos-LLM — cenario hospitalar obrigatorio ---
        positive, negative = self._validate_scene_context(positive, negative, product, objective)

        # Garantir qualidade fotorrealista, cores neutras e anti-texto no positivo
        quality_suffix = "professional DSLR photography, photorealistic, warm neutral tones, no text, no writing, no labels, no medical equipment, empty center composition"
        if positive and "no text" not in positive.lower():
            positive = positive.rstrip(".," ) + ", " + quality_suffix
        # Remover termos proibidos que o LLM pode ter incluido
        # 1. Equipamentos medicos (NB2 insere o produto real depois)
        banned_equipment = [
            "surgical light", "operating light", "surgical lamp", "operating table",
            "surgical table", "medical monitor", "patient monitor", "pendant light",
            "ceiling mounted light", "overhead surgical", "surgical focus",
            "LED light", "examination light", "surgical saw", "bone saw",
        ]
        # 2. Cenarios proibidos (geram imagens inutilizaveis)
        banned_scenes = [
            "hallway", "corridor", "elevator", "escalator", "passageway",
            "lobby", "reception area", "waiting room", "break room",
            "office space", "conference room", "meeting room",
            "parking", "garage", "warehouse", "factory floor",
            "street", "outdoor", "garden", "rooftop",
            "bathroom", "restroom", "kitchen", "cafeteria",
            "staircase", "stairwell", "entrance hall",
        ]
        for banned in banned_equipment:
            positive = positive.replace(banned, "").replace("  ", " ")
        # Cenarios: substituir por contexto hospitalar se detectado
        scene_replaced = False
        for banned in banned_scenes:
            if banned in positive.lower():
                logger.warning("CENARIO PROIBIDO detectado: '%s' — substituindo por sala cirurgica", banned)
                positive = re.sub(re.escape(banned), "modern surgical suite", positive, flags=re.IGNORECASE)
                scene_replaced = True
        if scene_replaced:
            positive = positive.replace("  ", " ")

        # Garantir negatives obrigatorios mesmo que LLM esqueca
        mandatory_neg = (
            get_mandatory_negatives()["universal"]
            + get_mandatory_negatives()["medical"]
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

    # ------------------------------------------------------------------
    # Validacao de cenario pos-LLM (Fix 3)
    # ------------------------------------------------------------------

    # Termos que indicam contexto hospitalar/cirurgico valido
    _VALID_SCENE_TERMS = [
        "surgical", "surgery", "operating room", "operating theatre",
        "hospital", "clinical", "medical", "sterile", "OR suite",
        "surgical suite", "ICU", "intensive care", "examination room",
        "biomedical", "healthcare", "medical center", "clean room",
        "stainless steel", "scrubs", "scalpel", "instruments",
        "patient", "surgeon", "nurse", "anesthesia", "procedure",
        "equipment room", "technical room", "maintenance bay",
    ]

    # Presets seguros por tipo de conteudo (fallback deterministico)
    _SAFE_PRESETS = {
        "engenharia": (
            "clinical engineer in white lab coat inspecting technical panel "
            "inside modern surgical suite, precision tools on stainless steel table, "
            "tablet showing technical schematics, warm overhead lighting, "
            "sterile environment, professional DSLR photography, Canon EOS R5, "
            "24-70mm f/2.8, photorealistic, warm neutral tones, no text, no writing"
        ),
        "medico": (
            "medical team in modern operating room, concentrated atmosphere, "
            "surgical light seen from below, sterile gloved hands, "
            "warm neutral tones, professional DSLR photography, Canon EOS R5, "
            "photorealistic, no text, no writing"
        ),
        "enfermeiro": (
            "healthcare professional organizing surgical instruments on stainless steel tray, "
            "clean sterile environment, warm lighting, caring atmosphere, "
            "modern hospital setting, professional DSLR photography, "
            "photorealistic, warm neutral tones, no text, no writing"
        ),
        "institucional": (
            "panoramic view of modern surgical suite with integrated technology, "
            "stainless steel surfaces, warm overhead lighting, clean sterile atmosphere, "
            "multiple procedure rooms visible, cutting-edge medical environment, "
            "professional DSLR photography, Canon EOS R5, photorealistic, "
            "warm neutral tones, no text, no writing"
        ),
    }

    def _validate_scene_context(
        self, positive: str, negative: str, product: str, objective: str = ""
    ) -> tuple[str, str]:
        """
        Valida se o prompt gerado contem contexto hospitalar/cirurgico.

        Para conteudo institucional (sem produto), e CRITICO que a cena seja
        hospitalar. Se nao for, substitui por preset seguro.
        Para conteudo com produto, e menos critico (NB2 ja insere o produto).
        """
        if not positive:
            return positive, negative

        positive_lower = positive.lower()
        has_valid_scene = any(
            term.lower() in positive_lower for term in self._VALID_SCENE_TERMS
        )

        if has_valid_scene:
            return positive, negative

        # Cenario invalido detectado
        if product:
            # Com produto: apenas injetar contexto hospitalar no prompt
            logger.warning(
                "VALIDACAO CENA: prompt com produto '%s' sem contexto hospitalar — injetando",
                product,
            )
            positive = f"inside modern surgical suite, sterile hospital environment, {positive}"
            return positive, negative

        # Sem produto (institucional): fallback para preset seguro
        logger.warning(
            "VALIDACAO CENA: prompt institucional SEM contexto hospitalar — usando preset seguro. "
            "Prompt original: %s",
            positive[:200],
        )

        # Escolher preset baseado no objetivo
        obj_lower = (objective or "").lower()
        preset_key = "institucional"
        if any(k in obj_lower for k in ["engenhar", "biomedic", "tecnic"]):
            preset_key = "engenharia"
        elif any(k in obj_lower for k in ["medic", "cirurgi", "doctor"]):
            preset_key = "medico"
        elif any(k in obj_lower for k in ["enfermeir", "nurse", "cuidado"]):
            preset_key = "enfermeiro"

        logger.info("VALIDACAO CENA: preset selecionado = '%s'", preset_key)
        return self._SAFE_PRESETS[preset_key], negative

    @staticmethod
    def list_dimensions() -> dict:
        """Lista todas as dimensoes e opcoes disponiveis."""
        return {
            dim: list(options.keys())
            for dim, options in get_prompt_dimensions().items()
        }

    @staticmethod
    def list_products() -> list[str]:
        """Lista produtos com regras especificas."""
        return list(get_product_rules().keys())
