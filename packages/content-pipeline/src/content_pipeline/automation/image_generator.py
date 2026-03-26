"""
fal.ai Image Generator — FLUX/NB2 image generation via fal.ai API.

Pipeline: NB2 prompt (Apex) → fal.ai FLUX → imagem PNG
Custo: ~$0.08/imagem (FLUX dev), ~$0.12/imagem (FLUX pro)

Uso:
    gen = FalImageGenerator(api_key="fal_...")
    result = await gen.generate_image(
        prompt="Dramatic surgical room, overhead light beam...",
        width=1080, height=1350,
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COST_PER_IMAGE_DEV = 0.04
COST_PER_IMAGE_PRO = 0.08

DIMENSION_PRESETS = {
    "feed": (1080, 1350),       # 4:5 Instagram feed
    "square": (1080, 1080),     # 1:1
    "stories": (1080, 1920),    # 9:16 Stories/Reels
    "landscape": (1920, 1080),  # 16:9 YouTube
    "banner": (2560, 720),      # Wide banner
}


@dataclass
class ImageResult:
    """Resultado de uma geracao de imagem."""
    success: bool
    image_url: str = ""
    image_path: str = ""
    width: int = 0
    height: int = 0
    cost_usd: float = 0
    elapsed_seconds: float = 0
    request_id: str = ""
    seed: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "image_url": self.image_url,
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "request_id": self.request_id,
            "seed": self.seed,
            "error": self.error,
        }


class FalImageGenerator:
    """Cliente para geração de imagens via fal.ai (FLUX)."""

    QUEUE_URL = "https://queue.fal.run"

    MODELS = {
        "flux-dev": "fal-ai/flux/dev",
        "flux-pro": "fal-ai/flux-pro/v1.1",
        "flux-schnell": "fal-ai/flux/schnell",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: Optional[Path] = None,
        budget_tracker: Optional[object] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("FAL_API_KEY", "")
        self.output_dir = output_dir or Path("output/generated")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.budget_tracker = budget_tracker

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_dimensions(self, format_preset: str = "", width: int = 0, height: int = 0) -> tuple[int, int]:
        if format_preset and format_preset in DIMENSION_PRESETS:
            return DIMENSION_PRESETS[format_preset]
        return (width or 1080, height or 1350)

    async def generate_image(
        self,
        prompt: str,
        width: int = 1080,
        height: int = 1350,
        negative_prompt: str = "",
        model: str = "flux-dev",
        format_preset: str = "",
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        seed: Optional[int] = None,
    ) -> ImageResult:
        """Gera imagem usando fal.ai FLUX."""
        if not self.configured:
            return ImageResult(success=False, error="FAL_API_KEY não configurada")

        start = time.time()
        w, h = self._get_dimensions(format_preset, width, height)
        model_id = self.MODELS.get(model, model)

        try:
            # Submit request to queue
            request_id = await self._submit(model_id, prompt, w, h, negative_prompt,
                                            num_inference_steps, guidance_scale, seed)

            # Poll for result
            result_data = await self._poll(model_id, request_id, timeout=180)

            # Download image
            images = result_data.get("images", [])
            if not images:
                return ImageResult(success=False, error="Nenhuma imagem retornada", request_id=request_id)

            image_info = images[0]
            image_url = image_info.get("url", "")
            image_path = await self._download(image_url, request_id)

            cost = COST_PER_IMAGE_PRO if "pro" in model else COST_PER_IMAGE_DEV
            elapsed = time.time() - start

            if self.budget_tracker:
                try:
                    self.budget_tracker.add_cost("fal_image", cost)
                except Exception:
                    pass

            logger.info("Imagem gerada: %s (%.1fs, $%.4f)", image_path.name, elapsed, cost)

            return ImageResult(
                success=True,
                image_url=image_url,
                image_path=str(image_path),
                width=image_info.get("width", w),
                height=image_info.get("height", h),
                cost_usd=cost,
                elapsed_seconds=elapsed,
                request_id=request_id,
                seed=result_data.get("seed", 0),
            )

        except Exception as e:
            logger.error("Erro ao gerar imagem: %s", e, exc_info=True)
            return ImageResult(
                success=False,
                error=str(e),
                elapsed_seconds=time.time() - start,
            )

    async def _submit(self, model_id, prompt, width, height, negative_prompt,
                      steps, guidance, seed) -> str:
        """Submete request para a fila do fal.ai."""
        payload = {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "num_images": 1,
            "enable_safety_checker": False,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if seed is not None:
            payload["seed"] = seed

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.QUEUE_URL}/{model_id}",
                headers={
                    "Authorization": f"Key {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            request_id = data.get("request_id", "")
            logger.info("fal.ai request submitted: %s", request_id)
            return request_id

    async def _poll(self, model_id: str, request_id: str, timeout: int = 180) -> dict:
        """Faz polling até o resultado estar pronto."""
        status_url = f"{self.QUEUE_URL}/{model_id}/requests/{request_id}/status"
        result_url = f"{self.QUEUE_URL}/{model_id}/requests/{request_id}"
        headers = {"Authorization": f"Key {self.api_key}"}

        deadline = time.time() + timeout
        while time.time() < deadline:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(status_url, headers=headers)
                resp.raise_for_status()
                status = resp.json()

                if status.get("status") == "COMPLETED":
                    # Fetch full result
                    result_resp = await client.get(result_url, headers=headers)
                    result_resp.raise_for_status()
                    return result_resp.json()

                if status.get("status") in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"fal.ai request failed: {status}")

            await asyncio.sleep(2)

        raise TimeoutError(f"fal.ai request timeout after {timeout}s")

    async def _download(self, url: str, request_id: str) -> Path:
        """Baixa imagem gerada."""
        ext = "png"
        if ".jpg" in url or ".jpeg" in url:
            ext = "jpg"
        elif ".webp" in url:
            ext = "webp"

        filename = f"{request_id[:12]}.{ext}"
        out_path = self.output_dir / filename

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        logger.info("Imagem salva: %s", out_path)
        return out_path
