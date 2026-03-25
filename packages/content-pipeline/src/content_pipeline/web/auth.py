"""
Auth — Autenticacao simples JWT para Content Studio.

Credenciais via variaveis de ambiente:
  STUDIO_USER (default: admin)
  STUDIO_PASS (default: studio2026)
  STUDIO_JWT_SECRET (default: auto-generated)
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# JWT minimo sem dependencia externa (HMAC-SHA256 com base64)
import base64
import hmac
import json

_JWT_SECRET = os.getenv("STUDIO_JWT_SECRET", "salk-content-studio-secret-2026")
_STUDIO_USER = os.getenv("STUDIO_USER", "admin")
_STUDIO_PASS = os.getenv("STUDIO_PASS", "studio2026")
_TOKEN_EXPIRY = 86400  # 24 horas


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_in: int


# ------------------------------------------------------------------
# JWT simples (sem dependencia python-jose)
# ------------------------------------------------------------------

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(username: str) -> str:
    """Cria JWT token HMAC-SHA256."""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64encode(json.dumps({
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + _TOKEN_EXPIRY,
    }).encode())
    signature_input = f"{header}.{payload}".encode()
    signature = _b64encode(
        hmac.new(_JWT_SECRET.encode(), signature_input, hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> Optional[dict]:
    """Verifica JWT token. Retorna payload ou None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, signature = parts

        # Verificar assinatura
        signature_input = f"{header}.{payload}".encode()
        expected = _b64encode(
            hmac.new(_JWT_SECRET.encode(), signature_input, hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None

        # Decodificar payload
        data = json.loads(_b64decode(payload))

        # Verificar expiracao
        if data.get("exp", 0) < time.time():
            return None

        return data
    except Exception:
        return None


def authenticate(username: str, password: str) -> Optional[str]:
    """Valida credenciais e retorna token JWT ou None."""
    if username == _STUDIO_USER and password == _STUDIO_PASS:
        return create_token(username)
    return None


# ------------------------------------------------------------------
# FastAPI Security
# ------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)

# Rotas que NAO precisam de autenticacao
PUBLIC_PATHS = {
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/health",
    "/api/auth/login",
}


async def require_auth(request: Request) -> dict:
    """Middleware-like dependency para proteger rotas."""
    path = request.url.path

    # Rotas publicas
    if path in PUBLIC_PATHS:
        return {"sub": "anonymous"}

    # Assets estaticos
    if path.startswith(("/assets/", "/output/")):
        return {"sub": "anonymous"}

    # Extrair token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Token ausente. Faca login em /api/auth/login")

    token = auth_header[7:]
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(401, "Token invalido ou expirado")

    return payload
