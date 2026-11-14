# Individual / Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Tài liệu nộp cá nhân (`DANGHOANGGIA-03065`) cho track **T09 · Multi-Market Privacy Decision Gate**. Mọi số liệu hiệu năng báo cáo bên dưới được sinh trực tiếp từ script (`src.main`, `src.baseline`, `src.metrics.tracks.eval_t09`, `src.metrics.estimation.wilson_ci`) trên môi trường offline Windows/Python 3.12.5. Riêng tập `eval` (`CASE-09..12`) không có file GT phân phối sẵn trong repo học viên (`fixtures/t09_privacy_gate/gt/gold_decisions.csv` → `src.evaluate` trả exit `2`), nên các bảng dưới phân biệt rõ **đo đạc trên `dev` (`CASE-01..08`)** và **lệnh chính thức để giảng viên chạy trên `eval`**.

---

## 00 · Header

| Mục | Giá trị |
|---|---|
| Student / Group ID | `IND-03065` · **Dang Hoang Gia** (Cá nhân) |
| Challenge | **T09 · Multi-Market Privacy Decision Gate** |
| Vai trò đảm nhiệm | End-to-end cá nhân: Config/Policy contract, Baselines (`src/baseline.py`), Policy Engine + 5-step Gate (`src/policy_engine.py`, `src/pipeline.py`), Tests (`tests/test_pipeline.py`), HITL Review + Report (`reports/`, `demo/`) |
| Git author (`git shortlog`) | `dieu-cay-15 <danggia2412@gmail.com>` |
| Tag `demo-180m` (commit) | `demo-180m` → commit `69ded3b` |
| Tag `final-24h` (commit) | `final-24h` → nhánh `main` (commit báo cáo & nghiệm thu cuối) |
| Ngày hoàn thành (giờ VN) | `2026-11-14` (`Asia/Ho_Chi_Minh`) |

---

## 01 · Problem statement

- **Ai bị ảnh hưởng / chịu hậu quả khi hệ thống sai:** Chủ thể dữ liệu (người đi bộ, tài xế, hành khách trong cabin, trẻ em) bị thu thập video/khuôn mặt thô lên cloud không mã hóa hoặc không rút lại được đồng ý; đội kỹ thuật ADAS phải thu hồi mô hình/xóa tập dữ liệu trái phép; doanh nghiệp đối mặt chế tài nặng (GDPR, Luật BVDLCN 91/2025/QH15, CCPA/CPRA, SG PDPA) khi chuyển dữ liệu xuyên biên giới thiếu hồ sơ đánh giá tác động hoặc cơ chế chuyển giao. Ngược lại, nếu gate `HOLD` nhầm các luồng edge an toàn (`GO`), quá trình phát triển/huấn luyện ADAS bị đình trệ oan.
- **Điểm nghẽn cụ thể:** Các checklist đơn giản kiểu *"có consent thì cho qua"* bỏ sót sự khác biệt cốt lõi giữa các thị trường (VN không có căn cứ lợi ích hợp pháp; US-CA không dùng mô hình lawful basis của GDPR; EU bắt buộc DPIA cho giám sát video hệ thống và cơ chế Chương V) và trộn lẫn nghĩa vụ hiện hành với luật sắp có hiệu lực (Ấn Độ DPDP 05/2027, EU AI Act 12/2027 & 08/2028).
- **Đầu vào → Đầu ra:**
  - Đầu vào: 12 hồ sơ xử lý dữ liệu (`fixtures/t09_privacy_gate/cases/CASE-01.json..CASE-12.json`), `manifest.csv` (sha256), và policy rule YAML có version + điều khoản nguồn (`configs/policies/t09_policy.yaml`, `policy_version: 1.0.0`, `sha256=e5713ddb41a8`).
  - Đầu ra: `decisions.csv` (`case_id`, `decision ∈ {GO, HOLD, REWORK}`, `reason_codes`), `decisions_raw.csv`, `review_queue.csv`, `contact_sheet.html`, `audit_checklist.md`, `audit_log.jsonl`, `decision.json`, `decision_log.csv`, `run_info.json`.
- **Tiêu chí `GO` / `HOLD` / `REWORK` (chốt trước eval trong `configs/policies/t09_policy.yaml`):**
  - Precedence cấp case: **`HOLD > REWORK > GO`**.
  - `HOLD`: Vi phạm căn cứ pháp lý (`NO_LAWFUL_BASIS`), thiếu cơ chế/hồ sơ chuyển dữ liệu xuyên biên giới (`XBORDER_NO_MECHANISM`, `XBORDER_NO_IMPACT_ASSESSMENT`), PII thô chưa ẩn danh trên cloud (`RAW_PII_IN_CLOUD`), thiếu DPIA bắt buộc (`DPIA_MISSING`), trẻ em (`MINORS`), thị trường chưa map, hoặc còn `ambiguity_notes` (`AMBIGUOUS_NEEDS_LEGAL`).
  - `REWORK`: Khắc phục được bằng kỹ thuật/vận hành trước release — thiếu notice (`NOTICE_MISSING`), không mã hóa at-rest (`NO_ENCRYPTION`), consent gộp/thiếu chứng từ (`CONSENT_INVALID`, `CONSENT_RECORD_MISSING`), lưu trữ vô hạn/quá ngưỡng (`RETENTION_UNBOUNDED`, `RETENTION_EXCESSIVE`).
  - `GO`: Mọi rule đang hiệu lực (`rule.effective_date <= as_of_date`) đều đạt; rule tương lai chỉ ghi ở cột `advisory_notes`.
  - Release gate tổng (`decide()`): **`HOLD`** nếu tồn tại ≥1 ca `HOLD`; **`REWORK`** nếu không có `HOLD` nhưng ≥1 ca `REWORK`; chỉ **`GO`** khi 100% case hợp lệ.
- **Giả định cần DPO / Legal xác nhận:** Các ngưỡng giữ dữ liệu (`>365d` raw/unredacted, `>730d` general) và diễn giải chi tiết hồ sơ theo Luật 91/2025/QH15 + Nghị định 356/2025/NĐ-CP được gắn `confidence: medium` và `needs_legal_review: true` trong YAML, bắt buộc con người rà soát lại.

---

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| `dev` (`CASE-01..08`) | 8 | `synthetic:tools/make_fixtures.py (seed 42)` trong `fixtures/t09_privacy_gate/manifest.csv` | `CC0-1.0 (synthetic, generated for AI20K Day06)` | Có (100% synthetic) |
| `eval` / heldout (`CASE-09..12`) | 4 | Cùng fixture `fixtures/t09_privacy_gate/manifest.csv`; GT nằm ngoài repo học viên (`fixtures/t09_privacy_gate/gt/gold_decisions.csv` thuộc bản giảng viên) | `CC0-1.0` | Có (100% synthetic) |

- **Schema & class mapping:** Mỗi JSON có `case_id`, `market` (`VN`, `EU`, `US-CA`, `SG`, `IN`), `purpose`, `data_types`, `data_subjects`, `lawful_basis`, `consent.{obtained, granular, withdrawable, record_available}`, `notice_given`, `storage.{raw_retained, location, encryption_at_rest}`, `transfer.{cross_border, destination, mechanism, transfer_impact_assessment}`, `retention_days`, `dpia_done`, `minors_possible`, `anonymization`, `ambiguity_notes` (và hỗ trợ tùy chọn `li_assessment_done`, `effective_date`). Output map sang 3 nhãn chuẩn qua `canonical_status`: `GO`, `HOLD`, `REWORK`.
- **Seed & Split:** `seed = 42`. `CASE-01..08` là tập `dev` để xây dựng & kiểm thử rule; `CASE-09..12` được giữ kín khi thiết kế rule (`CASE-09..12` không dùng để tinh chỉnh ngưỡng thủ công).
- **`manifest.csv` verified (`sha256`):** **Có** — `python -m tools.verify_manifests` trả `OK fixtures\t09_privacy_gate\manifest.csv` (`14 manifests, 0 failing`, exit `0`), và `strict_provenance: true` trong `src/pipeline.py` chặn chạy (exit `2`) nếu phát hiện sai hash/thiếu manifest.
- **Dữ liệu thật:** Không dùng (tình huống pháp lý tổng hợp không chứa PII thật; `README_disclaimer.md` được giữ nguyên).

---

## 03 · Research & design

- **Tham chiếu chính & lý do chọn kiến trúc:**
  1. **GDPR / EDPB Guidelines 01/2020 (Connected Vehicles) & 02/2026** (EUR-Lex / EDPB, xem ngày `2026-11-14`): làm cơ sở cho rule ẩn danh biên trước khi lên cloud (`R-STO-01`), DPIA bắt buộc (`R-EU-02`), chứng từ đồng ý có thể rút lại (`R-CON-02/03`), và cơ chế Chương V (`R-XB-EU-01`).
  2. **Luật BVDLCN 91/2025/QH15 & Nghị định 356/2025/NĐ-CP** (xem ngày `2026-11-14`): phân tách chặt quy tắc Việt Nam — không cho phép `legitimate_interest` (`R-VN-01`), yêu cầu hồ sơ đánh giá tác động xử lý (`R-VN-03`) và hồ sơ đánh giá tác động chuyển dữ liệu ra nước ngoài (`R-VN-02`, `R-VN-02B`).
  3. **CCPA/CPRA (§1798.100, §1798.120(c)), SG PDPA (s.20, s.24–26), India DPDP 2023/Rules 2025 (13/05/2027), Regulation (EU) 2026/1744 (AI Act 02/12/2027 & 02/08/2028)**: thiết kế cơ chế phân tách `effective_date` giúp không báo lỗi sai trên nghĩa vụ tương lai.
  - **Vì sao chọn Policy Engine AST khai báo YAML thay vì ML classifier hoặc `if/else` cứng trong code:** Tập dữ liệu nhỏ (12 ca), yêu cầu giải thích 100% có điều khoản luật trích dẫn, và có quy tắc phụ thuộc thời gian (`effective_date`) + dấu vết kiểm toán (`sha256` file policy). Dùng `ast.parse(..., mode="eval")` có whitelist node (`BoolOp`, `UnaryOp(Not)`, `Compare`, `Attribute`, `Constant`) thay `eval()` của Python vừa bảo đảm an toàn offline, vừa dễ cập nhật luật bằng YAML khi pháp luật thay đổi mà không sửa code Python.
- **Sơ đồ data flow 5 bước (`src/pipeline.py`):**
  `manifest.csv (sha256)` + `CASE-01..12.json` + `t09_policy.yaml` → **01 `load()`** (strict provenance + policy hash) → **02 `process()`** (`evaluate_case`: lọc `markets`, check `effective_date <= as_of_date`, tách `active_hits` vs `advisory_hits`, precedence `HOLD > REWORK > GO`) → **03 `rank()`** (`score = base + sum(severity) + 5*advisory`, xuất `review_queue.csv` & `contact_sheet.html`) → **04 `review()`** (lưu `decisions_raw.csv`, nạp `review_queue_reviewed.csv`, ghi diff append-only vào `audit_log.jsonl`) → **05 `decide()`** (xuất `audit_checklist.md`, `decisions.csv`, `decision.json`, `decision_log.csv`).
- **Thành phần offline:** 100% rule deterministic nội bộ (không dùng LLM API hay model weights ngoài; `offline_guard` xác nhận PASS trong `preflight`).
- **Trade-offs đã cân nhắc:**
  - *Strict provenance fail-fast vs cảnh báo:* chọn fail-fast (`exit 2`) khi hash `manifest.csv` sai để không bao giờ ký duyệt gate trên dữ liệu bị sửa ngầm.
  - *Conservatism khi gặp thị trường lạ / `ambiguity_notes`:* đẩy về `HOLD` (`AMBIGUOUS_NEEDS_LEGAL`) thay vì đoán, đánh đổi rủi ro tăng False HOLD nhẹ lấy an toàn pháp lý tuyệt đối (vẫn dễ dàng pass guardrail `<= 0.5`).

---

## 04 · Baseline vs PoC

- **Baseline 1 (`consent_naive`):** `src/baseline.py` (`baseline_mode: consent_naive`, commit `18e653e`) — quy tắc ngây thơ `"consent.obtained == true hoặc lawful_basis != unknown → GO, ngược lại HOLD"`. Chạy cùng candidate pool (12 ca), budget `B=12`, `seed=42`, `--offline`.
- **Baseline 2 (`all_hold` — tầm thường):** `src/baseline.py` (`baseline_mode: all_hold`) — đặt `HOLD` toàn bộ mọi case để đạt `Critical-miss Rate = 0` nhưng làm sập guardrail.
- **PoC (`T09 Multi-Market Privacy Gate`):** `src/pipeline.py` + `src/policy_engine.py` + `configs/policies/t09_policy.yaml` (`policy_version: 1.0.0`, 24 rule có nguồn, commit `b0ba5c0`), cùng pool, `B=12`, `seed=42`, `--offline`.

> **Trạng thái file eval chính thức:** Do `fixtures/t09_privacy_gate/gt/gold_decisions.csv` không nằm trong repo học viên, lệnh `python -m src.evaluate --track t09 --pred out/poc/decisions.csv` trả `exit 2` (`Ground truth is not distributed in the student repo`). Khi giảng viên nạp `gt/`, chạy:
> ```bash
> python -m src.evaluate --track t09 --pred out/baseline/decisions.csv --run-name baseline --out reports/metrics_baseline.json
> python -m src.evaluate --track t09 --pred out/poc/decisions.csv --run-name poc --out reports/metrics_poc.json
> python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md
> ```

**Bảng 1 · Baseline vs Ablation vs PoC đo trực tiếp trên `dev` (`CASE-01..08`, `N=8`: 7 ca rủi ro + 1 ca `GO`)**

*(Tính bằng chính hàm `src/metrics/tracks.py::eval_t09` và `src/metrics/estimation.py::wilson_ci` ở 95% độ tin cậy)*

| Hệ thống / Cấu hình | Critical-miss Rate ↓ *(Wilson 95% CI)* | High-risk Recall ↑ | False HOLD Rate ↓ (Guardrail `<=0.50`) | Exact Decision Accuracy ↑ | Reason-code Match (risky) ↑ | Guardrail Status | Runtime / 12 ca (`~per 100`) |
|---|---|---|---|---|---|---|---|
| **Baseline 1: `consent_naive`** | **0.8571** (`6/7`) `[0.487, 0.974]` | `0.1429` (`1/7`) | `0.000` (`0/1`) `[0.000, 0.793]` | `0.250` (`2/8`) | `0.1429` (`1/7`) | PASS | `0.1816s` (`~1.51s`) |
| **Baseline 2: `all_hold`** *(tầm thường)* | `0.000` (`0/7`) `[0.000, 0.354]` | `1.000` (`7/7`) | **1.000** (`1/1`) `[0.207, 1.000]` | `0.750` (`6/8`) | `0.000` (`0/7`) | **FAIL** | — |
| **Ablation 1: Global-only rules** *(bỏ rule VN/EU/SG)* | `0.5714` (`4/7`) `[0.250, 0.842]` | `0.4286` (`3/7`) | `0.000` (`0/1`) `[0.000, 0.793]` | `0.500` (`4/8`) | `0.4286` (`3/7`) | PASS | — |
| **Ablation 2: Bỏ rule `R-AMB-01`** *(trên dev)* | `0.000` (`0/7`) | `1.000` (`7/7`) | `0.000` (`0/1`) | `1.000` (`8/8`) | `1.000` (`7/7`) *(mất code `AMBIGUOUS_NEEDS_LEGAL` ở CASE-08)* | PASS | — |
| **T09 PoC (Full YAML Policy + HITL)** | **0.000 (`0/7`)** `[0.000, 0.354]` | **1.000 (`7/7`)** | **0.000 (`0/1`)** `[0.000, 0.793]` | **1.000 (`8/8`)** | **1.000 (`7/7`)** `[0.646, 1.000]` | **PASS** | `0.4203s` (`~3.50s`) |

---

## 05 · Evaluation protocol

- **Primary metric & Guardrail (`reports/metric_contract.md`):**
  - `Critical-miss Rate = count(gold_decision != "GO" and pred == "GO") / count(gold_decision != "GO")` (thấp hơn = tốt, mục tiêu `0.0`).
  - Constrained Guardrail: `False HOLD rate = count(gold_decision == "GO" and pred != "GO") / count(gold_decision == "GO") <= 0.50`.
  - Secondary: `High-risk HOLD Recall`, `Exact decision accuracy`, `Reason-code match (risky)` (`bool(gold_codes & pred_codes)` trên phần tử tách theo `;`). Ca bị thiếu trong `decisions.csv` bị tính mặc định là `GO` (worst case).
- **Budget / Threshold:** `B = 12` (toàn bộ 12 ca được xếp hạng ưu tiên DPO); mọi rule và `as_of_date = "2026-11-14"` đóng băng trước khi chạm vào `eval`.
- **Độ bất định khi N nhỏ:** Với `N_dev = 8` (`N_safe = 1`), khoảng tin cậy Wilson 95% của False HOLD rate ở `0/1` khá rộng (`[0.000, 0.793]`), do đó báo cáo bắt buộc liệt kê **từng case cụ thể** bên cạnh tỷ lệ tổng hợp.
- **Lệnh evaluate chính thức (cùng lệnh khi giảng viên gắn `gt/`):**
  `python -m src.evaluate --track t09 --pred out/poc/decisions.csv --run-name poc --out reports/metrics_poc.json`

---

## 06 · Result slices & Failure analysis

**Bảng 2 · Slice theo `gold_decision` và kết quả từng case trên `dev` (`CASE-01..08`)**

| Case (Market) | Kỳ vọng (`dev`) | `consent_naive` | Global-only Abl. | **T09 PoC (`decisions_raw` → `decisions` HITL)** | Ghi chú rule / luật kích hoạt |
|---|---|---|---|---|---|
| `CASE-01` (`VN`) | `HOLD` | `GO` **(MISS)** | `GO` **(MISS)** | **`HOLD`** (`NO_LAWFUL_BASIS`) | `R-VN-01` (Luật 91/2025 VN không có `legitimate_interest`) |
| `CASE-02` (`EU`) | `HOLD` | `GO` **(MISS)** | `GO` **(MISS)** | **`HOLD`** (`XBORDER_NO_MECHANISM`) | `R-XB-EU-01` (GDPR Ch.V) + advisory `R-EU-AIACT-2028` |
| `CASE-03` (`VN`) | `HOLD` | `GO` **(MISS)** | `HOLD` | **`HOLD`** `[DPO: approve]` (`RAW_PII_IN_CLOUD;CONSENT_INVALID;RETENTION_UNBOUNDED`) | `R-STO-01; R-CON-02; R-RET-01` |
| `CASE-04` (`EU`) | `HOLD` | `GO` **(MISS)** | `GO` **(MISS)** | **`HOLD`** (`DPIA_MISSING`) | `R-EU-02` (GDPR Đ.35) + 2 advisory `EU AI Act 2027/2028` |
| `CASE-05` (`US-CA`) | `REWORK` | `GO` **(MISS)** | `REWORK` | **`REWORK`** `[DPO: approve]` (`NOTICE_MISSING`) | `R-NOT-01` (`lawful_basis=n/a` không bị phạt oan theo CCPA) |
| `CASE-06` (`SG`) | `GO` | `GO` | `GO` | **`GO`** `[DPO: approve]` (`-`) | Xử lý biên + làm mờ trước upload + đã có LIA |
| `CASE-07` (`VN`) | `HOLD` | `GO` **(MISS)** | `GO` **(MISS)** | **`HOLD`** `[DPO: edit + AMBIGUOUS_NEEDS_LEGAL]` (`XBORDER_NO_IMPACT_ASSESSMENT;XBORDER_NO_MECHANISM`) | `R-VN-02; R-VN-02B` + DPO edit đòi ký duyệt hồ sơ NĐ 356 |
| `CASE-08` (`EU`) | `HOLD` | `HOLD` | `HOLD` | **`HOLD`** `[DPO: escalate]` (`AMBIGUOUS_NEEDS_LEGAL;NO_LAWFUL_BASIS`) | `R-AMB-01; R-EU-01` + advisory `R-EU-AIACT-2028` |

*(Xem trực quan tại [t09_dev_comparison.png](../demo/t09_dev_comparison.png) và [t09_dev_case_matrix.png](../demo/t09_dev_case_matrix.png))*

- **Failure case 1 — Kết luận hợp pháp chỉ dựa vào `consent` (`CASE-03`, VN):**
  - *Bằng chứng metadata:* `lawful_basis: "consent"`, `consent: {"obtained": true, "granular": false, "withdrawable": false, "record_available": true}`, `data_types: ["exterior_video", "face"]`, `storage: {"raw_retained": true, "location": "cloud", "encryption_at_rest": true}`, `anonymization: "none"`, `retention_days: null`.
  - *Root cause:* Baseline `consent_naive` chỉ kiểm `consent.obtained == true` nên cho `GO` (`score=0.0`), bỏ lọt 3 vi phạm nghiêm trọng đồng thời: lưu khuôn mặt thô lên cloud không ẩn danh (`R-STO-01` → `HOLD`), consent gộp/không thể rút lại (`R-CON-02`), và lưu trữ vô thời hạn (`R-RET-01`). PoC xếp ca này ở `rank=2` (`score=317.0`) để DPO xác nhận `HOLD`.
- **Failure case 2 — Bỏ sót rủi ro chuyển dữ liệu xuyên biên giới (`CASE-02` EU & `CASE-07` VN):**
  - *Bằng chứng metadata:* `CASE-02` (`EU`, `consent.obtained=true`, `transfer: {"cross_border": true, "destination": "non-adequate third country", "mechanism": null}`); `CASE-07` (`VN`, `consent.obtained=true`, `transfer: {"cross_border": true, "destination": "SG", "mechanism": "unknown", "transfer_impact_assessment": false}`).
  - *Root cause:* Cả `consent_naive` lẫn phiên bản ablation chỉ có rule chung toàn cầu (`Global-only`) đều cho `GO` vì thiếu kiểm tra điều kiện theo lãnh thổ: EU yêu cầu SCC/BCR/adequacy theo GDPR Chương V (`R-XB-EU-01`), còn VN yêu cầu **cả** hồ sơ đánh giá tác động chuyển dữ liệu ra nước ngoài lẫn cơ chế bảo vệ theo Luật 91/2025 Đ.21 & NĐ 356/2025 (`R-VN-02`, `R-VN-02B`).
- **Latency / Compute:** Máy `Intel64 Family 6 Model 142 Stepping 10, GenuineIntel`, `Windows-10-10.0.19045-SP0`, `Python 3.12.5`: baseline chạy `0.1816s` (12 ca ≈ `15.1 ms/ca`), PoC đầy đủ (bao gồm HTML contact sheet, audit log, markdown checklist) chạy `0.4203s` (12 ca ≈ `35.0 ms/ca`, tức ~`3.5s` / 100 ca trên CPU đơn luồng).

---

## 07 · Human & decision

- **Review queue (`reports/review_queue.csv`, `B = 12`):** Xếp hạng giảm dần theo `score = base(GO=0, REWORK=40, HOLD=100) + sum(rule_severity) + 5*n_advisory` (đẩy các ca có `AMBIGUOUS_NEEDS_LEGAL`, vi phạm đa chiều, vị thành niên lên đầu `rank 1..4`). Sinh đồng thời `out/poc/contact_sheet.html` phục vụ DPO duyệt offline.
- **Quy trình override & audit log bất biến (`out/poc/audit_log.jsonl`):**
  1. Lượt chạy 1 xuất `out/poc/decisions_raw.csv` giữ nguyên quyết định máy (`pending_review`).
  2. Reviewer **Dang Hoang Gia** điền `out/poc/review_queue_reviewed.csv` trên 7 ca trọng tâm (`CASE-09`, `CASE-08`: `escalate`; `CASE-03`, `CASE-12`, `CASE-05`, `CASE-06`: `approve`; `CASE-07`: `edit` với `override_value="HOLD|XBORDER_NO_IMPACT_ASSESSMENT;XBORDER_NO_MECHANISM;AMBIGUOUS_NEEDS_LEGAL"` để buộc ký duyệt hồ sơ NĐ 356). `load_review_decisions` bắt buộc có `reviewer` (nếu trống → fail-fast exit `2`).
  3. Lượt chạy 2 áp dụng override lên `out/poc/decisions.csv` trong khi giữ nguyên `decisions_raw.csv`, và ghi thêm 7 bản ghi `human_review:*` (`actor`, `before`, `after`, `reason`) vào `audit_log.jsonl` (tổng 33 dòng append-only sau 2 lượt). Bản đã duyệt được lưu nộp tại `reports/review_queue.csv`.
- **Decision policy & `decision_log.csv` (`reports/decision_log.csv`):** Release tổng hiện tại kết luận **`HOLD`** (`reason_code: AMBIGUOUS_OR_LEGAL_BLOCKERS`, `owner: Dang Hoang Gia (DPO / Privacy Reviewer)`, lý do: `Blocked release: 9/12 case(s) on HOLD (4 ambiguous, 1 REWORK, 2 GO; reviewed=7/12)`). Pipeline chỉ tự động đề xuất `GO` khi không còn bất kỳ `HOLD`, `REWORK`, hay ambiguity nào; mọi ca có `HOLD`/`REWORK` đều chặn release cho tới khi khắc phục kỹ thuật hoặc DPO ký ngoại lệ có căn cứ.

---

## 08 · Reproduce & tests

```bash
# 1. Cài đặt môi trường (trên Windows dùng .venv\Scripts\python.exe; repo chạy offline hoàn toàn)
python -m venv .venv && .\.venv\Scripts\pip.exe install -r requirements.txt
python -m tools.preflight && python -m tools.verify_manifests

# 2. Chạy Baseline & PoC (seed=42, offline)
python -m src.main --track t09 --pipeline src.baseline --output out/baseline --run-name baseline --offline --seed 42
python -m src.main --input fixtures/t09_privacy_gate --config configs/lab.yaml --output out/poc --run-name poc --offline --seed 42

# 3. Chạy Evaluate chính thức (yêu cầu thư mục gt/ của giảng viên; thiếu gt/ trả exit code 2 rõ ràng)
python -m src.evaluate --track t09 --pred out/baseline/decisions.csv --run-name baseline --out reports/metrics_baseline.json
python -m src.evaluate --track t09 --pred out/poc/decisions.csv      --run-name poc      --out reports/metrics_poc.json
python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md

# 4. Chạy bộ kiểm thử
pytest -q
```

- **Kết quả kiểm thử gần nhất:** `pytest -v tests/test_pipeline.py` đạt **`7 passed`** (`test_t09_poc_e2e_determinism`, `test_t09_baseline_modes`, `test_t09_hitl_override_and_audit_log`, `test_t09_hitl_missing_reviewer_fails_clearly`, `test_t09_strict_provenance_fails_on_tampered_manifest`, `test_t09_jurisdiction_and_effective_date_rules`, `test_t09_dev_self_evaluation_beats_baselines`), và `pytest -q` toàn repo trả **exit `0`** (chỉ skip các test đánh dấu `requires_gt` vì chưa có `gt/`).
- **Môi trường chạy thực tế:** `Windows-10-10.0.19045-SP0` · `Intel64 Family 6 Model 142 Stepping 10` · `Python 3.12.5` · lịch sử commit đối chiếu qua `git log --oneline`.

---

## 09 · Limitations & ethics

- **Rủi ro pháp lý / PII / license:** Tất cả 12 case trong `fixtures/t09_privacy_gate/` là dữ liệu tổng hợp `CC0-1.0`, không chứa hình ảnh/PII người thật. Tuy nhiên rule `policy v1.0.0` có trích dẫn tham khảo văn bản pháp luật đa quốc gia vẫn mang tính giáo dục.
- **TUYỆT ĐỐI KHÔNG tuyên bố "đạt GDPR / Luật BVDLCN Việt Nam":** Một rule engine YAML kiểm tra JSON có cấu trúc **không phải** tư vấn pháp lý hay chứng chỉ tuân thủ. Nhiều nội dung định tính (tính chính xác nội dung thông báo bảo mật, tương xứng giữa lợi ích và quyền chủ thể trong LIA/DPIA, hiệu lực hợp đồng SCC ký với nhà cung cấp cụ thể) không thể rút ra từ giá trị boolean `true/false`. Mọi quyết định cuối buộc phải qua **DPO / Pháp chế doanh nghiệp** (`needs_legal_review: true`).
- **Điều chưa biết, false alarms & scale 10×:**
  - *Điều chưa biết:* Nếu nội dung mâu thuẫn nằm ở văn bản tự do ngoài field `ambiguity_notes` (vd. mô tả dài trong `purpose`), AST rule hiện chưa phân tích NLP tự do → cần kết hợp bước rà soát con người.
  - *False alarms:* Nếu `as_of_date` đặt vượt mốc hiệu lực hoặc cấu hình rule tương lai sai `effective_date`, các nghĩa vụ sắp tới (như DPDP Ấn Độ `2027-05-13`) sẽ tạo báo động giả chặn release hiện hành.
  - *Khi scale 10×–100× (hàng nghìn ca):* Chi phí evaluate rule bằng Python chỉ ~`ms/ca`, nhưng **nút cổ chai là sức duyệt con người (`B`)** — giải pháp tiếp theo là tách auto-rework queue (`NOTICE_MISSING`, `NO_ENCRYPTION`) đẩy thẳng về Jira kỹ thuật, giữ hàng đợi DPO chỉ cho nhóm `HOLD` / `AMBIGUOUS_NEEDS_LEGAL` / `MINORS`.

---

## 10 · Team contribution

**Bảng 3 · Individual contribution evidence** (đối chiếu khớp với `git shortlog -sne --all`: `dieu-cay-15 <danggia2412@gmail.com>` và `reports/team_contributions.csv`):

| Học viên | Git author / email | Module / vai trò | Commit SHA chứng minh | Trình bày? |
|---|---|---|---|---|
| **Dang Hoang Gia** (`IND-03065`) | `dieu-cay-15 <danggia2412@gmail.com>` | Config, Policy YAML `v1.0.0` & Metric Contract (`configs/`, `reports/metric_contract.md`) | `7ceb4e9` | Có (cá nhân) |
| **Dang Hoang Gia** (`IND-03065`) | `dieu-cay-15 <danggia2412@gmail.com>` | Baseline `consent_naive` & `all_hold` (`src/baseline.py`) | `18e653e` | Có (cá nhân) |
| **Dang Hoang Gia** (`IND-03065`) | `dieu-cay-15 <danggia2412@gmail.com>` | AST Policy Engine & 5-step Gate + HITL (`src/policy_engine.py`, `src/pipeline.py`) | `b0ba5c0` | Có (cá nhân) |
| **Dang Hoang Gia** (`IND-03065`) | `dieu-cay-15 <danggia2412@gmail.com>` | 7 Tests: Determinism, HITL, Provenance, `effective_date`, Dev Self-eval (`tests/test_pipeline.py`) | `b26389b` | Có (cá nhân) |
| **Dang Hoang Gia** (`IND-03065`) | `dieu-cay-15 <danggia2412@gmail.com>` | DPO Review Queue, Charts, Audit Evidence & Final Report (`demo/`, `reports/`) | `69ded3b` (`demo-180m`) + commit `final-24h` | Có (cá nhân) |

---

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa thiết kế |
|---|---|---|
| https://eur-lex.europa.eu/eli/reg/2016/679/oj | `2026-11-14` | Căn cứ pháp lý GDPR (Art. 5/25/32 minimization & encryption, Art. 6(1) lawful basis, Art. 35 DPIA, Ch. V Art. 44–49 cross-border) & tham chiếu cùng EDPB Guidelines 01/2020 (Connected Vehicles) (`R-STO-01`). |
| https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Luat-Bao-ve-du-lieu-ca-nhan-2025-so-91-2025-QH15-625628.aspx | `2026-11-14` | Luật BVDLCN 91/2025/QH15 (cùng NĐ 356/2025/NĐ-CP): loại bỏ `legitimate_interest` tại VN (`R-VN-01`), quy định hồ sơ DPIA & đánh giá tác động chuyển dữ liệu ra nước ngoài (`R-VN-02/03`). |
| https://oag.ca.gov/privacy/ccpa | `2026-11-14` | CCPA/CPRA California: tách khỏi mô hình lawful basis GDPR, tập trung Notice at Collection (`R-NOT-01`), retention (`R-RET-02`) và bảo vệ trẻ em (`R-MIN-01`). |
| https://sso.agc.gov.sg/Act/PDPA2012 | `2026-11-14` | Singapore PDPA 2012 (rev. 2020): ngoại lệ Legitimate Interests kèm đánh giá LIA (`R-SG-02`) và Transfer Limitation (`R-XB-SG-01`). |
| https://www.meity.gov.in/ | `2026-11-14` | India DPDP Act 2023 / Rules 2025 (cốt lõi hiệu lực 13/05/2027) và Regulation (EU) 2026/1744 (02/12/2027 & 02/08/2028): thiết kế phân tách `effective_date` advisory vs active. |

---

**Checklist chốt khi nộp:**

- [x] Repo nội bộ đã khởi tạo git lịch sử sạch với hai tag mốc `demo-180m` và `final-24h`; input mẫu `CC0-1.0` hoàn toàn synthetic không chứa PII thật.
- [x] Đúng 1 lệnh run (`src.main --offline --seed 42`), 1 lệnh evaluate (`src.evaluate --track t09`), 1 lệnh test (`pytest -q`); không phụ thuộc tải mạng khi chạy.
- [x] Có đủ số liệu Baseline vs PoC + Ablation trên `dev` (`CASE-01..08`), ≥2 failure cases kèm bằng chứng metadata, reviewer evidence (`reports/review_queue.csv`), audit log, và `reports/decision_log.csv`.
- [x] Đầy đủ license/source provenance (`sha256` verified `14/14`), tách bạch `dev` vs `eval`, `seed=42`, thông số môi trường offline Windows/Python 3.12.5, nêu rõ trạng thái chưa có `gt/` từ phía học viên.
- [x] Mọi commit đều do `dieu-cay-15 <danggia2412@gmail.com>` (`IND-03065`) thực hiện và khớp minh bạch với `git shortlog -sne --all` và `reports/team_contributions.csv`.
