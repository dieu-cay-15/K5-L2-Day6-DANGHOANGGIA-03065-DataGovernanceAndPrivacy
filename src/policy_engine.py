"""Declarative YAML privacy policy engine for T09 (Multi-Market Privacy Decision Gate).

Evaluates structured privacy case JSON objects against a versioned, source-cited
YAML ruleset using a safe AST boolean expression evaluator (never Python ``eval``).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .common.io import sha256_file

PRECEDENCE_RANK = {"GO": 0, "REWORK": 1, "HOLD": 2}
_LITERAL_NAMES = {"null": None, "None": None, "true": True, "True": True, "false": False, "False": False}


def _resolve_attr(obj: Any, attr: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(attr, None)
    return getattr(obj, attr, None)


def _eval_node(node: ast.AST, data: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, data)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _LITERAL_NAMES:
            return _LITERAL_NAMES[node.id]
        return data.get(node.id, None)
    if isinstance(node, ast.Attribute):
        return _resolve_attr(_eval_node(node.value, data), node.attr)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        vals = [_eval_node(el, data) for el in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(vals)
        if isinstance(node, ast.Set):
            return set(vals)
        return vals
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_eval_node(node.operand, data))
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for v in node.values:
                if not bool(_eval_node(v, data)):
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for v in node.values:
                if bool(_eval_node(v, data)):
                    return True
            return False
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, data)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval_node(comp, data)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Is):
                ok = left is right
            elif isinstance(op, ast.IsNot):
                ok = left is not right
            elif isinstance(op, ast.In):
                ok = False if right is None else (left in right)
            elif isinstance(op, ast.NotIn):
                ok = True if right is None else (left not in right)
            elif isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                if left is None or right is None:
                    ok = False
                elif isinstance(op, ast.Lt):
                    ok = left < right
                elif isinstance(op, ast.LtE):
                    ok = left <= right
                elif isinstance(op, ast.Gt):
                    ok = left > right
                else:
                    ok = left >= right
            else:
                raise ValueError(f"Unsupported comparison operator in policy rule: {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True
    raise ValueError(f"Unsupported AST node in policy rule: {type(node).__name__}")


def eval_condition(expr: str, case: dict[str, Any]) -> bool:
    """Safely evaluate a policy ``when`` boolean expression against ``case``."""
    tree = ast.parse(expr, mode="eval")
    return bool(_eval_node(tree, case))


@dataclass
class PolicyBundle:
    path: Path
    sha256: str
    policy_version: str
    effective_date: date
    default_as_of_date: date
    known_markets: set[str]
    rules: list[dict[str, Any]]


def load_policy(path: str | Path) -> PolicyBundle:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Policy file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    eff = date.fromisoformat(str(raw.get("effective_date", "2026-01-01")))
    as_of = date.fromisoformat(str(raw.get("default_as_of_date", "2026-11-14")))
    rules = raw.get("rules") or []
    for r in rules:
        if "id" not in r or "when" not in r or "decision" not in r or "reason_code" not in r:
            raise ValueError(f"Invalid rule entry in {p}: {r}")
        if r["decision"] not in PRECEDENCE_RANK:
            raise ValueError(f"Unsupported rule decision {r['decision']!r} in {r['id']}")
        ast.parse(r["when"], mode="eval")
    return PolicyBundle(
        path=p,
        sha256=sha256_file(p),
        policy_version=str(raw.get("policy_version", "unknown")),
        effective_date=eff,
        default_as_of_date=as_of,
        known_markets=set(raw.get("known_markets") or []),
        rules=rules,
    )


def _rule_source_str(rule: dict[str, Any]) -> str:
    src = rule.get("source") or {}
    doc = src.get("doc", "Policy")
    ref = src.get("ref", "")
    return f"{rule['id']}: {doc}" + (f" ({ref})" if ref else "")


def evaluate_case(case: dict[str, Any], policy: PolicyBundle, as_of_date: date | None = None) -> dict[str, Any]:
    """Evaluate one privacy case against ``policy`` at ``as_of_date``."""
    eval_date = as_of_date or policy.default_as_of_date
    market = str(case.get("market") or "").strip()
    case_eff_raw = case.get("effective_date")
    case_is_future = False
    if case_eff_raw:
        case_is_future = date.fromisoformat(str(case_eff_raw)) > eval_date

    active_hits: list[dict[str, Any]] = []
    advisory_hits: list[dict[str, Any]] = []

    for rule in policy.rules:
        markets = rule.get("markets") or ["*"]
        if "*" not in markets and market not in markets:
            continue
        if not eval_condition(rule["when"], case):
            continue
        rule_eff = date.fromisoformat(str(rule.get("effective_date", policy.effective_date.isoformat())))
        if rule_eff > eval_date or case_is_future:
            advisory_hits.append(rule)
        else:
            active_hits.append(rule)

    if policy.known_markets and market not in policy.known_markets:
        active_hits.append(
            {
                "id": "R-SYS-UNMAPPED-MKT",
                "decision": "HOLD",
                "reason_code": "AMBIGUOUS_NEEDS_LEGAL",
                "severity": 95,
                "note": f"Market {market!r} is not mapped in policy version {policy.policy_version}.",
                "source": {"doc": "Internal Privacy Gate Standard", "ref": "Jurisdiction Coverage Check"},
                "needs_legal_review": True,
            }
        )

    final_decision = "GO"
    for hit in active_hits:
        if PRECEDENCE_RANK[hit["decision"]] > PRECEDENCE_RANK[final_decision]:
            final_decision = hit["decision"]

    sorted_hits = sorted(
        active_hits,
        key=lambda r: (PRECEDENCE_RANK[r["decision"]], float(r.get("severity", 50))),
        reverse=True,
    )
    reason_codes: list[str] = []
    for h in sorted_hits:
        rc = str(h["reason_code"])
        if rc not in reason_codes:
            reason_codes.append(rc)

    base_score = {"GO": 0.0, "REWORK": 40.0, "HOLD": 100.0}[final_decision]
    severity_sum = sum(float(h.get("severity", 50)) for h in sorted_hits)
    advisory_bonus = 5.0 * len(advisory_hits)
    score = base_score + severity_sum + advisory_bonus

    triggered_ids = [str(h["id"]) for h in sorted_hits]
    sources = [_rule_source_str(h) for h in sorted_hits]
    notes = [str(h.get("note", "")) for h in sorted_hits if h.get("note")]
    advisory_notes = [
        f"{h['id']} (effective {h.get('effective_date')}): {h.get('note', h['reason_code'])}"
        for h in advisory_hits
    ]

    if final_decision == "GO":
        reason_text = "All active market checks passed"
        if advisory_notes:
            reason_text += f"; {len(advisory_notes)} upcoming rule notice(s)"
        suggested_action = "approve"
    else:
        reason_text = "; ".join(notes) if notes else "; ".join(reason_codes)
        suggested_action = "escalate" if "AMBIGUOUS_NEEDS_LEGAL" in reason_codes else (
            "reject" if final_decision == "HOLD" else "edit"
        )

    return {
        "case_id": str(case["case_id"]),
        "decision": final_decision,
        "reason_codes": ";".join(reason_codes),
        "score": round(score, 3),
        "reason": reason_text,
        "suggested_action": suggested_action,
        "slice": f"market={market}|basis={case.get('lawful_basis', 'n/a')}",
        "market": market,
        "lawful_basis": str(case.get("lawful_basis", "")),
        "cross_border": bool((case.get("transfer") or {}).get("cross_border", False)),
        "dpia_done": bool(case.get("dpia_done", False)),
        "retention_days": case.get("retention_days"),
        "triggered_rules": ";".join(triggered_ids),
        "legal_sources": " | ".join(sources),
        "advisory_notes": " | ".join(advisory_notes),
        "needs_legal_review": any(bool(h.get("needs_legal_review", False)) for h in sorted_hits),
        "policy_version": policy.policy_version,
    }
