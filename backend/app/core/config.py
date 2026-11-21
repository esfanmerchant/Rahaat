"""Runtime settings. Values come from the environment or a `.env` file in the repo root."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

PROTOTYPE_LABEL = "Prototype. Not an official service. All identity, payment and data services are simulated."
# Keep identical to PROTOTYPE_LABEL_UR in frontend/src/shared/components/PrototypeFooter.tsx.
PROTOTYPE_LABEL_UR = "یہ آزمائشی نمونہ ہے، سرکاری سروس نہیں۔ شناخت، ادائیگی اور ڈیٹا کی سب سروسز فرضی ہیں۔"

DEV_SECRET_KEY = "dev-only-secret-key-not-for-demo-or-prod-0000000000"
DEV_MASTER_KEY = base64.b64encode(b"dev-only-master-key-000000000000").decode()
DEV_APP_DB_PASSWORD = "rahat_app_dev_password"
APP_DB_ROLE = "rahat_app"

Env = Literal["dev", "test", "demo", "prod"]

_url_cache: dict[str, URL] = {}


@dataclass(frozen=True, slots=True)
class RateLimits:
    """Requests per minute for each token bucket. A bucket holds one minute's worth, so short bursts pass."""

    enabled: bool
    anonymous_per_minute: int  # per client network, for calls without a valid credential
    user_per_minute: int  # per signed-in user in a department
    tenant_per_minute: int  # everything a department does together (users and API keys)
    api_key_default_per_minute: int  # used when an admin creates a key without naming a limit


# Deployed defaults. Tests use very high values unless a test sets its own, so the suite never trips them.
_RATE_DEFAULTS = {"anonymous": 300, "user": 600, "tenant": 6000}
_RATE_TEST_DEFAULT = 1_000_000


def _normalise(url: str) -> URL:
    """Accept postgres:// and postgresql:// and always use the psycopg 3 driver."""
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed


class Settings(BaseSettings):
    # Empty values (as in a copied .env.example) are ignored, so the safe defaults below still apply.
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    app_env: Env = "dev"
    app_version: str = "0.1.0"
    port: int = 8000

    database_url_owner: str | None = None
    database_url: str | None = None
    app_db_password: str = DEV_APP_DB_PASSWORD
    # Runtime connections. A hosted pooler in session mode (Supabase) caps clients at its pool size,
    # so keep pool + overflow + the owner engine's 3 under that cap.
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=50)

    secret_key: str = DEV_SECRET_KEY
    jwt_active_kid: str = "k1"
    jwt_extra_keys: str = ""  # "kid=secret,kid=secret": older keys still accepted while rotating
    jwt_issuer: str = "rahat"
    jwt_audience: str = "rahat-api"
    access_ttl_seconds: int = 600
    refresh_ttl_seconds: int = 7 * 24 * 3600
    master_key: str = DEV_MASTER_KEY
    cookie_secure: bool | None = None

    frontend_dist: str = "../frontend/dist"
    upload_dir: str = "var/uploads"
    mock_base_url: str = "http://127.0.0.1:9001"
    ai_profile: Literal["full", "lite"] = "lite"
    feature_flags: str = ""
    stubs_enabled: bool | None = None
    worker_enabled: bool | None = None  # background job loop; on by default except in tests
    # Serverless hosting (Vercel). Every default below keeps the always-on server's behaviour.
    jobs_mode: Literal["thread", "inline"] = "thread"  # inline: no worker thread; due jobs run inside the request that queued them
    jobs_inline_budget_seconds: float = Field(default=5.0, gt=0, le=30)
    jobs_inline_max_jobs: int = Field(default=25, ge=1, le=200)
    cron_secret: str | None = None  # the bearer Vercel Cron sends to the drain endpoint; unset means that endpoint is off
    mocks_in_process: bool = False  # call the mock services inside this process instead of over HTTP at MOCK_BASE_URL
    client_ip_header: str | None = None  # a header the platform sets and a client cannot forge, e.g. x-vercel-forwarded-for
    startup_warmup: bool = True  # false: skip the background model, OCR and corpus warm-ups at start (cold-start friendly)
    max_body_bytes: int = 6_000_000
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    login_ip_attempts_per_minute: int = 30
    rate_limit_enabled: bool = True
    rate_limit_anonymous_per_minute: int | None = None
    rate_limit_user_per_minute: int | None = None
    rate_limit_tenant_per_minute: int | None = None
    api_key_default_per_minute: int = 60

    def rate_limits(self) -> RateLimits:
        def pick(value: int | None, name: str) -> int:
            if value is not None:
                return max(1, value)
            return _RATE_TEST_DEFAULT if self.app_env == "test" else _RATE_DEFAULTS[name]

        return RateLimits(
            enabled=self.rate_limit_enabled,
            anonymous_per_minute=pick(self.rate_limit_anonymous_per_minute, "anonymous"),
            user_per_minute=pick(self.rate_limit_user_per_minute, "user"),
            tenant_per_minute=pick(self.rate_limit_tenant_per_minute, "tenant"),
            api_key_default_per_minute=max(1, self.api_key_default_per_minute),
        )

    @property
    def demo_mode(self) -> bool:
        """Demo accounts page, Challenge Lab and mock controls are available outside prod."""
        return self.app_env != "prod"

    @property
    def defaults_allowed(self) -> bool:
        return self.app_env in ("dev", "test")

    @property
    def cookie_secure_effective(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env in ("demo", "prod")

    @property
    def stubs_effective(self) -> bool:
        """Contract stubs never run on a deployed instance: a feature is real or it is absent."""
        if self.stubs_enabled is not None:
            return self.stubs_enabled and self.defaults_allowed
        return self.defaults_allowed

    @property
    def worker_enabled_effective(self) -> bool:
        if self.worker_enabled is not None:
            return self.worker_enabled
        return self.app_env != "test"

    @property
    def job_thread_enabled(self) -> bool:
        """The long-lived worker thread: never in inline mode, where requests drain the queue themselves."""
        return self.jobs_mode == "thread" and self.worker_enabled_effective

    @property
    def jobs_inline(self) -> bool:
        return self.jobs_mode == "inline"

    def jwt_keys(self) -> dict[str, str]:
        keys = {self.jwt_active_kid: self.secret_key}
        for pair in filter(None, (p.strip() for p in self.jwt_extra_keys.split(","))):
            kid, _, secret = pair.partition("=")
            if kid and secret:
                keys.setdefault(kid, secret)
        return keys

    def master_key_bytes(self) -> bytes:
        raw = base64.b64decode(self.master_key)
        if len(raw) != 32:
            raise RuntimeError("MASTER_KEY must be the base64 encoding of exactly 32 bytes")
        return raw

    def features(self) -> dict[str, bool]:
        return {name.strip(): True for name in self.feature_flags.split(",") if name.strip()}

    def check_secrets(self) -> None:
        """Refuse to run a deployed instance on the built-in development secrets."""
        self.master_key_bytes()
        if self.defaults_allowed:
            return
        problems = []
        if self.secret_key == DEV_SECRET_KEY or len(self.secret_key) < 32:
            problems.append("SECRET_KEY")
        if self.master_key == DEV_MASTER_KEY:
            problems.append("MASTER_KEY")
        if self.app_db_password == DEV_APP_DB_PASSWORD and not self.database_url:
            problems.append("APP_DB_PASSWORD")
        # The demo keeps the public development issuer key so the committed specimen cards verify. Prod must not.
        if self.app_env == "prod" and not os.environ.get("MOCK_ISSUER_SEED"):
            problems.append("MOCK_ISSUER_SEED")
        if problems:
            raise RuntimeError(
                f"APP_ENV={self.app_env} refuses to start with default or weak secrets: {', '.join(problems)}"
            )

    def owner_url(self) -> URL:
        """Connection used for migrations only. It owns the tables, so it is never used at runtime."""
        if "owner" not in _url_cache:
            if self.database_url_owner:
                _url_cache["owner"] = _normalise(self.database_url_owner)
            elif self.defaults_allowed:
                from app import devdb

                _url_cache["owner"] = _normalise(devdb.database_uri("rahat_dev"))
            else:
                raise RuntimeError("DATABASE_URL_OWNER is required when APP_ENV is demo or prod")
        return _url_cache["owner"]

    def app_url(self) -> URL:
        """Runtime connection: the low-privilege role that Row Level Security applies to."""
        if self.database_url:
            return _normalise(self.database_url)
        owner = self.owner_url()
        # Poolers such as Supabase's name a user "<role>.<project-ref>"; the app role keeps the project part.
        user = owner.username or ""
        suffix = user[user.index("."):] if "." in user else ""
        return owner.set(username=APP_DB_ROLE + suffix, password=self.app_db_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
    _url_cache.clear()
