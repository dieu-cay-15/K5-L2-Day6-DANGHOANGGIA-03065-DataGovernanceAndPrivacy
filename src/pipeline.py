"""YOUR PoC PIPELINE — Multi-Market Privacy Decision Gate (T09).

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      input cases + provenance check (manifest.csv) + versioned YAML policy
    02 process   declarative policy engine evaluation (active vs future effective_date)
    03 rank      prioritise cases by privacy risk/ambiguity for DPO review + contact sheet
    04 review    human-in-the-loop: load reviewed CSV -> apply overrides -> append-only audit log
    05 decide    release-level GO / HOLD / REWORK gate with reason_code + owner + evidence
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, canonical_status, write_decision
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track
from .policy_engine import PolicyBundle, evaluate_case, load_policy


def _resolve_policy_path(ctx: RunContext) -> Path:
    raw = str(ctx.param("policy_file", "rules/policy_example.yaml"))
    candidates = [Path(raw), ctx.input_dir / raw]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"Policy file {raw!r} not found in {[str(c) for c in candidates]}")


def _merge_reason_codes(existing: str, extra_code: str) -> str:
    parts = [p.strip() for p in str(existing or "").split(";") if p.strip() and p.strip() != "nan"]
    if extra_code and extra_code not in parts:
        parts.append(extra_code)
    return ";".join(parts)


def _safe_md_cell(val: object, default: str = "-") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    text = str(val).strip()
    if not text or text.lower() == "nan":
        return default
    return text.replace(" | ", "; ").replace("|", ";")


def _write_audit_checklist(df: pd.DataFrame, policy: PolicyBundle, as_of: date, out_path: Path) -> Path:
    lines = [
        f"# T09 Privacy Gate Audit Checklist (Policy v{policy.policy_version})",
        "",
        f"- **Evaluation date (`as_of_date`):** `{as_of.isoformat()}`",
        f"- **Policy file:** `{policy.path}` (`sha256={policy.sha256[:12]}`)",
        "- **Disclaimer:** Academic exercise only — not legal advice; final decision requires DPO/Legal approval.",
        "",
        "| Case | Market | Decision | Reason Codes | Rules | Advisory (Future Law) | Review Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in df.itertuples(index=False):
        rc = _safe_md_cell(row.reason_codes)
        rules = _safe_md_cell(row.triggered_rules)
        adv = _safe_md_cell(row.advisory_notes)
        rev = _safe_md_cell(getattr(row, "review_status", "pending_review"), "pending_review")
        lines.append(
            f"| {row.case_id} | {row.market} | **{row.decision}** | `{rc}` | `{rules}` | {adv} | {rev} |"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    if ctx.track != "t09":
        raise NotImplementedError(
            f"src/pipeline.py is implemented for t09 (got {ctx.track}); switch configs/lab.yaml or pass --track t09"
        )
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        if ctx.audit:
            ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")

    case_files = sorted((ctx.input_dir / "cases").glob("CASE-*.json"))
    if not case_files:
        raise FileNotFoundError(f"No CASE-*.json files found under {ctx.input_dir / 'cases'}")
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in case_files]

    policy_path = _resolve_policy_path(ctx)
    policy = load_policy(policy_path)
    as_of_raw = ctx.param("as_of_date", policy.default_as_of_date.isoformat())
    as_of_date = date.fromisoformat(str(as_of_raw))

    if ctx.audit:
        ctx.audit.log(
            actor="pipeline",
            action="load_policy",
            item_id=str(policy.path),
            after={"policy_version": policy.policy_version, "sha256": policy.sha256, "as_of_date": as_of_date.isoformat()},
            reason=f"Loaded {len(cases)} cases and {len(policy.rules)} policy rules",
        )
    return {
        "manifest": pd.read_csv(manifest) if manifest.exists() else None,
        "cases": cases,
        "policy": policy,
        "as_of_date": as_of_date,
    }


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    policy: PolicyBundle = data["policy"]
    as_of_date: date = data["as_of_date"]
    results = [evaluate_case(case, policy, as_of_date=as_of_date) for case in data["cases"]]
    df = pd.DataFrame(results).sort_values("case_id", kind="mergesort").reset_index(drop=True)
    ctx.stats["policy_version"] = policy.policy_version
    ctx.stats["as_of_date"] = as_of_date.isoformat()
    ctx.stats["n_auto_hold"] = int((df["decision"] == "HOLD").sum())
    ctx.stats["n_auto_rework"] = int((df["decision"] == "REWORK").sum())
    ctx.stats["n_auto_go"] = int((df["decision"] == "GO").sum())
    return df


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Rank cases by privacy risk & ambiguity score for DPO/Legal review."""
    budget = int(ctx.param("budget", len(scored)))
    if "score" not in scored.columns:
        raise ValueError("rank(): process() output needs a numeric `score` column")
    q = make_review_queue(
        scored,
        id_col="case_id",
        score_col="score",
        budget=budget,
        reason_col="reason",
        action_col="suggested_action",
        slice_col="slice",
    )
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(
        q,
        ctx.out("contact_sheet.html"),
        image_col=None,
        fields=("rank", "item_id", "score", "reason", "suggested_action", "slice"),
        title="T09 · Multi-Market Privacy Gate — DPO Review Queue",
    )
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Preserve raw automated decisions, then apply human DPO/legal decisions if reviewed."""
    spec = get_track(ctx.track)
    out = scored.copy()
    out["review_status"] = "pending_review"

    raw_cols = spec.pred_columns + [c for c in out.columns if c not in spec.pred_columns]
    out[raw_cols].to_csv(ctx.out("decisions_raw.csv"), index=False)

    if ctx.audit:
        for row in out.itertuples(index=False):
            ctx.audit.log(
                actor="policy_engine",
                action="auto_evaluate",
                item_id=row.case_id,
                after={"decision": row.decision, "reason_codes": row.reason_codes, "rules": row.triggered_rules},
                reason=row.reason,
            )

    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if not reviewed_path.exists():
        ctx.stats["n_reviewed"] = 0
        return out

    reviewed = load_review_decisions(reviewed_path)
    ctx.stats["n_reviewed"] = len(reviewed)
    out["case_id"] = out["case_id"].astype(str)
    id_set = set(out["case_id"])

    for r in reviewed.itertuples(index=False):
        cid = str(r.item_id)
        if cid not in id_set:
            continue
        mask = out["case_id"] == cid
        before_dec = str(out.loc[mask, "decision"].iloc[0])
        before_codes = str(out.loc[mask, "reason_codes"].iloc[0])
        dec_type = str(r.reviewer_decision).strip().lower()
        ov_raw = str(r.override_value).strip()
        note = str(r.review_note).strip()

        new_dec = before_dec
        new_codes = before_codes

        if dec_type in {"edit", "reject"}:
            if ov_raw:
                if "|" in ov_raw:
                    ov_dec, ov_codes = ov_raw.split("|", 1)
                    new_dec = canonical_status(ov_dec)
                    new_codes = ov_codes.strip()
                else:
                    new_dec = canonical_status(ov_raw)
                    if new_dec == "GO":
                        new_codes = ""
            elif dec_type == "reject":
                new_dec = "HOLD"
                new_codes = _merge_reason_codes(before_codes, "AMBIGUOUS_NEEDS_LEGAL")
        elif dec_type == "escalate":
            new_dec = "HOLD"
            new_codes = _merge_reason_codes(before_codes, "AMBIGUOUS_NEEDS_LEGAL")

        out.loc[mask, "decision"] = new_dec
        out.loc[mask, "reason_codes"] = new_codes
        out.loc[mask, "review_status"] = f"reviewed:{dec_type}"

        if ctx.audit:
            ctx.audit.log(
                actor=str(r.reviewer),
                action=f"human_review:{dec_type}",
                item_id=cid,
                before={"decision": before_dec, "reason_codes": before_codes},
                after={"decision": new_dec, "reason_codes": new_codes},
                reason=note or f"Human reviewer action: {dec_type}",
            )

    return out


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    owner = str(ctx.config.get("owner") or "").strip()
    if not owner or owner.upper().startswith("TODO"):
        raise ValueError("Decision.owner must be set to a real reviewer/role in configs/lab.yaml (not TODO)")

    n_total = len(final)
    n_hold = int((final["decision"] == "HOLD").sum())
    n_rework = int((final["decision"] == "REWORK").sum())
    n_go = int((final["decision"] == "GO").sum())
    n_ambig = int(final["reason_codes"].astype(str).str.contains("AMBIGUOUS_NEEDS_LEGAL", na=False).sum())
    n_reviewed = int(ctx.stats.get("n_reviewed", 0))

    if n_hold > 0:
        status = "HOLD"
        reason_code = "AMBIGUOUS_OR_LEGAL_BLOCKERS" if n_ambig > 0 else "PRIVACY_BLOCKERS_PRESENT"
        reason = (
            f"Blocked release: {n_hold}/{n_total} case(s) on HOLD "
            f"({n_ambig} ambiguous, {n_rework} REWORK, {n_go} GO; reviewed={n_reviewed}/{n_total})."
        )
    elif n_rework > 0:
        status = "REWORK"
        reason_code = "PRIVACY_REMEDIATION_REQUIRED"
        reason = (
            f"Remediation required before release: {n_rework}/{n_total} case(s) require REWORK "
            f"({n_go} GO; reviewed={n_reviewed}/{n_total})."
        )
    else:
        status = "GO"
        reason_code = "ALL_CASES_COMPLIANT"
        reason = f"All {n_total} multi-market privacy cases cleared under policy v{ctx.stats.get('policy_version')}."

    return Decision(
        status=status,
        reason_code=reason_code,
        reason=reason,
        owner=owner,
        scope=f"{ctx.track} (policy v{ctx.stats.get('policy_version', 'unknown')})",
        evidence=[
            str(ctx.out("decisions.csv")),
            str(ctx.out("decisions_raw.csv")),
            str(ctx.out("audit_log.jsonl")),
            str(ctx.out("audit_checklist.md")),
        ],
        metrics={
            "n_cases": n_total,
            "n_hold": n_hold,
            "n_rework": n_rework,
            "n_go": n_go,
            "n_ambiguous": n_ambig,
            "n_reviewed": n_reviewed,
        },
    )


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    _write_audit_checklist(final, data["policy"], data["as_of_date"], ctx.out("audit_checklist.md"))
    out_cols = spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]
    final[out_cols].to_csv(ctx.out(spec.pred_file), index=False)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
