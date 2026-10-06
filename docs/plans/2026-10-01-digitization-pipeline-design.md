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
   `{folder_path, scan_user_name_level=1}`; chỉ Admin):
   - 403: không phải Admin. 422: body sai kiểu.
   - 404: dự án không tồn tại; hộp không tồn tại hoặc không thuộc dự án.
   - 400: `scan_user_name_level < 0`; thư mục không hợp lệ hoặc nằm ngoài `DOCUMENT_SOURCE_ROOT`.
   - 409: số hộp không khớp; dự án chưa bật bước Scan; bước Scan đã `done`; bước `scan_qc` đã rời
     `pending`; hộp đang có gói `processing`; bước liền trước Scan (vd. Chỉnh lý nếu được bật)
     chưa xong (`{code: stage_blocked, message}` do `transition_case_stage` trả về).
   - Trạng thái Scan: chưa có dòng = `pending`. `pending`/`rejected` → chuyển START (ghi sự kiện);
     `in_progress` → chỉ thêm gói, không chuyển bước.
2. **Khớp số hộp**: số hộp của hộp = N trong khóa `::muc-luc/hop-N` (hộp chờ scan), nếu không thì
   dãy số ĐẦU TIÊN trong `case_key`, rồi trong tên hiển thị. Số của thư mục = dãy số đầu tiên trong
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
   - Sau khi nộp: hỏi `GET` cùng URL mỗi 2 giây tới khi gói hết `processing`; dừng khi đóng hộp
     thoại. Hiện tiến độ (processed + failed)/total; khi xong hiện S{version}, tên người scan
     (hoặc "chưa có tên"), số trang, trang A4 quy đổi, thời gian (giờ Việt Nam), cảnh báo theo cờ và
     số file lỗi của gói `done`; gói `failed` hiện `error_message` màu đỏ. Danh sách S1, S2...
     của hộp; xong thì làm mới bảng quy trình.
- Việc 05/10: chặn người duyệt Check scan có tên khớp `scanned_by_name`; so khớp thư mục hồ sơ
  với mục lục (BR-01).
- Check scan cho ngày 10/10 (phương án a): người check kiểm ngoài hệ thống trước khi đưa lên máy chủ;
  hệ thống chỉ tự so khớp thư mục (BR-01) và người check bấm "Duyệt". Phương án (b) mở từng file
  trong hệ thống để sau 10/10. Khác BA v1.0.

## Việc sau 10/10

- Luồng cũ (giao tài liệu lẻ, nhập thư mục máy chủ) vẫn chỉ nhận tài khoản thường làm người nhập;
  cân nhắc mở cho Admin theo BA 3.3 (đã chốt giữ nguyên trước khi chạy thật).
- FR-ARR-02: Theo dõi 5 mốc giao nhận hồ sơ giấy (nhận từ khách, giao chỉnh lý, giao scan, trả kho, trả khách).
- Check scan phương án (b): hiển thị và mở từng file PDF trên web.
- Chấm công KPI scan theo chuỗi tên người scan (`scanned_by_name`).
- Nộp S: thư mục rỗng hiện vẫn được nhận (gói `done` với 0 file); cần chặn hoặc cảnh báo.
- Nộp S: mở lại hộp thoại khi gói của hộp đang `processing` thì chưa tự hỏi tiến độ lại
  (chỉ hiện trong danh sách các lần nộp).

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

- 02/10: Commit `204140b` đã tách 10 hàm khỏi `frontend/auth.js` sang `js/account_management.js`
  và `js/admin_dashboard.js`, nhưng không trang nào nạp hai file này. Hậu quả: trang nhập liệu
  báo `populateTemplateDropdown is not defined` (không chọn được biểu mẫu), trang admin mất
  Nhân sự/sửa user/đổi mật khẩu. Đã khôi phục `auth.js` về bản chạy được (`0f2fd76`, đúng như
  self-check mong đợi), xóa hai bản sao không dùng, nâng `auth.js?v=102.01`.
