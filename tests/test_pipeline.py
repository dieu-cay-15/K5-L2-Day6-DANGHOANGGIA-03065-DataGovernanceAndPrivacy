"""Unit, HITL, provenance, and dev self-evaluation tests for T09 Privacy Gate."""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

import src.main as runner
from src.metrics.tracks import TRACKS, eval_t09
from src.policy_engine import eval_condition, evaluate_case, load_policy

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_T09 = ROOT / "fixtures" / "t09_privacy_gate"
POLICY_T09 = ROOT / "configs" / "policies" / "t09_policy.yaml"
LAB_CFG = ROOT / "configs" / "lab.yaml"


def _copy_t09_fixture(dst: Path) -> Path:
    shutil.copytree(FIXTURE_T09, dst)
    return dst


def _write_cfg(path: Path, extra: dict | None = None) -> Path:
    cfg = yaml.safe_load(LAB_CFG.read_text(encoding="utf-8")) or {}
    cfg["track"] = "t09"
    cfg["track_config"] = str(ROOT / "configs" / "tracks" / "t09.yaml")
    cfg.setdefault("params", {})["policy_file"] = str(POLICY_T09)
    if extra:
        for k, v in extra.items():
            if k == "params" and isinstance(v, dict):
                cfg["params"].update(v)
            else:
                cfg[k] = v
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def test_t09_poc_e2e_determinism(tmp_path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    rc1 = runner.main(
        ["--input", str(FIXTURE_T09), "--config", str(LAB_CFG), "--output", str(out1), "--offline", "--seed", "42"]
    )
    rc2 = runner.main(
        ["--input", str(FIXTURE_T09), "--config", str(LAB_CFG), "--output", str(out2), "--offline", "--seed", "42"]
    )
    assert rc1 == 0 and rc2 == 0

    required = [
        "decisions.csv",
        "decisions_raw.csv",
        "review_queue.csv",
        "contact_sheet.html",
        "audit_checklist.md",
        "audit_log.jsonl",
        "decision.json",
        "decision_log.csv",
        "run_info.json",
    ]
    for name in required:
        assert (out1 / name).exists(), f"missing {name}"

    assert (out1 / "decisions.csv").read_text(encoding="utf-8") == (out2 / "decisions.csv").read_text(encoding="utf-8")
    assert (out1 / "decisions_raw.csv").read_text(encoding="utf-8") == (out2 / "decisions_raw.csv").read_text(encoding="utf-8")

    info = json.loads((out1 / "run_info.json").read_text(encoding="utf-8"))
    assert info["status"] == 0 and info["seed"] == 42 and info["offline"] is True
    assert info["output_check"]["missing_columns"] == []


def test_t09_baseline_modes(tmp_path):
    out_naive = tmp_path / "naive"
    out_hold = tmp_path / "all_hold"
    cfg_hold = _write_cfg(tmp_path / "cfg_hold.yaml", {"params": {"baseline_mode": "all_hold"}})

    rc_naive = runner.main(
        ["--track", "t09", "--pipeline", "src.baseline", "--input", str(FIXTURE_T09), "--output", str(out_naive), "--offline", "--seed", "42"]
    )
    rc_hold = runner.main(
        ["--track", "t09", "--pipeline", "src.baseline", "--config", str(cfg_hold), "--input", str(FIXTURE_T09), "--output", str(out_hold), "--offline", "--seed", "42"]
    )
    assert rc_naive == 0 and rc_hold == 0

    df_naive = pd.read_csv(out_naive / "decisions.csv")
    df_hold = pd.read_csv(out_hold / "decisions.csv")
    assert (df_naive["decision"] == "GO").sum() > 1
    assert (df_hold["decision"] == "HOLD").all()
    assert (out_naive / "decision.json").exists()


def test_t09_hitl_override_and_audit_log(tmp_path):
    out = tmp_path / "poc"
    args = ["--input", str(FIXTURE_T09), "--config", str(LAB_CFG), "--output", str(out), "--offline", "--seed", "42"]
    assert runner.main(args) == 0

    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    q.loc[q["item_id"] == "CASE-05", ["reviewer", "reviewer_decision", "override_value", "review_note", "reviewed_at"]] = [
        "Dang Hoang Gia",
        "edit",
        "REWORK|NOTICE_MISSING;CONSENT_RECORD_MISSING",
        "Keep REWORK and add consent audit proof gap.",
        "2026-11-14T21:10:00+07:00",
    ]
    q.loc[q["item_id"] == "CASE-06", ["reviewer", "reviewer_decision", "override_value", "review_note", "reviewed_at"]] = [
        "Dang Hoang Gia",
        "escalate",
        "",
        "Escalate for secondary SG DPO spot-check.",
        "2026-11-14T21:10:15+07:00",
    ]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)

    assert runner.main(args) == 0

    raw = pd.read_csv(out / "decisions_raw.csv").set_index("case_id")
    final = pd.read_csv(out / "decisions.csv").set_index("case_id")

    assert raw.loc["CASE-06", "decision"] == "GO"
    assert final.loc["CASE-06", "decision"] == "HOLD"
    assert final.loc["CASE-06", "review_status"] == "reviewed:escalate"
    assert "AMBIGUOUS_NEEDS_LEGAL" in str(final.loc["CASE-06", "reason_codes"])

    assert final.loc["CASE-05", "decision"] == "REWORK"
    assert "CONSENT_RECORD_MISSING" in str(final.loc["CASE-05", "reason_codes"])
    assert final.loc["CASE-05", "review_status"] == "reviewed:edit"

    events = [json.loads(line) for line in (out / "audit_log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    human_events = [e for e in events if str(e.get("action", "")).startswith("human_review:")]
    assert len(human_events) == 2
    assert all(e["actor"] == "Dang Hoang Gia" for e in human_events)


def test_t09_hitl_missing_reviewer_fails_clearly(tmp_path):
    out = tmp_path / "poc"
    args = ["--input", str(FIXTURE_T09), "--config", str(LAB_CFG), "--output", str(out), "--offline", "--seed", "42"]
    assert runner.main(args) == 0

    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    q.loc[q["item_id"] == "CASE-01", ["reviewer", "reviewer_decision"]] = ["", "approve"]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)

    rc = runner.main(args)
    assert rc == 2  # ValueError from load_review_decisions maps to explicit IO/validation exit 2


def test_t09_strict_provenance_fails_on_tampered_manifest(tmp_path):
    bad_input = _copy_t09_fixture(tmp_path / "bad_fixture")
    (bad_input / "cases" / "CASE-01.json").write_text('{"tampered": true}\n', encoding="utf-8")

    out = tmp_path / "out"
    rc = runner.main(
        ["--input", str(bad_input), "--config", str(LAB_CFG), "--output", str(out), "--offline", "--seed", "42"]
    )
    assert rc == 2


def test_t09_jurisdiction_and_effective_date_rules():
    policy = load_policy(POLICY_T09)

    base = {
        "purpose": "telemetry safety check",
        "data_types": ["vehicle_telemetry"],
        "consent": {"obtained": True, "granular": True, "withdrawable": True, "record_available": True},
        "storage": {"location": "edge", "raw_retained": False, "encryption_at_rest": True},
        "transfer": {"cross_border": False, "mechanism": None, "transfer_impact_assessment": False},
        "retention_days": 90,
        "notice_given": True,
        "dpia_done": True,
        "li_assessment_done": True,
        "minors_possible": False,
        "anonymization": "blur_on_edge_before_upload",
        "ambiguity_notes": "",
    }

    # VN forbids legitimate_interest
    vn = evaluate_case({**base, "case_id": "SYN-VN", "market": "VN", "lawful_basis": "legitimate_interest"}, policy, date(2026, 11, 14))
    assert vn["decision"] == "HOLD" and "NO_LAWFUL_BASIS" in vn["reason_codes"]

    # US-CA does not require GDPR lawful_basis; notice controls GO vs REWORK
    us_ok = evaluate_case({**base, "case_id": "SYN-US-OK", "market": "US-CA", "lawful_basis": "n/a"}, policy, date(2026, 11, 14))
    assert us_ok["decision"] == "GO"
    us_bad = evaluate_case({**base, "case_id": "SYN-US-BAD", "market": "US-CA", "lawful_basis": "n/a", "notice_given": False}, policy, date(2026, 11, 14))
    assert us_bad["decision"] == "REWORK" and "NOTICE_MISSING" in us_bad["reason_codes"]

    # Unmapped market escalates cleanly to HOLD
    unmapped = evaluate_case({**base, "case_id": "SYN-JP", "market": "JP", "lawful_basis": "consent"}, policy, date(2026, 11, 14))
    assert unmapped["decision"] == "HOLD" and "AMBIGUOUS_NEEDS_LEGAL" in unmapped["reason_codes"]

    # Future-effective law (India DPDP 2027-05-13): advisory before effective date, enforced after
    in_case = {**base, "case_id": "SYN-IN", "market": "IN", "lawful_basis": "legitimate_interest"}
    before = evaluate_case(in_case, policy, date(2026, 11, 14))
    after = evaluate_case(in_case, policy, date(2027, 6, 1))
    assert before["decision"] == "GO"
    assert "R-IN-DPDP-2027" in before["advisory_notes"]
    assert after["decision"] == "HOLD" and "NO_LAWFUL_BASIS" in after["reason_codes"]

    # Safe AST evaluator blocks arbitrary calls
    assert eval_condition("transfer.cross_border and not transfer.transfer_impact_assessment", {
        "transfer": {"cross_border": True, "transfer_impact_assessment": False}
    }) is True
    try:
        eval_condition("__import__('os').system('echo unsafe')", {})
        assert False, "Expected ValueError on Call AST node"
    except ValueError:
        pass


def test_t09_dev_self_evaluation_beats_baselines(tmp_path):
    # Strictly dev split (CASE-01..CASE-08); eval split (CASE-09..12) remains untouched for instructor gt/.
    dev_gt = pd.DataFrame(
        [
            {"case_id": "CASE-01", "split": "dev", "gold_decision": "HOLD", "gold_reason_codes": "NO_LAWFUL_BASIS"},
            {"case_id": "CASE-02", "split": "dev", "gold_decision": "HOLD", "gold_reason_codes": "XBORDER_NO_MECHANISM"},
            {"case_id": "CASE-03", "split": "dev", "gold_decision": "HOLD", "gold_reason_codes": "RAW_PII_IN_CLOUD;CONSENT_INVALID;RETENTION_UNBOUNDED"},
            {"case_id": "CASE-04", "split": "dev", "gold_decision": "HOLD", "gold_reason_codes": "DPIA_MISSING"},
            {"case_id": "CASE-05", "split": "dev", "gold_decision": "REWORK", "gold_reason_codes": "NOTICE_MISSING"},
            {"case_id": "CASE-06", "split": "dev", "gold_decision": "GO", "gold_reason_codes": ""},
            {"case_id": "CASE-07", "split": "dev", "gold_decision": "HOLD", "gold_reason_codes": "XBORDER_NO_IMPACT_ASSESSMENT;XBORDER_NO_MECHANISM"},
            {"case_id": "CASE-08", "split": "dev", "gold_decision": "HOLD", "gold_reason_codes": "AMBIGUOUS_NEEDS_LEGAL;NO_LAWFUL_BASIS"},
        ]
    )
    gt_path = tmp_path / "dev_ref.csv"
    dev_gt.to_csv(gt_path, index=False)

    out_poc = tmp_path / "poc"
    out_naive = tmp_path / "naive"
    out_hold = tmp_path / "hold"
    cfg_hold = _write_cfg(tmp_path / "cfg_hold.yaml", {"params": {"baseline_mode": "all_hold"}})

    assert runner.main(["--input", str(FIXTURE_T09), "--config", str(LAB_CFG), "--output", str(out_poc), "--offline", "--seed", "42"]) == 0
    assert runner.main(["--track", "t09", "--pipeline", "src.baseline", "--input", str(FIXTURE_T09), "--output", str(out_naive), "--offline", "--seed", "42"]) == 0
    assert runner.main(["--track", "t09", "--pipeline", "src.baseline", "--config", str(cfg_hold), "--input", str(FIXTURE_T09), "--output", str(out_hold), "--offline", "--seed", "42"]) == 0

    ev_poc = eval_t09(gt_path, out_poc / TRACKS["t09"].pred_file, {"split": "dev", "max_false_hold": 0.5})
    ev_naive = eval_t09(gt_path, out_naive / TRACKS["t09"].pred_file, {"split": "dev", "max_false_hold": 0.5})
    ev_hold = eval_t09(gt_path, out_hold / TRACKS["t09"].pred_file, {"split": "dev", "max_false_hold": 0.5})

    m_poc = {m.name: m.value for m in ev_poc.metrics}
    m_naive = {m.name: m.value for m in ev_naive.metrics}
    m_hold = {m.name: m.value for m in ev_hold.metrics}

    assert m_poc["Critical-miss Rate"] == 0.0
    assert m_poc["False HOLD rate"] == 0.0
    assert m_poc["Guardrail: False HOLD rate <= 0.5"] == 1.0
    assert m_poc["Exact decision accuracy"] == 1.0
    assert m_poc["Reason-code match (risky)"] == 1.0

    assert m_naive["Critical-miss Rate"] > 0.5
    assert m_hold["False HOLD rate"] == 1.0
    assert m_hold["Guardrail: False HOLD rate <= 0.5"] == 0.0
