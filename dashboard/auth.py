# -*- coding: utf-8 -*-
"""座舱登录：RDS cockpit_users 表 + HMAC 会话 Token。

优先从 public.cockpit_users 校验账号（密码为 PBKDF2 哈希）。
可选环境变量 COCKPIT_USER / COCKPIT_PASSWORD 作为本机兜底单账号。

环境变量：
  DATABASE_URL / RDS_DATABASE_URL — 读用户表
  COCKPIT_AUTH_SECRET             — Token 签名密钥（生产建议显式设置）
  COCKPIT_TOKEN_TTL_HOURS         — 默认 168（7 天）
  COCKPIT_USER / COCKPIT_PASSWORD — 可选兜底账号（无库或表为空时）
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_PREFIXES = (
    "/api/auth/login",
    "/api/auth/status",
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
)

_warned_open = False
_PBKDF2_ITERS = 120_000
_enabled_cache: tuple[float, bool] | None = None
_ENABLED_CACHE_TTL = 30.0
_dotenv_loaded = False


def _ensure_dotenv() -> None:
    """Load project `.env` into os.environ.

    Most keys use setdefault (shell wins). Cockpit login keys always take
    values from `.env` when present, so local fallback matches the file.
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    path = _ROOT / ".env"
    if path.is_file():
        try:
            force_keys = {
                "COCKPIT_USER",
                "COCKPIT_PASSWORD",
                "COCKPIT_AUTH_SECRET",
                "COCKPIT_TOKEN_TTL_HOURS",
            }
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key in force_keys:
                    os.environ[key] = value
                else:
                    os.environ.setdefault(key, value)
        except OSError as exc:
            logger.warning("读取 .env 失败: %s", exc)
    _dotenv_loaded = True


@dataclass(frozen=True)
class AuthConfig:
    secret: bytes
    ttl_seconds: int
    env_username: str
    env_password: str
    enabled: bool


@dataclass(frozen=True)
class CockpitUser:
    username: str
    password_hash: str
    is_active: bool


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _database_url() -> str:
    _ensure_dotenv()
    return (
        os.environ.get("RDS_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )


def _connect_pg():
    url = _database_url()
    if not url:
        return None
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 未安装，无法读取 cockpit_users")
        return None
    try:
        # Keep auth snappy when RDS is unreachable from home network.
        return psycopg2.connect(url, connect_timeout=2)
    except Exception as exc:
        logger.warning("连接数据库失败，无法读取 cockpit_users: %s", exc)
        return None


def count_active_users() -> int:
    conn = _connect_pg()
    if conn is None:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM public.cockpit_users WHERE is_active = TRUE"
            )
            row = cur.fetchone()
            return int(row[0] if row else 0)
    except Exception as exc:
        logger.warning("查询 cockpit_users 失败: %s", exc)
        return 0
    finally:
        conn.close()


def fetch_user(username: str) -> CockpitUser | None:
    uname = username.strip()
    if not uname:
        return None
    conn = _connect_pg()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT username, password_hash, is_active
                FROM public.cockpit_users
                WHERE username = %s
                LIMIT 1
                """,
                (uname,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return CockpitUser(
                username=str(row[0]),
                password_hash=str(row[1]),
                is_active=bool(row[2]),
            )
    except Exception as exc:
        logger.warning("读取 cockpit_users 失败: %s", exc)
        return None
    finally:
        conn.close()


def user_exists(username: str) -> bool:
    user = fetch_user(username)
    return bool(user and user.is_active)


def _auth_enabled_now(env_user: str, env_password: str) -> bool:
    global _enabled_cache
    now = time.time()
    # Local fallback alone is enough to enable auth; don't block on RDS.
    if env_user and env_password:
        _enabled_cache = (now, True)
        return True
    if _enabled_cache and now - _enabled_cache[0] < _ENABLED_CACHE_TTL:
        return _enabled_cache[1]
    db_users = count_active_users()
    enabled = db_users > 0
    _enabled_cache = (now, enabled)
    return enabled


def load_auth_config() -> AuthConfig:
    _ensure_dotenv()
    env_user = (os.getenv("COCKPIT_USER") or "").strip()
    env_password = os.getenv("COCKPIT_PASSWORD") or ""
    ttl_hours = float(os.getenv("COCKPIT_TOKEN_TTL_HOURS") or "168")
    ttl_seconds = max(3600, int(ttl_hours * 3600))
    enabled = _auth_enabled_now(env_user, env_password)

    secret_raw = (os.getenv("COCKPIT_AUTH_SECRET") or "").strip()
    if secret_raw:
        secret = secret_raw.encode("utf-8")
    else:
        material = (
            f"ignitequant-cockpit|{env_user}|{env_password}|{_database_url()[:48]}"
        ).encode("utf-8")
        secret = hashlib.sha256(material).digest()

    return AuthConfig(
        secret=secret,
        ttl_seconds=ttl_seconds,
        env_username=env_user,
        env_password=env_password,
        enabled=enabled,
    )


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    import base64

    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(cfg: AuthConfig, username: str) -> tuple[str, int]:
    exp = int(time.time()) + cfg.ttl_seconds
    body = f"{username}.{exp}".encode("utf-8")
    sig = hmac.new(cfg.secret, body, hashlib.sha256).digest()
    token = f"{_b64url(body)}.{_b64url(sig)}"
    return token, exp


def verify_token(cfg: AuthConfig, token: str) -> str | None:
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        expected = hmac.new(cfg.secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        username, exp_s = body.decode("utf-8").split(".", 1)
        if int(exp_s) < int(time.time()):
            return None
        # Prefer local env account (no RDS round-trip) when username matches.
        if cfg.env_username and hmac.compare_digest(username, cfg.env_username):
            return username
        if user_exists(username):
            return username
        return None
    except Exception:
        return None


def authenticate(cfg: AuthConfig, username: str, password: str) -> tuple[str, int]:
    if not cfg.enabled:
        raise HTTPException(
            status_code=503,
            detail="未配置座舱账号（请写入 cockpit_users 或 COCKPIT_USER/PASSWORD）",
        )
    uname = username.strip()

    # Local .env fallback first — avoids waiting on unreachable RDS.
    if cfg.env_username and cfg.env_password:
        user_ok = hmac.compare_digest(uname, cfg.env_username)
        pass_ok = hmac.compare_digest(password, cfg.env_password)
        if user_ok and pass_ok:
            return issue_token(cfg, cfg.env_username)

    user = fetch_user(uname)
    if user is not None:
        if not user.is_active or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return issue_token(cfg, user.username)

    raise HTTPException(status_code=401, detail="用户名或密码错误")


def extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get("iq_session") or None


class CockpitAuthMiddleware(BaseHTTPMiddleware):
    """保护 /api/*；静态页与公开端点放行。"""

    def __init__(self, app, config_loader: Callable[[], AuthConfig] = load_auth_config):
        super().__init__(app)
        self._config_loader = config_loader

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if request.method == "OPTIONS":
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)
        if any(path == p or path.startswith(p + "/") for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        cfg = self._config_loader()
        if not cfg.enabled:
            global _warned_open
            if not _warned_open:
                logger.warning(
                    "座舱鉴权未启用：无 cockpit_users 且未配置 COCKPIT_USER/PASSWORD"
                )
                _warned_open = True
            return await call_next(request)

        token = extract_bearer(request)
        if not token or verify_token(cfg, token) is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "未登录或会话已过期"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)
