# Trạng thái (cập nhật mỗi lát)
Cổng: python scripts/gate.py  (dùng --static để kiểm nhanh)
## 4b Nộp S: sửa theo review c4e1a0f. Đặc tả sửa: docs/plans/4b-fix-checklist.md
- [x] L0 Công cụ (lát này). Model: Flash
- [x] L1 Migration 0011 viết tay + cô lập test khỏi DB dev + chuyển truy vấn vào repository. Model: Pro. Cổng phải hết lỗi tĩnh và 3 test đang fail.
- [x] L2 Logic dịch vụ (mục 3a-3h, 3k, 3l của checklist) kèm test hồi quy. Model: Pro
- [x] L3 Xử lý nền (try/except, total_files, bỏ vòng sleep), dọn gói kẹt khi khởi động. Model: Pro
- [x] L3b Sửa L3 theo review 3b3a8f3: gộp warning_flags, rollback + nạp lại gói khi lỗi DB (không kẹt 'processing'), đổi tên fail_stuck_processing_packages, bổ sung test hồi quy.
- [ ] L4 Giao diện Nộp S + selfcheck JS chạy hàm. Model: Flash
- [ ] L5 Tài liệu. Model: Flash
