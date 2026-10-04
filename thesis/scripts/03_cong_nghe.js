const { p, bullets, numbered, table, h, titleBlock, build } = require('./lib');

const children = [
  ...titleBlock('LIỆT KÊ CÁC CÔNG NGHỆ, KIẾN THỨC MỚI CẦN TÌM HIỂU'),

  h(1, '1. Tổng quan'),
  p('Đề tài kế thừa một phần mềm nhập liệu đã có (Python/FastAPI, PostgreSQL, giao diện HTML/JavaScript) và mở rộng thành hệ thống quản lý khép kín 7 công đoạn số hóa, tích hợp AI. Vì vậy các công nghệ được chia làm hai loại:'),
  ...bullets([
    '**Đã dùng trong hệ thống hiện có:** cần nắm vững để mở rộng đúng kiến trúc.',
    '**Mới, cần tìm hiểu:** kiến thức nghiệp vụ lưu trữ, chuẩn định dạng, và toàn bộ phần AI.',
  ]),

  h(1, '2. Bảng tổng hợp'),
  table([2.1, 2.6, 3.3, 2.0], [
    ['Nhóm', 'Công nghệ / kiến thức', 'Dùng để làm gì trong đề tài', 'Mức độ'],
    ['Nghiệp vụ', 'Quy trình số hóa tài liệu lưu trữ; Luật Lưu trữ 2024; Thông tư 02/2019/TT-BNV', 'Mô hình hóa 7 công đoạn, metadata hồ sơ/văn bản', 'Mới'],
    ['Chuẩn định dạng', 'PDF/A (ISO 19005); veraPDF', 'Chuyển đổi và kiểm tra file đầu ra đạt chuẩn lưu trữ lâu dài', 'Mới'],
    ['Chuẩn định dạng', 'Chữ ký số trên PDF (PAdES)', 'Quản lý trạng thái ký, kiểm tra file đã ký còn hợp lệ', 'Mới'],
    ['Chuẩn định dạng', 'Mô hình OAIS, gói tin SIP (ISO 14721)', 'Đóng gói dữ liệu bàn giao', 'Mới'],
    ['Máy chủ', 'Python, FastAPI, Pydantic', 'API cho toàn bộ chức năng', 'Đã dùng'],
    ['Máy chủ', 'SQLAlchemy, Alembic, PostgreSQL', 'Mô hình dữ liệu, migration không phá dữ liệu cũ', 'Đã dùng, cần sâu hơn'],
    ['Máy chủ', 'Máy trạng thái (state machine)', 'Điều khiển chuyển công đoạn, trả lại, mở lại', 'Mới'],
    ['Máy chủ', 'Tác vụ nền, xử lý file lớn', 'Quét thư mục scan, chuyển PDF/A, đóng gói', 'Đã dùng một phần'],
    ['Giao diện', 'HTML/JavaScript, Bootstrap, PDF.js', 'Màn hình nhập liệu, kiểm tra, quản trị', 'Đã dùng'],
    ['Giao diện', 'Content Security Policy (CSP)', 'Giao diện an toàn, không dùng script nội tuyến', 'Đã dùng, cần sâu hơn'],
    ['AI – OCR', 'Tesseract, PaddleOCR, VietOCR', 'Nhận dạng chữ tiếng Việt từ bản scan; so sánh để chọn engine tốt nhất', 'Mới'],
    ['AI – Xử lý ảnh', 'OpenCV', 'Tiền xử lý ảnh; phát hiện ảnh mờ, nghiêng, trang trắng', 'Mới'],
    ['AI – Trích xuất', 'Trích xuất thông tin (luật + mô hình học máy, mô hình ngôn ngữ chạy cục bộ)', 'Gợi ý metadata: số/ký hiệu, ngày ban hành, cơ quan, trích yếu', 'Mới'],
    ['AI – Đánh giá', 'CER, WER, Precision/Recall/F1', 'Đo độ chính xác OCR và trích xuất', 'Mới'],
    ['Bảo mật', 'JWT, băm mật khẩu scrypt, phân quyền RBAC, nhật ký kiểm toán', 'Xác thực, phân quyền 3 vai trò, truy vết', 'Đã dùng, cần sâu hơn'],
    ['Pháp lý', 'Nghị định 13/2023/NĐ-CP', 'Bảo vệ dữ liệu cá nhân của cộng tác viên', 'Mới'],
    ['Kiểm thử', 'pytest; kiểm thử tải (Locust)', 'Kiểm thử tự động; kiểm tra chịu tải 100 người dùng', 'pytest đã dùng; Locust mới'],
    ['Vận hành', 'Caddy (HTTPS), sao lưu PostgreSQL, triển khai trên Windows', 'Chạy thật trên máy chủ nội bộ', 'Đã dùng một phần'],
  ]),

  h(1, '3. Chi tiết các nội dung cần tìm hiểu'),
  h(2, '3.1. Nghiệp vụ và chuẩn lưu trữ'),
  ...bullets([
    '**Quy trình số hóa tài liệu lưu trữ:** chỉnh lý (phân loại, lập hồ sơ, lập mục lục), scan, kiểm tra, nhập metadata, chuẩn hóa, bàn giao; cách tổ chức phông, hộp, hồ sơ, văn bản.',
    '**Metadata hồ sơ và văn bản:** các trường bắt buộc, danh mục mã (thời hạn lưu trữ, chế độ sử dụng, tên loại văn bản), định dạng ngày.',
    '**PDF/A:** khác biệt so với PDF thường (nhúng font, không phụ thuộc tài nguyên ngoài); các mức tuân thủ; công cụ chuyển đổi (Ghostscript, OCRmyPDF) và công cụ kiểm tra (veraPDF).',
    '**Chữ ký số trên PDF:** nguyên lý ký, vị trí hiển thị chữ ký, ảnh hưởng của việc ký tới chuẩn PDF/A, cách kiểm tra file đã ký.',
    '**Gói tin SIP theo OAIS:** cấu trúc gói, thông tin mô tả gói và phông, kiểm tra toàn vẹn bằng mã băm (SHA-256).',
  ]),
  h(2, '3.2. Phát triển hệ thống'),
  ...bullets([
    '**FastAPI nâng cao:** dependency injection cho phân quyền theo vai trò và theo dự án, xử lý lỗi thống nhất, tài liệu API tự sinh.',
    '**SQLAlchemy và Alembic:** thiết kế bảng mới mà không sửa schema đã đóng băng; migration có thể kiểm thử; khóa dòng (row lock) chống tranh chấp khi nhiều người thao tác.',
    '**Máy trạng thái:** mô hình hóa trạng thái chờ, đang làm, xong, trả lại; điều kiện chuyển trạng thái; ghi sự kiện bất biến.',
    '**Xử lý file lớn:** quét thư mục qua mạng nội bộ, phát hiện file đang chép dở, tính SHA-256, đếm trang PDF.',
    '**Hiệu năng giao diện:** hiển thị PDF theo từng phần cho người dùng ở xa, phân trang danh sách lớn.',
  ]),
  h(2, '3.3. Trí tuệ nhân tạo'),
  ...bullets([
    '**OCR tiếng Việt:** tiền xử lý ảnh (khử nhiễu, chỉnh nghiêng, nhị phân hóa); so sánh Tesseract (đang có trong hệ thống), PaddleOCR và VietOCR về độ chính xác và tốc độ trên dữ liệu thật.',
    '**Trích xuất metadata:**',
    [
      'Cách tiếp cận dựa trên luật: biểu thức chính quy cho số/ký hiệu, ngày tháng; vị trí các thành phần trong thể thức văn bản hành chính.',
      'Cách tiếp cận học máy: nhận dạng thực thể có tên, mô hình hiểu bố cục tài liệu (LayoutLM), hoặc mô hình ngôn ngữ chạy cục bộ.',
      'Kết hợp: luật cho trường có mẫu rõ, mô hình cho trường tự do như trích yếu; tính độ tin cậy cho từng trường.',
    ],
    '**Kiểm tra chất lượng ảnh:** đo độ mờ (phương sai Laplacian), phát hiện độ nghiêng (biến đổi Hough/chiếu ngang), phát hiện trang trắng, kiểm tra độ phân giải và độ sâu màu.',
    '**Đánh giá mô hình:** xây dựng bộ dữ liệu chuẩn từ các bản ghi đã qua kiểm tra của con người; đo CER/WER cho OCR, Precision/Recall/F1 cho từng trường, thời gian nhập liệu khi có và không có gợi ý.',
    '**Triển khai cục bộ:** chạy mô hình trên máy chủ nội bộ (có hoặc không có GPU), không gửi dữ liệu nhạy cảm ra ngoài.',
  ]),
  h(2, '3.4. Bảo mật, kiểm thử và vận hành'),
  ...bullets([
    'Phân quyền theo vai trò kết hợp theo dự án; nguyên tắc người làm không tự kiểm tra; nhật ký kiểm toán chỉ ghi thêm.',
    'Bảo vệ dữ liệu cá nhân (số điện thoại, tài khoản ngân hàng của cộng tác viên) theo Nghị định 13/2023/NĐ-CP.',
    'Kiểm thử tải với 100 người dùng đồng thời bằng Locust; kiểm thử tự động bằng pytest.',
    'Triển khai HTTPS bằng Caddy, sao lưu và thử khôi phục cơ sở dữ liệu, chạy dịch vụ trên Windows.',
  ]),

  h(1, '4. Kế hoạch tìm hiểu'),
  table([1.5, 5.0, 3.5], [
    ['Thời gian', 'Nội dung', 'Kết quả'],
    ['Tuần 1', 'Nghiệp vụ số hóa, metadata, PDF/A, chữ ký số, SIP', 'Ghi chú nghiệp vụ, tài liệu BA'],
    ['Tuần 1–2', 'FastAPI, SQLAlchemy/Alembic nâng cao, máy trạng thái', 'Nền tảng quy trình 7 công đoạn'],
    ['Tuần 3–4', 'OCR tiếng Việt và tiền xử lý ảnh', 'Bảng so sánh 3 engine OCR'],
    ['Tuần 5–6', 'Trích xuất thông tin và kiểm tra chất lượng ảnh', 'Module AI thử nghiệm'],
    ['Tuần 7', 'Phương pháp đánh giá mô hình, kiểm thử tải', 'Số liệu đánh giá'],
  ]),

  h(1, '5. Tài liệu tham khảo'),
  ...numbered([
    'ISO 19005 – Electronic document file format for long-term preservation (PDF/A).',
    'ISO 14721 – Open Archival Information System (OAIS) Reference Model.',
    'Quốc hội (2024), Luật Lưu trữ số 33/2024/QH15.',
    'Bộ Nội vụ (2019), Thông tư 02/2019/TT-BNV.',
    'Chính phủ (2023), Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.',
    'R. Smith (2007), An Overview of the Tesseract OCR Engine, ICDAR 2007.',
    'Y. Du et al. (2020), PP-OCR: A Practical Ultra Lightweight OCR System, arXiv:2009.09941.',
    'VietOCR, https://github.com/pbcquoc/vietocr.',
    'Y. Xu et al. (2020), LayoutLM: Pre-training of Text and Layout for Document Image Understanding, KDD 2020.',
    'OpenCV documentation, https://docs.opencv.org.',
    'veraPDF – PDF/A validator, https://verapdf.org; OCRmyPDF, https://ocrmypdf.readthedocs.io.',
    'FastAPI (https://fastapi.tiangolo.com), SQLAlchemy, Alembic, PostgreSQL, Locust (https://locust.io).',
  ]),
];

build(process.argv[2] || 'thesis/03_Cong_nghe_kien_thuc_moi.docx', children);
