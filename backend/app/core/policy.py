"""Central access policy. Every route declares exactly one `Policy` or `Public` marker.

    @router.get("/cases")
    def list_cases(principal: Principal = Depends(Policy("cases:read", roles=["officer"]))): ...

`describe_routes()` lists the whole endpoint-to-role registry, and a test fails the build when any route
has no marker. A role check here is the first layer; Row Level Security in the database is the second.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import Depends, FastAPI
from fastapi import routing as fastapi_routing
from fastapi.routing import APIRoute

from app.core import audit, metrics
from app.core.deps import ALL_ROLES, Principal, get_principal
from app.core.errors import Forbidden


class Public:
    """Marks a route that is intentionally reachable without signing in. The reason is part of the registry."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __call__(self) -> None:
        return None


class Policy:
    def __init__(self, name: str, roles: Iterable[str], *, description: str = "") -> None:
        self.name = name
        self.roles = tuple(roles)
        self.description = description
        unknown = set(self.roles) - set(ALL_ROLES)
        if unknown:
            raise ValueError(f"policy {name!r} names unknown roles: {sorted(unknown)}")

    def __call__(self, principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in self.roles:
            metrics.ACCESS_DENIED.labels("role").inc()
            audit.write_independent(
                tenant_id=principal.tenant_id,
                action="access.denied",
                actor_id=principal.user_id,
                actor_role=principal.role,
                object_type="policy",
                object_id=self.name,
                result="denied",
                reason="role_not_allowed",
                details={"allowed_roles": list(self.roles)},
            )
            raise Forbidden("Your role cannot do this.", code="role_not_allowed")
        return principal


def any_authenticated(name: str) -> Policy:
    return Policy(name, ALL_ROLES)


def _find_marker(dependant: Any) -> Policy | Public | None:
    call = getattr(dependant, "call", None)
    if isinstance(call, Policy | Public):
        return call
    for child in getattr(dependant, "dependencies", []):
        found = _find_marker(child)
        if found is not None:
            return found
    return None


def _api_routes(app: FastAPI) -> Iterator[tuple[str, set[str], Any]]:
    """Yield (effective path, methods, dependant) for every API route, including routes from included routers.

    Recent FastAPI versions keep included routers as lazy wrappers instead of copying their routes into
    `app.routes`, so the public `iter_route_contexts` helper is used when it exists.
    """
    iter_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if iter_contexts is None:
        for route in app.routes:
            if isinstance(route, APIRoute):
                yield route.path, set(route.methods or ()), route.dependant
        return
    for context in iter_contexts(app.routes):
        original = context.original_route
        if isinstance(original, APIRoute):
            dependant = getattr(context, "dependant", None) or original.dependant
            yield context.path or original.path, set(context.methods or original.methods or ()), dependant


def describe_routes(app: FastAPI) -> list[dict[str, Any]]:
    """The endpoint-to-role registry: one entry per method and path."""
    entries: list[dict[str, Any]] = []
    for path, methods, dependant in _api_routes(app):
        marker = _find_marker(dependant)
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            entry: dict[str, Any] = {"method": method, "path": path, "policy": None, "roles": [], "public": False}
            if isinstance(marker, Policy):
                entry.update(policy=marker.name, roles=list(marker.roles))
            elif isinstance(marker, Public):
                entry.update(policy="public", public=True, reason=marker.reason)
            entries.append(entry)
    return sorted(entries, key=lambda e: (e["path"], e["method"]))


def undeclared_routes(app: FastAPI) -> list[str]:
    return [f"{e['method']} {e['path']}" for e in describe_routes(app) if e["policy"] is None]
