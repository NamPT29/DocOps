# Trạng thái (cập nhật mỗi lát)
Cổng: python scripts/gate.py  (dùng --static để kiểm nhanh)
## Triển khai (nhánh claude/nice-hamilton-7pg8bk)
- [x] H1a Sổ giao nhận hồ sơ giấy (CSDL, API, xuất Excel)
- [x] R1 scripts/preflight.py (chỉ đọc) + tests/test_preflight.py + docs/plans/runbook-trien-khai.md
- [x] R2 tests/test_migrations_postgres_offline.py (SQL PostgreSQL offline 0010 -> head); đã chạy thật 0001 -> 0014 trên PostgreSQL 16
- [x] R3 Runbook + test offline cập nhật cho 0015_entry_qc_round2; đã chạy thật hạ 0015 -> 0010 -> head trên PostgreSQL 16 (0 khác biệt)
- [x] R4 Cổng thêm luật: cổng đầy đủ phải chạy trên cây đã commit, test không sinh file trong repo, selfcheck chỉ dùng module có sẵn của Node, trang HTML không dán/nạp trùng; AGENTS.md thêm "Bài học từ review" và mẫu báo cáo
- [x] R5 Cổng coi selfcheck JS không in dòng cuối (OK/passed/ready) là hỏng, vì Node thoát mã 0 khi một lời hứa treo; tests/test_gate_rules.py
## Chấm công (nhánh claude/nice-hamilton-7pg8bk)
- [x] T1 Sheet "Chấm công theo ngày" trong mọi file Excel xuất (mỗi người mỗi ngày: số hàng đã nhập, đã duyệt)
## 4b Nộp S: sửa theo review c4e1a0f. Đặc tả sửa: docs/plans/4b-fix-checklist.md
- [x] L0 Công cụ (lát này). Model: Flash
- [x] L1 Migration 0011 viết tay + cô lập test khỏi DB dev + chuyển truy vấn vào repository. Model: Pro. Cổng phải hết lỗi tĩnh và 3 test đang fail.
- [x] L2 Logic dịch vụ (mục 3a-3h, 3k, 3l của checklist) kèm test hồi quy. Model: Pro
- [x] L3 Xử lý nền (try/except, total_files, bỏ vòng sleep), dọn gói kẹt khi khởi động. Model: Pro
- [x] L3b Sửa L3 theo review 3b3a8f3: gộp warning_flags, rollback + nạp lại gói khi lỗi DB (không kẹt 'processing'), đổi tên fail_stuck_processing_packages, bổ sung test hồi quy.
- [x] L4 Giao diện Nộp S + selfcheck JS chạy hàm. Model: Flash
- [x] L4b Sửa L4 theo review bd4a431: setTimeout bọc hàm (hết "Illegal invocation", poll chạy tiếp), scanSubmitErrorText cho detail {code,message}, scanSubmitCanSubmit xét available, giữ body.modal-open khi còn modal khác; project_scan_submit.js?v=1.01.
- [x] L5 Tài liệu: mục "Nộp S" trong design doc viết lại theo code (điều kiện + mã lỗi, khớp số hộp, người scan, phiên bản, xử lý nền, QC-06, giao diện); thêm 2 việc sau 10/10. Model: Flash
- [x] E1 Chặn Nộp S thư mục không có file nào (409 empty_folder)
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
- [x] C1b (giao diện Check nhập hộp; sửa ở C1b-2)
- [x] C1c-1 (backend): hộp vượt ngưỡng BR-07 thì chặn bước sau, Admin duyệt kèm lý do.
- [x] C1c-1b (sửa lỗi C1c-1, gọn migration, refactor test)
- [x] C1c-1c (thêm test cổng, dọn code/comment)
- [x] C1b-2 (selfcheck báo lỗi đúng, Dự kiến theo would_pass, luật gate chặn selfcheck nuốt lỗi)
- [x] C2a (Check nhập vòng 2 - Chính sách & Lấy mẫu)
- [x] C2b (Check từng phiếu, chốt vòng 2, Admin duyệt)
- [x] C2c (Giao diện Admin vòng 2)
- [x] C2c-2 (sửa lưu chính sách 422, popup vòng 2 đọc đúng API)
- [x] C2d-1 (backend vòng 2: mở phiếu mẫu, xem PDF, đếm đúng, chặn bước sau)
- [x] C2d-1b (sửa C2d-1: status ok, mock settings, test gate + pdf, tự đánh giá chốt trùng)
- [x] C2d-2 (giao diện check phiếu mẫu vòng 2)
- [x] C2d-2b (dropdown trống không còn bị tính là sửa; backend chỉ ghi trường thay đổi)
- [x] C2d-2c (test dùng biểu mẫu thật; vòng 2 chỉ nhận trường đang hiện)
- [x] C2e (sửa ForeignKeyViolation trên PostgreSQL khi xóa dự án/phiếu có mẫu vòng 2)
- [x] C2f (dọn C2e: 403 trước 409 khi xóa phiếu đã lấy mẫu, bỏ code thừa)

## Trang Hành chính (C3)
- [x] C3a (Hành chính tự làm Nộp S, Check scan, Check nhập; API my-projects, my-work)
- [x] C3a-2 (Sửa lỗi logic C3a, phân loại tài khoản db)
- [x] C3b (tab Việc của tôi ở index.html: Chỉnh lý, Nộp S, Check scan)
- [x] C3b-2 (reviewer: sửa index.html dán trùng, tab cho người chỉ làm quy trình, my-work hộp chưa có người phụ trách, giờ VN)
- [x] C3b-3 (gộp C3b-2, test_f đủ ca, sửa tài liệu C3)
- [x] C3c (Check nhập vòng 1/2 cho người kiểm tra ở index.html; sửa giờ Check nhập lệch 7 tiếng)
- [x] E4 (giờ thông báo và nhật ký bước trả kèm múi giờ UTC, hết lệch 7 tiếng)
- [x] E3 (mở lại hộp thoại Nộp S khi đang xử lý)
- [x] E3-2 (sửa E3 theo review: mở hộp thoại TRƯỚC KHI theo dõi gói processing)
- [x] E3-3 (reviewer: code E3-2 đạt, thử trình duyệt bản cũ không mở được hộp thoại, bản mới mở sau 0,2 giây; viết lại test để 7/7 mutation bị bắt, điều 10 AGENTS nguyên văn, sửa dòng tài liệu sai)
- [x] E2 (reviewer làm thay: test đặt LOG_DIR sang thư mục tạm trong tests/conftest.py, hết ghi logs/ của repo; uploads/ đã sạch; tests/test_test_isolation.py bảo vệ)
- [x] E5 (người nhập: lưu hồ sơ mới cho file đã có hồ sơ báo 409 rõ ràng thay vì "không thuộc người dùng"; lời nhắn sau khi lưu nháp chỉ tab Hồ sơ đã nhập; dòng giải thích chữ gạch ngang/Đã nhập; submission.js v100.06)
## Bìa hồ sơ (nhánh claude/nice-hamilton-7pg8bk)
- [x] F1 Bìa dùng chung theo thư mục: GET /api/cover-data, bìa chỉ mang sang file cùng thư mục, sang thư mục khác nạp bìa đã lưu; chỉ hỏi đồng bộ khi bìa đổi; biểu mẫu ≤ 30 trường mở mọi nhóm; mẫu docs/standards/Mau_Ho_So_Van_Ban.xlsx + danh mục QC-14; form_renderer.js v101.02, submission.js v100.07
- [x] F2 apiCall xóa bộ nhớ đệm GET sau mọi lệnh ghi (từ điển vừa tạo không hiện, cấu hình mở lại thấy bản cũ); auth.js v102.05
## Chuẩn hóa và Bàn giao (nhánh claude/nice-hamilton-7pg8bk)
- [x] G1 Kế hoạch chuẩn hóa (chỉ đọc): GET /api/projects/{pid}/normalization-plan, Excel mã hồ sơ/mã văn bản/đường dẫn bàn giao QC-03/QC-04 + vấn đề từng file; menu dự án "Kế hoạch chuẩn hóa (Excel)"; project_reports.js v1.01, project_management.js v2.17
- [x] G2 Đóng gói bàn giao: POST/GET /api/projects/{pid}/handover-package, chép file theo kế hoạch G1 vào HANDOVER_DIR (kiểm SHA-256, chạy lại bỏ qua file đúng), Metadata_NN-SIP.xlsx + SHA256SUMS.txt + Nhat_ky_dong_goi.xlsx; khóa theo dự án; menu "Đóng gói bàn giao"; project_reports.js v1.02, project_management.js v2.18
- [x] G3 Biên bản bàn giao Bien_ban_ban_giao.docx tự sinh mỗi lần đóng gói (docx_writer.py, không thêm thư viện); GET /api/projects/{pid}/handover-package/report; menu "Tải biên bản bàn giao"; project_reports.js v1.03, project_management.js v2.19
## Đợt B (giao Antigravity, nhánh claude/charming-planck-b2k42f; đặc tả docs/plans/2026-10-08-dot-b-spec.md)
Làm lần lượt; lát trước được reviewer duyệt mới làm lát sau.
- [x] H1a Sổ giao nhận hồ sơ giấy 5 mốc (FR-ARR-02): CSDL + API + Excel, revision 0016_case_paper_handoffs
- [x] H1a-2 Sửa H1a (Sổ giao nhận hồ sơ giấy) theo review 15ab685
- [ ] H1b Sổ giao nhận hồ sơ giấy: giao diện
- [ ] D1 Bảng tiến độ dự án: API GET /api/projects/{pid}/dashboard
- [ ] D2 Bảng tiến độ dự án: giao diện
- [ ] R1 Đối soát R1–R4 (Excel, giả định reviewer)
- [ ] K1a Khóa sửa hồ sơ sau bàn giao (thay G4): CSDL + API + chặn, revision 0017_project_handover_lock
- [ ] K1b Khóa sửa hồ sơ sau bàn giao: giao diện
- [ ] P1a Chi trả theo sản lượng: đơn giá + bảng tạm tính (API, Excel), revision 0018_project_work_rates
- [ ] P1b Chi trả theo sản lượng: giao diện
- [ ] P2 Chi trả: chốt kỳ, lưu kèm tham số, revision 0019_payroll_periods
