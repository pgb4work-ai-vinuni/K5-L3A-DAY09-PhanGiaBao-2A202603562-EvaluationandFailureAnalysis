# Trace case: từ trace tới quyết định sai đầu tiên

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run `E-seeded_regression-20261117-eda2` (row `E-002`, seed 11) |
| Triệu chứng | `TrialPass` FAIL (`status resolved != denied`), `RefundAmountCorrect` FAIL, `DbFactKept` FAIL. Reply "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." Ledger `refund_vnd=20000, refund_count=1`, trong khi nhãn là `refund_vnd=0`, `status=denied`. |
| Bước sai đầu tiên | Event **3** `model_override` `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (chỉ có tool read-only). Event 2 `investigator` đọc đúng DB: O-202 `delay_days=2`, chưa đủ điều kiện hoàn phí ship. Event 3 ghi đè fact DB bằng con số "trễ 5 ngày" khách tự khai. Event 4 `quote` 20.000đ (`SHIP-LATE-03`) chỉ là hệ quả của event 3. |
| Failure mode | FM-03 ticket_trust |
| Đối chứng | `fixed C-002@11`: event 2 giống hệt, **không có** `model_override`, event 3 `quote` = 0 (`no_entitlement`), reply "chưa đủ điều kiện", ledger 0. Đúng nhãn. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_seeded_regression_overrides_db_fact` (`DbFactKept`=False, `RefundAmountCorrect`=False, ledger 20.000) và `test_lab9_trace_case_fixed_keeps_db_fact` (pass trên `fixed`). Cả hai chạy trong `pytest -m student -k lab9`. Đã thấy fail trên variant lỗi và pass trên `fixed`. |
| Chưa chắc chắn | Trace không cho biết *vì sao* agent tin ticket (MockLLM chỉ là công tắc). Với LLM thật, nguyên nhân có thể là prompt hoặc thứ tự context. Trace cũng không chứng minh được biến thể `quiet_override` (cùng lỗi nhưng không ghi event): ở đó `DbFactKept` mù, chỉ `RefundAmountCorrect` bắt được. |

## Quy tắc
- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được.
