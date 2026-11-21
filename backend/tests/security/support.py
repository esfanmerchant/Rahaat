"""Machinery for the security suite.

* `registry()`: every route and its policy, from `describe_routes`, so a new route is covered automatically.
* `World`: two departments, each with every role, a second officer and admin, a helper with a delegation, API keys,
  and one real object behind every id that appears in a path (case, application, document, consent, ...).
* `Bodies`: a valid minimal request body for any route, generated from the OpenAPI schema, so a refusal is
  never just a 422 for a missing field.
* `fingerprint()`: a hash of every row a department owns, to prove that a refused request wrote nothing.
"""

from __future__ import annotations

import io
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, text

from app.core import apikeys
from app.core.db import system_session
from app.core.policy import describe_routes
from app.core.security import decode_access_token, hash_secret
from app.db import models
from app.db.base import Base
from app.modules.cases import testing as case_data
from app.seed import RULES_V1

PARAM = re.compile(r"\{([a-z_]+)\}")
ROLES = ("citizen", "helper", "officer", "admin", "auditor")
FAMILY_PIN = "4826"  # the PIN every family in this suite gave its helper
TOKEN_REFRESH_SECONDS = 300  # access tokens live 10 minutes; sign in again well before that


@lru_cache(maxsize=1)
def registry() -> tuple[dict[str, Any], ...]:
    """The route registry at collection time. Building the app needs no database."""
    from app.main import create_app

    return tuple(describe_routes(create_app()))


def protected_routes() -> list[dict[str, Any]]:
    return [r for r in registry() if not r["public"]]


def route_id(route: dict[str, Any]) -> str:
    return f"{route['method']} {route['path']}"


def fill(path: str, values: dict[str, Any]) -> str:
    return PARAM.sub(lambda m: str(values.get(m.group(1), uuid.uuid4())), path)


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), (200, 180, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


# --- request bodies from the OpenAPI schema ---------------------------------------------------------------


class Bodies:
    """The smallest valid body for a route, so that what is tested is the policy and the lookup, not validation."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self._png = png_bytes()

    def _resolve(self, ref: str) -> dict[str, Any]:
        node: Any = self.spec
        for part in ref.removeprefix("#/").split("/"):
            node = node[part]
        return dict(node)

    def value(self, schema: dict[str, Any], depth: int = 0) -> Any:  # noqa: C901, PLR0911, PLR0912
        if depth > 12:
            return None
        if "$ref" in schema:
            return self.value(self._resolve(schema["$ref"]), depth + 1)
        if "const" in schema:
            return schema["const"]
        if "enum" in schema:
            return schema["enum"][0]
        for key in ("anyOf", "oneOf"):
            if key in schema:
                options = [s for s in schema[key] if s.get("type") != "null"]
                return self.value(options[0], depth + 1) if options else None
        if "allOf" in schema:
            merged: dict[str, Any] = {}
            for part in schema["allOf"]:
                merged.update(self._resolve(part["$ref"]) if "$ref" in part else part)
            return self.value(merged, depth + 1)
        kind = schema.get("type")
        if kind == "object" or "properties" in schema:
            props = schema.get("properties", {})
            return {name: self.value(props[name], depth + 1) for name in schema.get("required", [])}
        if kind == "array":
            return [self.value(schema.get("items", {}), depth + 1) for _ in range(schema.get("minItems", 0))]
        if kind == "string":
            fmt = schema.get("format")
            if fmt == "uuid":
                return str(uuid.uuid4())
            if fmt == "date":
                return "1990-01-01"
            if fmt == "date-time":
                return datetime.now(UTC).isoformat()
            if fmt == "email":
                return "probe@test.rahat.example"
            length = max(schema.get("minLength", 1), min(16, schema.get("maxLength", 16)))
            return ("security probe " * 20)[:length]
        if kind == "integer":
            low = schema.get("minimum", schema["exclusiveMinimum"] + 1 if "exclusiveMinimum" in schema else 1)
            return int(min(low, schema.get("maximum", low)))
        if kind == "number":
            low = schema.get("minimum", 0.5)
            return float(min(max(low, 0.5), schema.get("maximum", 1.0)))
        if kind == "boolean":
            return True
        return {} if kind is None else None

    def request_kwargs(self, method: str, path: str) -> dict[str, Any]:
        operation = self.spec["paths"].get(path, {}).get(method.lower(), {})
        content = operation.get("requestBody", {}).get("content", {})
        if "multipart/form-data" in content:
            schema = content["multipart/form-data"]["schema"]
            fields = self.value(schema)
            fields.pop("file", None)
            return {"files": {"file": ("probe.png", self._png, "image/png")}, "data": fields}
        if "application/json" in content:
            return {"json": self.value(content["application/json"]["schema"])}
        if method in ("POST", "PUT", "PATCH"):
            return {"json": {}}
        return {}


# --- two populated departments ------------------------------------------------------------------------------


@dataclass
class Side:
    label: str
    tenant_id: uuid.UUID
    accounts: dict[str, Any]
    ids: dict[str, uuid.UUID]  # path parameter name -> a real object of this department
    keys: dict[str, str]  # "payments" | "cases" -> the raw key
    key_scopes: dict[str, list[str]]
    tenant: Any = None  # the factory's tenant row, to add more accounts later
    tokens: dict[str, tuple[float, str]] = field(default_factory=dict)
    tickets: dict[str, str] = field(default_factory=dict)  # role -> switch ticket of the helper's current session

    @property
    def user_ids(self) -> list[uuid.UUID]:
        return [a.user_id for a in self.accounts.values()]

    @property
    def markers(self) -> set[str]:
        """Strings that must never appear in another department's responses."""
        found = {str(self.tenant_id), str(self.accounts["citizen"].person_id)}
        found |= {str(v) for v in self.ids.values()}
        found |= {str(u) for u in self.user_ids}
        return found


def _review_case(tenant_id: uuid.UUID, person_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """`case_data.review_case`, but on a rule version that passes the validator (the test helper's `all: []` does not).

    A published version cannot be edited, so the program is made here with the seed's rules, and the case on top of it.
    """
    with system_session() as db:
        program = models.Program(id=uuid.uuid4(), tenant_id=tenant_id, slug=f"p-{uuid.uuid4().hex[:8]}", name="Security suite program")
        db.add(program)
        db.flush()
        rule_set = models.RuleSet(id=uuid.uuid4(), tenant_id=tenant_id, program_id=program.id, name="Security suite rules")
        db.add(rule_set)
        db.flush()
        version = models.RuleVersion(id=uuid.uuid4(), tenant_id=tenant_id, rule_set_id=rule_set.id, version_no=1, status="published",
                                     dsl=RULES_V1)  # fmt: skip
        db.add(version)
        db.flush()
        rule_set.active_version_id = version.id
        program_id, version_id = program.id, version.id
    application_id = case_data.application(tenant_id, person_id, program_id)
    decision_id = case_data.decision(tenant_id, application_id, person_id, version_id)
    with system_session() as db:
        case = case_data.open_case(db, tenant_id=tenant_id, kind="application_review", opened_reason="income_unverified",
                                   application_id=application_id, person_id=person_id, decision_id=decision_id,
                                   handoff=case_data.handoff(), confidence=0.81, priority=40)  # fmt: skip
        case_id = case.id
    return {"case_id": case_id, "application_id": application_id, "decision_id": decision_id, "program_id": program_id,
            "rule_version_id": version_id}  # fmt: skip


def _build_side(client: TestClient, factory: Any, label: str) -> Side:
    tenant = factory.tenant(f"Security suite {label}")
    accounts = {role: factory.account(tenant, role) for role in ROLES}
    accounts["officer2"] = factory.account(tenant, "officer")
    accounts["admin2"] = factory.account(tenant, "admin")
    citizen = accounts["citizen"]
    now = datetime.now(UTC)
    review = _review_case(tenant.id, citizen.person_id)
    keys: dict[str, str] = {}
    key_scopes = {"payments": ["payments:read"], "cases": ["cases:read"]}
    key_ids: dict[str, uuid.UUID] = {}
    other = factory.account(tenant, "citizen")  # a second person: the other half of a duplicate pair
    with system_session() as db:
        delegation = models.HelperDelegation(id=uuid.uuid4(), tenant_id=tenant.id, helper_user_id=accounts["helper"].user_id,
                                             person_id=citizen.person_id, scopes=["track", "apply", "upload"],
                                             pin_hash=hash_secret(FAMILY_PIN), expires_at=now + timedelta(days=1))  # fmt: skip
        candidate = models.DuplicateCandidate(id=uuid.uuid4(), tenant_id=tenant.id, person_a_id=citizen.person_id, person_b_id=other.person_id,
                                              score=0.7, band="possible", evidence={}, status="open")  # fmt: skip
        run = models.TwinRun(id=uuid.uuid4(), tenant_id=tenant.id, draft_version_id=review["rule_version_id"], status="done", summary={})
        report = models.ScamReport(id=uuid.uuid4(), tenant_id=tenant.id, reporter_person_id=citizen.person_id, channel="text",
                                   text_redacted="[security probe]", text_hash="0" * 64, label="unknown", confidence=0.5, route="human",
                                   district="Lahore", classification={"source": "security"})  # fmt: skip
        warning = models.PublicWarning(id=uuid.uuid4(), tenant_id=tenant.id, title="Security probe", body_en="Probe.", district="Lahore",
                                       status="published", published_at=now)  # fmt: skip
        db.add_all([delegation, candidate, run, report, warning])
        document = models.Document(id=uuid.uuid4(), tenant_id=tenant.id, application_id=review["application_id"], person_id=citizen.person_id,
                                   kind="rahat_id", storage_key=f"security-{uuid.uuid4().hex}.png", sha256="0" * 64, mime="image/png",
                                   size_bytes=68)  # fmt: skip
        approval = models.Approval(id=uuid.uuid4(), tenant_id=tenant.id, kind="payment", subject_type="payment", subject_id=uuid.uuid4(),
                                   status="pending", requested_by=accounts["officer"].user_id)  # fmt: skip
        job = models.Job(id=uuid.uuid4(), tenant_id=tenant.id, kind="security.probe", status="dead", payload={})
        db.add_all([document, approval, job])
        for name, scopes in key_scopes.items():
            raw, prefix, digest = apikeys.generate()
            key = models.ApiKey(id=uuid.uuid4(), tenant_id=tenant.id, name=f"security {name}", prefix=prefix, key_hash=digest,
                                scopes=scopes, rate_limit_per_min=100_000, expires_at=now + timedelta(days=1))  # fmt: skip
            db.add(key)
            keys[name], key_ids[name] = raw, key.id
        db.flush()
        consent_id = db.scalar(select(models.Consent.id).where(models.Consent.person_id == citizen.person_id))
    session_id = decode_access_token(factory.login(client, citizen)["access_token"]).session_id
    ids = {
        "case_id": review["case_id"], "application_id": review["application_id"], "decision_id": review["decision_id"],
        "version_id": review["rule_version_id"], "document_id": document.id, "approval_id": approval.id, "job_id": job.id,
        "consent_id": consent_id, "session_id": session_id, "key_id": key_ids["payments"],
        "candidate_id": candidate.id, "run_id": run.id, "report_id": report.id, "warning_id": warning.id, "delegation_id": delegation.id,
    }  # fmt: skip
    return Side(label=label, tenant_id=tenant.id, accounts=accounts, ids=ids, keys=keys, key_scopes=key_scopes, tenant=tenant)


class World:
    def __init__(self, client: TestClient, factory: Any) -> None:
        self.client = client
        self.factory = factory
        self.a = _build_side(client, factory, "A")
        self.b = _build_side(client, factory, "B")
        self.bodies = Bodies(client.app.openapi())  # type: ignore[attr-defined]

    def headers(self, side: Side, who: str) -> dict[str, str]:
        """`who` is a role, `officer2`, `admin2`, `anonymous`, or `key:<name>`."""
        if who == "anonymous":
            return {}
        if who.startswith("key:"):
            return {"Authorization": f"Bearer {side.keys[who.removeprefix('key:')]}"}
        issued_at, token = side.tokens.get(who, (0.0, ""))
        if time.monotonic() - issued_at > TOKEN_REFRESH_SECONDS:
            token = self.factory.login(self.client, side.accounts[who])["access_token"]
            side.tokens[who] = (time.monotonic(), token)
            side.tickets.pop(who, None)  # a ticket belongs to one session
        headers = {"Authorization": f"Bearer {token}"}
        if who == "helper":
            if who not in side.tickets:
                side.tickets[who] = self.switch(side, headers, side.accounts["citizen"].person_id)
            headers["X-Acting-For"] = str(side.accounts["citizen"].person_id)
            headers["X-Helper-Ticket"] = side.tickets[who]
        return headers

    def switch(self, side: Side, headers: dict[str, str], person_id: uuid.UUID, pin: str = FAMILY_PIN) -> str:
        """The helper enters the family's PIN and gets the ticket that every request for that person must carry."""
        response = self.client.post("/v1/helper/switch", json={"person_id": str(person_id), "pin": pin}, headers=headers)
        assert response.status_code == 200, f"helper switch failed: {response.text}"
        return str(response.json()["ticket"])

    def warm(self) -> None:
        """Sign everyone in now, so no sign-in happens between two fingerprints."""
        for side in (self.a, self.b):
            for who in side.accounts:
                self.headers(side, who)

    def call(self, method: str, path: str, *, side: Side, who: str, template: str | None = None) -> Any:
        kwargs = self.bodies.request_kwargs(method, template or path)
        return self.client.request(method, path, headers=self.headers(side, who), **kwargs)


def admitted_caller(route: dict[str, Any]) -> str:
    """A caller of the route's own department that the policy lets in (person routes: the citizen)."""
    for who in ("citizen", "officer", "admin", "auditor", "helper"):
        if who in route["roles"]:
            return who
    raise AssertionError(f"no role admits {route_id(route)}")


def key_without_scope(side: Side, route: dict[str, Any]) -> str | None:
    for name, scopes in side.key_scopes.items():
        if not set(scopes) & set(route["api_scopes"]):
            return f"key:{name}"
    return None


def leaked(text_body: str, markers: set[str]) -> list[str]:
    return sorted(m for m in markers if m in text_body)


# --- write detection ------------------------------------------------------------------------------------------


def _tenant_tables() -> list[str]:
    # audit_log is checked row by row instead; sessions are matched by user below.
    return sorted(t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c and t.name not in ("audit_log", "sessions"))


def _digest(table: str, where: str) -> str:
    return (f"SELECT '{table}' AS tbl, count(*) AS n, "
            f"coalesce(md5(string_agg(md5(x::text), ',' ORDER BY md5(x::text))), '') AS h FROM {table} x WHERE {where}")  # fmt: skip


def fingerprint(*sides: Side) -> dict[str, tuple[int, str]]:
    """Row count and content hash of every table, limited to the given departments and their users."""
    parts = [_digest(name, "x.tenant_id = ANY(:tenants)") for name in _tenant_tables()]
    parts += [_digest("users", "x.id = ANY(:users)"), _digest("sessions", "x.user_id = ANY(:users)"),
              _digest("tenants", "x.id = ANY(:tenants)")]  # fmt: skip
    params = {"tenants": [s.tenant_id for s in sides], "users": [u for s in sides for u in s.user_ids]}
    with system_session() as db:
        rows = db.execute(text(" UNION ALL ".join(parts)), params).all()
    found = {row.tbl: (int(row.n), str(row.h)) for row in rows}
    assert len(found) == len(parts), "every table is fingerprinted once"
    return found


def audit_heads(*sides: Side) -> dict[uuid.UUID, int]:
    with system_session() as db:
        rows = db.execute(text("SELECT tenant_id, max(seq) AS seq FROM audit_log WHERE tenant_id = ANY(:t) GROUP BY tenant_id"),
                          {"t": [s.tenant_id for s in sides]}).all()  # fmt: skip
    heads = {s.tenant_id: 0 for s in sides}
    heads.update({row.tenant_id: int(row.seq) for row in rows})
    return heads


def audit_since(heads: dict[uuid.UUID, int]) -> list[Any]:
    found: list[Any] = []
    with system_session() as db:
        for tenant_id, seq in heads.items():
            found += db.execute(text("SELECT action, actor_type, reason FROM audit_log WHERE tenant_id = :t AND seq > :s ORDER BY seq"),
                                {"t": tenant_id, "s": seq}).all()  # fmt: skip
    return found
