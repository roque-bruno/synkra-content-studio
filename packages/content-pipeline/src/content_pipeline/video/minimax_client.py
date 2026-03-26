"""
Minimax (Hailuo) — API client para Image-to-Video.

Anima imagens estaticas em videos de 6 segundos.
Custo: ~$0.12/video de 6s em 720p.

Uso:
    client = MinimaxClient(api_key="...")
    result = await client.image_to_video(
        image_path="hero_lev.png",
        prompt="Camera slowly dolly forward, light beam activates",
    )
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COST_PER_VIDEO = 0.12  # USD ~6s 720p


@dataclass
class MinimaxResult:
    """Resultado de uma geracao de video via Minimax."""
    success: bool
    video_url: str = ""
    video_path: str = ""
    duration_seconds: float = 6
    cost_usd: float = 0
    elapsed_seconds: float = 0
    task_id: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "video_url": self.video_url,
            "video_path": self.video_path,
            "duration_seconds": self.duration_seconds,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "task_id": self.task_id,
            "error": self.error,
        }


class MinimaxClient:
    """Cliente para Minimax/Hailuo Video Generation API."""

    BASE_URL = "https://api.minimaxi.chat/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
        budget_tracker: Optional[object] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.output_dir = output_dir or Path("output/video")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.budget_tracker = budget_tracker

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def image_to_video(
        self,
        image_path: str,
        prompt: str = "Subtle camera movement, cinematic lighting",
        duration: int = 6,
    ) -> MinimaxResult:
        """Anima uma imagem estatica em video."""
        if not self.configured:
            return MinimaxResult(success=False, error="MINIMAX_API_KEY não configurada")

        start = time.time()

        try:
            # Read and encode image
            img_data = Path(image_path).read_bytes()
            img_b64 = base64.b64encode(img_data).decode()
            mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

            # Submit task
            task_id = await self._submit(img_b64, mime, prompt)

            # Poll for completion
            result_data = await self._poll(task_id, timeout=300)

            # Download video
            # file_id is an opaque ID, not a URL — always get download URL
            video_url = result_data.get("video_url", "")
            if not video_url:
                file_id = result_data.get("file_id", "")
                video_url = await self._get_download_url(file_id or task_id)

            video_path = await self._download(video_url, task_id)
            elapsed = time.time() - start

            if self.budget_tracker:
                try:
                    self.budget_tracker.add_cost("minimax_video", COST_PER_VIDEO)
                except Exception:
                    pass

            logger.info("Video gerado: %s (%.1fs, $%.2f)", video_path.name, elapsed, COST_PER_VIDEO)

            return MinimaxResult(
                success=True,
                video_url=video_url,
                video_path=str(video_path),
                duration_seconds=duration,
                cost_usd=COST_PER_VIDEO,
                elapsed_seconds=elapsed,
                task_id=task_id,
            )

        except Exception as e:
            logger.error("Erro ao gerar video Minimax: %s", e, exc_info=True)
            return MinimaxResult(
                success=False,
                error=str(e),
                elapsed_seconds=time.time() - start,
            )

    async def _submit(self, image_b64: str, mime: str, prompt: str) -> str:
        """Submete task de geracao de video."""
        payload = {
            "model": "video-01",
            "first_frame_image": f"data:{mime};base64,{image_b64}",
            "prompt": prompt,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.BASE_URL}/video_generation",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("task_id", "")
            logger.info("Minimax task submitted: %s", task_id)
            return task_id

    async def _poll(self, task_id: str, timeout: int = 300) -> dict:
        """Faz polling até o video estar pronto."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.time() + timeout

        while time.time() < deadline:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/query/video_generation",
                    params={"task_id": task_id},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "")

                if status == "Success":
                    return data
                if status in ("Fail", "Failed"):
                    raise RuntimeError(f"Minimax video failed: {data}")

            await asyncio.sleep(5)

        raise TimeoutError(f"Minimax video timeout after {timeout}s")

    async def _get_download_url(self, task_id: str) -> str:
        """Obtem URL de download do video gerado."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/files/retrieve",
                params={"task_id": task_id},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("file", {}).get("download_url", "")

    async def _download(self, url: str, task_id: str) -> Path:
        """Baixa video gerado."""
        filename = f"minimax_{task_id[:12]}.mp4"
        out_path = self.output_dir / filename

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        logger.info("Video salvo: %s", out_path)
        return out_path
