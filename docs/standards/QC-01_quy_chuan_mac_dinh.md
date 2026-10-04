# QC-01. Quy chuẩn mặc định cho dự án số hóa (v0.1, 04/10/2026)

**Mục đích:** các câu hỏi nghiệp vụ chưa có câu trả lời chính thức được chốt tạm bằng giá trị mặc định ở đây, để hệ thống làm được ngay.
Khi có thông tin thật (từ Duy Vũ hoặc khách hàng), chỉ cần **sửa giá trị trong tài liệu này và nâng phiên bản**.

Quy ước:
- Mỗi mục có mã `QC-xx` để code, test và tài liệu đồ án tham chiếu.
- Cột **Nguồn**: `Mẫu` = lấy từ file công cụ/dữ liệu thật đã phân tích (`docs/plans/2026-10-04-sample-files-analysis.md`); `Giả định` = chưa có căn cứ, cần xác nhận.
- Mọi giá trị có thể khác nhau giữa các dự án sẽ là **cấu hình theo dự án**, lấy giá trị trong tài liệu này làm mặc định khi tạo dự án.

## Bảng tổng hợp các quyết định tạm

| Mã | Câu hỏi | Mặc định | Nguồn | Cấu hình theo dự án |
|---|---|---|---|---|
| QC-01 | Chuẩn metadata đầu ra | **Khối Nhà nước** (bộ trường `Metadata_Tong`, gói SIP). Hồ sơ khối Đảng (49 cột, HD40) là hồ sơ xuất thứ 2 | Mẫu | Có |
| QC-02 | Mã cơ quan, ký hiệu hồ sơ | Admin nhập khi tạo dự án; hệ thống ghép mã theo QC-03 | Giả định | Có |
| QC-03 | Mã hồ sơ / mã văn bản | `{Mã cơ quan}.{Năm}.{Số HS 2 chữ số}[.{Ký hiệu}]` / mã hồ sơ + `.{STT 7 chữ số}` | Mẫu | Ký hiệu: có |
| QC-04 | Cây thư mục bàn giao | `<Gốc>\<Cơ quan>\<Năm>\<THBQ viết tắt>\<Mã phông>\<Mã hồ sơ>\<Mã văn bản>[_signed].pdf` | Mẫu | Gốc: có |
| QC-05 | Ngày văn bản | **1 ô** `dd/mm/yyyy`; cho phép thiếu ngày/tháng (xem mục "Ngày thiếu thông tin") | Mẫu | Không |
| QC-06 | Tính sản lượng scan | **Quy đổi A4** = A4×1 + A3×2 + A2×4 + A1×8 + A0×16, vượt khổ >10% tính lên 1 khổ | Mẫu | Không |
| QC-07 | Giấy xấu | Đánh dấu ở **cấp hộp** khi chỉnh lý (người chỉnh lý đề xuất, Admin duyệt). Hệ số đơn giá **1,3** | Giả định | Hệ số: có |
| QC-08 | Kiểm tra chất lượng | Ngưỡng lỗi 5%; check vòng 2 lấy mẫu 30%; hạn xử lý hộp 2 ngày | BA v1.0 | Có |
| QC-09 | Chấm công | NS / CC / NS.OT / CC.OT; tối đa 4 việc/người/ngày; ≤ 14 giờ/ngày; hệ số OT 1,2; Chủ nhật 1,4 | Mẫu | Hệ số: có |
| QC-10 | Định mức công việc | Theo bảng QC-10 bên dưới | Mẫu + giả định | Có |
| QC-11 | Dữ liệu OCR cho đồ án | Dùng metadata đã bàn giao làm nhãn, **chỉ trên máy nội bộ**, chờ Duy Vũ cho phép | Giả định | — |

---

## QC-01. Chuẩn metadata đầu ra

Hai hồ sơ xuất, chọn khi tạo dự án:

| Hồ sơ xuất | Khi nào dùng | Định dạng |
|---|---|---|
| `NN-SIP` (mặc định) | Cơ quan khối Nhà nước, ví dụ Bộ Y tế | Excel 2 sheet `Metadata_HS` + `MetadataVB` theo `Metadata_Tong`, tên trường ở dòng 1, đưa vào tool SIP |
| `DANG-HD40` | Cơ quan khối Đảng | 1 sheet phẳng 49 cột, mỗi dòng một văn bản, dòng 2 là tên trường tiếng Anh |

## QC-03. Mã định danh

- **Mã hồ sơ:** `{Mã cơ quan}.{Năm}.{Số hồ sơ}[.{Ký hiệu}]`, ví dụ `H05.02.02.2008.01.HC`.
  - Mã cơ quan: Admin nhập khi tạo dự án (bắt buộc).
  - Năm: năm của *Thời gian bắt đầu* hồ sơ.
  - Số hồ sơ: lấy từ mục lục, bù 0 cho đủ 2 chữ số (`1` → `01`; từ 100 giữ nguyên).
  - Ký hiệu: tùy chọn, theo phông/nhóm (ví dụ `HC`).
- **Mã văn bản:** mã hồ sơ + `.` + STT 7 chữ số, ví dụ `H05.02.02.2008.01.HC.0000001`. STT đánh theo **thứ tự tự nhiên** của tên file trong thư mục hồ sơ (QC-12).
- **File bìa** (`BIA.pdf` hoặc tên chứa `BIA`) không tính là văn bản: không đánh STT, đi theo hồ sơ.

## QC-04. Cây thư mục bàn giao

```
<Gốc>\<Cơ quan>\<Năm>\<THBQ viết tắt>\<Mã phông>\<Mã hồ sơ>\<Mã văn bản>[_signed].pdf
```
- `<Gốc>` mặc định `CSDL_SOHOA_<Mã dự án>`.
- THBQ viết tắt theo danh mục QC-13 (`VV`, `LD`, ...).
- Hậu tố `_signed` chỉ có sau khi file đã ký số.
- Tên thư mục và tên file: chỉ chữ không dấu, số, `.`, `_`, `-`; không khoảng trắng.

## Bộ trường hồ sơ (mặc định, hồ sơ xuất `NN-SIP`)

| Trường | Tên kỹ thuật | Kiểu | Bắt buộc | Ghi chú |
|---|---|---|---|---|
| Mã hồ sơ | fileCode | Chuỗi ≤ 100 | Có | Sinh tự động (QC-03) |
| Tiêu đề hồ sơ | title | Chuỗi ≤ 1000 | Có | Từ mục lục |
| Thời hạn bảo quản | maintenance | Mã | Có | QC-13 |
| Chế độ sử dụng | mode | Mã | Có | Mặc định `01` |
| Ngôn ngữ | language | Mã | Có | Mặc định `01` (tiếng Việt) |
| Thời gian bắt đầu / kết thúc | startDate / endDate | dd/mm/yyyy | Có | |
| Từ khóa | keyword | Chuỗi | Không | |
| Tổng số văn bản | totalDoc | Số | Có | Tự đếm |
| Số tờ | numberOfPaper | Số | Có | Từ mục lục |
| Số trang | numberOfPage | Số | Có | Tự đếm từ PDF |
| Tình trạng vật lý | format | Chuỗi | Không | Mặc định `Bình thường` |
| Ký hiệu thông tin, Mức độ tin cậy, Mã hồ sơ giấy, Chế độ dự phòng, Tình trạng dự phòng, Ghi chú | | | Không | Mức độ tin cậy mặc định `02` |
| Bổ sung: Mục lục số, Hộp số, Hồ sơ số, Tên phông, Mã phông, Giai đoạn/Nhiệm kỳ, Path | | | Có (trừ nhiệm kỳ) | Từ mục lục và cấu hình dự án |

## Bộ trường văn bản (mặc định)

| Trường | Tên kỹ thuật | Kiểu | Bắt buộc | Quy tắc nhập |
|---|---|---|---|---|
| Tên loại văn bản | typeName | Danh mục QC-14 | Có | **IN HOA**, chọn từ danh mục |
| Số của văn bản | codeNumber | Chuỗi ≤ 11 | Không | Giữ số 0 đầu (`01`); văn bản không số để trống |
| Ký hiệu văn bản | codeNotation | Chuỗi ≤ 30 | Không | Bắt đầu bằng `/`, ví dụ `/2008/CT-UBND` |
| Ngày văn bản | issuedDate | dd/mm/yyyy | Có | QC-05 |
| Cơ quan ban hành | organName | Chuỗi ≤ 200 | Có | **IN HOA** |
| Trích yếu | subject | Chuỗi ≤ 500 | Có | Viết hoa chữ đầu câu, không dấu chấm cuối |
| Ngôn ngữ, Chế độ sử dụng, Mức độ tin cậy | | Mã | Có | Mặc định `01`, `01`, `02` |
| Số trang | numberOfPage | Số | Có | Tự đếm từ PDF |
| Người ký | | Chuỗi ≤ 50 | Không | |
| Bút tích, Ký hiệu thông tin, Từ khóa, Tình trạng vật lý, Ghi chú | | | Không | |

### Ngày thiếu thông tin (QC-05)
- Đủ ngày: `08/01/2008`.
- Thiếu ngày: `00/01/2008`. Thiếu ngày và tháng: `00/00/2008`. Không xác định năm: để trống và ghi chú.
- Kiểm tra: ngày ≤ 31, tháng ≤ 12, năm trong [1945, năm hiện tại]; ngày văn bản nằm trong khoảng thời gian của hồ sơ thì hợp lệ, ngoài khoảng thì cảnh báo, không chặn.

## QC-06. Đếm trang theo khổ giấy

| Khổ | Kích thước chuẩn (point) | Hệ số quy đổi A4 |
|---|---|---|
| A0 | 2384 × 3370 | 16 |
| A1 | 1684 × 2384 | 8 |
| A2 | 1190 × 1684 | 4 |
| A3 | 842 × 1190 | 2 |
| A4 | 595 × 842 | 1 |
| A5 | 420 × 595 | 1 (tính như A4, *giả định*) |

- Diện tích trang vượt khổ chuẩn quá **10%** thì tính lên một khổ. Nhỏ hơn A5 tính A5, lớn hơn A0 tính A0.
- File không đọc được: số trang `-1`, đưa vào danh sách lỗi, không tính sản lượng.

## QC-08. Kiểm tra chất lượng và hạn xử lý (chi tiết)
- **Ngưỡng lỗi của hộp (BR-07)**: 5%. Khác với "tỷ lệ lỗi tối đa của biểu mẫu" (xếp *một báo cáo* vào loại lỗi); hai ngưỡng tồn tại song song, đặt tên phân biệt.
- **Tỷ lệ lấy mẫu check vòng 2**: 30%.
- **Hạn xử lý hộp**: 2 ngày **lịch**, tính đủ 48 giờ kể từ lúc giao (không trừ thứ Bảy, Chủ nhật, ngày lễ), vì CTV làm cả cuối tuần. *(giả định)*
- Giới hạn nhập: tỷ lệ 0–100; hạn 1–365 ngày; hệ số > 0 và ≤ 10 (chặn gõ nhầm "13" thay vì "1,3").

## Cách áp dụng giá trị mặc định
- Trường cấu hình dự án **để trống = theo QC-01 hiện hành**. QC-01 lên phiên bản mới thì mọi dự án chưa đặt riêng tự theo; giá trị Admin đã đặt riêng giữ nguyên.
- Kết quả đã tính (sản lượng, chi trả, kết luận đạt/trả lại) phải **lưu kèm giá trị tham số tại thời điểm tính**, để đổi QC-01 sau này không làm thay đổi số liệu cũ.
- Mã cơ quan được để trống khi tạo dự án; **bắt buộc khi sinh mã hồ sơ** ở bước chuẩn hóa/đóng gói.

## QC-07. Giấy xấu
- Cờ `giấy xấu` gắn ở **hộp**. Người chỉnh lý đánh dấu khi chỉnh lý, Admin duyệt.
- Hộp giấy xấu tính công việc loại 2 (Scan Ax2, Nhập liệu 2) với hệ số đơn giá **1,3** (*giả định*).

## QC-09. Chấm công và giờ công
- Loại: `NS` (tính năng suất, cần sản lượng), `CC` (chấm công theo giờ, cần thời gian), `NS.OT`, `CC.OT` (ngoài giờ).
- Tối đa 4 việc/người/ngày. Tổng thời gian một người trong ngày không quá 14 giờ.
- Hệ số ngoài giờ 1,2; Chủ nhật 1,4 (Leader làm Chủ nhật tính OT toàn bộ thời gian).
- Lỗi phải chặn: thiếu thời gian/loại/nội dung; không có người; việc có đơn vị tính mà sản lượng ≤ 0 hoặc không phải số; chấm sản lượng cho việc không có đơn vị tính; nội dung không có trong danh mục; thời gian ≤ 0; NS không có sản lượng; CC không có thời gian.
- CTV làm từ xa: không tính lương cơ bản, chỉ tính sản lượng.

## QC-10. Danh mục công việc và định mức (mặc định khi tạo dự án)

| Mã | Công việc | Đơn vị | Định mức / 8h | Nguồn |
|---|---|---|---|---|
| CL | Chỉnh lý, lập mục lục | hồ sơ | 40 | Giả định |
| SC-A4-1 | Scan A4 giấy thường | trang | 3.500 | Mẫu |
| SC-A4-2 | Scan A4 giấy xấu | trang | 2.000 | Giả định |
| SC-A3-1 / SC-A3-2 | Scan A3 thường / xấu | trang | 1.500 / 900 | Giả định |
| CS-1 / CS-2 | Check scan vòng 1 / 2 | trang | 6.000 / 10.000 | Giả định |
| NL-1 / NL-2 | Nhập liệu tài liệu thường / xấu | văn bản | 250 / 150 | Giả định |
| CN-1 / CN-2 | Check nhập liệu vòng 1 / 2 | văn bản | 600 / 1.500 | Giả định |
| CH | Chuẩn hóa, đóng gói | hồ sơ | 200 | Giả định |
| BG | Bàn giao, nghiệm thu | lần | — (chấm công) | Mẫu |

Định mức là căn cứ tính **% năng suất** và **ngày dự kiến hoàn thành**, không chặn thao tác. Admin sửa được theo dự án.

## QC-12. Sắp xếp
Mọi danh sách file và thư mục (hiển thị, đánh STT văn bản, xuất Excel) dùng **sắp xếp tự nhiên**: `1, 2, …, 10`, không dùng `1, 10, 2`. So sánh không phân biệt hoa thường.

## QC-13. Danh mục mã

**Thời hạn bảo quản**
| Mã | Nhãn | Viết tắt | Nguồn |
|---|---|---|---|
| 01 | Vĩnh viễn | VV | Mẫu |
| 02 | Có thời hạn (lâu dài) | LD | Giả định: cần đối chiếu danh mục chính thức |

**Chế độ sử dụng:** `01` Công khai (mặc định), `02` Sử dụng có điều kiện, `03` Mật. *(giả định)*
**Ngôn ngữ:** `01` Tiếng Việt (mặc định). *(Mẫu)*
**Mức độ tin cậy:** `02` cho tài liệu số hóa (mặc định). *(Mẫu)*

## QC-14. Danh mục tên loại văn bản (viết tắt)
Lấy theo sheet 2 của biểu mẫu `templates/UBND.xlsx` (33 loại): Nghị quyết (NQ), Quyết định (QĐ), Thông tri (TT), Chỉ thị (CT), Quy chế (QC), Quy định (QyĐ), Thông cáo (TC), Thông báo (TB), Hướng dẫn (HD), Chương trình (Ctr), Kế hoạch (KH), Phương án (PA), Đề án (ĐA), Dự án (DA), Báo cáo (BC), Biên bản (BB), Tờ trình (TTr), Hợp đồng (HĐ), Công điện (CĐ), Bản ghi nhớ (BGN), Bản thỏa thuận (BTT), Giấy ủy quyền (GUQ), Giấy mời (GM), Giấy giới thiệu (GGT), Giấy nghỉ phép (GNP), Phiếu gửi (PG), Phiếu chuyển (PC), Phiếu báo (PB), Công văn (CV), Bản sao y (SY), Bản trích sao (TrS), Bản sao lục (SL), Tài liệu khác (TLK).
Bổ sung theo dữ liệu đã bàn giao: **Dự thảo**, **Tờ trình**, **Biên bản** là nhóm phổ biến. Danh mục là cấu hình theo dự án.

## QC-15. Làm sạch dữ liệu (công đoạn chuẩn hóa)
- Bỏ khoảng trắng đầu/cuối, gộp nhiều khoảng trắng thành một, chuẩn Unicode **NFC**.
- Trường IN HOA (tên loại, cơ quan ban hành) chuyển in hoa tự động.
- Số văn bản giữ nguyên chuỗi (không đổi `01` thành `1`).
- Đổi tên file theo QC-03/QC-04, ghi nhật ký cặp *đường dẫn cũ → mới* và trạng thái từng file; cho phép xuất nhật ký ra Excel.

## QC-16. Mục lục chỉnh lý (đầu vào import)
Dùng file mẫu `docs/standards/Mau_Muc_luc_chinh_ly.xlsx`:
- Mỗi dòng một hồ sơ, tiêu đề cột ở dòng 1, dữ liệu từ dòng 2.
- Khóa so khớp với gói scan: **Hộp số + Hồ sơ số** ↔ đường dẫn thư mục `<Hộp>\<Hồ sơ>` (bù 0 theo số chữ số lớn nhất trong hộp).
- Lỗi theo dòng: thiếu cột bắt buộc, trùng (Hộp số, Hồ sơ số), ngày sai định dạng, ngày bắt đầu > ngày kết thúc, THBQ không có trong danh mục.

---

## Lịch sử thay đổi
| Phiên bản | Ngày | Nội dung |
|---|---|---|
| 0.1 | 04/10/2026 | Bản đầu, chốt tạm theo mẫu đã phân tích và giả định |
| 0.1.1 | 04/10/2026 | Chốt cách áp mặc định, giới hạn nhập, hạn xử lý theo ngày lịch, mã cơ quan bắt buộc ở bước đóng gói |
