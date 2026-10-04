# Phân tích tài liệu mẫu đợt 1 (04/10)

Nguồn: các file công cụ đang dùng ở đơn vị thi công. Ghi chép này chỉ lưu **cấu trúc**, không chép dữ liệu thật.

| File | Nội dung |
|---|---|
| `HuongdanToolSIP.docx` | Hướng dẫn tool đóng gói SIP (`DataPackaging.exe`) |
| `00. Metadata_Tong.xlsx` | Mẫu metadata đầu vào của tool SIP: sheet hồ sơ, sheet văn bản, đặc tả trường |
| `Nhap lieu_BIA_.xlsm` | Công cụ nhập liệu bìa hồ sơ bằng Excel + VBA |
| `Nhap lieu_VB_pass_123.xlsm` | Công cụ nhập liệu văn bản bằng Excel + VBA |
| `DUAN_Thong ke ho so so hoa.xls` | Trùng với file đã gửi ngày 01/10 (đã dùng khi lập BA) |

## 1. Gói SIP và cây thư mục bàn giao

Tool SIP nhận: (1) Excel metadata có sheet hồ sơ và sheet văn bản, tên trường ở **dòng 1**; (2) thư mục PDF.
Người dùng tự mapping cột Excel ↔ trường SIP, rồi chọn "Vị trí mã phông" = số lớp thư mục tính từ cuối lên (tính cả file).

Cây thư mục đầu ra theo ví dụ trong hướng dẫn:

```
<CSDL_SOHOA_xxx>\<Cơ quan>\<Năm>\<THBQ>\<Mã phông>\<Mã hồ sơ>\<Mã hồ sơ>.<STT 7 số>[_signed].pdf
ví dụ: CSDL_SOHOA_SNVTN\UBND\2008\VV\01\H05.02.02.2008.01.HC\H05.02.02.2008.01.HC.0000001_signed.pdf
```

- Mã hồ sơ: `<mã cơ quan>.<năm>.<số hồ sơ>.<ký hiệu>` (ví dụ `H05.02.02.2008.01.HC`).
- Mã lưu trữ văn bản = mã hồ sơ + `.` + STT 7 chữ số.
- `_signed` là hậu tố sau khi ký số.
- THBQ viết tắt (VV = vĩnh viễn, ...), danh mục có trong sheet 2 của biểu mẫu UBND.

**Hệ quả cho hệ thống:** công đoạn *chuẩn hóa* phải sinh được đúng cây thư mục và tên file này từ metadata, và xuất Excel metadata đúng 2 sheet để đưa vào tool SIP. Giai đoạn đầu **không viết lại tool SIP**: hệ thống xuất đầu vào cho tool, tool đóng gói (khớp quyết định "ký số ngoài hệ thống").

## 2. Bộ trường metadata chuẩn

Sheet `Mau_Metadata_BIA` và `Mau_Metadata_VB` đặc tả tên trường tiếng Anh, kiểu và độ dài (theo chuẩn metadata hồ sơ/tài liệu số của ngành lưu trữ).

**Hồ sơ (19 trường chuẩn + trường bổ sung):** fileCode (Mã hồ sơ), title, maintenance (THBQ), mode (chế độ sử dụng), language, startDate, endDate, keyword, totalDoc, numberOfPaper, numberOfPage, format (tình trạng vật lý), inforSign, confidenceLevel, paperFileCode, riskRecovery, riskRecoveryStatus, description; bổ sung: tệp tin hồ sơ, mục lục số, hộp số, hồ sơ số, tên phông, mã phông, giai đoạn/nhiệm kỳ, path.

**Văn bản (22 trường chuẩn + bổ sung):** docId, docCode (mã lưu trữ), maintenance, typeName (tên loại), codeNumber (số), codeNotation (ký hiệu), issuedDate, organName (cơ quan ban hành), subject (trích yếu), language, numberOfPage, inforSign, keyword, mode, confidenceLevel, autograph (bút tích), format, riskRecovery, riskRecoveryStatus, process, description; bổ sung như hồ sơ.

Nhiều trường là **mã** chứ không phải chữ (ví dụ THBQ `01`, chế độ sử dụng `01`, ngôn ngữ `01`). Cần bảng danh mục mã → nhãn.

5 trường OCR của đồ án ánh xạ thẳng vào: typeName, codeNumber + codeNotation, issuedDate, organName, subject.

## 3. Công cụ nhập liệu Excel hiện tại (BIA và VB)

Cùng một khung VBA, khác cấu hình trường:

- Load mọi PDF trong thư mục gốc (đệ quy), đếm trang và dung lượng; file không đọc được (số trang -1) vào sheet `Error`.
- Form nhập: hiện PDF bên cạnh, `<`, `>`, `Goto` để chuyển file; Enter để lưu; lưu vào sheet `Data` kèm ngày giờ và tên máy.
- **Sheet `Setup Field`**: tối đa 36 trường, mỗi trường có: tên, kiểu (Chuỗi ký tự / Số / Ngày / Tháng / Năm), kiểu con (Số ký tự, Số tự nhiên, Số thực), Min, Max, cho phép NULL, IN HOA, danh sách chọn (combobox).
- Trường VB đang dùng: Cơ quan ban hành, Số, Ký hiệu, Ngày, Tháng, Năm (tách 3 ô), Tên loại, Trích yếu, Người ký, Số lượng trang, Loại bản, Mức độ mật.
- Trường BIA: Tiêu đề hồ sơ, Ngày bắt đầu, Ngày kết thúc, Số tờ.
- Readme ghi các mong muốn chưa làm được: **thời gian nhập liệu, tài khoản người nhập**, không cho lưu khi chỉ chuyển qua lại.

**Đếm trang theo khổ giấy (A5 → A0, ISO 216):** trang nhỏ hơn A5 tính A5, lớn hơn A0 tính A0; tham số **OverSize** (mặc định 110%): diện tích vượt khổ chuẩn quá 10% thì tính lên một khổ. Đây là căn cứ tính sản lượng và chi trả theo trang.

**Hệ quả cho hệ thống:**
- Biểu mẫu trên web cần đủ các ràng buộc của `Setup Field` (kiểu, min/max, độ dài, bắt buộc, in hoa, danh sách chọn). Cần đối chiếu với cơ chế biểu mẫu hiện có và bổ sung chỗ thiếu.
- Web đã giải quyết sẵn 2 điểm Readme còn thiếu (tài khoản người nhập, thời gian), là lý do thuyết phục để thay công cụ Excel.
- Đếm trang theo khổ giấy nên làm ngay khi nạp gói scan (FR-SCN-01), lưu số trang từng khổ cho mỗi file.

## 4. Câu hỏi còn mở

1. Dự án Bộ Y tế dùng bộ trường nào: theo mẫu UBND (40 cột), theo `Metadata_Tong` (chuẩn SIP), hay mẫu riêng? Có file mẫu của Bộ Y tế không?
2. Ngày văn bản nhập tách 3 ô (ngày/tháng/năm) như công cụ cũ, hay một ô dd/mm/yyyy?
3. Sản lượng chi trả tính theo trang quy đổi A4 hay theo từng khổ có đơn giá riêng?
4. Mã cơ quan (ví dụ `H05.02.02`) và ký hiệu hồ sơ (`HC`) lấy từ đâu: khách hàng cấp hay đơn vị tự đặt?
5. Còn thiếu: file **mục lục chỉnh lý** mẫu (đầu vào cho import mục lục).
