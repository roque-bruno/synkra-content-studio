"""
ElevenLabs TTS — Narracao com vozes dinamicas, multilingual_v2.

Model: eleven_multilingual_v2
Default voice: Bill (pqHfZKP75CvOlQylNhV4) — pode ser alterado via seletor na UI.

Uso:
    tts = ElevenLabsTTS(api_key="...")
    voices = await tts.get_voices()  # Lista todas as vozes disponiveis
    result = await tts.generate("Texto", voice_id=voices[0]["voice_id"])
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "pqHfZKP75CvOlQylNhV4"  # Bill
DEFAULT_MODEL = "eleven_multilingual_v2"


@dataclass
class TTSResult:
    """Resultado de geracao TTS."""
    success: bool
    audio_path: str = ""
    duration_seconds: float = 0
    char_count: int = 0
    cost_usd: float = 0
    elapsed_seconds: float = 0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "audio_path": self.audio_path,
            "duration_seconds": round(self.duration_seconds, 1),
            "char_count": self.char_count,
            "cost_usd": round(self.cost_usd, 4),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "error": self.error,
        }


class ElevenLabsTTS:
    """Cliente para ElevenLabs Text-to-Speech API."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: str = DEFAULT_VOICE_ID,
        model_id: str = DEFAULT_MODEL,
        output_dir: Optional[Path] = None,
        budget_tracker: Optional[object] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_dir = output_dir or Path("output/audio")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.budget_tracker = budget_tracker

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        text: str,
        output_path: Optional[str | Path] = None,
        voice_id: Optional[str] = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
    ) -> TTSResult:
        """
        Gera audio a partir de texto.

        Args:
            text: Texto para narrar
            output_path: Caminho de saida (auto se None)
            voice_id: Override de voz
            stability: Estabilidade (0-1, maior = mais estavel)
            similarity_boost: Similaridade com a voz original (0-1)
            style: Expressividade (0-1)

        Returns:
            TTSResult com audio_path
        """
        if not self.configured:
            return TTSResult(
                success=False,
                error="ElevenLabs API nao configurado — ELEVENLABS_API_KEY ausente",
                char_count=len(text),
            )

        if not text.strip():
            return TTSResult(success=False, error="Texto vazio")

        vid = voice_id or self.voice_id
        if output_path is None:
            output_path = self.output_dir / f"tts_{int(time.time())}.mp3"
        output_path = Path(output_path)

        start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.BASE_URL}/text-to-speech/{vid}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json={
                        "text": text,
                        "model_id": self.model_id,
                        "voice_settings": {
                            "stability": stability,
                            "similarity_boost": similarity_boost,
                            "style": style,
                        },
                    },
                )
                response.raise_for_status()
                audio_bytes = response.content

            output_path.write_bytes(audio_bytes)
            elapsed = time.monotonic() - start

            # Estimar duracao (~150 palavras/minuto, ~5 chars/palavra)
            word_count = len(text.split())
            estimated_duration = word_count / 150 * 60  # segundos

            # Custo: ~$0.30 por 1000 chars (Starter plan)
            cost = len(text) / 1000 * 0.30

            if self.budget_tracker and hasattr(self.budget_tracker, "record"):
                self.budget_tracker.record("tts_elevenlabs", cost, {
                    "char_count": len(text),
                    "voice_id": vid,
                    "duration_est": round(estimated_duration, 1),
                })

            return TTSResult(
                success=True,
                audio_path=str(output_path),
                duration_seconds=estimated_duration,
                char_count=len(text),
                cost_usd=cost,
                elapsed_seconds=elapsed,
            )

        except httpx.HTTPStatusError as e:
            logger.error("ElevenLabs TTS failed: %s %s", e.response.status_code, e.response.text[:200])
            return TTSResult(
                success=False,
                char_count=len(text),
                elapsed_seconds=time.monotonic() - start,
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except Exception as e:
            return TTSResult(
                success=False,
                char_count=len(text),
                elapsed_seconds=time.monotonic() - start,
                error=str(e),
            )

    async def get_voices(self) -> list[dict]:
        """Lista vozes disponiveis."""
        if not self.configured:
            return [{"voice_id": DEFAULT_VOICE_ID, "name": "Bill (default)", "preview": True}]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"{self.BASE_URL}/voices",
                    headers={"xi-api-key": self.api_key},
                )
                response.raise_for_status()
                data = response.json()
                return [
                    {"voice_id": v["voice_id"], "name": v["name"]}
                    for v in data.get("voices", [])
                ]
        except Exception as e:
            logger.warning("Failed to list voices: %s", e)
            return [{"voice_id": DEFAULT_VOICE_ID, "name": "Bill (default)"}]
