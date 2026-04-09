"""
Post Composer — Compoe post final para Instagram/social media.

Layout profissional inspirado em advertising hospitalar real:
- Logo top-right em zona reservada (sem texto invadindo)
- Faixa horizontal de cor da marca (separador visual)
- Headline DOMINANTE bottom-left, fonte ExtraBold/Black, multilinha
- Subline (descricao curta) abaixo do headline em peso lighter
- CTA box (opcional) com cor da marca
- Spec line bottom-center pequena
- ANVISA badge bottom-right pequeno
- Gradiente bottom escuro para legibilidade do headline
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Diretorio de fontes embutidas (Montserrat, Google Fonts OFL)
_FONTS_DIR = Path(__file__).parent / "fonts"

# Logos embutidas no static
_STATIC_IMG_DIR = Path(__file__).parent.parent / "web" / "static" / "img"

LOGO_FILES = {
    "salk": "logo-salk-white.png",
    "manager": "logo-manager-white.png",
    "mendel": "logo-salk-white.png",
    "dayho": "logo-salk-white.png",
}

# Cores por marca (primary usado em faixas e CTAs)
BRAND_COLORS = {
    "salk":    {"primary": (0, 51, 102),     "accent": (0, 102, 204)},
    "manager": {"primary": (0, 51, 102),     "accent": (0, 102, 204)},
    "mendel":  {"primary": (26, 26, 46),     "accent": (22, 33, 62)},
    "dayho":   {"primary": (45, 45, 45),     "accent": (68, 68, 68)},
}


def _load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Carrega Montserrat embutida. weight: regular | bold | black | light."""
    weight_map = {
        "regular": "Montserrat-Regular.ttf",
        "bold": "Montserrat-Bold.ttf",
        "black": "Montserrat-Bold.ttf",  # Usamos Bold como fallback se Black nao existir
        "light": "Montserrat-Light.ttf",
    }
    fname = weight_map.get(weight, "Montserrat-Regular.ttf")
    bundled = _FONTS_DIR / fname

    if bundled.exists():
        try:
            return ImageFont.truetype(str(bundled), size)
        except (OSError, IOError):
            pass

    # Fallback Linux
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


def _measure_lines(lines: list[str], font: ImageFont.FreeTypeFont, line_spacing: float = 1.1) -> tuple[int, int, int]:
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
    total_h = line_h_spaced * len(lines)
    return (max_w, total_h, line_h_spaced)


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
    """Compoe post final com layout profissional.

    Args:
        image_path: Caminho da imagem de fundo (ja em portrait)
        headline: Texto principal (max ~6 palavras, vai grande)
        subline: Texto secundario (descricao curta)
        cta: Call-to-action (vai num box colorido)
        brand: Marca (salk, mendel, dayho, manager)
        spec_line: Linha tecnica do rodape
        anvisa_badge: Badge ANVISA (canto inferior direito)
        target_size: Dimensoes finais (1080x1350 default)

    Returns:
        Path do arquivo composto
    """
    img = Image.open(image_path).convert("RGBA")

    if img.size != target_size:
        # Crop centralizado para preservar aspecto, depois resize
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
    margin = int(width * 0.06)  # ~65px em 1080
    brand_color = BRAND_COLORS.get(brand.lower(), BRAND_COLORS["salk"])

    # ════════════════════════════════════════════════════════════
    # 1. GRADIENTE BOTTOM (fundo escuro para legibilidade do headline)
    # ════════════════════════════════════════════════════════════
    grad = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_grad = ImageDraw.Draw(grad)
    grad_start = int(height * 0.42)  # 42% do topo (deixa imagem livre na parte de cima)
    for y in range(grad_start, height):
        progress = (y - grad_start) / (height - grad_start)
        # Curva suave: comeca transparente, termina 88% preto
        alpha = int(225 * (progress ** 1.4))
        draw_grad.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad)

    # ════════════════════════════════════════════════════════════
    # 2. GRADIENTE TOP suave (para logo nao ficar perdida em fundo claro)
    # ════════════════════════════════════════════════════════════
    grad_top = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_gt = ImageDraw.Draw(grad_top)
    top_h = int(height * 0.20)
    for y in range(top_h):
        alpha = int(120 * (1 - y / top_h) ** 1.2)
        draw_gt.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad_top)

    # ════════════════════════════════════════════════════════════
    # 3. LOGO TOP-RIGHT (zona reservada — texto NUNCA invade)
    # ════════════════════════════════════════════════════════════
    logo_w_target = 220
    logo_h_actual = 0
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
            logo_y = margin
            img.paste(logo, (logo_x, logo_y), logo)
            logo_h_actual = logo_h
        except Exception as e:
            logger.warning("Falha ao colocar logo: %s", e)

    # Zona reservada da logo: top-right ate logo_y + logo_h + padding
    logo_zone_bottom = margin + logo_h_actual + 20

    # ════════════════════════════════════════════════════════════
    # 4. CAMADA DE TEXTO
    # ════════════════════════════════════════════════════════════
    txt_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    # Area util para textos (descontando margens)
    text_max_w = width - 2 * margin

    # ────────────────────────────────────────────────────────────
    # HEADLINE (bottom-left, fonte grande Bold, multilinha)
    # ────────────────────────────────────────────────────────────
    headline_lines: list[str] = []
    headline_total_h = 0
    headline_line_h = 0
    if headline:
        # Tamanho dinamico: comeca em 78pt, reduz se nao couber em 3 linhas
        for size in (82, 76, 70, 64, 58, 52):
            font_h = _load_font(size, weight="bold")
            lines = _wrap_text(headline.upper(), font_h, text_max_w)
            if len(lines) <= 3:
                headline_lines = lines
                _, headline_total_h, headline_line_h = _measure_lines(lines, font_h, line_spacing=1.05)
                font_headline = font_h
                break
        else:
            font_headline = _load_font(52, weight="bold")
            headline_lines = _wrap_text(headline.upper(), font_headline, text_max_w)[:3]
            _, headline_total_h, headline_line_h = _measure_lines(headline_lines, font_headline, line_spacing=1.05)

    # ────────────────────────────────────────────────────────────
    # SUBLINE (texto secundario abaixo do headline)
    # ────────────────────────────────────────────────────────────
    subline_lines: list[str] = []
    subline_total_h = 0
    subline_line_h = 0
    font_subline = None
    if subline:
        font_subline = _load_font(28, weight="regular")
        subline_lines = _wrap_text(subline, font_subline, text_max_w)[:2]
        _, subline_total_h, subline_line_h = _measure_lines(subline_lines, font_subline, line_spacing=1.25)

    # ────────────────────────────────────────────────────────────
    # CTA box
    # ────────────────────────────────────────────────────────────
    cta_h = 0
    cta_w = 0
    font_cta = None
    if cta:
        font_cta = _load_font(24, weight="bold")
        bbox = font_cta.getbbox(cta.upper())
        cta_text_w = bbox[2] - bbox[0]
        cta_text_h = bbox[3] - bbox[1]
        cta_padding_x = 28
        cta_padding_y = 16
        cta_w = cta_text_w + 2 * cta_padding_x
        cta_h = cta_text_h + 2 * cta_padding_y

    # ────────────────────────────────────────────────────────────
    # Footer reservado (spec line + anvisa)
    # ────────────────────────────────────────────────────────────
    footer_h = 0
    if spec_line or anvisa_badge:
        footer_h = 50

    # ────────────────────────────────────────────────────────────
    # Calcular posicoes (de baixo para cima)
    # ────────────────────────────────────────────────────────────
    cursor_y = height - margin - footer_h

    # CTA (acima do footer)
    cta_y = 0
    if cta:
        cursor_y -= cta_h + 25
        cta_y = cursor_y

    # Subline (acima do CTA)
    subline_y = 0
    if subline_lines:
        cursor_y -= subline_total_h + 18
        subline_y = cursor_y

    # Headline (acima da subline) — espacamento generoso
    headline_y = 0
    if headline_lines:
        cursor_y -= headline_total_h + 8
        headline_y = cursor_y

    # Faixa de marca (linha horizontal acima do headline)
    brand_bar_y = headline_y - 28

    # ────────────────────────────────────────────────────────────
    # DESENHAR: faixa de marca
    # ────────────────────────────────────────────────────────────
    if headline_lines:
        bar_w = 80
        bar_h = 6
        draw.rectangle(
            [(margin, brand_bar_y), (margin + bar_w, brand_bar_y + bar_h)],
            fill=brand_color["accent"] + (255,),
        )

    # ────────────────────────────────────────────────────────────
    # DESENHAR: headline (com sombra suave)
    # ────────────────────────────────────────────────────────────
    if headline_lines:
        y = headline_y
        for line in headline_lines:
            # Sombra
            draw.text((margin + 2, y + 2), line, font=font_headline, fill=(0, 0, 0, 200))
            # Texto principal
            draw.text((margin, y), line, font=font_headline, fill=(255, 255, 255, 255))
            y += headline_line_h

    # ────────────────────────────────────────────────────────────
    # DESENHAR: subline
    # ────────────────────────────────────────────────────────────
    if subline_lines and font_subline:
        y = subline_y
        for line in subline_lines:
            draw.text((margin + 1, y + 1), line, font=font_subline, fill=(0, 0, 0, 180))
            draw.text((margin, y), line, font=font_subline, fill=(255, 255, 255, 230))
            y += subline_line_h

    # ────────────────────────────────────────────────────────────
    # DESENHAR: CTA box
    # ────────────────────────────────────────────────────────────
    if cta and font_cta:
        cta_x = margin
        # Fundo do CTA com cor da marca
        draw.rectangle(
            [(cta_x, cta_y), (cta_x + cta_w, cta_y + cta_h)],
            fill=brand_color["accent"] + (255,),
        )
        # Texto centralizado no box
        cta_text = cta.upper()
        bbox = font_cta.getbbox(cta_text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        text_x = cta_x + (cta_w - tw) // 2
        text_y = cta_y + (cta_h - th) // 2 - bbox[1]
        draw.text((text_x, text_y), cta_text, font=font_cta, fill=(255, 255, 255, 255))

    # ────────────────────────────────────────────────────────────
    # DESENHAR: spec line (rodape centralizado)
    # ────────────────────────────────────────────────────────────
    if spec_line:
        font_spec = _load_font(18, weight="light")
        bbox = font_spec.getbbox(spec_line)
        sw_ = bbox[2] - bbox[0]
        sx = (width - sw_) // 2
        sy = height - margin - 25
        draw.text((sx, sy), spec_line, font=font_spec, fill=(255, 255, 255, 180))

    # ────────────────────────────────────────────────────────────
    # DESENHAR: ANVISA badge (rodape direita)
    # ────────────────────────────────────────────────────────────
    if anvisa_badge:
        font_badge = _load_font(13, weight="light")
        bbox = font_badge.getbbox(anvisa_badge)
        bw = bbox[2] - bbox[0]
        bx = width - margin - bw
        by = height - margin - 12
        draw.text((bx, by), anvisa_badge, font=font_badge, fill=(255, 255, 255, 140))

    img = Image.alpha_composite(img, txt_layer)

    # ════════════════════════════════════════════════════════════
    # Salvar
    # ════════════════════════════════════════════════════════════
    final = img.convert("RGB")
    if output_path is None:
        p = Path(image_path)
        output_path = p.parent / f"{p.stem}_composed{p.suffix}"
    final.save(str(output_path), quality=95)
    logger.info("Post composto salvo: %s (%dx%d)", output_path, width, height)
    return output_path
