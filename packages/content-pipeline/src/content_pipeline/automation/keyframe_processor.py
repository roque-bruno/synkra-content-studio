"""
Keyframe Processor — Extrai frames de vídeo, aplica variações via IA, remonta.

Pipeline: video → FFmpeg extract → fal.ai variations → FFmpeg reassemble
Uso para A/B testing: criar múltiplas versões de um vídeo vencedor.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class KeyframeProcessor:
    """Extrai keyframes, aplica variações via IA, remonta vídeo."""

    def __init__(
        self,
        image_generator=None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.image_generator = image_generator
        self.output_dir = output_dir or Path("output/keyframes")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    async def extract_keyframes(
        self,
        video_path: str,
        fps: float = 2,
        max_frames: int = 30,
    ) -> list[Path]:
        """Extrai keyframes do video."""
        video = Path(video_path)
        if not video.exists():
            raise FileNotFoundError(f"Video não encontrado: {video_path}")

        frames_dir = self.output_dir / f"frames_{video.stem}"
        frames_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y", "-i", str(video),
            "-vf", f"fps={fps}",
            "-frames:v", str(max_frames),
            str(frames_dir / "frame_%04d.png"),
        ]

        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg extraction failed: {proc.stderr[:300]}")

        frames = sorted(frames_dir.glob("frame_*.png"))
        logger.info("Extraídos %d keyframes de %s", len(frames), video.name)
        return frames

    async def process_keyframes(
        self,
        keyframes: list[Path],
        variation_prompt: str,
        negative_prompt: str = "",
    ) -> list[Path]:
        """Aplica variação visual em cada keyframe via fal.ai."""
        if not self.image_generator or not self.image_generator.configured:
            raise RuntimeError("Image generator não configurado")

        processed = []
        for i, frame in enumerate(keyframes):
            try:
                result = await self.image_generator.generate_image(
                    prompt=variation_prompt,
                    negative_prompt=negative_prompt,
                    width=1920, height=1080,
                    model="flux-dev",
                )
                if result.success and result.image_path:
                    processed.append(Path(result.image_path))
                else:
                    processed.append(frame)  # fallback to original
                    logger.warning("Frame %d falhou, usando original", i)
            except Exception as e:
                logger.error("Erro processando frame %d: %s", i, e)
                processed.append(frame)

        return processed

    async def reassemble_video(
        self,
        frames: list[Path],
        output_name: str,
        fps: float = 2,
        audio_source: Optional[str] = None,
    ) -> Path:
        """Remonta frames em vídeo."""
        # Create temp dir with sequential numbered frames
        temp_dir = self.output_dir / f"reassemble_{output_name}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        for i, frame in enumerate(frames):
            dest = temp_dir / f"frame_{i:04d}.png"
            shutil.copy2(frame, dest)

        output_path = self.output_dir / f"{output_name}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(temp_dir / "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        ]

        if audio_source:
            cmd.extend(["-i", audio_source, "-c:a", "aac", "-shortest"])

        cmd.append(str(output_path))

        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg reassembly failed: {proc.stderr[:300]}")

        # Cleanup temp
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info("Video remontado: %s", output_path.name)
        return output_path

    async def create_variation(
        self,
        video_path: str,
        variation_prompt: str,
        negative_prompt: str = "",
        fps: float = 2,
        output_name: str = "variation",
    ) -> dict:
        """Pipeline completo: extract → process → reassemble."""
        frames = await self.extract_keyframes(video_path, fps=fps)
        processed = await self.process_keyframes(frames, variation_prompt, negative_prompt)
        output = await self.reassemble_video(processed, output_name, fps=fps, audio_source=video_path)
        return {
            "success": True,
            "output_path": str(output),
            "frames_processed": len(processed),
            "variation_prompt": variation_prompt,
        }
