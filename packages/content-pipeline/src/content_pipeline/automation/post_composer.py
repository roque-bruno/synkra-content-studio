"""
Post Composer — Layout editorial para Instagram (Salk Medical / Manager Grupo).

Direcao criativa (Apex/Visual Designer):
Estilo The Economist cover / Apple keynote / Bloomberg Businessweek.
Foto protagonista, uma unica sentenca tipograficamente forte no terco
inferior, muito espaco negativo. CTA tipo link, sem box. Headline two-tier
(eyebrow menor + titulo grande) quando a copy tem ":".

Principios:
- Subtracao > adicao
- 60% foto, 30% headline, 10% UI
- Eyebrow ACIMA do headline (kicker)
- CTA link-style, nao botao
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_FONTS_DIR = Path(__file__).parent / "fonts"
_STATIC_IMG_DIR = Path(__file__).parent.parent / "web" / "static" / "img"

LOGO_FILES = {
    "salk": "logo-salk-white.png",
    "manager": "logo-manager-white.png",
    "mendel": "logo-salk-white.png",
    "dayho": "logo-salk-white.png",
}

# Cores por marca: accent usado em CTA link e detalhes
BRAND_COLORS = {
    "salk":    {"primary": (0, 51, 102),  "accent": (102, 178, 255)},
    "manager": {"primary": (0, 51, 102),  "accent": (102, 178, 255)},
    "mendel":  {"primary": (26, 26, 46),  "accent": (130, 150, 200)},
    "dayho":   {"primary": (45, 45, 45),  "accent": (200, 200, 200)},
}

CTA_FALLBACK = "SAIBA MAIS →"
CTA_MAX_WORDS = 5


def _load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Carrega Montserrat embutida. weight: regular | bold | light."""
    weight_map = {
        "regular": "Montserrat-Regular.ttf",
        "bold":    "Montserrat-Bold.ttf",
        "black":   "Montserrat-Bold.ttf",  # Usamos Bold como Black
        "light":   "Montserrat-Light.ttf",
    }
    bundled = _FONTS_DIR / weight_map.get(weight, "Montserrat-Regular.ttf")
    if bundled.exists():
        try:
            return ImageFont.truetype(str(bundled), size)
        except (OSError, IOError):
            pass
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Quebra texto em linhas que cabem em max_width pixels."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        bbox = font.getbbox(test)
        if (bbox[2] - bbox[0]) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _measure_lines(
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    line_spacing: float = 1.0,
) -> tuple[int, int, int]:
    """Retorna (largura_max, altura_total, line_height)."""
    if not lines:
        return (0, 0, 0)
    max_w = 0
    line_h = 0
    for line in lines:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w > max_w:
            max_w = w
        if h > line_h:
            line_h = h
    line_h_spaced = int(line_h * line_spacing)
    return (max_w, line_h_spaced * len(lines), line_h_spaced)


def _split_two_tier(headline: str) -> tuple[str, str]:
    """Quebra headline em (eyebrow_kicker, main_title) usando ':' como pivot.
    Se nao tem ':', retorna ('', headline).
    """
    if ":" in headline:
        a, b = headline.split(":", 1)
        return (a.strip(), b.strip())
    return ("", headline.strip())


def _truncate_cta(cta: str) -> str:
    """CTA so passa se tiver <= CTA_MAX_WORDS palavras. Senao usa fallback."""
    if not cta:
        return ""
    clean = cta.strip().lstrip(">>").lstrip("→").lstrip("➤").strip().rstrip(".")
    words = clean.split()
    if len(words) <= CTA_MAX_WORDS:
        return clean.upper() + " →"
    return CTA_FALLBACK


def _draw_text_with_blur_shadow(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
) -> None:
    """Texto com sombra simulando blur (2 passadas em offsets diferentes)."""
    x, y = pos
    # Passada 1: offset maior, alpha menor (blur largo)
    draw.text((x + 2, y + 4), text, font=font, fill=(0, 0, 0, 90))
    # Passada 2: offset menor, alpha maior (core da sombra)
    draw.text((x + 1, y + 2), text, font=font, fill=(0, 0, 0, 130))
    # Texto principal
    draw.text((x, y), text, font=font, fill=fill)


def compose_post(
    image_path: str | Path,
    headline: str = "",
    subline: str = "",
    cta: str = "",
    brand: str = "salk",
    logo_dir: Optional[Path] = None,
    spec_line: str = "",
    anvisa_badge: str = "",
    output_path: Optional[Path] = None,
    target_size: tuple[int, int] = (1080, 1350),
) -> Path:
    """Compoe post final com layout editorial.

    Args:
        image_path: Foto de fundo (ja em portrait)
        headline: Titulo principal. Se contem ':', vira two-tier.
        subline: Eyebrow/kicker — vai ACIMA do headline, pequeno.
        cta: Call-to-action curto. Se >5 palavras, vira "SAIBA MAIS →".
        brand: salk | manager | mendel | dayho
        spec_line: Linha tecnica rodape
        anvisa_badge: Badge ANVISA rodape direita
        target_size: Dimensoes finais (1080x1350 default = Instagram feed 4:5)
    """
    img = Image.open(image_path).convert("RGBA")

    # Crop centralizado + scale (sem distorcao)
    if img.size != target_size:
        tw, th = target_size
        sw, sh = img.size
        src_ratio = sw / sh
        tgt_ratio = tw / th
        if abs(src_ratio - tgt_ratio) > 0.01:
            if src_ratio > tgt_ratio:
                new_w = int(sh * tgt_ratio)
                left = (sw - new_w) // 2
                img = img.crop((left, 0, left + new_w, sh))
            else:
                new_h = int(sw / tgt_ratio)
                top = (sh - new_h) // 2
                img = img.crop((0, top, sw, top + new_h))
        img = img.resize(target_size, Image.LANCZOS)

    width, height = target_size
    margin = int(width * 0.075)  # 7.5% (~81px) — premium
    brand_color = BRAND_COLORS.get(brand.lower(), BRAND_COLORS["salk"])

    # ════════════════════════════════════════════════════════════
    # 1. GRADIENTE BOTTOM (Apex: bloco subiu p/ 74%, gradient
    #    comeca em 45% para cobrir eyebrow tambem)
    # ════════════════════════════════════════════════════════════
    grad = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_grad = ImageDraw.Draw(grad)
    grad_start = int(height * 0.45)  # era 55%
    for y in range(grad_start, height):
        progress = (y - grad_start) / (height - grad_start)
        alpha = int(220 * (progress ** 1.6))  # alpha 220, curva 1.6
        draw_grad.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad)

    # ════════════════════════════════════════════════════════════
    # 2. GRADIENTE TOP (mais forte — Apex: logo precisa ser legivel
    #    em qualquer foto, fundos claros estavam apagando a marca)
    # ════════════════════════════════════════════════════════════
    grad_top = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_gt = ImageDraw.Draw(grad_top)
    top_h = int(height * 0.22)  # 22% (era 12%)
    for y in range(top_h):
        alpha = int(160 * (1 - y / top_h) ** 1.5)  # alpha 160 (era 95)
        draw_gt.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad_top)

    # ════════════════════════════════════════════════════════════
    # 3. LOGO TOP-RIGHT (185px — Apex: marca com mais presenca)
    # ════════════════════════════════════════════════════════════
    logo_w_target = 185
    logo_filename = LOGO_FILES.get(brand.lower(), "logo-salk-white.png")
    logo_path = _STATIC_IMG_DIR / logo_filename
    if not logo_path.exists() and logo_dir:
        for cand in ["LogSalkMedicalPNG - W.png", "LogSalk.png", "salk-logo-white.png"]:
            alt = logo_dir / cand
            if alt.exists():
                logo_path = alt
                break
    if logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            ratio = logo_w_target / logo.width
            logo_h = int(logo.height * ratio)
            logo = logo.resize((logo_w_target, logo_h), Image.LANCZOS)
            logo_x = width - margin - logo_w_target
            logo_y = margin + 8  # Apex: leve respiro do topo
            img.paste(logo, (logo_x, logo_y), logo)
        except Exception as e:
            logger.warning("Falha ao colocar logo: %s", e)

    # ════════════════════════════════════════════════════════════
    # 4. CAMADA DE TEXTO
    # ════════════════════════════════════════════════════════════
    txt_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    text_max_w = width - 2 * margin

    # ────────────────────────────────────────────────────────────
    # HEADLINE two-tier (split em ':' se houver)
    # ────────────────────────────────────────────────────────────
    eyebrow_from_split, main_title = _split_two_tier(headline) if headline else ("", "")

    # Eyebrow vem do split do headline OU do parametro subline (mas split tem prioridade)
    eyebrow_text = eyebrow_from_split if eyebrow_from_split else (subline.strip() if subline else "")

    # Main title: Apex prescreveu tamanhos maiores (84/76/68/60) e
    # line_spacing 0.92 (era 0.98) — tipografia keynote tight
    main_lines: list[str] = []
    main_total_h = 0
    main_line_h = 0
    font_main = None
    if main_title:
        for size in (84, 76, 68, 60):
            font_main = _load_font(size, weight="black")
            lines = _wrap_text(main_title.upper(), font_main, text_max_w)
            if len(lines) <= 3:
                main_lines = lines
                _, main_total_h, main_line_h = _measure_lines(lines, font_main, line_spacing=0.92)
                break
        else:
            font_main = _load_font(60, weight="black")
            main_lines = _wrap_text(main_title.upper(), font_main, text_max_w)[:3]
            _, main_total_h, main_line_h = _measure_lines(main_lines, font_main, line_spacing=0.92)

    # Eyebrow: Apex prescreveu 28pt BOLD UPPERCASE accent color (era 22 regular cinza)
    # Kicker editorial precisa gritar a categoria, nao sussurrar
    eyebrow_lines: list[str] = []
    eyebrow_total_h = 0
    eyebrow_line_h = 0
    font_eyebrow = None
    if eyebrow_text:
        font_eyebrow = _load_font(28, weight="bold")
        eyebrow_text = eyebrow_text.upper()
        eyebrow_lines = _wrap_text(eyebrow_text, font_eyebrow, text_max_w)[:2]
        _, eyebrow_total_h, eyebrow_line_h = _measure_lines(eyebrow_lines, font_eyebrow, line_spacing=1.25)

    # CTA link-style com regua horizontal (Apex: presenca de "link editorial")
    cta_text = _truncate_cta(cta)
    font_cta = None
    cta_w_px = 0
    cta_h_px = 0
    if cta_text:
        font_cta = _load_font(20, weight="bold")  # 18 -> 20
        bbox = font_cta.getbbox(cta_text)
        cta_w_px = bbox[2] - bbox[0]
        cta_h_px = bbox[3] - bbox[1]

    # ────────────────────────────────────────────────────────────
    # POSICIONAMENTO (Apex: baseline 74% — terco inferior real)
    # eyebrow → gap 24px → headline → gap 44px (com regua) → CTA
    # ────────────────────────────────────────────────────────────
    # Footer: spec_line + anvisa
    footer_reserve = 50 if (spec_line or anvisa_badge) else 20
    footer_y = height - margin - footer_reserve

    # Bloco de texto: ancora baseline do main_title em 74% (era 82%)
    # Libera respiro inferior — terco inferior classico editorial
    block_baseline = int(height * 0.74)

    # Y do main_title (topo)
    main_y = block_baseline - main_total_h

    # Y do eyebrow (acima do main, com gap 24 — era 16)
    eyebrow_y = main_y - eyebrow_total_h - 24 if eyebrow_lines else 0

    # Y do CTA (abaixo do main, com gap 44 — era 32)
    # A regua sera desenhada 12px acima do texto do CTA
    cta_y = block_baseline + 44

    # Garantir que CTA nao colide com footer
    if cta_text and (cta_y + cta_h_px > footer_y - 10):
        cta_y = footer_y - cta_h_px - 10

    # ────────────────────────────────────────────────────────────
    # DESENHAR: eyebrow (Apex: accent color bold uppercase)
    # Kicker editorial colorido — The Economist style
    # ────────────────────────────────────────────────────────────
    if eyebrow_lines and font_eyebrow:
        y = eyebrow_y
        accent_rgb = brand_color["accent"]
        for line in eyebrow_lines:
            _draw_text_with_blur_shadow(
                draw, (margin, y), line, font_eyebrow, accent_rgb + (255,)
            )
            y += eyebrow_line_h

    # ────────────────────────────────────────────────────────────
    # DESENHAR: main title (branco, peso black, tight spacing)
    # ────────────────────────────────────────────────────────────
    if main_lines and font_main:
        y = main_y
        for line in main_lines:
            _draw_text_with_blur_shadow(
                draw, (margin, y), line, font_main, (255, 255, 255, 255)
            )
            y += main_line_h

    # ────────────────────────────────────────────────────────────
    # DESENHAR: CTA link-style com regua horizontal accent
    # (Apex: presenca de "link editorial" tipo Monocle)
    # ────────────────────────────────────────────────────────────
    if cta_text and font_cta:
        accent_rgb = brand_color["accent"]
        # Regua horizontal 40px / 2px stroke / 12px acima do texto
        rule_y = cta_y - 12
        draw.line(
            [(margin, rule_y), (margin + 40, rule_y)],
            fill=accent_rgb + (255,),
            width=2,
        )
        _draw_text_with_blur_shadow(
            draw,
            (margin, cta_y),
            cta_text,
            font_cta,
            accent_rgb + (255,),
        )

    # ────────────────────────────────────────────────────────────
    # DESENHAR: spec line (rodape centralizado, dentro da margem)
    # ────────────────────────────────────────────────────────────
    if spec_line:
        font_spec = _load_font(16, weight="light")
        bbox = font_spec.getbbox(spec_line)
        sw_ = bbox[2] - bbox[0]
        sx = (width - sw_) // 2
        sy = height - margin - 22
        draw.text((sx, sy), spec_line, font=font_spec, fill=(255, 255, 255, 160))

    # ────────────────────────────────────────────────────────────
    # DESENHAR: ANVISA badge (rodape direita)
    # ────────────────────────────────────────────────────────────
    if anvisa_badge:
        font_badge = _load_font(12, weight="light")
        bbox = font_badge.getbbox(anvisa_badge)
        bw = bbox[2] - bbox[0]
        bx = width - margin - bw
        by = height - margin - 10
        draw.text((bx, by), anvisa_badge, font=font_badge, fill=(255, 255, 255, 130))

    img = Image.alpha_composite(img, txt_layer)

    # Salvar
    final = img.convert("RGB")
    if output_path is None:
        p = Path(image_path)
        output_path = p.parent / f"{p.stem}_composed{p.suffix}"
    final.save(str(output_path), quality=95)
    logger.info("Post composto salvo: %s (%dx%d)", output_path, width, height)
    return output_path
