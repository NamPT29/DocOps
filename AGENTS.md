# Hướng dẫn cho AI agent (Claude Code, Antigravity, ...)

Dự án DocOps: hệ thống số hóa tài liệu lưu trữ (đồ án "Hệ thống số hóa tài liệu tích hợp AI"),
chạy thật cho Duy Vũ ngày 10/10/2026. Quy trình: chỉnh lý → scan → check scan → nhập liệu →
check nhập liệu → chuẩn hóa → bàn giao.

## Đọc trước khi làm
1. `docs/plans/2026-10-01-digitization-pipeline-design.md`: thiết kế, quyết định đã chốt, lộ trình, việc sau 10/10.
2. `docs/standards/QC-01_quy_chuan_mac_dinh.md`: giá trị mặc định nghiệp vụ (mã QC-xx).
3. `docs/plans/2026-10-04-sample-files-analysis.md`: phân tích công cụ và dữ liệu mẫu.
4. `git log -8 --stat`: các nhiệm vụ gần nhất.

## Quy trình làm việc
- Chỉ làm trên nhánh `claude/charming-planck-b2k42f`. Không tạo PR, không force push, không sửa lịch sử đã push.
- Mỗi nhiệm vụ chia thành các LÁT nhỏ ghi ở docs/plans/STATUS.md. Mỗi lát: sửa -> `python scripts/gate.py` phải in "KẾT QUẢ CỔNG: ĐẠT" -> commit -> push.
- Phiên mới: git pull, đọc AGENTS.md và docs/plans/STATUS.md, làm lát kế tiếp; không đọc lại cả repo; chỉ sửa các file nêu trong lát; mở chat mới cho mỗi lát.
- Báo cáo cuối lát: dán nguyên đầu ra của gate.py. Không ghi "pass"/"xong" nếu chưa có dòng "KẾT QUẢ CỔNG: ĐẠT".
- Lúc làm chỉ chạy test mục tiêu; gate đầy đủ ở cuối lát.
- Test luôn dùng SQLite tạm; cấm create_all/drop_all trên engine toàn cục; cấm ghi file vào thư mục repo (dùng tmp_path).
- Sắp hết quota: commit và push phần đã xong, cập nhật STATUS.md trước khi dừng.
- docs/ nằm trong .gitignore: file MỚI trong docs/ phải `git add -f`.
- Chỗ nghiệp vụ chưa rõ: hỏi người dùng, không tự đoán. Giá trị mặc định lấy theo QC-01, cấu hình được theo dự án.
- Sau mỗi nhiệm vụ: chỉ người dùng các bước bấm trên web để kiểm tra.

## Test (bắt buộc pass trước khi commit)
```
python scripts/gate.py           # đầy đủ
python scripts/gate.py --static  # nhanh
```

## Ràng buộc kỹ thuật
- Router/service không gọi `.query(`; repository không `commit`/`rollback` (có test bảo vệ).
- Schema `0001` đóng băng. Bảng/cột mới gắn `info={"revision": ...}`; mỗi migration mới nâng `HEAD_REVISION`;
  migration không import `server.*`; chạy được cả SQLite và PostgreSQL.
- Frontend: JS thuần, tuân thủ CSP (không inline script/handler; dùng `data-admin-action` / `data-admin-change`;
  hiển thị bằng `textContent`). Sửa file JS thì nâng `?v=` trong HTML.
- `users.role` là cờ quyền (`admin`/`user`); loại tài khoản ở `users.account_type` (`staff`/`ctv`).
- Chính sách dự án đọc qua `project_policy_service.get_effective_policy(db, project_id=...)`.
  Kết quả tính toán (chi trả, đạt/trả lại) phải lưu kèm giá trị tham số đã dùng.

## Dữ liệu
- Dữ liệu khách hàng là nhạy cảm. Không commit, không gửi lên dịch vụ ngoài.
  Dữ liệu mẫu thật để ở `samples_local/`, thư mục này đã loại khỏi Git.
- Không chép thông tin cá nhân (SĐT, CCCD, số tài khoản) vào code, test hay tài liệu.
