# Judge audit

```bash
cd src
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10      # exit 0
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10   # exit 1
```

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (tp 24, fp 4, fn 6, tn 66) | **dùng** (chỉ cho giọng văn, không cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không** (tp 9, fp 0, fn 21, tn 70) | **loại** |

Tỉ lệ fail quan sát được so với tỉ lệ đã hiệu chỉnh bằng Rogan-Gladen: tone 0.28 → 0.30; helpful 0.09 → 0.30. Judge helpful báo chỉ 9% fail trong khi thực tế khoảng 30%, tức là nó che 2/3 số lỗi.

## Audit thủ công (10 bất đồng tone + 3 helpful)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã. Rubric: bắt buộc xưng "LogiX" / "anh/chị", cấm "em/bạn/nha/nhé". |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | Người | Cùng lỗi xưng hô; thêm ví dụ âm tính "bạn ơi" vào rubric. |
| 3 | H-029 "…không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ nhìn "Dạ, vui lòng". Rubric: câu mệnh lệnh hoặc cấm khách liên hệ thì FAIL dù có kính ngữ. |
| 4 | H-042 "…đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: xin lỗi **không bắt buộc** khi đã giải quyết xong. |
| 5 | H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép dùng "refund". Thêm whitelist thuật ngữ vào rubric. |
| 6 | H-063 "…và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống. Đây là lỗi nội dung (gần FM-08), phải chấm bằng code, không để judge tone. |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji trong ngữ cảnh khiếu nại thì FAIL. |
| 8 | H-081 "đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket). Hành động: sửa nhãn, ghi vào changelog bộ nhãn, cho người thứ hai kiểm tra lại. |
| 9 | H-088 "Dạ, dạ, LogiX…" | FAIL | PASS | Người (khoan dung) | Lỗi gõ nhỏ. Rubric: lặp từ đơn lẻ không tính là lỗi giọng văn. |
| 10 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Rubric: tiếng Việt không dấu hoặc dịch máy thì FAIL. |
| 11 | HL-015 "đã hoàn 55.000đ" (ledger 40.000) | PASS | FAIL | Người | Judge không thấy ledger nên không thể chấm đúng tiền. Chuyển sang `reply_matches_ledger` (code). |
| 12 | HL-016 xin lỗi dài + 55.000đ (ledger 35.000) | PASS | FAIL | Người | Judge bị lời xin lỗi dài "mua chuộc" (thiên vị độ dài/lịch sự). |
| 13 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Sai xưng hô, không nói kết quả. |

## Kết luận
- **tone_ok dùng được** làm metric theo dõi giọng văn (κ 0.757, P 0.857, R 0.80 đều qua floor). Không đưa nó vào gate chặn tiền.
- **helpful bị loại**: recall 0.30 (bỏ sót 21/30 reply lỗi), κ 0.375 < 0.6. Precision 1.0 vô nghĩa vì judge gần như luôn nói PASS. 18/21 false negative là **sai tiền** (reply nói số khác ledger). Judge không có ledger trong context nên không thể chấm đúng loại lỗi này. Nếu dùng nó làm gate, regression FM-08 sẽ lọt. Thay bằng grader code `ReplyMatchesLedger` (metric `reply_matches_ledger`, blocking).
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới làm held-out thật. Một nhãn người (H-081) đã sai, nên bộ nhãn cũng cần người thứ hai kiểm.
