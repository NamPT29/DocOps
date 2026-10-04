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

---

# Đợt 2 (04/10)

| File | Nội dung |
|---|---|
| `12. BM-TKDA-01-12_UBKTHB.xls` (thực chất là xlsx) | Sổ theo dõi dự án của PM: định mức, chấm công, năng suất, chi phí nhân công, bảng lương |
| `Dem trang PDF ed3 ... A4_check.xlsm`, `..._bao_cao_da_doi_ten.xlsm` | Công cụ đếm trang theo khổ giấy và quy đổi A4 |
| `RenameFile - CopyFile.xlsm` | Đổi tên/sao chép hàng loạt theo cặp đường dẫn cũ → mới |
| Ảnh hướng dẫn Total Commander | Sắp xếp tên file kiểu tự nhiên (1, 2, …, 10) |
| 4 file `CSDL_SOHOA_Metadata_*.xlsx` | Metadata thật đã bàn giao của 4 dự án (dữ liệu nhạy cảm, chỉ ghi số liệu thống kê) |

## 5. Đếm trang và quy đổi A4 (trả lời câu hỏi 3)

- Kích thước chuẩn theo point (ISO 216): A0 2384×3370, A1 1684×2384, A2 1190×1684, A3 842×1190, A4 595×842.
- OverSize = 1,1: trang vượt khổ chuẩn quá 10% thì tính lên một khổ.
- **Tổng quy đổi A4 = A4×1 + A3×2 + A2×4 + A1×8 + A0×16.** Sổ dự án cũng dùng đúng hệ số này cho mục Scan.
- Kết quả đếm lưu theo từng file (số trang, dung lượng, số trang mỗi khổ); file lỗi có số trang -1.

## 6. Sổ theo dõi dự án BM-TKDA-01-12

- **Danh mục công việc** có định mức/8h và đơn vị (hồ sơ, trang, file, hộp, bộ). Có tách theo loại giấy:
  Scan A3/A4/A5 × (1 = giấy thường, 2 = giấy xấu); Check SC V1/V2; Nhập liệu 1 (thường) / 2 (xấu); Check NL V1/V2.
  Ngoài ra: Setup mặt bằng, nhập hồ sơ lên phần mềm, ghép file mềm, upload, xuất dữ liệu, tích hợp hệ thống KH, bàn giao, ký nghiệm thu.
- **Chấm công hằng ngày:** mỗi người tối đa 4 công việc/ngày; mỗi việc gồm thời gian (giờ), loại `NS` (tính năng suất), `CC` (chấm công), `NS.OT`, `CC.OT`, nội dung, khối lượng.
  Hệ số OT 1,2; hệ số Chủ nhật 1,4. Nhân sự chia Lead / nhân viên chính thức / thời vụ, mỗi người có lương cơ bản 8h và lương dự án 8h.
- **Các lỗi bắt khi nhập:** thiếu thời gian/loại/nội dung; có dữ liệu nhưng không có tên; việc có ĐVT mà sản lượng ≤ 0 hoặc là chữ; chấm sản lượng cho việc không có ĐVT; nội dung không có trong danh mục; thời gian sai; loại không thuộc 4 loại; NS mà không có sản lượng; CC mà không có thời gian; **tổng thời gian một người trong ngày > 14 giờ**.
- Báo cáo: tiến độ theo hạng mục (khối lượng hợp đồng, lũy kế, % hoàn thành, năng suất định mức và thực tế, ngày dự kiến xong), năng suất từng người, chi phí nhân công, bảng lương, theo dõi chi phí so với dự toán. Mọi thay đổi ghi vào sheet Log.

**Hệ quả:** đây chính là đặc tả cho module WorkLog/KPI (FR-KPI-01/02). WorkType nên có thêm *định mức/8h*, *đơn vị*, *loại giấy (thường/xấu)*; WorkLog có *loại NS/CC/OT*, hệ số OT và Chủ nhật; các quy tắc kiểm tra ở trên dùng nguyên làm validation. Phần lương và chi phí chi tiết để sau 10/10.

## 7. Đổi tên và sắp xếp

- Đổi tên hàng loạt theo cặp *đường dẫn cũ → đường dẫn mới*, ghi trạng thái từng dòng. Ví dụ tách thư mục bìa sang cây riêng (`..._01_BIA`). Công đoạn chuẩn hóa cần làm được việc này và có nhật ký.
- **Mọi danh sách file/thư mục phải sắp xếp tự nhiên** (1, 2, …, 10 chứ không phải 1, 10, 2), cả khi hiển thị lẫn khi đánh số thứ tự văn bản.

## 8. Metadata thật đã bàn giao (4 dự án)

- Định dạng **khác** `Metadata_Tong`: một sheet phẳng 49 cột, mỗi dòng một văn bản kèm lặp lại thông tin hồ sơ. Dòng 2 là tên trường tiếng Anh. Có cột `Path đổi theo HD40`, tức chuẩn theo hướng dẫn metadata của khối Đảng.
  → Có ít nhất **2 chuẩn đầu ra**: khối Nhà nước (`Metadata_Tong`, gói SIP) và khối Đảng (49 cột, HD40). Hệ thống cần cấu hình xuất theo dự án. Câu hỏi 1 (Bộ Y tế dùng chuẩn nào) càng quan trọng.
- Ngày tài liệu đều dạng `dd/mm/yyyy` (một ô).
- Cấu trúc cây thư mục đều 8–9 lớp.
- Quy mô: khoảng **61.600 văn bản**, khoảng 59.400 văn bản có đủ tên loại, ngày, cơ quan ban hành, trích yếu. Tên loại phổ biến: Báo cáo, Biên bản, Quyết định, Thông báo, Tờ trình, Kế hoạch.
- **Giá trị cho đồ án:** đây là nhãn đúng (đã qua kiểm tra và bàn giao) cho bài toán OCR trích xuất 5 trường. Nếu có PDF tương ứng (theo cột Path), có thể dựng bộ đánh giá mà không cần gán nhãn thủ công. Dữ liệu là của khách hàng: chỉ dùng trên máy nội bộ, không đưa lên Git hay cloud, ảnh minh họa trong báo cáo phải che thông tin.

## Câu hỏi bổ sung

6. Hệ số giấy xấu (Scan A42, Nhập liệu 2) có đơn giá riêng không, và ai quyết định một hộp là giấy xấu?
7. Có được dùng PDF + metadata của 4 dự án trên (chỉ trên máy nội bộ) làm dữ liệu đánh giá OCR cho đồ án không? Cần xin phép Duy Vũ/khách hàng không?
