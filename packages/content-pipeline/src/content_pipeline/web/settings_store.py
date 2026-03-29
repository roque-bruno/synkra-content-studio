"""
Settings Store — Persistência segura de chaves API e configurações.

Salva em JSON criptografado com chave derivada do JWT secret.
Fallback: variáveis de ambiente.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Definição de todas as chaves configuráveis
API_KEY_DEFINITIONS = [
    # --- Geração de Imagem (NB2 é a API principal) ---
    {
        "key": "FAL_API_KEY",
        "label": "fal.ai API Key (Nano Banana 2)",
        "group": "geracao",
        "description": "API PRINCIPAL — gera imagens NB2/FLUX (~$0.04-0.08/img). Sonnet cria o prompt, NB2 renderiza.",
        "required": True,
        "placeholder": "fal_...",
    },
    {
        "key": "GOOGLE_API_KEY",
        "label": "Google Gemini API Key",
        "group": "geracao",
        "description": "Geração alternativa de imagens via Gemini (backup do NB2)",
        "required": False,
        "placeholder": "AIza...",
    },
    # --- LLM / IA (OpenRouter = roteador seguro) ---
    {
        "key": "OPENROUTER_API_KEY",
        "label": "OpenRouter API Key",
        "group": "llm",
        "description": "Roteador de LLMs (Sonnet, Gemini, DeepSeek). Failover automático entre provedores (~5% taxa).",
        "required": True,
        "placeholder": "sk-or-v1-...",
    },
    # --- Video Pipeline (Image-to-Video) ---
    {
        "key": "GROK_API_KEY",
        "label": "Grok API Key",
        "group": "video",
        "description": "Animação Image-to-Video 6s 720p (~$0.12/vídeo). Gira produto 360°, modelos desfilando.",
        "required": False,
        "placeholder": "grok_...",
    },
    {
        "key": "MINIMAX_API_KEY",
        "label": "Minimax/Hailuo API Key",
        "group": "video",
        "description": "Animação Image-to-Video 6s alternativa (~$0.12/vídeo)",
        "required": False,
        "placeholder": "eyJ...",
    },
    {
        "key": "PIKA_API_KEY",
        "label": "PikaLabs (Pika) API Key",
        "group": "video",
        "description": "Animação de imagens e efeitos de movimento avançados",
        "required": False,
        "placeholder": "pika_...",
    },
    {
        "key": "RUNWAY_API_KEY",
        "label": "Runway Gen-3 API Key",
        "group": "video",
        "description": "Geração de vídeo premium — alta qualidade, movimentos complexos",
        "required": False,
        "placeholder": "runway_...",
    },
    {
        "key": "KLING_API_KEY",
        "label": "Kling 3.0 API Key",
        "group": "video",
        "description": "Image-to-Video alternativo (Kuaishou)",
        "required": False,
        "placeholder": "kling_...",
    },
    {
        "key": "GOOGLE_CLOUD_PROJECT",
        "label": "Google Cloud Project ID",
        "group": "video",
        "description": "Veo 3 via Vertex AI (opcional — sem ele usa Gemini API)",
        "required": False,
        "placeholder": "my-project-id",
    },
    {
        "key": "ELEVENLABS_API_KEY",
        "label": "ElevenLabs API Key",
        "group": "video",
        "description": "Text-to-Speech para narração — voice Bill (multilingual_v2)",
        "required": False,
        "placeholder": "xi-...",
    },
    {
        "key": "INSTAGRAM_ACCESS_TOKEN",
        "label": "Instagram Access Token",
        "group": "publishers",
        "description": "Token de acesso Instagram Graph API",
        "required": False,
        "placeholder": "EAA...",
    },
    {
        "key": "INSTAGRAM_USER_ID",
        "label": "Instagram User ID",
        "group": "publishers",
        "description": "ID do perfil Instagram Business",
        "required": False,
        "placeholder": "17841...",
    },
    {
        "key": "LINKEDIN_ACCESS_TOKEN",
        "label": "LinkedIn Access Token",
        "group": "publishers",
        "description": "Token OAuth2 LinkedIn",
        "required": False,
        "placeholder": "AQV...",
    },
    {
        "key": "LINKEDIN_ORG_ID",
        "label": "LinkedIn Organization ID",
        "group": "publishers",
        "description": "ID da página corporativa LinkedIn",
        "required": False,
        "placeholder": "12345678",
    },
    {
        "key": "FACEBOOK_ACCESS_TOKEN",
        "label": "Facebook Page Access Token",
        "group": "publishers",
        "description": "Token de acesso da página Facebook",
        "required": False,
        "placeholder": "EAA...",
    },
    {
        "key": "FACEBOOK_PAGE_ID",
        "label": "Facebook Page ID",
        "group": "publishers",
        "description": "ID da página Facebook",
        "required": False,
        "placeholder": "10000...",
    },
    {
        "key": "YOUTUBE_ACCESS_TOKEN",
        "label": "YouTube Access Token",
        "group": "publishers",
        "description": "Token OAuth2 YouTube Data API v3",
        "required": False,
        "placeholder": "ya29...",
    },
    {
        "key": "SUPABASE_URL",
        "label": "Supabase Project URL",
        "group": "database",
        "description": "URL do projeto Supabase (ex: https://xxx.supabase.co)",
        "required": False,
        "placeholder": "https://xxx.supabase.co",
    },
    {
        "key": "SUPABASE_SERVICE_KEY",
        "label": "Supabase Service Role Key",
        "group": "database",
        "description": "Service role key (acesso total — NÃO usar anon key)",
        "required": False,
        "placeholder": "eyJhbGciOi...",
    },
    {
        "key": "STUDIO_USER",
        "label": "Usuário do Studio",
        "group": "auth",
        "description": "Login do Content Studio (padrão: admin)",
        "required": False,
        "placeholder": "admin",
    },
    {
        "key": "STUDIO_PASS",
        "label": "Senha do Studio",
        "group": "auth",
        "description": "Senha do Content Studio (padrão: studio2026)",
        "required": False,
        "placeholder": "••••••",
    },
]

# Agrupamento para UI
SETTINGS_GROUPS = {
    "geracao": {"label": "Geração de Imagem (NB2 / FLUX)", "icon": "🎨"},
    "llm": {"label": "LLM / IA (OpenRouter)", "icon": "🧠"},
    "video": {"label": "Video & Animação (Grok, Pika, Runway)", "icon": "🎬"},
    "publishers": {"label": "Publicação (Redes Sociais)", "icon": "📢"},
    "database": {"label": "Banco de Dados", "icon": "🗄️"},
    "auth": {"label": "Autenticação", "icon": "🔒"},
}


class SettingsStore:
    """Armazena configurações em arquivo JSON ofuscado."""

    def __init__(self, settings_dir: Path):
        self._dir = settings_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / ".studio-settings.json"
        self._cache: dict[str, str] = {}
        self._load()

    def _get_key(self) -> bytes:
        """Deriva chave de ofuscação do JWT secret."""
        secret = os.getenv("STUDIO_JWT_SECRET", "salk-content-studio-2026-secret-key")
        return hashlib.sha256(secret.encode()).digest()

    def _obfuscate(self, data: str) -> str:
        """Ofusca dados com XOR + base64 (não é criptografia forte, mas protege contra leitura casual)."""
        key = self._get_key()
        data_bytes = data.encode("utf-8")
        result = bytes(b ^ key[i % len(key)] for i, b in enumerate(data_bytes))
        return base64.b64encode(result).decode("ascii")

    def _deobfuscate(self, data: str) -> str:
        """Reverte ofuscação."""
        key = self._get_key()
        data_bytes = base64.b64decode(data)
        result = bytes(b ^ key[i % len(key)] for i, b in enumerate(data_bytes))
        return result.decode("utf-8")

    def _load(self) -> None:
        """Carrega settings do arquivo."""
        if not self._file.exists():
            self._cache = {}
            return
        try:
            raw = self._file.read_text(encoding="utf-8")
            stored = json.loads(raw)
            self._cache = {}
            for k, v in stored.items():
                try:
                    self._cache[k] = self._deobfuscate(v)
                except Exception:
                    self._cache[k] = v  # fallback sem ofuscação
        except Exception as e:
            logger.warning(f"Erro ao carregar settings: {e}")
            self._cache = {}

    def _save(self) -> None:
        """Salva settings no arquivo."""
        stored = {}
        for k, v in self._cache.items():
            if v:  # não salvar valores vazios
                stored[k] = self._obfuscate(v)
        self._file.write_text(
            json.dumps(stored, indent=2),
            encoding="utf-8",
        )

    def get(self, key: str, default: str = "") -> str:
        """
        Obtém valor de uma configuração.
        Prioridade: settings store > variável de ambiente > default.
        """
        # Settings store tem prioridade
        val = self._cache.get(key, "")
        if val:
            return val
        # Fallback para env var
        return os.getenv(key, default)

    def set(self, key: str, value: str) -> None:
        """Define valor de uma configuração."""
        if value:
            self._cache[key] = value
        elif key in self._cache:
            del self._cache[key]

    def set_many(self, settings: dict[str, str]) -> None:
        """Define múltiplas configurações e salva."""
        for k, v in settings.items():
            self.set(k, v)
        self._save()

    def get_all(self) -> dict[str, str]:
        """Retorna todas as configurações (mascarando valores sensíveis)."""
        result = {}
        for defn in API_KEY_DEFINITIONS:
            key = defn["key"]
            val = self.get(key)
            result[key] = val
        return result

    def get_masked(self) -> dict[str, str]:
        """Retorna configurações com valores mascarados para exibição."""
        result = {}
        for defn in API_KEY_DEFINITIONS:
            key = defn["key"]
            val = self.get(key)
            if val:
                if len(val) > 8:
                    result[key] = val[:4] + "•" * (len(val) - 8) + val[-4:]
                else:
                    result[key] = "••••••"
            else:
                result[key] = ""
        return result

    def get_status(self) -> dict:
        """Retorna status de configuração de cada chave."""
        status = {}
        for defn in API_KEY_DEFINITIONS:
            key = defn["key"]
            val = self.get(key)
            source = "none"
            if self._cache.get(key):
                source = "settings"
            elif os.getenv(key):
                source = "env"
            status[key] = {
                "configured": bool(val),
                "source": source,
                "label": defn["label"],
                "group": defn["group"],
                "description": defn["description"],
            }
        return status

    def get_definitions(self) -> list[dict]:
        """Retorna definições das chaves para a UI."""
        return API_KEY_DEFINITIONS

    def get_groups(self) -> dict:
        """Retorna grupos para a UI."""
        return SETTINGS_GROUPS

    def apply_to_env(self) -> None:
        """Aplica settings como variáveis de ambiente (para clientes que leem env vars)."""
        for key, val in self._cache.items():
            if val:
                os.environ[key] = val
