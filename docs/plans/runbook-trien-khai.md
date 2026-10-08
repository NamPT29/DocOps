# Hướng dẫn triển khai bản mới lên máy chủ (R1)

Áp dụng cho máy chủ chạy từ mã nguồn bằng `host_server.bat` (Windows, PostgreSQL, Caddy).
Viết theo mã thật: `host_server.bat`, `host_console.py`, `server/settings.py`,
`server/migration_runner.py`, `scripts/migrate_database.py`, `scripts/preflight.py`.
Không ghi giá trị thật (mật khẩu, đường dẫn khách hàng) vào tài liệu này.

**Điều quan trọng nhất:** `host_console.py` TỰ ÁP MIGRATION mỗi lần khởi động
(`upgrade_database(..., adopt_existing=True)`). Vì vậy phải sao lưu CSDL (bước 2)
TRƯỚC khi khởi động bản mới lần đầu. Không có bước "chạy thử mà chưa đổi CSDL".

## 1. Chuẩn bị máy

1. Dừng bản đang chạy: đóng cửa sổ "SỐ HÓA • HOST SERVER" (hoặc Ctrl+C trong cửa sổ đó).
   Không để người dùng thao tác trong lúc triển khai.
2. Lấy mã mới về thư mục dự án (git pull đúng nhánh/commit được bàn giao). Ghi lại mã commit
   cũ để quay lại nếu cần: `git rev-parse HEAD` trước khi pull.
3. Cài thư viện: `pip install -r requirements.txt`. Bản mới cần thêm `pypdf`
   (đọc khổ giấy, số trang khi Nộp S). Thiếu `pypdf` thì mọi gói scan chuyển sang lỗi
   "Thư viện pypdf chưa được cài đặt.".
4. Kiểm file `.env` ở thư mục dự án (biến môi trường của Windows thắng `.env`). Các biến cần có:

   | Biến | Ghi chú |
   |---|---|
   | `DATABASE_URL` | Dạng `postgresql+psycopg://<user>:<mật khẩu>@<máy>:5432/<tên CSDL>` |
   | `SECRET_KEY` | Tối thiểu 32 byte, giữ cố định giữa các lần khởi động |
   | `DOCUMENT_SOURCE_ROOT` | Thư mục gốc chứa thư mục scan; Nộp S chỉ nhận thư mục nằm bên trong |
   | `PORT` | `host_console.py` mặc định 80. Caddy (cổng 80) chuyển tiếp tới `127.0.0.1:8000`, nên khi chạy qua Caddy đặt `PORT=8000` |
   | `HOST` | Mặc định `0.0.0.0`. Khi chỉ cho truy cập qua Caddy có thể đặt `127.0.0.1` |
   | `APP_ENV` | `production` cho chạy thật. Khi đó bắt buộc thêm `PDF_STORAGE_PATH`, `TEMPLATE_STORAGE_PATH`, `EXPORT_WORK_DIR`, và nếu đặt `REDIS_URL` thì phải là `rediss://` |
   | `PUBLIC_HOSTNAME` | Tên miền cho Caddy (xem `Caddyfile`) |
   | `HANDOVER_DIR` | Thư mục nhận gói bàn giao (Đóng gói, G2). Không đặt thì dùng thư mục `handover` cạnh `PDF_STORAGE_PATH`. Cần chỗ trống bằng dung lượng PDF của dự án; nên trỏ sang ổ dữ liệu lớn |

## 2. Sao lưu PostgreSQL (bắt buộc, trước khi khởi động bản mới)

Lưu file sao lưu NGOÀI thư mục dự án (không để trong repo), ví dụ ổ dữ liệu riêng.

```bat
pg_dump -F c -h 127.0.0.1 -U <user> -d <tên CSDL> -f <thư mục sao lưu>\docops_<YYYYMMDD_HHMM>.dump
```

Kiểm file sao lưu đọc được và ghi lại trạng thái hiện tại:

```bat
pg_restore -l <file .dump> | more
psql -h 127.0.0.1 -U <user> -d <tên CSDL> -c "\dt"
psql -h 127.0.0.1 -U <user> -d <tên CSDL> -c "select version_num from alembic_version"
```

Ghi lại `version_num` hiện tại (ví dụ `0010_case_input_assignment`) vào sổ triển khai.

## 3. Chạy kiểm tra trước (preflight)

```bat
python scripts/preflight.py
```

Chỉ đọc, không sửa gì, không in mật khẩu. Dòng cuối phải là `KẾT QUẢ PREFLIGHT: ĐẠT`.

| Dòng | Xử lý |
|---|---|
| `[LỖI] pypdf` | Chạy lại `pip install -r requirements.txt` |
| `[LỖI] DATABASE_URL` / `[LỖI] Kết nối CSDL` | Kiểm dịch vụ PostgreSQL và `DATABASE_URL` trong `.env` |
| `[LỖI] SECRET_KEY` | Đặt khóa ≥ 32 byte (không đổi khóa đang dùng nếu đã có) |
| `[LỖI] DOCUMENT_SOURCE_ROOT` | Tạo thư mục hoặc sửa đường dẫn; tài khoản chạy dịch vụ phải đọc được |
| `[CẢNH BÁO] Migration: đang ở …` | Bình thường khi lên bản mới: bản mới sẽ tự nâng CSDL khi khởi động. Chỉ tiếp tục khi đã có file sao lưu ở bước 2 |
| `[LỖI] Migration: revision lạ …` | CSDL thuộc bản mã mới hơn mã đang có. Dừng lại, kiểm commit đã pull |
| `[CẢNH BÁO] Cổng: … đang có chương trình khác` | Bản cũ còn chạy, hoặc `PORT` trùng cổng của Caddy (80) |
| `[CẢNH BÁO] Dung lượng trống` | Ổ chứa tài liệu còn dưới 5 GB; dọn trước khi nhận scan |

## 4. Nâng CSDL

Hai cách, chọn một:

- **Tự động:** khởi động ở bước 5; cửa sổ host in dòng
  `Database migration: <cũ> -> 0015_entry_qc_round2` (hoặc revision mới nhất của bản bàn giao).
- **Chạy riêng để xem kết quả trước:** `python scripts/migrate_database.py`. In ra
  `Database upgraded: <cũ> -> <mới>`.

Nếu thấy `KHÔNG THỂ MIGRATE DATABASE` thì dừng, không thử lại nhiều lần, chuyển sang bước 7.

Kiểm sau khi nâng: chạy lại `python scripts/preflight.py`, dòng `Migration` phải là `[ĐẠT]`.
Hoặc trong psql: `select version_num from alembic_version` và `\dt` phải thấy thêm
`case_scan_packages`, `case_scan_files`, `case_entry_qc_results`, `case_entry_qc_samplings`,
`case_entry_qc_sample_items`.

## 5. Khởi động

Chạy `host_server.bat` ở thư mục dự án. Tệp này:
1. kiểm kết nối PostgreSQL theo `DATABASE_URL`;
2. bật Caddy ở cổng 80 nếu chưa chạy;
3. chạy `host_console.py` (tự áp migration, rồi khởi động máy chủ ứng dụng).

Không đóng cửa sổ host trong suốt thời gian làm việc.

## 6. Kiểm tra sau triển khai (khoảng 10 phút)

Dùng một **dự án thử** để không lẫn dữ liệu thật.

1. Mở trang đăng nhập qua Caddy, đăng nhập Admin.
2. Mở dự án thử → Quy trình số hóa: tab Tổng quan và Hồ sơ hiện đủ các bước đã bật.
3. Một hộp thử đã qua Chỉnh lý: bấm **Nộp S**, chọn thư mục của hộp (nằm trong
   `DOCUMENT_SOURCE_ROOT`), gửi. Gói phải chuyển từ "Đang xử lý" sang "Xong", có số trang
   và quy đổi A4.
4. Bấm **Xem so khớp** ở ô Check scan: thấy kết quả so khớp với mục lục.
5. Đăng nhập một tài khoản CTV thử ở trình duyệt khác: vào được trang nhập liệu.
6. Xem cửa sổ host không có dòng lỗi đỏ.

## 7. Quay lại bản cũ khi lỗi

CSDL đã nâng thì mã cũ KHÔNG chạy được nữa (mã cũ không biết revision mới), nên phải
khôi phục cả CSDL lẫn mã.

1. Dừng máy chủ (đóng cửa sổ host).
2. Khôi phục CSDL từ file sao lưu bước 2:
   ```bat
   pg_restore --clean --if-exists -h 127.0.0.1 -U <user> -d <tên CSDL> <file .dump>
   ```
3. Đưa mã về commit cũ đã ghi ở bước 1: `git checkout <mã commit cũ>`.
4. Chạy `python scripts/preflight.py`: dòng `Migration` phải `[ĐẠT]` với revision cũ.
5. Khởi động lại bằng `host_server.bat`, kiểm như bước 6.
6. Ghi lại lỗi gặp phải (ảnh chụp cửa sổ host, thời điểm) gửi người phụ trách kỹ thuật.

## Đã kiểm trên PostgreSQL thật

07/10/2026, PostgreSQL 16, mã tại commit `53ddb4f` (head `0015_entry_qc_round2`):
- Hạ từ `0015_entry_qc_round2` về `0010_case_input_assignment` rồi nâng lại `head`: thành công.
- Mọi bảng/cột trong model khớp CSDL sau khi nâng (0 khác biệt); có cột
  `project_policies.entry_qc_round2_enabled`, ràng buộc `chk_sampling_round_2`,
  `chk_sampling_sample_size_pos`, `uq_case_entry_qc_sample_item`.

06/10/2026:

Trên PostgreSQL 16 trống, mã tại commit `133f6af`:
- `scripts/migrate_database.py`: `<none> -> 0014_entry_qc_resolution`.
- Hạ về `0010_case_input_assignment` rồi nâng lại `head`: thành công.
- Mọi bảng/cột trong model khớp CSDL sau khi nâng (0 khác biệt), chỉ mục duy nhất
  `uq_case_scan_packages_active_case ... WHERE status = 'processing'` và ràng buộc
  `ck_entry_qc_resolution` có mặt.
Chưa kiểm: nâng một bản sao CSDL thật đang có dữ liệu. Nên làm trên bản sao
(`pg_restore` vào CSDL tạm) trước ngày chạy thật.
