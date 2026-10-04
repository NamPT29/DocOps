const { p, bullets, numbered, table, h, titleBlock, build } = require('./lib');

const outline = [
  ['MỞ ĐẦU', [
    'Lý do chọn đề tài',
    'Mục tiêu và nhiệm vụ của đề tài',
    'Đối tượng và phạm vi nghiên cứu',
    'Phương pháp thực hiện',
    'Bố cục báo cáo',
  ]],
  ['CHƯƠNG 1. TỔNG QUAN VỀ SỐ HÓA TÀI LIỆU LƯU TRỮ', [
    '1.1. Khái niệm và vai trò của số hóa tài liệu lưu trữ',
    '1.2. Quy trình số hóa tài liệu lưu trữ: chỉnh lý, scan, kiểm tra scan, nhập liệu, kiểm tra nhập liệu, chuẩn hóa, bàn giao',
    '1.3. Các quy định và tiêu chuẩn liên quan: định dạng PDF/A, chữ ký số, metadata hồ sơ/tài liệu, gói tin SIP',
    '1.4. Khảo sát hiện trạng tại đơn vị thi công số hóa và các khó khăn',
    '1.5. Khảo sát các hệ thống và đồ án liên quan',
    '1.6. Phát biểu bài toán và hướng giải quyết của đề tài',
  ]],
  ['CHƯƠNG 2. CƠ SỞ LÝ THUYẾT VÀ CÔNG NGHỆ', [
    '2.1. Kiến trúc ứng dụng web nhiều lớp và mẫu Repository',
    '2.2. Công nghệ phía máy chủ: Python, FastAPI, SQLAlchemy, PostgreSQL, Alembic',
    '2.3. Công nghệ phía giao diện: HTML/JavaScript, Bootstrap, PDF.js',
    '2.4. Mô hình máy trạng thái (state machine) trong quản lý quy trình',
    '2.5. Nhận dạng ký tự quang học (OCR) cho văn bản tiếng Việt',
    '2.6. Trích xuất thông tin có cấu trúc (metadata) từ văn bản hành chính',
    '2.7. Đánh giá chất lượng ảnh tài liệu bằng thị giác máy tính',
    '2.8. Bảo mật, phân quyền, nhật ký kiểm toán và bảo vệ dữ liệu cá nhân',
  ]],
  ['CHƯƠNG 3. PHÂN TÍCH VÀ THIẾT KẾ HỆ THỐNG', [
    '3.1. Xác định tác nhân và yêu cầu chức năng, phi chức năng',
    '3.2. Mô hình hóa quy trình nghiệp vụ hiện tại (as-is) và đề xuất (to-be)',
    '3.3. Biểu đồ use case và đặc tả các use case chính',
    '3.4. Thiết kế máy trạng thái cho quy trình 7 bước',
    '3.5. Thiết kế cơ sở dữ liệu',
    '3.6. Thiết kế kiến trúc tổng thể và API',
    '3.7. Thiết kế module AI: trích xuất metadata tự động và kiểm tra chất lượng ảnh scan',
    '3.8. Thiết kế giao diện người dùng',
  ]],
  ['CHƯƠNG 4. XÂY DỰNG VÀ TRIỂN KHAI HỆ THỐNG', [
    '4.1. Môi trường và công cụ phát triển',
    '4.2. Xây dựng các module nghiệp vụ: chỉnh lý, giao việc, scan, kiểm tra scan, nhập liệu, kiểm tra nhập liệu, chuẩn hóa, bàn giao',
    '4.3. Xây dựng module AI hỗ trợ nhập liệu và kiểm tra chất lượng ảnh',
    '4.4. Sản lượng, KPI, đối soát và báo cáo',
    '4.5. Triển khai hệ thống trên máy chủ nội bộ',
    '4.6. Kết quả giao diện chương trình',
  ]],
  ['CHƯƠNG 5. KIỂM THỬ VÀ ĐÁNH GIÁ', [
    '5.1. Kiểm thử chức năng và kiểm thử tự động',
    '5.2. Kiểm thử hiệu năng với người dùng đồng thời',
    '5.3. Thực nghiệm và so sánh các engine OCR tiếng Việt',
    '5.4. Đánh giá độ chính xác trích xuất metadata và thời gian nhập liệu tiết kiệm được',
    '5.5. Đánh giá module kiểm tra chất lượng ảnh scan',
    '5.6. Kết quả chạy thực tế tại đơn vị',
  ]],
  ['KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN', [
    'Kết quả đạt được',
    'Hạn chế',
    'Hướng phát triển',
  ]],
  ['TÀI LIỆU THAM KHẢO', []],
  ['PHỤ LỤC', [
    'Phụ lục A. Đặc tả yêu cầu nghiệp vụ (BA)',
    'Phụ lục B. Hướng dẫn cài đặt và sử dụng',
  ]],
];

const children = [
  ...titleBlock('ĐỀ CƯƠNG CHI TIẾT'),

  h(1, '1. Lý do chọn đề tài'),
  p('Số hóa tài liệu lưu trữ là nhiệm vụ trọng tâm của các cơ quan, tổ chức trong quá trình chuyển đổi số. Một dự án số hóa gồm nhiều công đoạn nối tiếp nhau: chỉnh lý hồ sơ giấy, scan, kiểm tra scan, nhập metadata, kiểm tra nhập liệu, chuẩn hóa (làm sạch, chuyển định dạng PDF/A, ký số, đóng gói) và bàn giao.'),
  p('Khảo sát tại một đơn vị thi công số hóa cho thấy phần lớn quy trình đang được quản lý thủ công bằng bảng tính Excel. Cách làm này dẫn đến các vấn đề:'),
  ...bullets([
    'Không theo dõi được một hồ sơ đang ở công đoạn nào, ai đang giữ hồ sơ giấy.',
    'Sai lệch số trang, số file giữa các công đoạn không được phát hiện và xử lý có hệ thống.',
    'Nhập liệu metadata hoàn toàn thủ công, tốn nhiều nhân lực (hàng chục cộng tác viên), dễ sai sót.',
    'Sản lượng, KPI và chi trả cho cộng tác viên phải tính tay, khó đối soát.',
    'Lỗi chất lượng ảnh scan (mờ, nghiêng, thiếu trang) chỉ được phát hiện muộn ở khâu kiểm tra.',
  ]),
  p('Đề tài xây dựng một hệ thống web quản lý khép kín toàn bộ quy trình số hóa, đồng thời **tích hợp AI** để hỗ trợ hai khâu tốn công nhất: tự động gợi ý metadata từ bản scan và tự động phát hiện lỗi chất lượng ảnh.'),

  h(1, '2. Mục tiêu của đề tài'),
  h(2, '2.1. Mục tiêu tổng quát'),
  p('Xây dựng hệ thống số hóa tài liệu tích hợp AI, quản lý xuyên suốt 7 công đoạn của dự án số hóa, đảm bảo truy vết, kiểm soát chất lượng và giảm thời gian nhập liệu.'),
  h(2, '2.2. Mục tiêu cụ thể'),
  ...bullets([
    'Quản lý dự án, hộp, hồ sơ, file PDF và trạng thái của từng hồ sơ qua 7 công đoạn.',
    'Phân quyền theo 3 vai trò (Quản trị, Nhân sự hành chính, Cộng tác viên); giao việc, thu hồi và phân lại công việc.',
    'Kiểm soát chất lượng: so khớp đường dẫn chỉnh lý với kết quả scan, kiểm tra scan 100%, kiểm tra nhập liệu 2 vòng (100% và lấy mẫu 30%).',
    'Tích hợp OCR tiếng Việt và mô hình trích xuất để gợi ý metadata văn bản (số/ký hiệu, ngày ban hành, cơ quan ban hành, trích yếu).',
    'Tự động phát hiện lỗi chất lượng ảnh scan (mờ, nghiêng, trang trắng, thiếu nội dung).',
    'Tính sản lượng theo trang, KPI, đối soát và đóng gói bàn giao (PDF/A, checksum, biên bản).',
    'Đánh giá định lượng hiệu quả của module AI trên dữ liệu thực tế.',
  ]),

  h(1, '3. Đối tượng và phạm vi nghiên cứu'),
  h(2, '3.1. Đối tượng'),
  ...bullets([
    'Quy trình thi công số hóa tài liệu lưu trữ hành chính (công văn, quyết định, nghị quyết…).',
    'Các kỹ thuật OCR tiếng Việt, trích xuất thông tin và đánh giá chất lượng ảnh tài liệu.',
  ]),
  h(2, '3.2. Phạm vi'),
  ...bullets([
    'Ứng dụng web chạy trên máy tính (Chrome, Edge); máy chủ đặt tại đơn vị, cộng tác viên truy cập qua Internet.',
    'Quy mô: khoảng 50 tài khoản nội bộ, tối đa 100 cộng tác viên đồng thời, khoảng 20.000 file PDF mỗi dự án.',
    'Ký số thực hiện bằng phần mềm chuyên dụng bên ngoài; hệ thống quản lý trạng thái ký và nhận lại file đã ký.',
    'Không bao gồm: tính lương kế toán, quản lý thiết bị, ứng dụng di động.',
  ]),

  h(1, '4. Phương pháp thực hiện'),
  ...bullets([
    '**Khảo sát thực tế:** phỏng vấn đơn vị thi công, phân tích file thống kê và phiếu yêu cầu của dự án thật.',
    '**Phân tích nghiệp vụ (BA):** xây dựng tài liệu yêu cầu với mã truy vết FR/BR/NFR, user story và tiêu chí chấp nhận.',
    '**Phát triển lặp:** chia nhỏ theo module, mỗi phần có kiểm thử tự động và được commit riêng.',
    '**Thực nghiệm:** so sánh các engine OCR và đánh giá module AI trên bộ dữ liệu đã được kiểm tra bởi con người.',
  ]),

  h(1, '5. Nội dung đề cương chi tiết (đến đề mục cấp 2)'),
  ...outline.flatMap(([chapter, items]) => [
    h(2, chapter),
    ...(items.length ? bullets(items) : [p('Danh mục tài liệu tham khảo (mục 8).', { run: { italics: true } })]),
  ]),

  h(1, '6. Kết quả dự kiến'),
  ...bullets([
    'Hệ thống web chạy thật cho một dự án số hóa, quản lý đủ 7 công đoạn.',
    'Module AI gợi ý metadata và kiểm tra chất lượng ảnh scan, có số liệu đánh giá (độ chính xác theo trường, tỉ lệ lỗi ký tự, thời gian nhập tiết kiệm).',
    'Bộ tài liệu: đặc tả yêu cầu (BA), thiết kế hệ thống, hướng dẫn cài đặt và sử dụng, báo cáo đồ án.',
  ]),

  h(1, '7. Kế hoạch thực hiện (dự kiến)'),
  table([1.4, 4.2, 2.4], [
    ['Thời gian', 'Công việc', 'Kết quả'],
    ['Tuần 1', 'Khảo sát, phân tích nghiệp vụ, chốt đề cương', 'Tài liệu BA, đề cương'],
    ['Tuần 2–3', 'Xây dựng các module nghiệp vụ 7 công đoạn, chạy thử với dữ liệu thật', 'Bản hệ thống chạy thật'],
    ['Tuần 4–5', 'Nghiên cứu, thử nghiệm các engine OCR tiếng Việt', 'Bảng so sánh OCR'],
    ['Tuần 6–7', 'Xây dựng module trích xuất metadata và kiểm tra chất lượng ảnh', 'Module AI tích hợp'],
    ['Tuần 8–9', 'Kiểm thử, đánh giá định lượng, hoàn thiện hệ thống', 'Số liệu thực nghiệm'],
    ['Tuần 10–12', 'Viết báo cáo, chuẩn bị bảo vệ', 'Báo cáo đồ án, slide'],
  ]),

  h(1, '8. Tài liệu tham khảo dự kiến'),
  ...numbered([
    'Quốc hội (2024), Luật Lưu trữ số 33/2024/QH15.',
    'Chính phủ (2023), Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.',
    'Bộ Nội vụ (2019), Thông tư 02/2019/TT-BNV quy định tiêu chuẩn dữ liệu thông tin đầu vào và yêu cầu bảo quản tài liệu lưu trữ điện tử.',
    'ISO 19005 (PDF/A) – Document management: Electronic document file format for long-term preservation.',
    'ISO 14721 – Open Archival Information System (OAIS) Reference Model (khái niệm gói tin SIP).',
    'R. Smith (2007), An Overview of the Tesseract OCR Engine, ICDAR 2007.',
    'Y. Du et al. (2020), PP-OCR: A Practical Ultra Lightweight OCR System, arXiv:2009.09941.',
    'VietOCR – Vietnamese OCR toolkit, https://github.com/pbcquoc/vietocr.',
    'Y. Xu et al. (2020), LayoutLM: Pre-training of Text and Layout for Document Image Understanding, KDD 2020.',
    'Tài liệu chính thức FastAPI (https://fastapi.tiangolo.com), SQLAlchemy, PostgreSQL, Alembic.',
  ]),
];

build(process.argv[2] || 'thesis/01_De_cuong_chi_tiet.docx', children);
