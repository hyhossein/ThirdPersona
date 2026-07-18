"""
Auth tests: token verification and JIT provisioning.

The security-relevant claims, each tested:
  1. A validly signed, unexpired token from our issuer is accepted.
  2. An expired token is rejected.
  3. A token signed by a DIFFERENT key (forgery) is rejected.
  4. A token from the wrong issuer is rejected.
  5. First authenticated request JIT-creates the user; second reuses it.
  6. jwt mode cannot be spoofed by the old X-User-ID header.
  7. Boot guard refuses dev-mode auth in production.
"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

import app.auth as auth
from app.auth import verify_jwt, resolve_user, assert_auth_config
from app.config import settings


# ---- test keys / tokens ------------------------------------------------

def _make_keypair(kid: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = pyjwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    return key, jwk


KEY, JWK = _make_keypair("test-key-1")
FORGER_KEY, _ = _make_keypair("test-key-1")  # same kid, different key = forgery
ISSUER = "https://test-issuer.example"


def mint(key=KEY, kid="test-key-1", exp_delta=3600, issuer=ISSUER, sub=None, **extra):
    payload = {
        "sub": sub or f"user_{uuid.uuid4().hex[:12]}",
        "iss": issuer,
        "exp": int(time.time()) + exp_delta,
        **extra,
    }
    return payload["sub"], pyjwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def _jwt_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "jwt")
    monkeypatch.setattr(settings, "jwt_jwks_url", "https://test-issuer.example/jwks.json")
    monkeypatch.setattr(settings, "jwt_issuer", ISSUER)
    monkeypatch.setattr(auth, "_fetch_jwks", lambda url: {"keys": [JWK]})
    auth.clear_jwks_cache()
    yield
    auth.clear_jwks_cache()


# ---- verification ------------------------------------------------------

def test_valid_token_accepted():
    sub, token = mint(email="h@example.com")
    claims = verify_jwt(token)
    assert claims["sub"] == sub
    assert claims["email"] == "h@example.com"


def test_expired_token_rejected():
    _, token = mint(exp_delta=-60)
    with pytest.raises(HTTPException) as e:
        verify_jwt(token)
    assert e.value.status_code == 401
    assert "expired" in e.value.detail.lower()


def test_forged_signature_rejected():
    _, token = mint(key=FORGER_KEY)  # right kid, wrong private key
    with pytest.raises(HTTPException) as e:
        verify_jwt(token)
    assert e.value.status_code == 401


def test_wrong_issuer_rejected():
    _, token = mint(issuer="https://evil.example")
    with pytest.raises(HTTPException) as e:
        verify_jwt(token)
    assert e.value.status_code == 401


def test_alg_none_rejected():
    # Classic downgrade attack: unsigned token claiming alg=none.
    payload = {"sub": "x", "iss": ISSUER, "exp": int(time.time()) + 600}
    token = pyjwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(HTTPException):
        verify_jwt(token)


# ---- JIT provisioning --------------------------------------------------

@pytest.mark.asyncio
async def test_jit_creates_then_reuses_user(conn):
    sub = f"clerk_{uuid.uuid4().hex[:10]}"
    claims = {"sub": sub, "email": f"{sub}@example.com", "name": "Hossein"}
    uid1 = await resolve_user(conn, claims)
    uid2 = await resolve_user(conn, claims)
    assert uid1 == uid2
    row = await conn.fetchrow("SELECT external_id, display_name FROM users WHERE id = $1", uid1)
    assert row["external_id"] == sub
    assert row["display_name"] == "Hossein"


@pytest.mark.asyncio
async def test_jit_without_email_uses_placeholder(conn):
    sub = f"clerk_{uuid.uuid4().hex[:10]}"
    uid = await resolve_user(conn, {"sub": sub})
    row = await conn.fetchrow("SELECT email FROM users WHERE id = $1", uid)
    assert row["email"].endswith("@jit.thirdpersona.invalid")


# ---- spoofing / config guards -----------------------------------------

@pytest.mark.asyncio
async def test_jwt_mode_ignores_x_user_id_header():
    """The old header must be dead in jwt mode — no token, no identity."""
    class FakeRequest:
        headers = {"X-User-ID": str(uuid.uuid4())}
    with pytest.raises(HTTPException) as e:
        await auth.get_current_user_id(FakeRequest())
    assert e.value.status_code == 401
    assert "Bearer" in e.value.detail


def test_boot_guard_refuses_dev_auth_in_production(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "thirdpersona_env", "production")
    with pytest.raises(RuntimeError, match="Refusing to start"):
        assert_auth_config()


def test_boot_guard_refuses_halfconfigured_jwt(monkeypatch):
    monkeypatch.setattr(settings, "jwt_jwks_url", "")
    with pytest.raises(RuntimeError, match="JWT_JWKS_URL"):
        assert_auth_config()
