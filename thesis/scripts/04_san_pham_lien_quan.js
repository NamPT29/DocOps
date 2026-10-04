const { p, bullets, numbered, table, h, titleBlock, build } = require('./lib');

const children = [
  ...titleBlock('CÁC SẢN PHẨM, ĐỒ ÁN LIÊN QUAN GẦN NHẤT'),

  h(1, '1. Mục đích khảo sát'),
  p('Khảo sát các sản phẩm, đồ án và nghiên cứu gần với đề tài để: (1) học hỏi các giải pháp đã có, (2) tránh làm trùng, và (3) xác định điểm mới của đề tài “Hệ thống số hóa tài liệu tích hợp AI”. Phạm vi khảo sát gồm bốn nhóm: sản phẩm tiền thân của đề tài, sản phẩm thương mại trong nước, phần mềm mã nguồn mở quốc tế, và các đồ án, luận văn, nghiên cứu liên quan.'),
  p('Ghi chú về nguồn: mục có đánh dấu (*) được lấy từ kết quả tra cứu ngày 04/10/2026, sinh viên cần mở đường dẫn để kiểm tra lại trước khi trích dẫn chính thức. Các mục còn lại đã được đối chiếu trực tiếp với trang dự án.', { run: { italics: true } }),

  h(1, '2. Sản phẩm tiền thân: phần mềm nhập liệu hiện có tại đơn vị'),
  p('Đề tài được phát triển tiếp từ một phần mềm nhập liệu đang dùng tại đơn vị thi công số hóa (Python/FastAPI, PostgreSQL, giao diện web). Đây là sản phẩm gần nhất với đề tài.'),
  table([3, 7], [
    ['Đã có', 'Còn thiếu (đề tài bổ sung)'],
    [[
      'Quản lý dự án, phân công hồ sơ cho người nhập và người kiểm tra',
      'Biểu mẫu nhập liệu sinh tự động từ file Excel mẫu, xem PDF song song',
      'Kiểm tra nhập liệu, lưu lịch sử sửa theo trường, chỉ số chất lượng',
      'Upload PDF theo lô có thể tiếp tục khi gián đoạn, xuất Excel',
      'OCR trên trình duyệt (Tesseract.js)',
    ], [
      'Các công đoạn chỉnh lý, scan, kiểm tra scan, chuẩn hóa, bàn giao (đang theo dõi bằng Excel)',
      'So khớp mục lục chỉnh lý với kết quả scan; đối soát giữa các công đoạn',
      'Vai trò cộng tác viên có thời hạn, giao/thu hồi việc theo hộp',
      'Sản lượng theo trang, KPI, chi trả cộng tác viên',
      'PDF/A, quản lý ký số, đóng gói SIP, biên bản bàn giao',
      'AI trích xuất metadata và kiểm tra chất lượng ảnh scan',
    ]],
  ]),

  h(1, '3. Sản phẩm thương mại trong nước'),
  table([2.2, 4.6, 3.2], [
    ['Sản phẩm', 'Chức năng chính (theo mô tả công bố)', 'Liên hệ với đề tài'],
    ['VNPT SmartReader (*)', 'Nền tảng xử lý tài liệu bằng AI: OCR số hóa văn bản, bóc tách trường thông tin; thư viện mẫu tài liệu cho nhiều lĩnh vực trong đó có hành chính; cấu hình trường và cung cấp qua API', 'Tham khảo cho module trích xuất metadata; là dịch vụ OCR, không quản lý quy trình số hóa'],
    ['FPT.AI Reader (*)', 'Kết hợp OCR và xử lý ngôn ngữ tự nhiên để trích xuất dữ liệu từ giấy tờ, hóa đơn, hợp đồng; xử lý được tài liệu có cấu trúc phức tạp', 'Tham khảo cách kết hợp OCR + NLP; dữ liệu gửi lên dịch vụ, khác yêu cầu chạy nội bộ của đề tài'],
    ['SmartDoc – phần mềm tự động số hóa và rút trích thông tin tài liệu (*)', 'Nhận dạng và rút trích thông tin văn bản hành chính theo thể thức của Bộ Nội vụ', 'Gần nhất với hướng AI trích xuất metadata văn bản hành chính của đề tài'],
  ]),

  h(1, '4. Phần mềm mã nguồn mở quốc tế'),
  table([2.0, 4.8, 3.2], [
    ['Sản phẩm', 'Chức năng chính', 'Liên hệ với đề tài'],
    ['Archivematica (Artefactual Systems, giấy phép AGPLv3)', 'Ứng dụng web mã nguồn mở bảo quản lâu dài tài liệu số theo chuẩn; xử lý tài liệu từ tiếp nhận đến lưu trữ; gồm dịch vụ lưu trữ và kho chính sách định dạng', 'Tham khảo mô hình OAIS và gói tin SIP cho khâu bàn giao; không có khâu scan, nhập liệu'],
    ['Paperless-ngx (GPL-3.0)', 'Quản lý tài liệu số: OCR bằng Tesseract (hơn 100 ngôn ngữ), lưu bản PDF/A cùng bản gốc, tự động gán nhãn, loại tài liệu bằng học máy, hệ thống workflow, phân quyền nhiều người dùng', 'Tham khảo cách tự động phân loại và lưu PDF/A; hướng tới cá nhân/văn phòng, không có quy trình thi công nhiều công đoạn và quản lý cộng tác viên'],
    ['OCRmyPDF (MPL-2.0)', 'Công cụ dòng lệnh thêm lớp chữ OCR vào PDF scan, xuất PDF/A mặc định, có chỉnh nghiêng và làm sạch ảnh, dùng Tesseract', 'Ứng viên cho bước chuyển PDF/A và tạo lớp chữ tìm kiếm được'],
    ['VietOCR (Apache 2.0)', 'Thư viện nhận dạng dòng chữ tiếng Việt in và viết tay, hai kiến trúc Transformer và Seq2Seq', 'Ứng viên engine OCR tiếng Việt để so sánh trong thực nghiệm'],
    ['PaddleOCR (Apache 2.0)', 'Bộ công cụ OCR và AI tài liệu: phát hiện, nhận dạng chữ, phân tích tài liệu, trích xuất bảng biểu', 'Ứng viên engine OCR và phân tích bố cục; cần kiểm tra độ chính xác với tiếng Việt'],
  ]),

  h(1, '5. Đồ án, luận văn và nghiên cứu liên quan'),
  h(2, '5.1. Các công trình tìm được qua tra cứu (*)'),
  table([4.2, 2.6, 3.2], [
    ['Công trình', 'Đơn vị / nơi công bố', 'Nội dung liên quan'],
    ['So sánh các giải pháp OCR trong nhận dạng văn bằng tiếng Việt và đề xuất ứng dụng thực tiễn', 'Tạp chí Khoa học Trường Đại học Mở Hà Nội', 'So sánh các phương pháp OCR (trong đó có mô hình ngôn ngữ thị giác và EasyOCR) cho văn bản tiếng Việt'],
    ['Nghiên cứu và ứng dụng Tesseract OCR trong xử lý văn bản tiếng Việt', 'Trường Đại học Duy Tân (luận văn)', 'Ứng dụng Tesseract cho tiếng Việt'],
    ['Đề án số hóa tài liệu lưu trữ tại Cục Phục vụ Ngoại giao đoàn (Bộ Ngoại giao)', 'Trường ĐH Khoa học Xã hội và Nhân văn – ĐHQG Hà Nội', 'Nguyên tắc, quy trình kỹ thuật và tổ chức số hóa tài liệu lưu trữ'],
    ['Số hóa tài liệu lưu trữ tại Kho Lưu trữ Trung ương Đảng: khảo sát, đánh giá và kiến nghị', 'Trường ĐH Khoa học Xã hội và Nhân văn – ĐHQG Hà Nội (luận văn)', 'Khảo sát thực tiễn số hóa tại kho lưu trữ'],
    ['Số hóa và tổ chức khai thác sử dụng tài liệu số hóa tại các lưu trữ lịch sử', 'Trường ĐH Khoa học Xã hội và Nhân văn – ĐHQG Hà Nội (luận án)', 'Tổ chức số hóa và khai thác tài liệu số hóa'],
  ]),
  p('Nhận xét: các công trình nhóm ngành lưu trữ học tập trung vào quy trình, tổ chức và chính sách số hóa; các công trình nhóm công nghệ tập trung vào độ chính xác OCR. Chưa thấy công trình nào kết hợp **quản lý thi công số hóa nhiều công đoạn** với **AI hỗ trợ nhập liệu và kiểm tra chất lượng** trong cùng một hệ thống.'),
  h(2, '5.2. Đồ án tốt nghiệp năm trước của khoa'),
  p('Bổ sung từ thư viện khoa hoặc giảng viên hướng dẫn (2–3 đồ án gần nhất có liên quan đến quản lý quy trình, xử lý tài liệu hoặc OCR):', { run: { italics: true } }),
  table([3.6, 2.2, 1.2, 3.0], [
    ['Tên đồ án', 'Sinh viên', 'Năm', 'Điểm tương đồng / khác biệt'],
    ['[……]', '[……]', '[……]', '[……]'],
    ['[……]', '[……]', '[……]', '[……]'],
    ['[……]', '[……]', '[……]', '[……]'],
  ]),

  h(1, '6. So sánh với đề tài'),
  p('Ký hiệu: ✔ có; ◐ có một phần; – không phải chức năng chính theo mô tả công bố; ? chưa rõ.', { run: { italics: true } }),
  table([3.0, 1.4, 1.4, 1.4, 1.4, 1.4], [
    ['Tiêu chí', 'Phần mềm hiện có', 'VNPT / FPT.AI Reader', 'Archivematica', 'Paperless-ngx', 'Đề tài'],
    ['Quản lý quy trình thi công 7 công đoạn', '◐', '–', '–', '–', '✔'],
    ['Giao việc, thu hồi, cộng tác viên có thời hạn', '◐', '–', '–', '–', '✔'],
    ['So khớp mục lục với kết quả scan, kiểm tra scan 100%', '–', '–', '–', '–', '✔'],
    ['Kiểm tra nhập liệu 2 vòng (100% + lấy mẫu)', '◐', '–', '–', '–', '✔'],
    ['OCR tiếng Việt', '◐', '✔', '–', '◐', '✔'],
    ['Trích xuất metadata văn bản hành chính', '–', '✔', '–', '◐', '✔'],
    ['Kiểm tra chất lượng ảnh scan bằng AI', '–', '–', '–', '–', '✔'],
    ['PDF/A, đóng gói SIP, checksum', '–', '–', '✔', '◐', '✔'],
    ['Sản lượng, KPI, chi trả cộng tác viên', '–', '–', '–', '–', '✔'],
    ['Chạy nội bộ, không gửi dữ liệu ra ngoài', '✔', '?', '✔', '✔', '✔'],
  ]),

  h(1, '7. Điểm mới của đề tài'),
  ...bullets([
    'Kết hợp trong **một hệ thống** việc quản lý thi công số hóa nhiều công đoạn và AI hỗ trợ con người, thay vì dùng rời rạc phần mềm quản lý và dịch vụ OCR.',
    '**Kiểm soát chất lượng tại nguồn:** so khớp bắt buộc mục lục với kết quả scan, kiểm tra 100% có bằng chứng đã mở file, kiểm tra nhập liệu lấy mẫu có ngưỡng lỗi.',
    '**AI chạy nội bộ** phù hợp với tài liệu nhạy cảm của cơ quan nhà nước.',
    '**Đánh giá định lượng** module AI bằng chính dữ liệu đã được con người kiểm tra trong quá trình vận hành thật.',
    'Quản lý **sản lượng theo trang, KPI và chi trả** cho cộng tác viên, gắn với kết quả kiểm tra chất lượng.',
  ]),

  h(1, '8. Nguồn tham khảo'),
  ...numbered([
    'Archivematica – https://github.com/artefactual/archivematica (truy cập 04/10/2026).',
    'Paperless-ngx – https://github.com/paperless-ngx/paperless-ngx; tài liệu docs/index.md trong cùng kho mã (truy cập 04/10/2026).',
    'OCRmyPDF – https://github.com/ocrmypdf/OCRmyPDF (truy cập 04/10/2026).',
    'VietOCR – https://github.com/pbcquoc/vietocr (truy cập 04/10/2026).',
    'PaddleOCR – https://github.com/PaddlePaddle/PaddleOCR (truy cập 04/10/2026).',
    '(*) VNPT SmartReader – https://smartreader.vnpt.vn/en/feature.',
    '(*) FPT.AI Reader – https://fpt.ai/blogs/how-to-use-fpt-ai-reader/.',
    '(*) Phần mềm tự động số hóa và rút trích thông tin tài liệu SmartDoc – https://bavutex.baria-vungtau.gov.vn/public/tin-tuc/phan-mem-tu-dong-so-hoa-va-rut-trich-thong-tin-tai-lieu-smartdoc.html.',
    '(*) So sánh các giải pháp OCR trong nhận dạng văn bằng tiếng Việt và đề xuất ứng dụng thực tiễn – https://jshou.edu.vn/houjs/article/view/720.',
    '(*) Nghiên cứu và ứng dụng Tesseract OCR trong xử lý văn bản tiếng Việt – https://elib.duytan.edu.vn/Luanvan/Detail/14698.',
    '(*) Đề án số hóa tài liệu lưu trữ tại Cục Phục vụ Ngoại giao đoàn – https://ussh.vnu.edu.vn/vi/dao-tao/luan-van/ttda-de-an-so-hoa-tai-lieu-luu-tru-tai-cuc-phuc-vu-ngoai-giao-doan-bo-ngoai-giao-23406.html.',
    '(*) Số hóa tài liệu lưu trữ tại Kho Lưu trữ Trung ương Đảng – https://ussh.vnu.edu.vn/vi/dao-tao/luan-van/ttlv-so-hoa-tai-lieu-luu-tru-tai-kho-luu-tru-trung-uong-dang-khao-sat-danh-gia-va-kien-nghi-10620.html.',
    '(*) Số hóa và tổ chức khai thác sử dụng tài liệu số hóa tại các lưu trữ lịch sử – https://ussh.vnu.edu.vn/vi/dao-tao/luan-an/ttla-so-hoa-va-to-chuc-khai-thac-su-dung-tai-lieu-so-hoa-tai-cac-luu-tru-lich-su-dap-ung-yeu-cau-phat-trien-nhan-van-so-o-viet-nam-22139.html.',
  ]),
];

build(process.argv[2] || 'thesis/04_San_pham_do_an_lien_quan.docx', children);
