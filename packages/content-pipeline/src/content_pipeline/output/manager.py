"""
Output Manager — gerenciamento de arquivos de saída.

Responsabilidades:
- Naming convention consistente
- Organização por produto/campanha/data
- Salvamento de imagens com qualidade configurável
- Metadados JSON por geração
- Log de produção (journey log)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image

from content_pipeline.nb2.vdp_loader import VDPSpec

logger = logging.getLogger(__name__)


class OutputManager:
    """
    Gerencia salvamento e organização de outputs do pipeline.

    Estrutura de diretórios:
        output/
        ├── nb2/
        │   ├── calibracao/
        │   │   ├── hero-lev-v1_2026-03-25_001.png
        │   │   └── hero-lev-v1_2026-03-25_001.meta.json
        │   └── batch-001/
        │       ├── lev-4lev_001.png
        │       └── lev-4lev_001.meta.json
        ├── composicao/
        └── logs/
            └── production-log.jsonl
    """

    def __init__(self, base_dir: Path, quality: int = 95) -> None:
        self._base_dir = Path(base_dir)
        self._quality = quality
        self._nb2_dir = self._base_dir / "nb2"
        self._comp_dir = self._base_dir / "composicao"
        self._logs_dir = self._base_dir / "logs"

    def save_nb2_image(
        self,
        image: Image.Image,
        vdp: VDPSpec,
        *,
        subdir: str = "",
        suffix: str = "",
    ) -> Path:
        """
        Salva imagem NB2 com naming convention padronizado.

        Args:
            image: Imagem PIL gerada.
            vdp: VDP da peça.
            subdir: Subdiretório (ex: "calibracao", "batch-001").
            suffix: Sufixo adicional (ex: "_attempt2").

        Returns:
            Caminho absoluto da imagem salva.
        """
        output_dir = self._nb2_dir / subdir if subdir else self._nb2_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        base_name = vdp.product_slug
        version = vdp.versao

        counter = 1
        while True:
            filename = f"{base_name}_{version}_{timestamp}_{counter:03d}{suffix}.png"
            output_path = output_dir / filename
            if not output_path.exists():
                break
            counter += 1

        if image.mode == "RGBA":
            image.save(str(output_path), "PNG", optimize=True)
        else:
            image = image.convert("RGB")
            image.save(str(output_path), "PNG", optimize=True)

        logger.info("Imagem salva: %s (%dx%d)", output_path.name, image.width, image.height)
        return output_path

    def save_generation_metadata(
        self,
        vdp: VDPSpec,
        output_path: Path,
        attempts: int,
        elapsed: float,
        prompt: str,
    ) -> Path:
        """
        Salva metadados da geração em JSON ao lado da imagem.

        Args:
            vdp: VDP da peça.
            output_path: Caminho da imagem gerada.
            attempts: Número de tentativas.
            elapsed: Tempo total em segundos.
            prompt: Prompt utilizado.

        Returns:
            Caminho do arquivo de metadados.
        """
        meta_path = output_path.with_suffix(".meta.json")

        metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "vdp": {
                "file": str(vdp.file_path.name),
                "produto": vdp.produto,
                "marca": vdp.marca,
                "conceito": vdp.conceito,
                "versao": vdp.versao,
                "png_referencia": vdp.png_referencia,
            },
            "generation": {
                "attempts": attempts,
                "elapsed_seconds": round(elapsed, 2),
                "prompt_length": len(prompt),
                "prompt_hash": hex(hash(prompt) & 0xFFFFFFFF),
            },
            "output": {
                "file": output_path.name,
                "format": "PNG",
            },
            "claims": [
                {"id": c.claim_id, "texto": c.texto} for c in vdp.claims
            ],
            "canva": {
                "template": vdp.canva.template,
                "headline": vdp.canva.headline,
                "spec_line": vdp.canva.spec_line,
                "logo": vdp.canva.logo,
                "anvisa": vdp.canva.anvisa_badge,
            },
        }

        meta_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("Metadados salvos: %s", meta_path.name)
        return meta_path

    def append_production_log(
        self,
        entry: dict,
    ) -> None:
        """
        Adiciona entrada ao log de produção (JSONL).

        Cada linha é um JSON com timestamp, ação e detalhes.
        """
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._logs_dir / "production-log.jsonl"

        entry["timestamp"] = datetime.now(timezone.utc).isoformat()

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_output_summary(self) -> dict:
        """Retorna sumário dos outputs gerados."""
        summary = {
            "nb2_images": 0,
            "compositions": 0,
            "total_size_mb": 0.0,
        }

        if self._nb2_dir.exists():
            pngs = list(self._nb2_dir.rglob("*.png"))
            summary["nb2_images"] = len(pngs)
            summary["total_size_mb"] = sum(p.stat().st_size for p in pngs) / (1024 * 1024)

        if self._comp_dir.exists():
            summary["compositions"] = len(list(self._comp_dir.rglob("*.png")))

        return summary
