# Thiết kế mở rộng: quy trình số hóa end-to-end

Quy trình thực tế: **chỉnh lý → scan → check scan → nhập liệu → check nhập liệu → chuẩn hóa → bàn giao**.
Trước đây hệ thống chỉ hỗ trợ hai bước giữa (nhập liệu, check nhập liệu).

Nguồn yêu cầu: tài liệu BA "BA DVOS – Nền tảng số hóa khép kín v1.0" (02/10/2026, kế thừa
DVOS-DIGI-BA-001 v0.1 của Duy Vũ). Tài liệu này chỉ ghi phần thiết kế kỹ thuật; mọi quy tắc
nghiệp vụ lấy theo BA (mã FR/BR/NFR ghi trong ngoặc).

## Quyết định đã chốt (theo BA v1.0)

| Chủ đề | Quyết định |
|---|---|
| Đơn vị theo dõi, giao việc | Thư mục cấp **hộp** (`ProjectCase`), như phần mềm hiện tại. Work Batch tùy ý để sau |
| Role | 3 role: Admin, Hành chính, CTV. WorkType tách khỏi Role (BA mục 3) |
| Ai làm bước nào | Chỉnh lý, scan, check scan: Admin + Hành chính. Chuẩn hóa, bàn giao: chỉ Admin (PM). Nhập liệu: cả 3 role |
| Không tự kiểm | Không ai check/duyệt việc của chính mình, **kể cả Admin** (BR-04) |
| Chuẩn hóa | Làm sạch tên/đường dẫn + chuyển PDF/A + ký số từng PDF (ngoài hệ thống) + đóng gói SIP |
| Bàn giao | Gói PDF/A đã ký + metadata + SHA-256 + biên bản tự sinh; nghiệm thu; khóa |
| Chỉnh lý | Excel mục lục, mỗi dòng một hồ sơ; so khớp thư mục hồ sơ với scan là bắt buộc (BR-01) |

## Kiến trúc nền (Phase 0, đã xong)

Bảng mới (revision `0005_workflow_stages`, chỉ thêm, không sửa bảng cũ):

- `project_stages` – bước nào được bật cho dự án. Dự án không có dòng nào chạy ở chế độ cũ.
- `project_stage_members` – người được làm các bước không có pool riêng. Nhập liệu/check nhập liệu
  vẫn dùng `project_members` (`input`/`reviewer`).
- `case_stage_states` – trạng thái từng hộp ở từng bước: `pending | in_progress | done | rejected`.
- `case_stage_events` – nhật ký chuyển trạng thái, chỉ ghi thêm.

Máy trạng thái thuần Python: `server/services/workflow_engine.py`.

- Bước sau chỉ mở khi bước bật liền trước đã `done`.
- Bước kiểm tra trả lại thì bước được kiểm chuyển `rejected` (lý do bắt buộc, tăng `rework_count`).
- Không trả lại/mở lại khi bước phía sau đã bắt đầu.
- `StageDef.allowed_roles` mã hóa BA mục 3.3; `configure_workflow` từ chối giao bước chỉ-Admin cho người khác.
- `data_entry`/`entry_qc` được **suy ra** từ `submissions`, không chuyển thủ công.

API (`server/routers/workflow.py`): `GET /api/workflow/stages`; dưới `/api/projects/{id}/workflow`:
`GET|PUT ""`, `GET overview`, `GET cases`, `GET my-work`, `GET cases/{case}/events`,
`POST cases/{case}/stages/{stage}/transition`, `PUT cases/{case}/stages/{stage}/assignee`.

Giao diện: Tab **Dự án → Thao tác → Quy trình số hóa** (`frontend/js/project_workflow.js`).

## Ràng buộc kỹ thuật của repo

- Schema `0001` đóng băng (`migrations/schema_0001.py`). Bảng sau baseline đánh dấu
  `info={"revision": ...}` để bộ sinh snapshot bỏ qua.
- Router/service không gọi `.query(`; repository không `commit/rollback` (có test bảo vệ).
- Migration không import `server.*`; mỗi revision mới nâng `HEAD_REVISION`.
- Quyền nhập/kiểm cụ thể vẫn **suy ra từ phân công** (`UserRepository.capability_flags`).
  Cột thêm sau baseline gắn `info={"revision": ...}` giống bảng mới; bộ sinh snapshot bỏ qua chúng.

## Loại tài khoản và hạn CTV (03/10, FR-AUT-02/03, revision `0006_user_account_type`)

- `users.role` giữ nguyên ('admin' | 'user') làm cờ phân quyền. Thêm `users.account_type`
  ('staff' = Hành chính | 'ctv') và `users.expires_on` (DATE, chỉ CTV). Tài khoản cũ thành 'staff'.
- Hàm thuần ở `server/services/account_policy_service.py`. CTV dùng được **hết ngày** `expires_on`
  theo giờ VN (UTC+7 cố định); từ 00:00 hôm sau: đăng nhập trả 403, phiên đang mở trả 401 và bị thu hồi.
- Không đặt hạn ở quá khứ (tạo và sửa); giữ nguyên ngày cũ thì vẫn sửa được thông tin khác.
- `allowed_roles` so theo loại tài khoản: CTV chỉ vào được bước có "ctv" (nhập liệu). CTV không được
  làm người kiểm tra ở mọi luồng (dự án, nhập thư mục máy chủ, giao tài liệu, chia lại người kiểm tra).
- Đổi Hành chính → CTV bị từ chối (409) nếu còn phân công không dành cho CTV; hệ thống liệt kê,
  không tự gỡ. Không đổi qua lại với Admin.



## Admin nhập liệu (03/10, BA 3.3, BR-04)

- Admin được phân làm người nhập trong dự án (bỏ quy tắc cũ "Quản trị viên không được phân làm
  người nhập").
- Admin vào trang nhập liệu bằng nút **Nhập liệu** trên trang quản trị (`index.html?mode=input`);
  trang chỉ hiện dự án Admin được phân nhập và hồ sơ của chính Admin (`GET /api/submissions?mine=true`).
  Hồ sơ Admin nhập có đủ phần phản hồi chất lượng và xác nhận chỉnh sửa như người nhập khác.
- BR-04 giữ nguyên: chia hộp không giao người kiểm tra trùng người nhập; mọi thao tác duyệt chặn
  người tạo hồ sơ, kể cả Admin; "hồ sơ tiếp theo" bỏ qua hồ sơ của chính người duyệt.
- Luồng cũ (giao tài liệu lẻ, nhập thư mục máy chủ) vẫn chỉ nhận tài khoản thường làm người nhập.

## Khóa / mở khóa tài khoản (03/10, nhiệm vụ 1c, revision `0007_user_lock`)

- `users.is_locked` + bảng `user_lock_events` chỉ ghi thêm (tài khoản, khóa/mở, người làm, thời
  điểm UTC, lý do). Tài khoản có nhật ký khóa không xóa được (giữ truy vết, như các lịch sử khác).
- Khóa: lý do bắt buộc; thu hồi mọi phiên ngay; cấm tự khóa và cấm khóa Admin cuối cùng còn hoạt
  động (409, có khóa dòng để hai Admin không khóa lẫn nhau cùng lúc). Mở khóa: lý do không bắt buộc.
- Người bị khóa chỉ thấy "Tài khoản đã bị khóa. Liên hệ quản trị viên." (đăng nhập 403, phiên cũ
  401); lý do chỉ Admin xem trong nhật ký (cửa sổ Sửa tài khoản). Khóa được ưu tiên hơn hết hạn CTV.

## Chính sách dự án (03/10, FR-PRJ-01/03, revision `0008_project_policies`)

- Bảng `project_policies` (một dòng mỗi dự án, mọi cột cho phép NULL): QC-08 (ngưỡng lỗi của hộp
  BR-07, tỷ lệ lấy mẫu check vòng 2, hạn xử lý hộp), QC-02/03 (mã cơ quan, ký hiệu hồ sơ), QC-01
  (chuẩn xuất `NN-SIP` / `DANG-HD40`), QC-07/09 (hệ số giấy xấu, ngoài giờ, Chủ nhật).
- NULL = theo QC-01 hiện hành (`project_policy_service.QC01_DEFAULTS`, `QC_VERSION`). Các bước sau
  đọc giá trị áp dụng bằng `get_effective_policy(db, project_id=...)`.
- Giới hạn (cả API lẫn CHECK ở DB): tỷ lệ 0–100, tối đa 2 chữ số thập phân; hạn 1–365 ngày; hệ số
  > 0 và ≤ 10; mã cơ quan / ký hiệu theo bộ ký tự QC-04.
- "Ngưỡng lỗi của hộp (BR-07)" khác "tỷ lệ lỗi tối đa của biểu mẫu" (xếp *một báo cáo* vào loại lỗi).
- Giao diện: Dự án → Thao tác → Chính sách dự án.

## Mục lục chỉnh lý (03/10, FR-ARR-01, revision `0009_arrangement_catalog`)

- Bảng `arrangement_dossiers` (mỗi dòng mục lục = một hồ sơ, gắn với hộp = `ProjectCase`) và
  `arrangement_imports` (nhật ký mỗi lần ghi: file, SHA-256, ai, khi nào, số thêm/sửa/xóa/giữ lại).
- Đọc theo QC-16: sheet `Muc_luc`, cột theo tên tiêu đề; Hộp số là số nguyên ("0020" = 20); Hồ sơ số
  là số + tối đa 1 chữ cái (12, 12a; lưu hậu tố chữ thường, sắp 12 < 12a < 13); ngày QC-05 (chữ
  dd/mm/yyyy kể cả 00, hoặc ô ngày Excel); THBQ theo QC-13; giấy xấu `x` → hộp *đề xuất* giấy xấu
  (QC-07, Admin duyệt ở 07/10). Tối đa 5 MB / 10.000 hồ sơ; lỗi báo theo dòng Excel và cột.
- Xem trước rồi mới ghi (mã xem trước chống ghi đè khi dữ liệu đổi giữa hai bước). File còn lỗi thì
  không ghi gì. Chỉ các hộp có trong file bị ảnh hưởng: dòng bị bỏ → xóa nếu hộp chưa scan, giữ lại
  + gắn cờ nếu hộp đã scan (có PDF hoặc bước Scan đã rời "Chờ").
- Dự án tạo được khi chưa có PDF (nhập tên folder gốc). Hộp chưa có thư mục scan được tạo dạng
  "hộp chờ scan" (khóa `::muc-luc/hop-N`), chưa tự giao người nhập/kiểm tra.
- Cấp thư mục (QC-16): thư mục ở cấp `case_level` = Hộp (tên là số), cấp dưới = Hồ sơ, PDF nằm
  trong thư mục hồ sơ. Dự án có mục lục: upload sai cấp (PDF ngay trong thư mục cấp hồ sơ → cấp hồ sơ
  đang là HỒ SƠ; sâu hơn → có vẻ là PHÔNG; tên hộp không phải số; một hộp ở nhiều thư mục) bị từ chối
  cả lần tải; upload đúng thì thư mục hộp gắn vào hộp chờ scan cùng số. Import vào dự án đã có PDF
  sai cấu trúc cũng bị từ chối.
- Bước Chỉnh lý không tự "xong"; chỉ chặn Hoàn tất khi hộp chưa có mục lục. Chỉ Admin import (UC-04
  cho Hành chính để sau).

## Ghi chú cho các nhiệm vụ sau

- 05/10 so khớp (BR-01): so thư mục hồ sơ (cấp `case_level + 1`) với Hồ sơ số + hậu tố của mục lục
  theo giá trị (bỏ số 0 đầu, hậu tố không phân biệt hoa thường); `BIA.pdf` không là văn bản (QC-03).
  Xử lý các hồ sơ bị gắn cờ "không còn trong mục lục mới".
- 07/10: duyệt "giấy xấu" của hộp (đề xuất = có hồ sơ đánh `x` trong mục lục).

- 04/10 giao/thu hồi hộp (BR-06): Admin cần thấy các hộp đang nằm ở CTV **đã hết hạn** hoặc ở
  tài khoản **bị khóa** để thu hồi (`account_policy.access_block_message`).
- 04/10: hạn xử lý hộp tính theo **ngày lịch**, đủ `box_deadline_days × 24` giờ kể từ lúc giao
  (mặc định 48 giờ), không trừ cuối tuần/ngày lễ.
- KPI, check vòng 2, chi trả: kết quả đã tính phải **lưu kèm giá trị tham số tại thời điểm tính**
  (ngưỡng, tỷ lệ mẫu, hệ số), để đổi QC-01 hay chính sách dự án không làm đổi số liệu cũ.
- Đóng gói: mã cơ quan **bắt buộc** khi sinh mã hồ sơ (QC-03).
- 07/10 WorkLog/KPI (FR-KPI-01): thống kê nhân sự hiện bỏ qua tài khoản Admin
  (`personnel_statistics_repository`), nên sản lượng Admin tự nhập chưa được tính.

## Giao / thu hồi hộp nhập liệu (04/10, nhiệm vụ 4a, FR-ENT-01, BR-06, revision `0010_case_input_assignment`)

- Bảng `case_input_assignments`: theo dõi kỳ giao hộp cho người nhập (`assigned_at`, `due_at`, `deadline_days`,
  `ended_at`, `end_reason`). Index duy nhất một phần (`uq_case_input_assignments_active_case`) đảm bảo
  mỗi hộp tại một thời điểm chỉ có tối đa một phân công hiệu lực (`ended_at IS NULL`).
- Hạn xử lý hộp: `due_at = assigned_at + box_deadline_days × 24h` tính cố định tại thời điểm giao
  theo `get_effective_policy`; lưu kèm `deadline_days`. Đổi chính sách sau đó không làm đổi hạn đã giao.
- Phân biệt tự giao và "Hộp chờ giao nhập":
  + Dự án đã bật quy trình: không tự giao người nhập khi upload.
  + Tự giao khi upload chỉ áp dụng cho dự án chưa bật quy trình và hộp CHƯA TỪNG có dòng `case_input_assignments`
    nào (kể cả dòng đã đóng).
  + Khi người nhập bị gỡ khỏi dự án đã bật quy trình: hộp của họ về trạng thái chưa giao (`assigned_input_user_id = NULL`,
    đóng kỳ giao), hiện lại ở "Hộp chờ giao nhập", không tự chuyển cho người khác.
  + Cấu hình thành viên chuyển hộp: đóng dòng cũ (`end_reason='member_configuration'`), mở dòng mới với `due_at`
    tính lại từ lúc chuyển.
- Danh sách "Hộp chờ giao nhập":
  + Loại hộp chờ scan (`is_placeholder_box_key`) và hộp chưa có PDF.
  + Nếu `previous_enabled("data_entry", enabled)` là `None` (nhập liệu là bước đầu được bật) thì mọi hộp
    có PDF đều sẵn sàng. Nếu có bước trước thì bước đó phải ở trạng thái `done`.
  + Giao diện chọn người nhập tự động loại trừ người kiểm tra của chính hộp đó (BR-04).
- Đồng bộ tài liệu khi đổi người giữ hộp:
  + Mọi thao tác Giao hộp, Thu hồi / giao lại, và chuyển hộp ở Cấu hình thành viên đều gọi
    `project_workspace_service.sync_project_assets_to_documents` trong CÙNG transaction.
    Sau thu hồi để trống thì `assigned_documents.assigned_to_user_id = NULL`; giao mới thì nhận ID người mới.
- Hộp cần xử lý (FR-ENT-01, BR-06):
  + Quá hạn (`now > due_at` và chưa nộp xong), bị trả lại, hoặc người giữ là CTV bị khóa / hết hạn.
  + Định nghĩa "Nhập liệu xong": các báo cáo ở trạng thái `rejected`, `pending_review`,
    `pending_input_confirmation`, `completed` được coi là đã nộp; chỉ `draft` là chưa nộp. Hộp có ít nhất
    một văn bản chưa nộp (hoặc chưa có báo cáo nào) bị coi là chưa nộp xong.
  + Admin thu hồi có lý do (`overdue`, `rejected_too_much`, `member_unavailable`, `other`), có thể giao lại ngay
    hoặc để trống đưa về "Hộp chờ giao nhập".
- An toàn kiểm tra (R5, R6):
  + Cột `submissions.submitted_by_user_id`: ghi nhận người thực hiện chuyển draft/rejected -> pending_review
    (kể cả Admin). Lưu lại văn bản đã pending_review không ghi đè.
  + Reviewer không được duyệt báo cáo do chính mình tạo (`created_by_user_id`) hoặc nộp (`submitted_by_user_id`).
  + Các câu truy vấn SQL an toàn với NULL (`or_(col.is_(None), col != reviewer_id)`).

## Nộp S (04/10, nhiệm vụ 4b, FR-SCN-01, revision `0011_scan_packages`)

Code: `server/services/scan_ingestion_service.py`, `server/repositories/scan_repository.py`,
API trong `server/routers/projects.py`, bảng `case_scan_packages` / `case_scan_files` (`server/models_scan.py`,
migration `0011_scan_packages`), giao diện `frontend/js/project_scan_submit.js`.

1. **Điều kiện nộp và mã lỗi** (`POST /api/projects/{pid}/cases/{cid}/scan-packages`, body
   `{folder_path, scan_user_name_level=1}`; Admin hoặc thành viên bước Scan của dự án):
   - 403: không phải Admin. 422: body sai kiểu.
   - 404: dự án không tồn tại; hộp không tồn tại hoặc không thuộc dự án.
   - 400: `scan_user_name_level < 0`; thư mục không hợp lệ hoặc nằm ngoài `DOCUMENT_SOURCE_ROOT`.
   - 409: số hộp không khớp; thư mục (kể cả thư mục con) không có file nào (`{code: empty_folder, message}`); dự án chưa bật bước Scan; bước Scan đã `done`; bước `scan_qc` đã rời
     `pending`; hộp đang có gói `processing`; bước liền trước Scan (vd. Chỉnh lý nếu được bật)
     chưa xong (`{code: stage_blocked, message}` do `transition_case_stage` trả về).
   - Trạng thái Scan: chưa có dòng = `pending`. `pending`/`rejected` → chuyển START (ghi sự kiện);
     `in_progress` → chỉ thêm gói, không chuyển bước.
2. **Khớp số hộp**: số hộp của hộp = `box_number_of_case_key(case_key)` (thành phần cuối của
   khóa, hiểu cả `::muc-luc/hop-N`); nếu trả `None` mới lấy dãy số đầu tiên trong tên hiển thị. Số của thư mục = dãy số đầu tiên trong
   tên thư mục được chọn. So theo giá trị (`0020` = 20); thiếu số hoặc lệch → 409.
3. **Tên người scan và người phụ trách**:
   - Người scan không cần tài khoản. `scanned_by_name` = tên thư mục nằm `scan_user_name_level` cấp
     phía trên thư mục hộp (1 = thư mục cha; 0 = không lấy tên), lưu nguyên tên thư mục.
     Đường dẫn không đủ cấp → cờ `missing_scan_user`.
   - `scanned_by_user_id`: khi tên (bỏ dấu, đ→d, bỏ khoảng trắng/`_`/`-`, chữ thường) khớp
     `full_name` hoặc `username` của ĐÚNG MỘT thành viên bước Scan của dự án; không khớp → NULL.
   - Sau mỗi lần nộp, `assigned_user_id` của bước Scan được ghi đè bằng `scanned_by_user_id`
     (hoặc NULL), kể cả khi START vừa gán Admin bấm nút.
4. **Phiên bản gói**: mỗi lần nộp tạo gói mới, `version` = phiên bản lớn nhất của hộp + 1 (S1, S2,
   ...; khóa `with_for_update`; duy nhất theo (hộp, version)). Mỗi hộp tối đa MỘT gói `processing`:
   kiểm ở service (409) và bằng chỉ mục duy nhất có điều kiện `status = 'processing'` trong DB.
5. **Xử lý nền** (`process_scan_package_background`, chạy bằng BackgroundTasks):
   - Duyệt mọi file trong thư mục (đệ quy), ghi `total_files` và commit NGAY trước khi đọc file.
   - Lấy mẫu kích thước + mtime hai lần cách nhau 2,5 giây; file thay đổi → `incomplete`
     (cờ `incomplete_files`); file biến mất giữa hai lần → bỏ qua.
   - Không phải `.pdf` → `not_pdf` (cờ `non_pdf_files`), vẫn tính vào `processed_files`.
   - PDF đọc tuần tự bằng `pypdf` (`strict=False`); mã hóa, 0 trang hoặc đọc lỗi (vd. file cụt)
     → `error`, `page_count = -1`, `error_message` "Lỗi đọc PDF: ..." (cờ `error_files`), tính vào
     `failed_files`. Một file lỗi KHÔNG làm hỏng cả gói: gói vẫn `done`.
   - Tiến độ (`processed_files`, `failed_files`) commit sau mỗi file PDF và khi kết thúc.
   - Kết thúc: `done`, `finished_at`; cờ mới được GỘP với cờ đã có lúc nộp (không ghi đè).
   - Gói `failed` (kèm `error_message`, `finished_at`): thiếu thư viện `pypdf`, hoặc bất kỳ lỗi
     ngoài dự kiến; khi lỗi DB thì rollback, nạp lại gói rồi mới đánh `failed`, nên gói không kẹt
     `processing`.
   - Khởi động máy chủ (`run_startup_maintenance` trong `server/main.py`, khi DB đã migrate):
     `fail_stuck_processing_packages` chuyển mọi gói còn `processing` thành `failed`
     ("Hệ thống bị tắt đột ngột khi đang xử lý").
6. **QC-06**: khổ của TỪNG TRANG tính theo diện tích `MediaBox × UserUnit` (trang xoay 90/270 đổi
   chiều, diện tích không đổi), so với A5, A4, A3, A2, A1, A0; vượt khổ quá 10 % diện tích thì tính
   lên khổ kế tiếp, lớn hơn A0 tính A0; nhỏ hơn A5 tính A5. Quy đổi:
   `A4 quy đổi = A5×1 + A4×1 + A3×2 + A2×4 + A1×8 + A0×16`, cộng vào `total_pages` và
   `total_a4_equivalent` của gói.
7. **Giao diện** (Quy trình số hóa → tab Hồ sơ):
   - Nút "Nộp S" trong ô Scan khi: Scan đang `in_progress`, hoặc `pending`/`rejected` và
     `available !== false`; đồng thời `scan_qc` (nếu bật) còn `pending` (`scanSubmitCanSubmit`).
   - Hộp thoại chọn thư mục từ `GET /api/documents/server-folders` (vào thư mục con, lên cấp cha,
     "Chọn thư mục này"; KHÔNG có ô gõ đường dẫn); ô "Cấp thư mục tên người scan" mặc định 1, min 0.
   - Lỗi hiện nguyên văn `detail` (detail dạng `{code, message}` hiện `message`).
   - Luồng theo dõi nộp S (bất đồng bộ): Hộp thoại hiện sau khi tải xong danh sách thư mục và lịch sử gói; nếu hộp đang có gói `processing` thì tự theo dõi gói đó SAU khi hộp thoại đã hiện (không chặn giao diện; bản E3 từng đợi theo dõi xong mới hiện hộp thoại nên hộp thoại không mở được). Theo dõi hỏi `GET` cùng URL mỗi 2 giây tới khi gói hết `processing`; dừng khi đóng hộp thoại hoặc khi mở lại; mở lại không tạo hai bộ theo dõi. Hiện tiến độ (processed + failed)/total; khi xong hiện S{version}, tên người scan
     (hoặc "chưa có tên"), số trang, trang A4 quy đổi, thời gian (giờ Việt Nam), cảnh báo theo cờ và
     số file lỗi của gói `done`; gói `failed` hiện `error_message` màu đỏ. Danh sách S1, S2...
     của hộp; xong thì làm mới bảng quy trình.
8. **So khớp mục lục (BR-01)**:
   - Chạy tự động sau khi gói quét `done`. Kỳ vọng là các dòng mục lục chưa bị đánh dấu `missing_from_import_id` của hộp; thực tế là các đường dẫn PDF trong gói.
   - Trả về `match_status` (`matched`, `mismatch`, hoặc `no_catalog` nếu hoàn toàn không có mục lục) và `match_summary` (được lưu vào gói, GET API trả về kèm).
   - Lỗi khi so khớp không làm hỏng gói mà gán cờ `catalog_match_error` và `match_status = NULL`.
- Việc 05/10: chặn người duyệt Check scan có tên khớp `scanned_by_name`; so khớp thư mục hồ sơ
  với mục lục (BR-01).
- Check scan cho ngày 10/10 (phương án a): người check kiểm ngoài hệ thống trước khi đưa lên máy chủ;
  hệ thống chỉ tự so khớp thư mục (BR-01) và người check bấm "Duyệt". Phương án (b) mở từng file
  trong hệ thống để sau 10/10. Khác BA v1.0.
- **Check nhập hộp (BR-07)**:
  + Chặn các bước tiếp theo (Chuẩn hóa, Bàn giao) nếu tỷ lệ trường lỗi của toàn hộp vượt ngưỡng cho phép.
  + "Trả lại cả hộp": hệ thống không tự đổi trạng thái của các báo cáo thành `rejected`, mà chỉ ĐÁNH DẤU hộp vượt ngưỡng. Admin sẽ quyết định "Duyệt" kèm lý do để cho phép hộp đi tiếp.

## Sheet "Chấm công theo ngày" trong file Excel xuất (07/10, T1, WorkLog/KPI)

Code: `server/services/timesheet_service.py`, `server/repositories/timesheet_repository.py`,
`_append_timesheet_sheet` trong `server/services/excel_service.py`. Không thêm bảng, không migration.

- Mọi file Excel xuất (`GET /api/export`, xuất nền theo biểu mẫu và theo dự án trong
  `server/export_worker.py`) có thêm sheet cuối "Chấm công theo ngày"; sheet dữ liệu và sheet
  đang mở giữ nguyên. Trùng tên sheet có sẵn trong mẫu thì đặt "Chấm công theo ngày (2)".
- Cột: Ngày (dd/mm/yyyy, giờ Việt Nam) | Họ và tên (họ tên, trống thì tên đăng nhập) |
  Số hàng đã nhập | Số hàng đã duyệt. Mỗi dòng là một người trong một ngày; sắp theo ngày rồi tên.
- Chỉ tính trên đúng các báo cáo có trong file xuất. Cách đếm giống bảng Thống kê nhân sự:
  + Đã nhập: người = `input_user_id` của baseline chất lượng (không có thì `created_by_user_id`);
    ngày = lúc tạo baseline, tức lần nộp kiểm tra đầu tiên (không có thì `created_at` của hồ sơ).
  + Đã duyệt: lần `review_confirmed` đầu tiên của hồ sơ; người = `reviewer_user_id`; ngày = lúc duyệt.
    Duyệt lại lần sau và `input_confirmed` không được tính.
- Sheet có tên người và năng suất nội bộ: file xuất gửi khách hàng thì xóa sheet này trước khi gửi.

## Việc của Hành chính (C3, 07/10)
- GET /api/workflow/my-projects: dự án có ít nhất 1 bước đang bật mà người dùng là thành viên bước (project_stage_members, is_active) hoặc reviewer (project_members). Trả {project_id, name, stages, is_reviewer}. CTV luôn nhận [] (loại tài khoản đọc từ DB).
- GET /api/projects/{pid}/workflow/my-work: hộp người dùng làm được ngay ở Chỉnh lý/Scan/Check scan (chờ hoặc bị trả lại và chưa ai nhận; đang làm do chính mình hoặc chưa có người phụ trách), cộng mục entry_qc cho reviewer khi hộp đã nhập xong và cổng Check nhập đang chặn (kèm gate_code).
- Nộp S và xem gói scan: Admin hoặc thành viên bước Scan của dự án (xem gói: thêm thành viên Check scan). Chọn thư mục (GET /api/documents/server-folders): Admin hoặc thành viên bước Scan ở ít nhất 1 dự án.
- Chuyển bước và BR-04 dùng luật cũ (_require_stage_worker). Duyệt Check scan khi lệch mục lục và duyệt hộp vượt ngưỡng Check nhập vẫn chỉ Admin.
- Giao diện: tab "Việc của tôi" ở index.html (js/my_work.js). Người không có quyền nhập/kiểm tra: auth.js configureCapabilityUI gọi applyMyWorkVisibility() để hiện lại thanh tab và mở tab này.

## Bìa hồ sơ dùng chung theo thư mục (08/10, F1)

Biểu mẫu mẫu: `docs/standards/Mau_Ho_So_Van_Ban.xlsx` (nhóm "Thông tin hồ sơ (Bìa)": Tiêu đề hồ sơ,
Thời gian bắt đầu, Thời gian kết thúc, Số tờ; nhóm "Thông tin văn bản": Tên cơ quan, tổ chức ban hành
văn bản, Số, Ký hiệu, Ngày ký, Thể loại văn bản, Trích yếu nội dung, Người ký). Danh mục thể loại
QC-14 để dán vào "Kho Từ điển > Thêm hàng loạt": `docs/standards/Tu_dien_The_loai_van_ban.txt`.

- Cấu hình biểu mẫu: tick "Bìa" cho các cột bìa, "Cấp thư mục đồng bộ Bìa" = 1 (thư mục chứa PDF là
  một hồ sơ); cột Thể loại gán từ điển, chế độ "Mã (Bên phải)" để lưu tên đầy đủ ("Quyết định").
- Thư mục dùng chung bìa: `cover_scope_folder(folder_path, cover_folder_level)` ở
  `server/services/submission_service.py`, `getCoverScope` ở `frontend/js/form_renderer.js` (cùng quy tắc:
  cấp 1 là thư mục chứa PDF, cấp 2 là thư mục cha).
- Khi mở PDF: cùng thư mục với file trước thì giữ bìa; sang thư mục khác thì xóa bìa cũ và gọi
  `GET /api/cover-data?template_id=&folder_path=` (chỉ đọc; người nhập chỉ đọc hồ sơ của mình, Admin đọc
  tất cả) để điền bìa đã lưu gần nhất của thư mục. Chỉ điền ô còn trống; câu trả lời đến muộn sau khi
  đã chuyển thư mục thì bỏ. Lỗi mạng thì im lặng, người nhập gõ tay.
- Lưu hồ sơ mới: chỉ hỏi "cập nhật bìa cho các báo cáo cùng thư mục" khi bìa khác bìa đã lưu của
  thư mục; thư mục chưa có hồ sơ nào thì không hỏi. Đồng ý thì `sync_cover_data` ghi bìa mới vào mọi
  hồ sơ của biểu mẫu trong cùng thư mục (kể cả thư mục con).
- Biểu mẫu từ 30 trường trở xuống mở sẵn mọi nhóm; biểu mẫu lớn hơn chỉ mở nhóm đầu như cũ.

## Chuẩn hóa: kế hoạch đổi tên (08/10, G1)

Code: `server/services/normalization_plan_service.py`, `server/repositories/normalization_repository.py`,
`GET /api/projects/{pid}/normalization-plan[?format=json]` (chỉ Admin, chỉ đọc), menu dự án
"Kế hoạch chuẩn hóa (Excel)" (`downloadNormalizationPlan` trong `frontend/js/project_reports.js`).

- Nguồn: file nhập liệu đang dùng (`project_document_assets.status = active`), mục lục (dòng chưa bị
  đánh `missing_from_import_id`), Chính sách dự án (Mã cơ quan, Ký hiệu hồ sơ).
- Cấu trúc bắt buộc: `<Hộp>/<Hồ sơ>/file.pdf` tính từ cấp hộp. Thư mục hồ sơ đọc số bằng
  `parse_dossier_number` (như so khớp BR-01), tra mục lục theo hộp + số hồ sơ + hậu tố.
- Mã hồ sơ (QC-03): `{Mã cơ quan}.{Năm bắt đầu}.{Số HS 2 chữ số}{hậu tố}[.{Ký hiệu}]`; ký hiệu lấy
  ở mục lục, không có thì lấy Chính sách dự án. Mã văn bản = mã hồ sơ + `.{STT 7 chữ số}`, STT theo
  thứ tự tự nhiên tên file (QC-12), bỏ qua file bìa.
- Đường dẫn bàn giao (QC-04): `CSDL_SOHOA_<tên dự án không dấu>/<Mã cơ quan>/<Năm>/<VV|LD>/<Mã phông
  không dấu>/<Mã hồ sơ>/<Mã văn bản>.pdf`; file bìa `<Mã hồ sơ>_BIA.pdf` trong thư mục hồ sơ.
- Giả định của reviewer (QC-01 chưa nói, sửa được): gốc lấy theo tên dự án; tên file bìa; hậu tố chữ
  của hồ sơ đặt ngay sau số; viết tắt THBQ chỉ có `01 → VV`, `02 → LD` (QC-13).
- Excel 2 sheet: "Tổng hợp" (mã cơ quan, gốc, số hồ sơ/văn bản/bìa, số file sẵn sàng, đếm từng vấn
  đề) và "Kế hoạch đổi tên" (mỗi file một dòng; cột Vấn đề tô màu). Vấn đề: chưa có Mã cơ quan;
  file không nằm đúng `<Hộp>/<Hồ sơ>/`; tên thư mục không đọc được số; hồ sơ không có trong mục lục;
  THBQ ngoài QC-13; văn bản chưa "Hoàn thành" nhập liệu (trạng thái của lần lưu mới nhất).
- PDF/A và ký số làm ngoài hệ thống (BA); file đã ký thêm hậu tố `_signed` (QC-04) do công cụ ký tạo.

## Đóng gói bàn giao (08/10, G2)

Code: `server/services/handover_package_service.py`; `POST/GET /api/projects/{pid}/handover-package`
(chỉ Admin); menu dự án "Đóng gói bàn giao" (`startHandoverPackage` trong `frontend/js/project_reports.js`,
hỏi tiến độ mỗi 3 giây). Biến `HANDOVER_DIR` (mặc định thư mục `handover` cạnh `PDF_STORAGE_PATH`).

- Hồ sơ được đóng gói khi MỌI file trong thư mục hồ sơ không còn vấn đề ở kế hoạch G1 và mã hồ sơ
  không trùng thư mục khác (ví dụ `012` và `0012` cùng ra một mã thì bỏ cả hai). Không có hồ sơ nào
  sẵn sàng thì `409`.
- Chạy nền trong máy chủ (luồng riêng). Khóa `HANDOVER_DIR/_jobs/project_<id>.lock` (tạo độc quyền,
  ghi PID): đang chạy thì `409`; PID đã chết thì lấy lại khóa. Trạng thái
  `_jobs/project_<id>.json` (queued/running/done/error, số file đã xử lý, thông báo). Khởi động máy
  chủ: lần đóng gói của tiến trình đã chết chuyển `error`, nhả khóa.
- Chép từ kho PDF sang `HANDOVER_DIR/<đường dẫn bàn giao G1>` qua file tạm `.part`; SHA-256 phải
  khớp `content_sha256` lúc tải lên, sai thì không đặt file và cả hồ sơ không vào metadata. Chạy lại:
  file đích đã đúng dung lượng và SHA-256 thì bỏ qua. File thừa của lần đóng gói cũ không bị xóa.
- Kết quả trong `HANDOVER_DIR/<gốc>/`:
  + `Metadata_NN-SIP.xlsx`: sheet `Metadata_HS` (18 trường chuẩn + Tệp tin hồ sơ, Mục lục số, Hộp số,
    Hồ sơ số, Tên phông, Mã phông, Giai đoạn/Nhiệm kỳ, Path) và `MetadataVB` (fileCode + 21 trường
    chuẩn + các trường bổ sung + Người ký, File gốc). Tên trường lấy theo
    `2026-10-04-sample-files-analysis.md`; công cụ SIP cần tên khác thì sửa `HS_FIELDS`/`VB_FIELDS`.
  + Hồ sơ: tiêu đề, THBQ, thời gian, số tờ, ghi chú lấy từ MỤC LỤC (QC-01); mode `01`, language `01`,
    confidenceLevel `02`, format `Bình thường`; totalDoc = số văn bản (không tính bìa); numberOfPage =
    tổng số trang PDF (đếm bằng pypdf, kể cả bìa).
  + Văn bản: docId = STT, docCode = mã văn bản; typeName, codeNumber, codeNotation, issuedDate,
    organName, subject, Người ký... lấy từ lần lưu mới nhất, dò cột theo NHÃN của biểu mẫu
    (`VB_LABEL_ALIASES`, so nguyên nhãn không dấu); làm sạch QC-15 (gộp khoảng trắng, NFC); tên loại
    và cơ quan ban hành IN HOA.
  + `SHA256SUMS.txt` (đường dẫn tính từ thư mục gốc, kiểm bằng `sha256sum -c`).
  + `Nhat_ky_dong_goi.xlsx`: Đã đóng gói (SHA-256, dung lượng, số trang, Đã chép/Đã có sẵn), Chưa
    đóng gói (lý do), Lỗi chép file.
- Hồ sơ xuất DANG-HD40 chưa hỗ trợ: gói luôn theo NN-SIP.

## Biên bản bàn giao (08/10, G3)

Code: `handover_report` trong `server/services/handover_package_service.py`, bộ ghi Word tối giản
`server/services/docx_writer.py` (không thêm thư viện; .docx = zip các tệp XML, A4, Times New Roman);
`GET /api/projects/{pid}/handover-package/report` (chỉ Admin; 404 khi chưa có lần đóng gói xong hoặc
file đã bị xóa); menu dự án "Tải biên bản bàn giao".

- Mỗi lần đóng gói xong ghi `Bien_ban_ban_giao.docx` vào thư mục gói: quốc hiệu, ngày (giờ Việt Nam),
  dự án, mã cơ quan, dòng trống Bên giao/Bên nhận; bảng số liệu (thư mục gói, số hồ sơ, số văn bản,
  tổng số trang kể cả bìa, dung lượng, SHA-256 của `SHA256SUMS.txt` = mã kiểm tra toàn gói, SHA-256
  của `Metadata_NN-SIP.xlsx`); số hồ sơ chưa đóng gói (chưa sẵn sàng + lỗi chép); danh sách hồ sơ
  (mã, tiêu đề mục lục, số văn bản, số trang); chỗ ký hai bên.
- Chưa làm (sau 10/10): khóa dự án sau bàn giao. Cần chặn mọi đường sửa hồ sơ (lưu, sửa, kiểm tra,
  đồng bộ bìa, xóa, thao tác hàng loạt) của văn bản đã đóng gói, nên không làm gấp trước chạy thật.

## Sổ giao nhận hồ sơ giấy (H1, FR-ARR-02, revision 0016)

Theo dõi 5 mốc giao nhận hồ sơ giấy của hộp (nhận từ khách, giao chỉnh lý, giao scan, trả kho, trả khách).
Người dùng là admin hoặc nhân viên thuộc tổ chỉnh lý, scan. Mỗi mốc ghi nhận thời gian, người giao, người nhận, ghi chú.
Dữ liệu lưu ở bảng `case_paper_handoffs` (revision 0016_case_paper_handoffs). Có thể xuất báo cáo Excel cho toàn dự án.

## Việc sau 10/10

- Luồng cũ (giao tài liệu lẻ, nhập thư mục máy chủ) vẫn chỉ nhận tài khoản thường làm người nhập;
  cân nhắc mở cho Admin theo BA 3.3 (đã chốt giữ nguyên trước khi chạy thật).
- Check scan phương án (b): hiển thị và mở từng file PDF trên web.
- Chấm công KPI scan theo chuỗi tên người scan (`scanned_by_name`).
- Nộp S: mở lại hộp thoại khi gói của hộp đang `processing` thì chưa tự hỏi tiến độ lại
  (chỉ hiện trong danh sách các lần nộp).
- Khóa dự án/hồ sơ sau khi ký biên bản bàn giao (G3 mới có biên bản, chưa khóa sửa).
- Bìa (như hệ thống mẫu): khung bìa riêng có nút "Lưu" bìa; Số tờ để trống thì tự cộng số tờ các
  văn bản đã lưu (cần biểu mẫu có cột số tờ của văn bản).

## Lộ trình (BA mục 12.2)

| Ngày | Việc |
|---|---|
| 02/10 | Xuất BA; rà Phase 0 theo BA; sửa lỗi frontend thiếu hàm (`auth.js`) |
| 03/10 | Tài khoản CTV có hạn, cấu hình Project/WorkType/chính sách, import mục lục |
| 04/10 | Giao nhận hồ sơ giấy, giao/thu hồi hộp (hạn 2 ngày), Nộp S |
| 05/10 | So khớp đường dẫn, Check scan (mở từng file, rework, S/CS) |
| 06/10 | Check nhập 1 và 2 (mẫu 30%), làm sạch, thông báo |
| 07/10 | WorkLog/KPI, PDF/A, ký số (xuất/nạp lại), đóng gói |
| 08/10 | Đối soát R1–R4, dashboard, nghiệm thu, test tải, test khôi phục |
| 09/10 | Chạy thử 1–2 hộp với vài CTV |
| 10/10 | Duy Vũ nghiệm thu, chạy thật |

Thứ tự cắt khi trễ: chi trả CTV → dashboard → đối soát R1/R3/R4 → nghiệm thu.

## Nhật ký sửa lỗi

- 08/10 (F2): `apiCall` giữ kết quả GET của `/api/templates…` và `/api/users…` 5 giây, kể cả ngay
  sau lệnh ghi. Hậu quả: tạo từ điển xong không thấy trong "Kho Từ điển"; tải biểu mẫu xong danh
  sách chưa có; mở lại "Cấu hình Biểu mẫu" ngay sau khi lưu thấy cấu hình cũ (lưu tiếp sẽ ghi đè).
  Sửa: mọi lệnh ghi qua `apiCall` (POST/PUT/DELETE, kể cả lỗi) xóa toàn bộ bộ nhớ đệm;
  `auth.js?v=102.05`, selfcheck `tests/api_cache_selfcheck.js`. Phát hiện khi chạy lại kịch bản
  cấu hình từ điển trên PostgreSQL.
- 02/10: Commit `204140b` đã tách 10 hàm khỏi `frontend/auth.js` sang `js/account_management.js`
  và `js/admin_dashboard.js`, nhưng không trang nào nạp hai file này. Hậu quả: trang nhập liệu
  báo `populateTemplateDropdown is not defined` (không chọn được biểu mẫu), trang admin mất
  Nhân sự/sửa user/đổi mật khẩu. Đã khôi phục `auth.js` về bản chạy được (`0f2fd76`, đúng như
  self-check mong đợi), xóa hai bản sao không dùng, nâng `auth.js?v=102.01`.
