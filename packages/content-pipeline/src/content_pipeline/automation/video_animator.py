"""
Video Animator — Facade que escolhe o melhor client disponível.

Prioridade: Minimax → Kling → Veo3
Escolhe automaticamente baseado em qual API key está configurada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AnimationResult:
    """Resultado unificado de animação."""
    success: bool
    video_url: str = ""
    video_path: str = ""
    duration_seconds: float = 0
    cost_usd: float = 0
    elapsed_seconds: float = 0
    engine: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "video_url": self.video_url,
            "video_path": self.video_path,
            "duration_seconds": self.duration_seconds,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "engine": self.engine,
            "error": self.error,
        }


class VideoAnimator:
    """Facade: escolhe o melhor engine disponível para animar imagem."""

    def __init__(
        self,
        minimax_client=None,
        kling_client=None,
        veo3_client=None,
    ) -> None:
        self.minimax = minimax_client
        self.kling = kling_client
        self.veo3 = veo3_client

    @property
    def configured(self) -> bool:
        return any([
            self.minimax and self.minimax.configured,
            self.kling and self.kling.configured,
            self.veo3 and self.veo3.configured,
        ])

    def available_engines(self) -> list[str]:
        engines = []
        if self.minimax and self.minimax.configured:
            engines.append("minimax")
        if self.kling and self.kling.configured:
            engines.append("kling")
        if self.veo3 and self.veo3.configured:
            engines.append("veo3")
        return engines

    async def animate(
        self,
        image_path: str,
        prompt: str = "Subtle camera movement, cinematic lighting",
        duration: int = 6,
        engine: str = "auto",
    ) -> AnimationResult:
        """Anima imagem usando o melhor engine disponível."""
        if engine == "auto":
            engine = self._pick_engine()

        if not engine:
            return AnimationResult(
                success=False,
                error="Nenhum engine de vídeo configurado (Minimax, Kling ou Veo3)",
            )

        logger.info("Animando imagem com engine: %s", engine)

        if engine == "minimax" and self.minimax:
            result = await self.minimax.image_to_video(
                image_path=image_path, prompt=prompt, duration=duration,
            )
            return AnimationResult(
                success=result.success,
                video_url=result.video_url,
                video_path=result.video_path,
                duration_seconds=result.duration_seconds,
                cost_usd=result.cost_usd,
                elapsed_seconds=result.elapsed_seconds,
                engine="minimax",
                error=result.error,
            )

        if engine == "kling" and self.kling:
            result = await self.kling.image_to_video(
                image_path=image_path, prompt=prompt, duration=duration,
            )
            return AnimationResult(
                success=result.success,
                video_url=result.video_url,
                video_path=result.video_path,
                duration_seconds=result.duration_seconds,
                cost_usd=result.cost_usd,
                elapsed_seconds=result.elapsed_seconds,
                engine="kling",
                error=result.error,
            )

        if engine == "veo3" and self.veo3:
            result = await self.veo3.text_to_video(prompt=prompt)
            return AnimationResult(
                success=result.success,
                video_url=getattr(result, "video_url", ""),
                video_path=getattr(result, "video_path", ""),
                duration_seconds=getattr(result, "duration_seconds", 0),
                cost_usd=getattr(result, "cost_usd", 0),
                elapsed_seconds=getattr(result, "elapsed_seconds", 0),
                engine="veo3",
                error=getattr(result, "error", ""),
            )

        return AnimationResult(success=False, error=f"Engine {engine} não disponível")

    def _pick_engine(self) -> str:
        if self.minimax and self.minimax.configured:
            return "minimax"
        if self.kling and self.kling.configured:
            return "kling"
        if self.veo3 and self.veo3.configured:
            return "veo3"
        return ""
