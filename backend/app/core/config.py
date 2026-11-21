"""Runtime settings. Values come from the environment or a `.env` file in the repo root."""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from typing import Literal

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
    max_body_bytes: int = 6_000_000
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    login_ip_attempts_per_minute: int = 30

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
        return self.owner_url().set(username=APP_DB_ROLE, password=self.app_db_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
    _url_cache.clear()
