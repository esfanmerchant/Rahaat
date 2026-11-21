"""Central access policy. Every route declares exactly one `Policy` or `Public` marker.

    @router.get("/cases")
    def list_cases(principal: Principal = Depends(Policy("cases:read", roles=["officer"]))): ...

    # admit API keys that hold a scope, and charge more than one request against the rate limits
    Policy("cases:read", roles=["officer"], api_scopes=["cases:read"], cost=1)

    # a route whose policy comes from a helper can still declare a cost
    @router.post("/upload", dependencies=[Depends(Cost(10))])

`describe_routes()` lists the whole endpoint-to-role registry, and a test fails the build when any route
has no marker. A role check here is the first layer; Row Level Security in the database is the second.

Order of checks for a protected route: the credential (401), the rate limits (429), then the role or the
API key's scope (403). Limiting before the role check caps how fast a caller can fill the audit log with
refused attempts.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi import routing as fastapi_routing
from fastapi.routing import APIRoute

from app.core import apikeys, audit, metrics, ratelimit
from app.core.apikeys import API_SCOPES
from app.core.deps import ALL_ROLES, Principal, get_principal
from app.core.errors import Forbidden


class Cost:
    """Declares that one call to a route uses `units` requests of the caller's rate limit."""

    def __init__(self, units: int) -> None:
        if not 1 <= units <= ratelimit.MAX_COST:
            raise ValueError(f"cost must be between 1 and {ratelimit.MAX_COST}")
        self.units = units

    def __call__(self) -> None:
        return None


class Public:
    """Marks a route that is intentionally reachable without signing in. The reason is part of the registry.

    Public `/v1/` routes are rate limited per client network. Health, metrics and static files are not.
    """

    def __init__(self, reason: str, *, cost: int = 1) -> None:
        self.reason = reason
        self.cost = Cost(cost).units

    def __call__(self, request: Request) -> None:
        ratelimit.charge_anonymous(request.url.path, route_cost(request, self.cost))
        return None


class Policy:
    def __init__(
        self,
        name: str,
        roles: Iterable[str],
        *,
        description: str = "",
        api_scopes: Iterable[str] = (),
        cost: int = 1,
    ) -> None:
        self.name = name
        self.roles = tuple(roles)
        self.description = description
        self.api_scopes = tuple(api_scopes)
        self.cost = Cost(cost).units
        unknown = set(self.roles) - set(ALL_ROLES)
        if unknown:
            raise ValueError(f"policy {name!r} names unknown roles: {sorted(unknown)}")
        unknown_scopes = set(self.api_scopes) - set(API_SCOPES)
        if unknown_scopes:
            raise ValueError(f"policy {name!r} names unknown API scopes: {sorted(unknown_scopes)}")

    def __call__(self, request: Request, principal: Principal = Depends(get_principal)) -> Principal:
        cost = route_cost(request, self.cost)
        if principal.api_key is not None:
            key = principal.api_key
            ratelimit.charge(request.url.path, ratelimit.api_key_charges(key.tenant_id, key.id, key.prefix, key.rate_limit_per_min), cost)
            if not set(key.scopes) & set(self.api_scopes):
                # A key is created with at least one scope, so no scopes at all means it waits for a second admin.
                code = "api_key_pending_approval" if not key.scopes else "api_scope_missing"
                self._deny(principal, code, {"allowed_scopes": list(self.api_scopes), "key_prefix": key.prefix})
                if not key.scopes:
                    raise Forbidden("This API key works only after a second admin approves it.", code=code)
                raise Forbidden("This API key is not allowed to call this endpoint.", code=code)
            apikeys.record_use(key)
            return principal
        ratelimit.charge(request.url.path, ratelimit.user_charges(principal.tenant_id, principal.user_id, principal.role), cost)
        if principal.role not in self.roles:
            self._deny(principal, "role_not_allowed", {"allowed_roles": list(self.roles)})
            raise Forbidden("Your role cannot do this.", code="role_not_allowed")
        return principal

    def _deny(self, principal: Principal, reason: str, details: dict[str, Any]) -> None:
        metrics.ACCESS_DENIED.labels("scope" if principal.api_key else "role").inc()
        audit.write_independent(
            tenant_id=principal.tenant_id,
            action="access.denied",
            actor_type="api_key" if principal.api_key else "user",
            actor_id=principal.user_id,
            actor_role=principal.role,
            object_type="policy",
            object_id=self.name,
            result="denied",
            reason=reason,
            details=details,
        )


def any_authenticated(name: str) -> Policy:
    return Policy(name, ALL_ROLES)


def _markers(dependant: Any) -> Iterator[Any]:
    call = getattr(dependant, "call", None)
    if isinstance(call, Policy | Public | Cost):
        yield call
    for child in getattr(dependant, "dependencies", []):
        yield from _markers(child)


def _find_marker(dependant: Any) -> Policy | Public | None:
    return next((m for m in _markers(dependant) if isinstance(m, Policy | Public)), None)


def _declared_cost(dependant: Any) -> int:
    return max((m.units if isinstance(m, Cost) else m.cost for m in _markers(dependant)), default=1)


# Routes define __eq__ and so cannot be dict keys. The cache keeps the route object itself next to its cost,
# which also stops its id from being reused by another object while the entry exists.
_route_costs: dict[int, tuple[Any, int]] = {}


def route_cost(request: Request, own: int = 1) -> int:
    """The highest cost declared anywhere on the matched route (its policy, or a `Cost` marker)."""
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return own
    cached = _route_costs.get(id(route))
    if cached is None or cached[0] is not route:
        cached = (route, _declared_cost(dependant))
        _route_costs[id(route)] = cached
    return max(own, cached[1])


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
            entry: dict[str, Any] = {"method": method, "path": path, "policy": None, "roles": [], "public": False,
                                     "api_scopes": [], "cost": _declared_cost(dependant)}  # fmt: skip
            if isinstance(marker, Policy):
                entry.update(policy=marker.name, roles=list(marker.roles), api_scopes=list(marker.api_scopes))
            elif isinstance(marker, Public):
                entry.update(policy="public", public=True, reason=marker.reason)
            entries.append(entry)
    return sorted(entries, key=lambda e: (e["path"], e["method"]))


def undeclared_routes(app: FastAPI) -> list[str]:
    return [f"{e['method']} {e['path']}" for e in describe_routes(app) if e["policy"] is None]
