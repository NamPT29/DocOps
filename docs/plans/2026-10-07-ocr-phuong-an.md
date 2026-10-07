# OCR gợi ý 5 trường: phương án và cách chọn (07/10/2026)

Trạng thái: **đang chọn phương án, chưa viết code.** Không gộp vào bản chạy thật 10/10.

## Đã chốt với người dùng
- Mục đích: khi nhập liệu, hệ thống điền sẵn 5 trường của văn bản: cơ quan ban hành (organName),
  số + ký hiệu (codeNumber, codeNotation), ngày ban hành (issuedDate), tên loại (typeName), trích yếu (subject).
  Người nhập xem, sửa rồi lưu như bình thường; máy không tự lưu, không ghi đè ô người đã gõ.
- OCR chạy trên máy nội bộ. Không gửi bản scan ra dịch vụ ngoài (dữ liệu khách hàng nhạy cảm).
- Làm trên nhánh riêng, ghép vào bản chính sau 10/10.

## Nguyên tắc tối ưu (áp dụng cho mọi phương án)
1. Chỉ đọc phần đầu trang 1 (khoảng 42% chiều cao): theo thể thức văn bản hành chính, cả 5 trường nằm ở đó.
2. Kiểm tra PDF đã có lớp chữ chưa; có thì đọc thẳng, bỏ qua OCR.
3. Lọc màu đỏ/tím (dấu "ĐẾN", dấu mộc) trước khi đọc.
4. Chạy nền ngay sau Nộp S, trong lúc hộp chờ Check scan; nhiều tiến trình, chừa nhân CPU cho web.
   Mục tiêu tốc độ: nhanh hơn tốc độ scan mỗi ngày (không cần xong 120 GB trong một lần).
5. Lưu chữ OCR thô riêng với kết quả tách trường: sửa luật tách thì chạy lại vài phút, không OCR lại.
6. Sau khi đọc: tách trường theo thể thức, sửa tên cơ quan/tên loại bằng danh mục, kiểm mẫu số/ký hiệu và ngày.
7. Trường máy không chắc thì tô màu khác để người nhập soát kỹ.

## Số đo ngày 07/10 (văn bản giả 8 trang, 300 dpi, 1 nhân CPU, không dùng dữ liệu khách)
| Cách | Thời gian | Đọc đúng 5 trường |
|---|---|---|
| Tesseract 5 (vie), cả văn bản 8 trang | 14,3 giây | — |
| Tesseract 5 (vie), phần đầu trang 1, 200 dpi | 0,4 giây | 5/5 |
| RapidOCR (PP-OCRv4 Trung/Anh), phần đầu trang 1 | 3,0 giây | không đọc được dấu tiếng Việt |

Văn bản giả sạch hơn tài liệu thật; số trên chỉ dùng để so tỷ lệ, không dùng để kết luận độ đúng.

## Ba cách cần lưu tâm
| | A | B | C |
|---|---|---|---|
| Tầng 1 | PP-OCRv6 tìm dòng, **VietOCR** đọc mọi dòng | **PP-OCRv6** tìm dòng và đọc | PP-OCRv6 tìm dòng, **VietOCR** đọc |
| Tầng 2 | không có | **SenOCR-Vi** đọc lại phần đầu trang của văn bản máy không chắc | **SenOCR-Vi** như B |
| Mạnh | Chữ in rõ tốt; huấn luyện thêm dễ nhất (file 2 cột ảnh/chữ, chạy được trên card 4 GB) | Bản xấu tốt hơn nhờ tầng 2; hai bộ đọc kiểm chéo, biết chỗ cần người soát; cùng hệ PaddleOCR | Lấy VietOCR làm tầng 1 nếu số đo cho thấy nó đọc tiếng Việt tốt hơn PP-OCRv6 |
| Yếu | VietOCR cũ (bản cuối 03/2024), ghim thư viện cũ, tải mô hình từ Google Drive; đọc từng dòng, không có ngữ cảnh | Tầng 2 có thể bịa chữ trông hợp lý; PP-OCRv6 chưa có số đo tiếng Việt | Cài cả hai hệ (Paddle + PyTorch) |
| Bộ nhớ card | dưới 1 GB | khoảng 2,5 GB | khoảng 3 GB |

Nhận định hiện tại: nghiêng về B cho tài liệu lưu trữ cũ; chưa có ai công bố so sánh trực tiếp trên văn bản
hành chính tiếng Việt, nên chọn bằng số đo. Bài đo ghi kết quả từng bộ đọc cho từng dòng, nên ghép được A, B, C
và nhiều ngưỡng chuyển tầng (10/20/30%) sau một lần đo.

## Thông tin các mô hình (tra ngày 07/10/2026)
- PP-OCRv6 (PaddleOCR 3.7.0, 11/06/2026, Apache 2.0): 3 cỡ tiny 1,5M / small 7,7M / medium 34,5M tham số;
  một mô hình cho 50 ngôn ngữ (danh sách có `vi`); nhà làm công bố nhanh hơn PP-OCRv5 khoảng 5 lần trên CPU (OpenVINO).
- SenOCR-Vi (VietAlphaLabs, Apache 2.0): huấn luyện thêm từ PaddleOCR-VL-1.6 (khoảng 0,96 tỷ tham số) cho tài liệu
  tiếng Việt kể cả tài liệu lưu trữ; nhà làm tự đo 86,7% chữ tiếng Việt trên 160 trang; khoảng 2 GB bộ nhớ card (FP16).
- PaddleOCR-VL-1.6 (05/2026, Apache 2.0): 109 ngôn ngữ, khoảng 2,1 GB bộ nhớ card (FP16).
- VietOCR (MIT, 2020, bản cuối 0.3.13 ngày 29/03/2024): vgg_transformer 0,88 / vgg_seq2seq 0,87 dòng đúng trọn vẹn
  trên bộ thử của tác giả.
- Đã xem và loại: TeleOCR, OvisOCR2 (chưa thấy hỗ trợ tiếng Việt), Qwen3-VL (nặng, thua mô hình tài liệu nhỏ),
  Vintern-1B (cũ hơn SenOCR-Vi), dịch vụ đám mây (dữ liệu không được ra ngoài).
- Đối chứng mua sẵn (người dùng tự hỏi giá/dùng thử, chạy trên máy): ABBYY FineReader; FPT akaOCR, VNPT SmartReader,
  Viettel IDP bản cài tại chỗ.

## Máy đo
Laptop Windows 11, Intel i5-11400H (6 nhân), RAM 16 GB, NVIDIA RTX 3050 Laptop 4 GB, ổ còn trống khoảng 199 GB.
Chạy nặng lâu: cắm sạc, chế độ Turbo, tản nhiệt, tắt chế độ ngủ, driver NVIDIA mới.

## Bài đo (lát O1)
- Bộ đọc: Tesseract (mốc), PP-OCRv6 small/medium, VietOCR, PaddleOCR-VL-1.6, SenOCR-Vi; trên cùng khoảng 100 văn bản
  thật đủ loại (đánh máy mới/cũ, mờ, dấu đè, viết tay; công văn, quyết định, biên bản...).
- Đáp án: các văn bản đã nhập và kiểm tra trong buổi chạy thử 09/10; thêm metadata đã bàn giao nếu Duy Vũ cho phép (QC-11).
- Kết quả in ra chỉ là số (không có nội dung văn bản): % đúng từng trường, giây/văn bản, % sai mà máy báo chắc,
  RAM/bộ nhớ card. Kết quả chi tiết nằm lại trên máy đo.
- Luật chọn: loại phương án có "sai mà báo chắc" quá 2%; loại phương án chậm hơn tốc độ scan mỗi ngày;
  trong số còn lại chọn % trường đúng cao nhất; chênh dưới 2 điểm thì chọn phương án đơn giản hơn.

## Các lát dự kiến
| Lát | Nội dung | Ai làm |
|---|---|---|
| O1 | Bộ công cụ đo, chạy trên máy nội bộ | Reviewer |
| O2 | Tách 5 trường từ chữ OCR (thể thức NĐ 30/2020 và các thể thức cũ) | Reviewer |
| O3 | Bảng lưu kết quả OCR (migration mới), hàng đợi | Antigravity |
| O4 | OCR chạy nền sau Nộp S, nhiều tiến trình | Reviewer |
| O5 | Admin chọn cột của mẫu biểu ứng với 5 trường | Antigravity |
| O6 | Điền gợi ý trên trang nhập liệu (dùng lại `ocr_fields` / `applyProposals` trong employee_ocr.js) | Reviewer |
| O7 | Thống kê % gợi ý được giữ nguyên theo trường | Antigravity |
| O8 (nếu cần) | Huấn luyện thêm trên dữ liệu đã nhập/đã bàn giao (cần QC-11, giữ mô hình trong máy nội bộ) | Reviewer |

## Còn chờ người dùng
1. Laptop trên có phải máy chủ chạy DocOps không.
2. 120 GB tài liệu để ở đâu (ổ máy, ổ ngoài, NAS).
3. Mỗi ngày đội scan được khoảng bao nhiêu văn bản/trang.
4. Duy Vũ trả lời QC-11 (dùng PDF + metadata đã bàn giao, chỉ trên máy nội bộ).

## Nguồn
- PaddleOCR 3.7.0 (PP-OCRv6): https://pypi.org/project/paddleocr/3.7.0/
- SenOCR-Vi: https://huggingface.co/VietAlphaLabs/SenOCR-Vi
- PaddleOCR-VL-1.6: https://arxiv.org/pdf/2606.03264
- VietOCR: https://pypi.org/project/vietocr/
- Xếp hạng mô hình OCR 2026: https://roboflow.com/blog/best-open-source-ocr-models
