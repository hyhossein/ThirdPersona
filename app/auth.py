"""
Authentication: Bearer JWT (RS256 via JWKS) with JIT user provisioning.

Two modes, chosen by settings.auth_mode:

  "jwt" (production): every request carries `Authorization: Bearer <token>`.
    The token is verified against the identity provider's JWKS (Clerk, or
    any OIDC provider) — signature, expiry, issuer. The `sub` claim maps to
    users.external_id; unknown subjects are JIT-provisioned. The X-User-ID
    header is IGNORED in this mode — identity comes only from cryptography.

  "dev" (local development ONLY): the old X-User-ID header. Kept because
    the vertical slice needs a frictionless local loop, but it is
    identification, not authentication — anyone naming a UUID becomes that
    user. The app refuses to run in dev mode when THIRDPERSONA_ENV=production.

Clerk hookup = three env vars, no code changes:
  AUTH_MODE=jwt
  JWT_JWKS_URL=https://<your-clerk-domain>/.well-known/jwks.json
  JWT_ISSUER=https://<your-clerk-domain>
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid

import asyncpg
import jwt as pyjwt
from fastapi import HTTPException, Request

from app.config import settings

# ---------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
JWKS_TTL_SECONDS = 3600


def _fetch_jwks(url: str) -> dict:
    """Fetch the JWKS document. Isolated for test monkeypatching."""
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read())


def _get_jwks() -> dict:
    now = time.time()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > JWKS_TTL_SECONDS:
        _jwks_cache["keys"] = _fetch_jwks(settings.jwt_jwks_url)
        _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


def clear_jwks_cache() -> None:
    _jwks_cache["keys"] = None
    _jwks_cache["fetched_at"] = 0.0


# ---------------------------------------------------------------
# Token verification (pure: token -> claims, or HTTPException)
# ---------------------------------------------------------------
def verify_jwt(token: str) -> dict:
    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Malformed token")

    jwks = _get_jwks()
    kid = header.get("kid")
    jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if jwk is None:
        # Key rotation: refetch once before failing.
        clear_jwks_cache()
        jwks = _get_jwks()
        jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if jwk is None:
        raise HTTPException(status_code=401, detail="Unknown signing key")

    try:
        public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        claims = pyjwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],  # never trust the token's own alg claim
            issuer=settings.jwt_issuer or None,
            options={"verify_aud": False, "require": ["exp", "sub"]},
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Wrong issuer")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return claims


# ---------------------------------------------------------------
# JIT provisioning (claims -> internal user uuid)
# ---------------------------------------------------------------
async def resolve_user(conn: asyncpg.Connection, claims: dict) -> uuid.UUID:
    """Map a verified token subject to an internal user, creating on first sight."""
    sub = claims["sub"]
    row = await conn.fetchrow("SELECT id FROM users WHERE external_id = $1", sub)
    if row:
        return row["id"]

    email = claims.get("email") or f"{sub}@jit.thirdpersona.invalid"
    name = claims.get("name") or claims.get("given_name") or "New user"
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, display_name, external_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (email) DO UPDATE SET external_id = COALESCE(users.external_id, EXCLUDED.external_id)
            RETURNING id
            """,
            email,
            name,
            sub,
        )
        return row["id"]
    except asyncpg.UniqueViolationError:
        # Raced with another request for the same new subject.
        row = await conn.fetchrow("SELECT id FROM users WHERE external_id = $1", sub)
        if row:
            return row["id"]
        raise HTTPException(status_code=500, detail="User provisioning failed")


# ---------------------------------------------------------------
# The FastAPI dependency
# ---------------------------------------------------------------
async def get_current_user_id(request: Request) -> uuid.UUID:
    if settings.auth_mode == "dev":
        x = request.headers.get("X-User-ID")
        if not x:
            raise HTTPException(status_code=401, detail="X-User-ID required (dev mode)")
        try:
            return uuid.UUID(x)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-User-ID must be a valid UUID")

    authz = request.headers.get("Authorization", "")
    if not authz.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    claims = verify_jwt(authz[7:])

    from app.database import get_pool  # late import: avoid cycle

    pool = get_pool()
    async with pool.acquire() as conn:
        return await resolve_user(conn, claims)


def assert_auth_config() -> None:
    """Boot-time guard: refuse misconfigured auth, loudly."""
    if settings.auth_mode == "jwt":
        if not settings.jwt_jwks_url:
            raise RuntimeError("AUTH_MODE=jwt requires JWT_JWKS_URL")
    elif settings.auth_mode == "dev":
        if settings.thirdpersona_env == "production":
            raise RuntimeError(
                "AUTH_MODE=dev in production: X-User-ID is identification, "
                "not authentication. Refusing to start."
            )
    else:
        raise RuntimeError(f"Unknown AUTH_MODE '{settings.auth_mode}'")
