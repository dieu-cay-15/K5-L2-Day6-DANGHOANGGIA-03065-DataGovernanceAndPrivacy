# Metric contract (khai báo bắt buộc — chốt trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi học viên **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của học viên (`DANGHOANGGIA-03065`) |
|---|---|
| Track | `T09 · Multi-Market Privacy Decision Gate` |
| Primary metric (tên đúng như evaluator in ra) | `Critical-miss Rate` (kèm constrained guardrail `Guardrail: False HOLD rate <= 0.5`) |
| Tăng tốt hay giảm tốt? | **Lower** (`Critical-miss Rate` giảm tốt; mục tiêu = `0.0`, guardrail `False HOLD rate <= 0.5`) |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | `case` (mỗi file `CASE-XX.json`) |
| Công thức + numerator / denominator | `Critical-miss Rate = count(gold_decision != "GO" and pred == "GO") / count(gold_decision != "GO")`<br>`False HOLD rate = count(gold_decision == "GO" and pred != "GO") / count(gold_decision == "GO")`<br>Secondary: `High-risk HOLD Recall`, `Exact decision accuracy`, `Reason-code match (risky)` |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | Khớp chính xác `1-1` theo `case_id`; `decision` chuẩn hóa qua `canonical_status` (`GO`/`HOLD`/`REWORK`; case thiếu bị tính là `GO` — worst case); `reason_codes` tách theo `;` và kiểm tra giao tập `bool(gold & pred)` |
| Candidate pool cố định | 12 case trong `fixtures/t09_privacy_gate/cases/CASE-01.json` .. `CASE-12.json` |
| Review budget B / K | `B = 12` (toàn bộ 12 case được xếp hạng giảm dần theo risk score để DPO/legal duyệt cuối; top rủi ro/ambiguity đứng đầu) |
| Seed | `42` |
| Threshold policy (chọn trên dev như thế nào) | Đóng băng toàn bộ luật trong `configs/policies/t09_policy.yaml` (`policy_version: 1.0.0`, `as_of_date: 2026-11-14`) dựa trên nghiên cứu `policy_example.yaml`, tài liệu pháp lý học tập (`VN` Luật 91/2025 + NĐ 356/2025, `EU` GDPR + EDPB 01/2020, `US-CA` CCPA/CPRA, `SG` PDPA) và phân tích 8 case `dev` (`CASE-01..08`). Thứ tự ưu tiên: `HOLD > REWORK > GO`; luật có `effective_date > as_of_date` chỉ ghi chú (`advisory`), không tính vi phạm hiện tại. |
| Eval split (không dùng để tune) | `split: eval` (`CASE-09..12`) — giữ kín hoàn toàn khi thiết kế & tinh chỉnh rule; `--split all` chỉ dùng tự kiểm nội bộ trên `dev` |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | Nghiêm trọng nhất: **Critical miss** (case rủi ro bị cho `GO`); tiếp theo là **False HOLD/REWORK** (vượt quá guardrail `0.5` làm tắc pipeline vô ích) |
| Slices sẽ báo cáo (≥2) | 1. Theo `gold_decision` (`GO`, `HOLD`, `REWORK` — in trực tiếp bởi `eval_t09`)<br>2. Theo `market` (`VN`, `EU`, `US-CA`, `SG`) & từng case chi tiết (`CASE-01..12`) |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | `N=12` (eval `N=4`) rất nhỏ → luôn báo kết quả **từng case** kèm `wilson_ci` (`src/metrics/estimation.py`) cho tỉ lệ miss / accuracy / false HOLD |
| Ngày giờ chốt + người chốt | `2026-11-14T21:05:00+07:00` — `Dang Hoang Gia (DANGHOANGGIA-03065)` |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
