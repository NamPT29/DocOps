const { p, bullets, numbered, table, h, titleBlock, build } = require('./lib');

const children = [
  ...titleBlock('BẢN MÔ TẢ TỔNG QUAN CÁC CHỨC NĂNG CHÍNH CỦA SẢN PHẨM'),

  h(1, '1. Giới thiệu sản phẩm'),
  p('**Hệ thống số hóa tài liệu tích hợp AI** là ứng dụng web quản lý khép kín toàn bộ quy trình thi công một dự án số hóa tài liệu lưu trữ, từ khi nhận hồ sơ giấy đến khi bàn giao dữ liệu số cho khách hàng. Hệ thống được xây dựng để thay thế cách quản lý thủ công bằng Excel tại một đơn vị thi công số hóa và được áp dụng cho dự án số hóa tài liệu hành chính (công văn, quyết định, nghị quyết…).'),
  p('Ba giá trị chính của sản phẩm:'),
  ...bullets([
    '**Truy vết xuyên suốt:** biết mỗi hộp, hồ sơ, file PDF đang ở công đoạn nào, do ai thực hiện, đã qua những lần kiểm tra nào.',
    '**Kiểm soát chất lượng tại nguồn:** chặn sai lệch ngay ở công đoạn phát sinh thay vì phát hiện khi bàn giao.',
    '**AI hỗ trợ con người:** tự động gợi ý metadata từ bản scan và tự động phát hiện ảnh scan kém chất lượng; con người luôn là người duyệt cuối cùng.',
  ]),

  h(1, '2. Người dùng và vai trò'),
  table([2.2, 4.3, 3.5], [
    ['Vai trò', 'Công việc chính', 'Giới hạn'],
    ['Quản trị (Admin, PM)', 'Cấu hình dự án, quản lý tài khoản, giao việc, làm sạch, đóng gói, bàn giao, duyệt chi trả, xem báo cáo', 'Không tự kiểm tra việc do chính mình làm'],
    ['Nhân sự hành chính', 'Chỉnh lý, scan, kiểm tra scan, nhập liệu, kiểm tra nhập liệu', 'Không kiểm tra việc của chính mình'],
    ['Cộng tác viên (CTV)', 'Nhập metadata hồ sơ và văn bản qua Internet', 'Chỉ thấy việc được giao, không tải được PDF, tài khoản có thời hạn'],
  ]),
  p('Quy mô thiết kế: khoảng 50 tài khoản nội bộ và tối đa 100 cộng tác viên làm việc đồng thời; mỗi dự án khoảng 20.000 file PDF.'),

  h(1, '3. Quy trình tổng thể'),
  p('Mỗi hộp hồ sơ đi qua 7 công đoạn. Một công đoạn chỉ được bắt đầu khi công đoạn trước đã hoàn tất; công đoạn kiểm tra có thể trả lại để làm lại (rework).'),
  table([0.6, 2.2, 4.4, 2.8], [
    ['#', 'Công đoạn', 'Hệ thống hỗ trợ', 'Đầu ra'],
    ['1', 'Chỉnh lý', 'Import Excel mục lục (năm, cơ quan, thể loại, hộp, hồ sơ); theo dõi giao nhận hồ sơ giấy', 'Danh sách hồ sơ có mã định danh'],
    ['2', 'Scan', 'Người scan bấm "Nộp S" cho từng hộp; hệ thống quét thư mục, lập danh sách file, số trang, mã kiểm tra', 'Gói scan (S) có phiên bản'],
    ['3', 'Kiểm tra scan', 'So khớp thư mục với mục lục; kiểm tra 100% (bắt buộc mở từng file); AI cảnh báo ảnh kém chất lượng', 'Gói scan đã duyệt (CS)'],
    ['4', 'Nhập liệu', 'Biểu mẫu nhập metadata hồ sơ và văn bản; AI gợi ý sẵn các trường', 'Bản ghi metadata'],
    ['5', 'Kiểm tra nhập liệu', 'Kiểm tra 1 (100%) và kiểm tra 2 (lấy mẫu 30%, ngưỡng lỗi 5%)', 'Dữ liệu đã duyệt'],
    ['6', 'Chuẩn hóa', 'Làm sạch tên file/đường dẫn; chuyển PDF/A; quản lý trạng thái ký số', 'File PDF/A đã ký'],
    ['7', 'Bàn giao', 'Đóng gói SIP, tính checksum, sinh biên bản; nghiệm thu', 'Gói bàn giao'],
  ]),

  h(1, '4. Các chức năng chính'),
  h(2, '4.1. Quản trị hệ thống và dự án'),
  ...bullets([
    'Quản lý tài khoản theo 3 vai trò; tài khoản cộng tác viên có ngày hết hạn, tự khóa và tự thu hồi việc khi hết hạn.',
    'Tạo dự án, cấu hình thư mục gốc, cấu trúc đường dẫn, biểu mẫu nhập liệu, danh mục mã (thời hạn lưu trữ, tên loại văn bản…).',
    'Cấu hình chính sách theo thời gian hiệu lực: KPI, đơn giá, ngưỡng lỗi, tỉ lệ lấy mẫu, hạn giao việc.',
    'Bật/tắt các công đoạn áp dụng cho từng dự án.',
  ]),
  h(2, '4.2. Chỉnh lý và giao việc'),
  ...bullets([
    'Import Excel mục lục: xem trước, kiểm tra trùng/thiếu/sai định dạng, giữ nguyên số 0 ở đầu mã, lưu dòng nguồn để truy vết.',
    'Theo dõi 5 mốc giao nhận hồ sơ giấy: nhận từ khách, giao chỉnh lý, giao scan, trả kho, trả khách.',
    'Giao việc theo hộp, hạn mặc định 2 ngày; thu hồi và phân lại khi cộng tác viên không tiếp tục được (giữ bản nháp).',
  ]),
  h(2, '4.3. Scan và kiểm tra scan'),
  ...bullets([
    'Nộp gói scan theo hộp; hệ thống tự đếm số trang, tính mã SHA-256, cảnh báo file đang chép dở.',
    'So khớp bắt buộc giữa thư mục hồ sơ và mục lục chỉnh lý; chênh lệch phải có lý do xử lý mới được duyệt.',
    'Kiểm tra 100% file: người kiểm tra phải mở từng file; sửa trực tiếp lỗi nhỏ hoặc trả về đúng người scan để làm lại.',
  ]),
  h(2, '4.4. Nhập liệu và kiểm tra nhập liệu'),
  ...bullets([
    'Xem PDF song song với biểu mẫu nhập liệu sinh tự động từ file Excel mẫu; lưu nháp, nộp, chống ghi đè đồng thời.',
    'Nhập 2 cấp metadata: hồ sơ (tiêu đề, thời hạn lưu trữ, thời gian…) và văn bản (tên loại, số/ký hiệu, ngày ban hành, cơ quan ban hành, trích yếu…).',
    'Kiểm tra 1: kiểm 100%, lưu lỗi theo từng trường (giá trị trước/sau, người kiểm tra).',
    'Kiểm tra 2: hệ thống chọn ngẫu nhiên 30% bản ghi của hộp; lỗi vượt 5% thì trả cả hộp về kiểm tra lại.',
  ]),
  h(2, '4.5. Chuẩn hóa và bàn giao'),
  ...bullets([
    'Làm sạch tên file và đường dẫn: tự sửa lỗi an toàn (khoảng trắng, chữ hoa/thường), cảnh báo lỗi cần người quyết định.',
    'Chuyển đổi PDF sang PDF/A; xuất file để ký số bằng phần mềm chuyên dụng và nạp lại file đã ký.',
    'Đóng gói bàn giao gồm PDF/A đã ký, metadata Excel, thông tin gói tin SIP, mã SHA-256 từng file và biên bản bàn giao tự sinh.',
    'Không cho đóng gói khi còn chênh lệch chưa xử lý; gói đã đóng bị khóa.',
  ]),
  h(2, '4.6. Sản lượng, KPI và báo cáo'),
  ...bullets([
    'Ghi nhận giờ công; tính sản lượng theo trang ở 4 lớp (đã làm, đã qua kiểm tra, được công nhận, đủ điều kiện chi trả).',
    'Tính KPI theo giờ làm thực tế; chi trả cộng tác viên theo sản lượng đã được công nhận.',
    'Đối soát 4 tầng (hồ sơ giấy, scan, nhập liệu, gói bàn giao); dashboard tiến độ, hộp quá hạn, năng suất, tỉ lệ lỗi.',
    'Thông báo trong hệ thống: việc mới, bị trả lại, tài khoản sắp hết hạn, hộp quá hạn, chênh lệch mới.',
    'Nhật ký kiểm toán: mọi thay đổi trạng thái, cấu hình, giao việc, kiểm tra đều được ghi lại và không thể sửa.',
  ]),

  h(1, '5. Chức năng tích hợp AI'),
  h(2, '5.1. Trích xuất metadata tự động'),
  ...bullets([
    'Chạy OCR tiếng Việt trên file PDF đã qua kiểm tra scan.',
    'Mô hình trích xuất nhận diện và gợi ý các trường: tên loại văn bản, số/ký hiệu, ngày ban hành, cơ quan ban hành, trích yếu.',
    'Người nhập chỉ xác nhận hoặc sửa; trường có độ tin cậy thấp được tô màu để chú ý.',
    'Kết quả kiểm tra của con người được dùng làm dữ liệu đo độ chính xác của AI.',
  ]),
  h(2, '5.2. Kiểm tra chất lượng ảnh scan'),
  ...bullets([
    'Tự động phát hiện trang mờ, nghiêng, trang trắng, ảnh bị cắt mất nội dung, độ phân giải thấp hơn 200 dpi.',
    'Đưa ra cảnh báo ngay khi nộp gói scan, giúp người scan sửa trước khi chuyển sang kiểm tra.',
  ]),
  p('Mô hình AI chạy trên máy chủ của đơn vị, không gửi dữ liệu ra dịch vụ bên ngoài, vì tài liệu là dữ liệu nhạy cảm.', { run: { italics: true } }),

  h(1, '6. Yêu cầu phi chức năng chính'),
  table([2.5, 7.5], [
    ['Nhóm', 'Yêu cầu'],
    ['Hiệu năng', 'Chịu tải 100 cộng tác viên đồng thời; mở một file PDF dưới 3 giây'],
    ['Khả dụng', 'Hoạt động 24/7, khung bảo trì 2h–4h sáng'],
    ['Bảo mật', 'HTTPS; khóa tạm khi đăng nhập sai nhiều lần; mỗi tài khoản một thiết bị; cách ly dữ liệu theo dự án; bảo vệ dữ liệu cá nhân theo Nghị định 13/2023/NĐ-CP'],
    ['Sao lưu', 'Sao lưu cơ sở dữ liệu và file hằng ngày, giữ 7 bản, đã thử khôi phục'],
    ['Tương thích', 'Trình duyệt Chrome, Edge trên máy tính; máy chủ Windows'],
  ]),

  h(1, '7. Công nghệ sử dụng (tóm tắt)'),
  ...bullets([
    'Máy chủ: Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL.',
    'Giao diện: HTML, JavaScript, Bootstrap, PDF.js.',
    'AI: OCR tiếng Việt (Tesseract, PaddleOCR, VietOCR – sẽ so sánh để chọn), mô hình trích xuất thông tin, kỹ thuật xử lý ảnh OpenCV.',
    'Triển khai: máy chủ Windows nội bộ, Caddy reverse proxy, sao lưu lên NAS.',
  ]),
];

build(process.argv[2] || 'thesis/02_Mo_ta_san_pham.docx', children);
