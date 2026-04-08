"""
Post Composer — Compoe post final para Instagram/social media.

Combina: imagem de fundo + headline + logo + gradiente + spec line
Resultado: imagem pronta para publicacao (sem precisar do Canva).

Regras de composicao (brand-guidelines.yaml):
- Margens: 60px (5.5% da largura)
- Logo: 180-200px min width
- Headline: 36pt bold, alinhado esquerda, topo
- Spec line: 18-20pt, branco 70% opacidade, centralizado rodape
- Gradientes: preto→transparente, topo 40-60%, rodape 50-70%
- Zona protegida: NUNCA texto sobre produto central
"""

from __future__ import annotations

import logging
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

# Diretorio de logos (relativo ao data_dir do squad)
LOGO_PATHS = {
    "salk": "logomarcas/Salk Medical/LogSalkMedicalPNG - W.png",
    "mendel": "logomarcas/Mendel/LogMendel-white.png",
    "dayho": "logomarcas/Dayho/LogDayho-white.png",
    "manager": "logomarcas/Manager Grupo/LogManager+logos_H-PTB-clean - white.png",
}

# Cores por marca
BRAND_COLORS = {
    "salk": {"primary": "#003366", "secondary": "#0066CC", "accent": "#FFFFFF"},
    "mendel": {"primary": "#1a1a2e", "secondary": "#16213e", "accent": "#FFFFFF"},
    "dayho": {"primary": "#2d2d2d", "secondary": "#444444", "accent": "#FFFFFF"},
    "manager": {"primary": "#003366", "secondary": "#0066CC", "accent": "#FFFFFF"},
}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Converte hex (#003366) para RGB tuple."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Carrega fonte. Tenta system fonts, fallback para default."""
    font_names = [
        "arial.ttf", "Arial.ttf",
        "arialbd.ttf", "Arial Bold.ttf",
        "segoeui.ttf", "Segoe UI.ttf",
        "segoeuib.ttf", "Segoe UI Bold.ttf",
        "calibri.ttf", "Calibri.ttf",
        "calibrib.ttf", "Calibri Bold.ttf",
    ]
    if bold:
        font_names = [f for f in font_names if "bd" in f.lower() or "bold" in f.lower()] + font_names

    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue

    # Fallback: PIL default font (bitmap, limited sizes)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except (OSError, IOError):
        return ImageFont.load_default()


def compose_post(
    image_path: str | Path,
    headline: str = "",
    brand: str = "salk",
    logo_dir: Optional[Path] = None,
    spec_line: str = "",
    anvisa_badge: str = "",
    output_path: Optional[Path] = None,
    target_size: tuple[int, int] = (1080, 1350),
) -> Path:
    """Compoe post final com imagem + headline + logo + gradiente.

    Args:
        image_path: Caminho da imagem de fundo gerada
        headline: Texto headline (primeira linha do copy)
        brand: Marca (salk, mendel, dayho, manager)
        logo_dir: Diretorio raiz das logos (docs_user/)
        spec_line: Linha tecnica do rodape (ex: "Registro ANVISA 1234")
        anvisa_badge: Badge ANVISA (canto inferior direito)
        output_path: Onde salvar (default: mesmo dir com sufixo _composed)
        target_size: Dimensoes finais (width, height)

    Returns:
        Path do arquivo composto
    """
    img = Image.open(image_path).convert("RGBA")

    # Resize para target se necessario
    if img.size != target_size:
        img = img.resize(target_size, Image.LANCZOS)

    width, height = target_size
    margin = int(width * 0.055)  # ~60px em 1080

    # ── Gradiente topo (para headline) ──────────────────────────
    if headline:
        grad_top = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw_grad = ImageDraw.Draw(grad_top)
        top_height = int(height * 0.45)  # 45% do topo
        for y in range(top_height):
            alpha = int(180 * (1 - y / top_height))  # 180→0 (70%→0%)
            draw_grad.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img, grad_top)

    # ── Gradiente rodape (para spec line / hashtags) ────────────
    grad_bottom = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_grad_b = ImageDraw.Draw(grad_bottom)
    bottom_start = int(height * 0.65)
    for y in range(bottom_start, height):
        progress = (y - bottom_start) / (height - bottom_start)
        alpha = int(200 * progress)  # 0→200 (0%→78%)
        draw_grad_b.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, grad_bottom)

    # ── Camada de texto ─────────────────────────────────────────
    txt_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    # Headline (36pt bold, topo esquerda)
    if headline:
        font_headline = _load_font(42, bold=True)
        # Word wrap
        max_chars = int((width - 2 * margin) / (42 * 0.55))  # ~chars por linha
        wrapped = textwrap.fill(headline, width=max_chars)
        # Sombra do texto (para legibilidade)
        shadow_offset = 2
        draw.multiline_text(
            (margin + shadow_offset, margin + shadow_offset),
            wrapped, font=font_headline, fill=(0, 0, 0, 160),
        )
        draw.multiline_text(
            (margin, margin),
            wrapped, font=font_headline, fill=(255, 255, 255, 255),
        )

    # Spec line (18pt, branco 70%, centralizado rodape)
    if spec_line:
        font_spec = _load_font(20, bold=False)
        bbox = draw.textbbox((0, 0), spec_line, font=font_spec)
        spec_w = bbox[2] - bbox[0]
        spec_x = (width - spec_w) // 2
        spec_y = height - margin - 30
        draw.text((spec_x, spec_y), spec_line, font=font_spec, fill=(255, 255, 255, 178))

    # ANVISA badge (12pt, branco 50%, canto inferior direito)
    if anvisa_badge:
        font_badge = _load_font(14, bold=False)
        bbox = draw.textbbox((0, 0), anvisa_badge, font=font_badge)
        badge_w = bbox[2] - bbox[0]
        draw.text(
            (width - margin - badge_w, height - margin - 15),
            anvisa_badge, font=font_badge, fill=(255, 255, 255, 128),
        )

    img = Image.alpha_composite(img, txt_layer)

    # ── Logo (canto superior direito) ───────────────────────────
    logo_placed = False
    if logo_dir:
        logo_rel = LOGO_PATHS.get(brand.lower(), LOGO_PATHS.get("salk", ""))
        logo_path = logo_dir / logo_rel
        if not logo_path.exists():
            # Tenta fallback no static dir
            alt_path = Path(__file__).parent.parent / "web" / "static" / "img" / "salk-logo-white.png"
            if alt_path.exists():
                logo_path = alt_path
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert("RGBA")
                # Redimensionar logo para ~180px de largura
                logo_target_w = 180
                ratio = logo_target_w / logo.width
                logo_h = int(logo.height * ratio)
                logo = logo.resize((logo_target_w, logo_h), Image.LANCZOS)
                # Posicionar no canto superior direito
                logo_x = width - margin - logo_target_w
                logo_y = margin
                img.paste(logo, (logo_x, logo_y), logo)
                logo_placed = True
            except Exception as e:
                logger.warning("Falha ao colocar logo: %s", e)

    if not logo_placed:
        logger.info("Logo não encontrada para brand=%s, compondo sem logo", brand)

    # ── Salvar resultado ────────────────────────────────────────
    final = img.convert("RGB")

    if output_path is None:
        p = Path(image_path)
        output_path = p.parent / f"{p.stem}_composed{p.suffix}"

    final.save(str(output_path), quality=95)
    logger.info("Post composto salvo: %s (%dx%d)", output_path, width, height)
    return output_path
