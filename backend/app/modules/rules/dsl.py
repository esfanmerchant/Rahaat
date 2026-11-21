"""The rule DSL (PLAN 6.8): rules are JSON data, never code.

    {"params": {"income_cap": 30000}, "required_docs": ["rahat_id"], "payment_pkr": 12000,
     "all": [{"id": "income_cap", "hard": true, "label_en": "...", "label_ur": "...",
              "expr": {"<=": [{"var": "verified_income_pkr"}, {"param": "income_cap"}]}}]}

Our own small interpreter. Only the operators listed in `OPERATORS` exist; nothing is ever passed to
`eval`. A rule version is limited to `MAX_NODES` expression nodes and each expression to `MAX_DEPTH` levels.

Three-valued (Kleene) logic: a variable the engine could not resolve is UNKNOWN, and UNKNOWN flows through
comparisons and arithmetic. `and`/`or` give a definite answer only when the known operands already decide it
(false AND anything is false; true OR anything is true), so a definite result never depends on a guess.

`validate()` never raises: it returns a list of repairable errors with a path to the offending node.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.contracts.decision import RuleTraceItem
from app.contracts.engine import Fact

MAX_DEPTH: Final = 8
MAX_NODES: Final = 200
MAX_RULES: Final = 50
MAX_PARAMS: Final = 30
MAX_STRING: Final = 200
MAX_LIST: Final = 50
MAX_PAYMENT_PKR: Final = 1_000_000

Type = Literal["bool", "number", "string", "list"]

# The variables a rule may read. The decision engine resolves each one from the evidence (decision/facts.py).
VARIABLES: Final[dict[str, Type]] = {
    "identity_verified": "bool",
    "verified_income_pkr": "number",
    "receives_other_aid": "bool",
    "is_widow": "bool",
    "has_disability": "bool",
    "household_size": "number",
    "age_years": "number",
    "district": "string",
    "gender": "string",
}

LOGIC: Final = frozenset({"and", "or"})
COMPARE: Final = frozenset({"==", "!=", "<", "<=", ">", ">="})
ORDERED: Final = frozenset({"<", "<=", ">", ">="})
ARITH: Final = frozenset({"+", "-", "*", "/"})
OPERATORS: Final = frozenset({*LOGIC, "not", *COMPARE, "in", *ARITH, "var", "param"})

TOP_LEVEL_KEYS: Final = frozenset({"params", "required_docs", "payment_pkr", "all"})
RULE_KEYS: Final = frozenset({"id", "hard", "label_en", "label_ur", "expr"})
DOCUMENT_KINDS: Final = frozenset({"rahat_id", "income_proof", "other"})

# Parameters with a meaning to the engine. Their ranges are checked; any other parameter is free.
ENGINE_PARAMS: Final[dict[str, tuple[float, float]]] = {
    "income_cap": (0, 10_000_000),
    "confidence_floor": (0.5, 1.0),
    "income_max_age_days": (1, 3650),
    "proof_days": (0, 60),
    "stale_income_settles_below": (0, 1),
    "identity_partial_min_name_score": (0.8, 1.0),
}

_ID = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class _Unknown:
    """The third truth value. A singleton; compare with `is UNKNOWN`."""

    _instance: _Unknown | None = None

    def __new__(cls) -> _Unknown:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __bool__(self) -> bool:  # pragma: no cover - a guard against accidental truthiness
        raise TypeError("UNKNOWN has no truth value; test it with `is UNKNOWN`")


UNKNOWN: Final = _Unknown()


@dataclass(frozen=True, slots=True)
class DslError:
    path: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


class DslInvalid(ValueError):
    def __init__(self, errors: list[DslError]) -> None:
        super().__init__("; ".join(f"{e.path}: {e.message}" for e in errors[:5]))
        self.errors = errors


class _EvalError(Exception):
    """A value of the wrong type reached an operator at run time. The rule becomes unknown, never a guess."""


# --- validation ----------------------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _literal_type(value: Any) -> Type | None:
    if isinstance(value, bool):
        return "bool"
    if _is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


class _Validator:
    def __init__(self, params: Mapping[str, Any]) -> None:
        self.params = params
        self.errors: list[DslError] = []
        self.nodes = 0

    def error(self, path: str, code: str, message: str) -> None:
        self.errors.append(DslError(path, code, message))

    def node(self, node: Any, path: str, depth: int) -> Type | None:
        self.nodes += 1
        if depth > MAX_DEPTH:
            self.error(path, "too_deep", f"Expressions may be at most {MAX_DEPTH} levels deep. Split this rule into simpler rules.")
            return None
        if node is None:
            self.error(path, "null_literal", "null is not allowed. A missing value is unknown by itself; do not test for it.")
            return None
        if isinstance(node, list):
            return self._list_literal(node, path)
        if not isinstance(node, dict):
            kind = _literal_type(node)
            if kind is None:
                self.error(path, "bad_literal", "Literals must be true, false, a finite number or a short string.")
            elif kind == "string" and len(node) > MAX_STRING:
                self.error(path, "string_too_long", f"Strings may be at most {MAX_STRING} characters.")
            return kind
        if len(node) != 1:
            self.error(path, "bad_node", 'Each expression node must have exactly one operator key, like {"<=": [a, b]}.')
            return None
        ((op, args),) = node.items()
        if op not in OPERATORS:
            allowed = ", ".join(sorted(OPERATORS))
            self.error(path, "unknown_operator", f"Unknown operator {op!r}. Allowed operators: {allowed}.")
            return None
        here = f"{path}.{op}"
        if op == "var":
            if not isinstance(args, str) or args not in VARIABLES:
                known = ", ".join(sorted(VARIABLES))
                self.error(here, "unknown_variable", f"Unknown variable {args!r}. Known variables: {known}.")
                return None
            return VARIABLES[args]
        if op == "param":
            if not isinstance(args, str) or args not in self.params:
                self.error(here, "unknown_parameter", f'Unknown parameter {args!r}. Define it under "params" first.')
                return None
            return _literal_type(self.params[args])
        if not isinstance(args, list):
            self.error(here, "operands_not_a_list", f"The operands of {op!r} must be a list.")
            return None
        if op in LOGIC:
            if len(args) < 1:
                self.error(here, "arity", f"{op!r} needs at least one operand.")
            for index, arg in enumerate(args):
                self._expect(arg, f"{here}[{index}]", depth + 1, "bool", op)
            return "bool"
        if op == "not":
            if len(args) != 1:
                self.error(here, "arity", "'not' takes exactly one operand.")
                return "bool"
            self._expect(args[0], f"{here}[0]", depth + 1, "bool", op)
            return "bool"
        if len(args) != 2:
            self.error(here, "arity", f"{op!r} takes exactly two operands.")
            for index, arg in enumerate(args):
                self.node(arg, f"{here}[{index}]", depth + 1)
            return "bool" if op in COMPARE or op == "in" else "number"
        left = self.node(args[0], f"{here}[0]", depth + 1)
        right = self.node(args[1], f"{here}[1]", depth + 1)
        if op in ARITH:
            for index, kind in ((0, left), (1, right)):
                if kind not in (None, "number"):
                    self.error(f"{here}[{index}]", "type", f"{op!r} works on numbers, not {kind}.")
            return "number"
        if op == "in":
            if left == "list":
                self.error(f"{here}[0]", "type", "The first operand of 'in' must be a single value.")
            if not isinstance(args[1], list):
                self.error(f"{here}[1]", "type", 'The second operand of \'in\' must be a literal list, like ["a", "b"].')
            elif left is not None and args[1] and _literal_type(args[1][0]) != left:
                self.error(f"{here}[1]", "type", f"The list holds {_literal_type(args[1][0])} values but the left side is {left}.")
            return "bool"
        if left == "list" or right == "list":
            self.error(here, "type", f"{op!r} cannot compare lists; use 'in'.")
        elif op in ORDERED:
            for index, kind in ((0, left), (1, right)):
                if kind not in (None, "number"):
                    self.error(f"{here}[{index}]", "type", f"{op!r} compares numbers, not {kind}.")
        elif left is not None and right is not None and left != right:
            self.error(here, "type", f"{op!r} compares values of the same type; got {left} and {right}.")
        return "bool"

    def _expect(self, node: Any, path: str, depth: int, wanted: Type, op: str) -> None:
        kind = self.node(node, path, depth)
        if kind is not None and kind != wanted:
            self.error(path, "type", f"Operands of {op!r} must be {wanted}, not {kind}.")

    def _list_literal(self, items: list[Any], path: str) -> Type | None:
        if len(items) > MAX_LIST:
            self.error(path, "list_too_long", f"Lists may hold at most {MAX_LIST} values.")
        kinds = {_literal_type(item) for item in items}
        if None in kinds or len(kinds) > 1:
            self.error(path, "bad_list", "A list must hold literal values of one type (all numbers or all strings).")
        self.nodes += len(items)
        return "list"


def validate(dsl: Any) -> list[DslError]:
    """Check a rule version. Returns repairable errors; an empty list means the DSL is valid."""
    if not isinstance(dsl, dict):
        return [DslError("$", "not_an_object", 'The rule version must be a JSON object with an "all" list of rules.')]
    errors: list[DslError] = []
    for key in sorted(set(dsl) - TOP_LEVEL_KEYS):
        errors.append(DslError(f"$.{key}", "unknown_key", f"Unknown key {key!r}. Allowed keys: {', '.join(sorted(TOP_LEVEL_KEYS))}."))

    params = dsl.get("params", {})
    if not isinstance(params, dict):
        errors.append(DslError("$.params", "bad_params", '"params" must be an object of name to value.'))
        params = {}
    if len(params) > MAX_PARAMS:
        errors.append(DslError("$.params", "too_many_params", f"At most {MAX_PARAMS} parameters."))
    for name, value in params.items():
        where = f"$.params.{name}"
        if not isinstance(name, str) or not _ID.match(name):
            errors.append(DslError(where, "bad_name", "Parameter names use lower case letters, digits and underscores."))
        if _literal_type(value) is None:
            errors.append(DslError(where, "bad_value", "A parameter is a number, true/false, or a short string."))
        elif name in ENGINE_PARAMS:
            low, high = ENGINE_PARAMS[name]
            if not _is_number(value) or not low <= value <= high:
                errors.append(DslError(where, "out_of_range", f"{name} must be a number from {low:g} to {high:g}."))

    docs = dsl.get("required_docs", [])
    if not isinstance(docs, list) or any(doc not in DOCUMENT_KINDS for doc in docs):
        errors.append(DslError("$.required_docs", "bad_documents", f"required_docs lists document kinds: {', '.join(sorted(DOCUMENT_KINDS))}."))
    payment = dsl.get("payment_pkr")
    if payment is not None and (isinstance(payment, bool) or not isinstance(payment, int) or not 0 <= payment <= MAX_PAYMENT_PKR):
        errors.append(DslError("$.payment_pkr", "bad_payment", f"payment_pkr is a whole number of rupees from 0 to {MAX_PAYMENT_PKR}."))

    rules = dsl.get("all")
    if not isinstance(rules, list) or not rules:
        errors.append(DslError("$.all", "no_rules", '"all" must be a non-empty list of rules.'))
        return errors
    if len(rules) > MAX_RULES:
        errors.append(DslError("$.all", "too_many_rules", f"At most {MAX_RULES} rules."))
    validator = _Validator(params)
    seen: set[str] = set()
    for index, rule in enumerate(rules):
        where = f"$.all[{index}]"
        if not isinstance(rule, dict):
            errors.append(DslError(where, "bad_rule", "Each rule is an object with id, hard and expr."))
            continue
        for key in sorted(set(rule) - RULE_KEYS):
            errors.append(DslError(f"{where}.{key}", "unknown_key", f"Unknown rule key {key!r}. Allowed: {', '.join(sorted(RULE_KEYS))}."))
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not _ID.match(rule_id):
            errors.append(DslError(f"{where}.id", "bad_id", "A rule id uses lower case letters, digits and underscores, starting with a letter."))
        elif rule_id in seen:
            errors.append(DslError(f"{where}.id", "duplicate_id", f"Rule id {rule_id!r} is used twice."))
        else:
            seen.add(rule_id)
        if not isinstance(rule.get("hard"), bool):
            errors.append(DslError(f"{where}.hard", "bad_hard", '"hard" must be true (must pass) or false (priority only).'))
        for label in ("label_en", "label_ur"):
            text = rule.get(label)
            if text is not None and (not isinstance(text, str) or len(text) > MAX_STRING):
                errors.append(DslError(f"{where}.{label}", "bad_label", f"Labels are text of at most {MAX_STRING} characters."))
        if "expr" not in rule:
            errors.append(DslError(f"{where}.expr", "missing_expr", 'Each rule needs an "expr".'))
            continue
        kind = validator.node(rule["expr"], f"{where}.expr", 1)
        if kind is not None and kind != "bool":
            errors.append(DslError(f"{where}.expr", "not_boolean", f"A rule must evaluate to true or false, not {kind}."))
    errors.extend(validator.errors)
    if validator.nodes > MAX_NODES:
        errors.append(DslError("$.all", "too_many_nodes", f"The rules use {validator.nodes} nodes; the limit is {MAX_NODES}."))
    return errors


def ensure_valid(dsl: Any) -> dict[str, Any]:
    errors = validate(dsl)
    if errors:
        raise DslInvalid(errors)
    return dsl  # type: ignore[no-any-return]


# --- evaluation ----------------------------------------------------------------------------------------


def _number(value: Any) -> float | int:
    if not _is_number(value):
        raise _EvalError(f"expected a number, got {type(value).__name__}")
    return value  # type: ignore[no-any-return]


def _truth(value: Any) -> bool | _Unknown:
    if value is UNKNOWN or isinstance(value, bool):
        return value
    raise _EvalError(f"expected true or false, got {type(value).__name__}")


def _eval(node: Any, facts: Mapping[str, Fact], params: Mapping[str, Any]) -> Any:
    if not isinstance(node, dict):
        return node  # a literal (validated) or a literal list
    ((op, args),) = node.items()
    if op == "var":
        fact = facts.get(args)
        return fact.value if fact is not None and fact.known and fact.value is not None else UNKNOWN
    if op == "param":
        return params[args]
    if op == "and":
        values = [_truth(_eval(arg, facts, params)) for arg in args]
        if any(v is False for v in values):
            return False
        return UNKNOWN if any(v is UNKNOWN for v in values) else True
    if op == "or":
        values = [_truth(_eval(arg, facts, params)) for arg in args]
        if any(v is True for v in values):
            return True
        return UNKNOWN if any(v is UNKNOWN for v in values) else False
    if op == "not":
        value = _truth(_eval(args[0], facts, params))
        return UNKNOWN if value is UNKNOWN else not value
    left = _eval(args[0], facts, params)
    right = _eval(args[1], facts, params)
    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN
    if op == "in":
        return left in right
    if op in ARITH:
        a, b = _number(left), _number(right)
        if op == "/" and b == 0:
            return UNKNOWN
        result = a + b if op == "+" else a - b if op == "-" else a * b if op == "*" else a / b
        return result if math.isfinite(result) else UNKNOWN
    if op in ORDERED:
        a, b = _number(left), _number(right)
        return a < b if op == "<" else a <= b if op == "<=" else a > b if op == ">" else a >= b
    if (_literal_type(left) or "?") != (_literal_type(right) or "!"):
        raise _EvalError("compared values of different types")
    return (left == right) if op == "==" else (left != right)


def evaluate_expr(expr: Any, facts: Mapping[str, Fact], params: Mapping[str, Any]) -> bool | _Unknown:
    """Evaluate one validated boolean expression. Returns True, False or UNKNOWN; never raises on bad data."""
    try:
        return _truth(_eval(expr, facts, params))
    except (_EvalError, TypeError, KeyError):
        return UNKNOWN


def referenced(expr: Any, kind: str) -> list[str]:
    """Variable (`kind="var"`) or parameter (`kind="param"`) names an expression reads, in first-seen order."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict) and len(node) == 1:
            ((op, args),) = node.items()
            if op == kind and isinstance(args, str):
                if args not in found:
                    found.append(args)
            elif isinstance(args, list):
                for arg in args:
                    walk(arg)

    walk(expr)
    return found


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """A rule's trace plus what the engine needs to decide whether the result is settled."""

    trace: RuleTraceItem
    variables: tuple[str, ...]
    min_confidence: float
    error: str | None = None

    @property
    def rule_id(self) -> str:
        return self.trace.rule_id

    def settled(self, result: str, floor: float) -> bool:
        """True when the rule has this result on verified inputs that all meet the confidence floor."""
        return self.trace.result == result and self.trace.verified_inputs and self.min_confidence >= floor


def evaluate_rules(dsl: Mapping[str, Any], facts: Mapping[str, Fact]) -> list[RuleEvaluation]:
    """Evaluate every rule of a validated rule version against resolved facts, in order."""
    params: Mapping[str, Any] = dsl.get("params", {})
    out: list[RuleEvaluation] = []
    for rule in dsl["all"]:
        expr = rule["expr"]
        names = referenced(expr, "var")
        error = None
        try:
            value = _truth(_eval(expr, facts, params))
        except (_EvalError, TypeError, KeyError) as exc:
            value, error = UNKNOWN, f"type_error: {exc}"
        result = "unknown" if value is UNKNOWN else ("pass" if value else "fail")
        used: dict[str, Any] = {}
        confidences: list[float] = []
        verified = True
        for name in names:
            fact = facts.get(name)
            known = fact is not None and fact.known and fact.value is not None
            used[name] = fact.value if known and fact is not None else None
            verified = verified and known and fact is not None and fact.verified
            confidences.append(fact.confidence if known and fact is not None else 0.0)
        for name in referenced(expr, "param"):
            used[f"param.{name}"] = params.get(name)
        trace = RuleTraceItem(
            rule_id=rule["id"], hard=bool(rule["hard"]), result=result, values_used=used, verified_inputs=verified,
            label_en=rule.get("label_en"), label_ur=rule.get("label_ur"),
        )  # fmt: skip
        out.append(RuleEvaluation(trace=trace, variables=tuple(names), min_confidence=min(confidences, default=1.0), error=error))
    return out


def diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[dict[str, Any]]:
    """A structural diff of two rule versions: params, documents, payment and rules by id."""
    changes: list[dict[str, Any]] = []

    def change(path: str, kind: str, before: Any, after: Any) -> None:
        changes.append({"path": path, "kind": kind, "old": before, "new": after})

    old_params, new_params = old.get("params", {}) or {}, new.get("params", {}) or {}
    for name in sorted(set(old_params) | set(new_params)):
        if name not in new_params:
            change(f"params.{name}", "removed", old_params[name], None)
        elif name not in old_params:
            change(f"params.{name}", "added", None, new_params[name])
        elif old_params[name] != new_params[name]:
            change(f"params.{name}", "changed", old_params[name], new_params[name])
    for key in ("required_docs", "payment_pkr"):
        if old.get(key) != new.get(key):
            change(key, "changed", old.get(key), new.get(key))

    def by_id(rules: Any) -> dict[str, Mapping[str, Any]]:
        return {r["id"]: r for r in rules or [] if isinstance(r, dict) and isinstance(r.get("id"), str)}

    old_rules, new_rules = by_id(old.get("all")), by_id(new.get("all"))
    for rule_id in [*old_rules, *[r for r in new_rules if r not in old_rules]]:
        if rule_id not in new_rules:
            change(f"rules.{rule_id}", "removed", old_rules[rule_id], None)
        elif rule_id not in old_rules:
            change(f"rules.{rule_id}", "added", None, new_rules[rule_id])
        else:
            for key in sorted(RULE_KEYS - {"id"}):
                if old_rules[rule_id].get(key) != new_rules[rule_id].get(key):
                    change(f"rules.{rule_id}.{key}", "changed", old_rules[rule_id].get(key), new_rules[rule_id].get(key))
    old_order = [r for r in old_rules if r in new_rules]
    new_order = [r for r in new_rules if r in old_rules]
    if old_order != new_order:
        change("rules", "reordered", old_order, new_order)
    return changes


def rule_ids(dsl: Mapping[str, Any]) -> Sequence[str]:
    return [rule["id"] for rule in dsl.get("all", [])]
