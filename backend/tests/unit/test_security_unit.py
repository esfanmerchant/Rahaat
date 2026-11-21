"""DB-free checks of tokens, hashing, encryption, mock formats and log redaction."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core import crypto, mockdata, security
from app.core.config import get_settings
from app.core.errors import Unauthorized, Unprocessable
from app.core.logging import redact


def _claims(**overrides: object) -> dict[str, object]:
    settings = get_settings()
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": settings.jwt_issuer, "aud": settings.jwt_audience, "sub": str(uuid.uuid4()), "sid": str(uuid.uuid4()),
        "tid": str(uuid.uuid4()), "role": "officer", "pid": None, "iat": now, "exp": now + 60, "jti": uuid.uuid4().hex,
    }  # fmt: skip
    claims.update(overrides)
    return claims


def _sign(claims: dict[str, object], *, key: str | None = None, alg: str = "HS256", kid: str | None = "k1") -> str:
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims, key or get_settings().secret_key, algorithm=alg, headers=headers)


def test_issued_token_round_trips() -> None:
    user, session, tenant = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token, ttl = security.issue_access_token(user_id=user, session_id=session, tenant_id=tenant, role="auditor", person_id=None)
    claims = security.decode_access_token(token)
    assert (claims.user_id, claims.session_id, claims.tenant_id, claims.role) == (user, session, tenant, "auditor")
    assert ttl == get_settings().access_ttl_seconds


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda: jwt.encode(_claims(), key=None, algorithm="none", headers={"kid": "k1"}),  # unsigned
        lambda: _sign(_claims(), key="another-secret-key-that-is-long-enough-000000"),  # wrong key
        lambda: _sign(_claims(), alg="HS512"),  # right key, algorithm not pinned
        lambda: _sign(_claims(), kid="unknown"),  # key id we do not hold
        lambda: _sign(_claims(), kid=None),  # no key id
        lambda: _sign(_claims(aud="someone-else")),
        lambda: _sign(_claims(iss="someone-else")),
        lambda: _sign(_claims(exp=int(time.time()) - 5)),
        lambda: _sign({k: v for k, v in _claims().items() if k != "sid"}),  # missing claim
        lambda: _sign(_claims(sub="not-a-uuid")),
        lambda: "not.a.token",
    ],
)
def test_bad_tokens_are_rejected(token_factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Unauthorized):
        security.decode_access_token(token_factory())


def test_changing_the_role_in_a_token_breaks_the_signature() -> None:
    header, payload, signature = _sign(_claims(role="citizen")).split(".")
    forged_payload = _sign(_claims(role="admin")).split(".")[1]
    with pytest.raises(Unauthorized):
        security.decode_access_token(f"{header}.{forged_payload}.{signature}")


def test_secret_hashing() -> None:
    hashed = security.hash_secret("Tested-Horse-Battery-9!")
    assert hashed.startswith("$argon2id$")
    assert security.verify_secret(hashed, "Tested-Horse-Battery-9!")
    assert not security.verify_secret(hashed, "wrong")
    assert not security.verify_secret(None, "anything"), "a missing account must never verify"


def test_password_and_pin_strength() -> None:
    security.check_password_strength("Tested-Horse-Battery-9!", email="officer@x.example")
    for weak in ("short", "password123", "officer-is-my-name-1"):
        with pytest.raises(Unprocessable):
            security.check_password_strength(weak, email="officer@x.example")
    security.check_pin_strength("4826")
    for weak in ("1234", "0000", "12", "abcd", "1234567"):
        with pytest.raises(Unprocessable):
            security.check_pin_strength(weak)


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    raw_a, hash_a = security.new_refresh_token()
    raw_b, _ = security.new_refresh_token()
    assert raw_a != raw_b and len(raw_a) >= 60
    assert hash_a == security.hash_token(raw_a) and raw_a not in hash_a


def test_field_encryption_round_trip_and_tenant_separation() -> None:
    dek_a, dek_b = crypto.new_wrapped_dek(), crypto.new_wrapped_dek()
    secret = mockdata.make_mock_id(1234567)
    sealed = crypto.encrypt_field(dek_a, secret)
    assert secret not in sealed
    assert crypto.decrypt_field(dek_a, sealed) == secret
    assert crypto.encrypt_field(dek_a, secret) != sealed, "a fresh nonce every time"
    with pytest.raises(Exception):  # noqa: B017  (another tenant's key must not open it)
        crypto.decrypt_field(dek_b, sealed)


def test_key_rotation_rewraps_the_tenant_key() -> None:
    settings = get_settings()
    old_master = settings.master_key_bytes()
    wrapped = crypto.new_wrapped_dek()
    sealed = crypto.encrypt_field(wrapped, "0999-1234567")
    assert crypto.decrypt_field(crypto.rewrap_dek(wrapped, old_master), sealed) == "0999-1234567"


def test_blind_index_is_deterministic_and_scoped() -> None:
    assert crypto.blind_index("0999-1234567") == crypto.blind_index(" 0999-1234567 ")
    assert crypto.blind_index("0999-1234567", scope="a") != crypto.blind_index("0999-1234567", scope="b")
    assert "0999" not in crypto.blind_index("0999-1234567")


@given(st.integers(min_value=0, max_value=9_999_999))
def test_mock_ids_always_validate_and_a_wrong_check_digit_never_does(serial: int) -> None:
    mock_id = mockdata.make_mock_id(serial)
    assert mock_id.startswith("00000-") and mockdata.mock_id_valid(mock_id)
    wrong = mock_id[:-1] + str((int(mock_id[-1]) + 1) % 10)
    assert mockdata.mock_id_shape_ok(wrong) and not mockdata.mock_id_valid(wrong)


def test_only_mock_shapes_are_accepted() -> None:
    assert mockdata.normalise_mock_phone("09991234567") == "0999-1234567"
    assert mockdata.normalise_mock_phone("0300-1234567") is None  # mock-lint: allow (a real-looking prefix must be refused)
    assert not mockdata.mock_id_shape_ok("42101-1234567-1")  # mock-lint: allow (a real-looking ID must be refused)
    assert mockdata.mask_identifier("00000-1234567-4").endswith("7-4") and "1234" not in mockdata.mask_identifier("00000-1234567-4")


def test_logs_are_redacted() -> None:
    line = redact("id 00000-1234567-4 phone 0999-1234567 mail officer@x.example Bearer abcdefghijklmnop\nforged line")
    assert "1234567" not in line and "officer@" not in line and "abcdefghijklmnop" not in line
    assert "\n" not in line, "newlines would let a caller forge log lines"


def test_prod_refuses_default_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        Settings(app_env="prod").check_secrets()
    with pytest.raises(RuntimeError):
        Settings(app_env="demo").check_secrets()
    Settings(app_env="dev").check_secrets()
    assert Settings(app_env="prod").demo_mode is False and Settings(app_env="demo").stubs_effective is False


def test_the_app_role_keeps_a_pooler_project_suffix() -> None:
    from app.core import config
    from app.core.config import Settings

    config._url_cache.clear()  # owner URLs are cached per process; each Settings below must compute its own
    pooled = Settings(app_env="dev", database_url_owner="postgresql://postgres.abcxyz:pw@pooler.example:5432/postgres", app_db_password="apw")
    assert pooled.app_url().username == "rahat_app.abcxyz" and pooled.app_url().password == "apw"
    config._url_cache.clear()
    plain = Settings(app_env="dev", database_url_owner="postgresql://owner:pw@db.example:5432/rahat", app_db_password="apw")
    assert plain.app_url().username == "rahat_app"
    config._url_cache.clear()
