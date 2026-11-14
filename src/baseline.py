"""T09 baselines for fair comparison on the same case pool and seed.

Implements:
1. Default (`consent_naive`): "has consent or non-unknown lawful basis -> GO, else HOLD"
   (documented in docs/tracks/T09.md and tests/test_track_evaluators.py).
2. Trivial (`all_hold`): HOLD every case (reaches 0 critical misses but fails guardrail).

Run:
    python -m src.main --track t09 --pipeline src.baseline --output out/baseline --run-name baseline --offline --seed 42
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.manifest import verify_manifest
from .common.review import make_review_queue, write_review_queue
from .metrics.tracks import get_track


def _load_cases(input_dir: Path) -> list[dict]:
    files = sorted((input_dir / "cases").glob("CASE-*.json"))
    if not files:
        raise FileNotFoundError(f"No CASE-*.json files found in {input_dir / 'cases'}")
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


def run(ctx: RunContext) -> None:
    if ctx.track != "t09":
        raise NotImplementedError(f"src.baseline implements t09 baselines (got {ctx.track})")

    spec = get_track(ctx.track)
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems and ctx.config.get("strict_provenance", True):
        raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")

    cases = _load_cases(ctx.input_dir)
    mode = str(ctx.param("baseline_mode", "consent_naive")).strip().lower()
    rows = []
    for c in cases:
        consent_ok = bool((c.get("consent") or {}).get("obtained", False))
        basis = str(c.get("lawful_basis") or "unknown").strip().lower()
        if mode == "all_hold":
            dec = "HOLD"
            code = "ALL_HOLD_TRIVIAL"
            score = 100.0
            reason = "Trivial all-HOLD baseline"
        else:
            is_go = consent_ok or basis not in {"unknown", "none", ""}
            dec = "GO" if is_go else "HOLD"
            code = "" if is_go else "NO_LAWFUL_BASIS"
            score = 0.0 if is_go else 100.0
            reason = "Naive rule: consent obtained or lawful_basis != unknown" if is_go else "lawful_basis is unknown"
        rows.append(
            {
                "case_id": str(c["case_id"]),
                "decision": dec,
                "reason_codes": code,
                "score": score,
                "reason": reason,
                "suggested_action": "approve" if dec == "GO" else "reject",
                "slice": f"market={c.get('market', '')}|basis={basis}",
            }
        )

    df = pd.DataFrame(rows)
    ctx.stats["n_items"] = len(df)
    ctx.stats["baseline_mode"] = mode

    budget = int(ctx.param("budget", 12))
    q = make_review_queue(
        df,
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
        title=f"T09 Baseline ({mode}) review queue",
    )

    out_cols = spec.pred_columns + [c for c in ["reason_codes", "score", "reason"] if c not in spec.pred_columns]
    pred_path = ctx.out(spec.pred_file)
    df[out_cols].to_csv(pred_path, index=False)

    write_decision(
        Decision(
            status="HOLD",
            reason_code="BASELINE_ONLY",
            reason=f"Baseline ({mode}) only — never release without multi-market policy gate & DPO review",
            owner=str(ctx.config.get("owner", "baseline")),
            scope=ctx.track,
            evidence=[str(pred_path)],
            metrics={"n_cases": len(df), "n_go": int((df["decision"] == "GO").sum()), "n_hold": int((df["decision"] == "HOLD").sum())},
        ),
        ctx.out("decision.json"),
        ctx.out("decision_log.csv"),
    )
