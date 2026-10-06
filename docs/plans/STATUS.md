# Trạng thái (cập nhật mỗi lát)
Cổng: python scripts/gate.py  (dùng --static để kiểm nhanh)
## 4b Nộp S: sửa theo review c4e1a0f. Đặc tả sửa: docs/plans/4b-fix-checklist.md
- [x] L0 Công cụ (lát này). Model: Flash
- [x] L1 Migration 0011 viết tay + cô lập test khỏi DB dev + chuyển truy vấn vào repository. Model: Pro. Cổng phải hết lỗi tĩnh và 3 test đang fail.
- [x] L2 Logic dịch vụ (mục 3a-3h, 3k, 3l của checklist) kèm test hồi quy. Model: Pro
- [x] L3 Xử lý nền (try/except, total_files, bỏ vòng sleep), dọn gói kẹt khi khởi động. Model: Pro
- [x] L3b Sửa L3 theo review 3b3a8f3: gộp warning_flags, rollback + nạp lại gói khi lỗi DB (không kẹt 'processing'), đổi tên fail_stuck_processing_packages, bổ sung test hồi quy.
- [x] L4 Giao diện Nộp S + selfcheck JS chạy hàm. Model: Flash
- [x] L4b Sửa L4 theo review bd4a431: setTimeout bọc hàm (hết "Illegal invocation", poll chạy tiếp), scanSubmitErrorText cho detail {code,message}, scanSubmitCanSubmit xét available, giữ body.modal-open khi còn modal khác; project_scan_submit.js?v=1.01.
- [x] L5 Tài liệu: mục "Nộp S" trong design doc viết lại theo code (điều kiện + mã lỗi, khớp số hộp, người scan, phiên bản, xử lý nền, QC-06, giao diện); thêm 2 việc sau 10/10. Model: Flash
## B0 Sửa khớp số hộp: case_key phân cấp ("phong01/0020") lấy nhầm số 1 thay vì 20
- [x] B0 Dùng box_number_of_case_key (thành phần cuối) thay vì dãy số đầu tiên; xóa nhánh ::muc-luc trong _extract_box_number; 3 test mới; cập nhật design doc.
## BR-01 so khớp mục lục + Check scan
- [x] B1a (dữ liệu + hàm so khớp)
- [x] B1b (nối vào xử lý nền + API)
- [x] B1c (sửa B1b: nối thẳng so khớp vào commit của gói)
- [x] B2a (chặn Đạt Check scan)
- [x] B2b (giao diện)
## BR-04: người check scan không được trùng người scan
- [x] B3 (chặn check scan trùng người scan)
## Check nhập hộp
- [x] C1a (model, service tính toán, API GET/POST round 1)
- [ ] C1b (nối vào xử lý nền hoặc test bổ sung - TBD)
- [x] C1c-1 (backend): hộp vượt ngưỡng BR-07 thì chặn bước sau, Admin duyệt kèm lý do.
- [ ] C2 (TBD)

