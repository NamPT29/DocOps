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

## Ghi chú cho các nhiệm vụ sau

- 04/10 giao/thu hồi hộp (BR-06): Admin cần thấy các hộp đang nằm ở CTV **đã hết hạn** để thu hồi
  (`account_policy.is_expired`).
- Chưa có chức năng **khóa tài khoản**. Muốn cắt quyền ngay hiện chỉ có "Giải phóng phiên" + đổi
  mật khẩu (hạn CTV không đặt được ở quá khứ, nên không dùng hạn để khóa ngay).

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
