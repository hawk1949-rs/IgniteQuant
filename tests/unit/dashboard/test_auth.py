# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import dashboard.auth as auth_mod


@pytest.fixture()
def auth_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COCKPIT_USER", "admin")
    monkeypatch.setenv("COCKPIT_PASSWORD", "secret-pass")
    monkeypatch.setenv("COCKPIT_AUTH_SECRET", "unit-test-secret")
    monkeypatch.setenv("COCKPIT_TOKEN_TTL_HOURS", "24")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)
    auth_mod._warned_open = False
    auth_mod._enabled_cache = None
    monkeypatch.setattr(auth_mod, "count_active_users", lambda: 0)
    monkeypatch.setattr(auth_mod, "fetch_user", lambda _u: None)
    monkeypatch.setattr(auth_mod, "user_exists", lambda _u: False)
    yield


def test_password_hash_roundtrip():
    hashed = auth_mod.hash_password("123456")
    assert hashed.startswith("pbkdf2_sha256$")
    assert auth_mod.verify_password("123456", hashed)
    assert not auth_mod.verify_password("wrong", hashed)


def test_login_and_protected_route(auth_env):
    from dashboard.api import app

    client = TestClient(app)
    assert client.get("/api/auth/status").json()["auth_required"] is True
    assert client.get("/api/catalog").status_code == 401

    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"username": "admin", "password": "secret-pass"})
    assert ok.status_code == 200
    token = ok.json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    catalog = client.get("/api/catalog", headers={"Authorization": f"Bearer {token}"})
    assert catalog.status_code == 200


def test_login_from_table(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("COCKPIT_USER", raising=False)
    monkeypatch.delenv("COCKPIT_PASSWORD", raising=False)
    monkeypatch.setenv("COCKPIT_AUTH_SECRET", "unit-test-secret")
    auth_mod._warned_open = False
    auth_mod._enabled_cache = None

    hashed = auth_mod.hash_password("123456")
    user = auth_mod.CockpitUser(
        username="hawk1949", password_hash=hashed, is_active=True
    )

    monkeypatch.setattr(auth_mod, "count_active_users", lambda: 1)
    monkeypatch.setattr(
        auth_mod,
        "fetch_user",
        lambda u: user if u == "hawk1949" else None,
    )
    monkeypatch.setattr(
        auth_mod,
        "user_exists",
        lambda u: u == "hawk1949",
    )

    from dashboard.api import app

    client = TestClient(app)
    assert client.get("/api/auth/status").json()["auth_required"] is True
    ok = client.post(
        "/api/auth/login", json={"username": "hawk1949", "password": "123456"}
    )
    assert ok.status_code == 200
    assert ok.json()["username"] == "hawk1949"
    token = ok.json()["token"]
    assert (
        client.get("/api/catalog", headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )


def test_auth_disabled_without_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("COCKPIT_USER", raising=False)
    monkeypatch.delenv("COCKPIT_PASSWORD", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)
    auth_mod._warned_open = False
    auth_mod._enabled_cache = None
    monkeypatch.setattr(auth_mod, "count_active_users", lambda: 0)
    monkeypatch.setattr(auth_mod, "fetch_user", lambda _u: None)

    from dashboard.api import app

    client = TestClient(app)
    assert client.get("/api/auth/status").json()["auth_required"] is False
    assert client.get("/api/health").status_code == 200
