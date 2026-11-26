"""Sesión propia del panel admin de support.

El handoff de osap-api entrega un *service token* de vida corta (5 min). Guardarlo tal
cual en la cookie hacía que el panel caducase a los pocos minutos —a veces segundos,
porque el proveedor M2M reutiliza tokens cacheados casi expirados— y las peticiones
posteriores devolvían 401/403.

La cookie de navegación NO debe ser una credencial M2M: aquí se emite un JWT HS256
propio, con vigencia independiente (8 h por defecto), tras validar el service token en
el handoff. La clave se toma de `server.admin_session_secret` o se genera y persiste en
`var/admin_session.key` (0600), de modo que varios workers/reinicios compartan sesión.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path

import jwt

from infrastructure.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

SESSION_USE = "support_admin_session"
SESSION_SCOPE = "support:admin"
SESSION_SUBJECT = "support-admin-web"
_KEY_FILE = PROJECT_ROOT / "var" / "admin_session.key"
_MIN_SECRET_LENGTH = 32

_signer: AdminSessionSigner | None = None


class AdminSessionSigner:
    """Emite y valida la cookie de sesión del panel admin de support."""

    def __init__(self, secret: str, ttl_seconds: int) -> None:
        self._secret = secret
        self._ttl_seconds = max(60, int(ttl_seconds))

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @classmethod
    def from_settings(cls, settings) -> AdminSessionSigner | None:
        server = getattr(settings, "server", None)
        configured = str(getattr(server, "admin_session_secret", "") or "").strip()
        ttl = int(getattr(server, "admin_session_ttl_seconds", 28800) or 28800)
        secret = configured or _load_or_create_key(_KEY_FILE)
        if not secret:
            logger.warning(
                "sin clave de sesión admin (server.admin_session_secret / var/%s); "
                "se mantiene la cookie de service token de vida corta",
                _KEY_FILE.name,
            )
            return None
        return cls(secret, ttl)

    def issue(self, *, client_id: str = "") -> tuple[str, int]:
        now = int(time.time())
        claims = {
            "sub": SESSION_SUBJECT,
            "scope": SESSION_SCOPE,
            "token_use": SESSION_USE,
            "iat": now,
            "exp": now + self._ttl_seconds,
            "jti": secrets.token_urlsafe(16),
        }
        if client_id:
            claims["client_id"] = client_id
        token = jwt.encode(claims, self._secret, algorithm="HS256")
        return token, self._ttl_seconds

    def validate(self, token: str) -> dict | None:
        """Devuelve los claims si es una sesión admin válida; `None` en caso contrario."""
        if not token:
            return None
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                options={"require": ["exp", "iat", "sub", "scope"]},
            )
        except jwt.PyJWTError:
            return None
        if claims.get("token_use") != SESSION_USE:
            return None
        if SESSION_SCOPE not in str(claims.get("scope") or "").split():
            return None
        return claims

    def is_session_token(self, token: str) -> bool:
        """True si el token *parece* una sesión admin (aunque esté caducada)."""
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError:
            return False
        return claims.get("token_use") == SESSION_USE


def configure(settings) -> AdminSessionSigner | None:
    """Configura el firmante global del proceso (idempotente)."""
    return set_signer(AdminSessionSigner.from_settings(settings))


def set_signer(signer: AdminSessionSigner | None) -> AdminSessionSigner | None:
    """Fija el firmante global (los tests pueden limpiarlo con `None`)."""
    global _signer
    _signer = signer
    return _signer


def current() -> AdminSessionSigner | None:
    return _signer


def is_admin_session(token: str) -> bool:
    return _signer is not None and _signer.validate(token) is not None


def _load_or_create_key(path: Path) -> str:
    """Lee la clave persistida o crea una nueva de forma atómica con permisos 0600."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_text(encoding="ascii").strip()
            if len(existing) >= _MIN_SECRET_LENGTH:
                return existing
            logger.warning("clave de sesión admin demasiado corta en %s; se regenera", path)
            key = secrets.token_urlsafe(48)
            path.write_text(key, encoding="ascii")
            try:
                path.chmod(0o600)
            except OSError:
                pass
            return key
        key = secrets.token_urlsafe(48)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # Otro worker acaba de crearla: esperar a que termine de escribirla.
            for _ in range(50):
                existing = path.read_text(encoding="ascii").strip()
                if len(existing) >= _MIN_SECRET_LENGTH:
                    return existing
                time.sleep(0.02)
            return ""
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(key)
        return key
    except OSError as exc:
        logger.warning("no se pudo leer/crear %s: %s", path, exc)
        return ""
