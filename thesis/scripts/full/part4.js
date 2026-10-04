// Phần đặc tả yêu cầu sơ bộ và thiết kế dự kiến (lấy từ tài liệu BA của dự án thật).
// Mỗi bảng: hàng đầu là tiêu đề cột.

module.exports.intro = 'Phần này tóm tắt kết quả khảo sát và phân tích nghiệp vụ đã thực hiện trước khi viết đề cương, làm căn cứ cho Chương 3 và Chương 4 của báo cáo. Các yêu cầu được đánh mã để truy vết từ yêu cầu đến chức năng, ca kiểm thử và kết quả đánh giá: FR (yêu cầu chức năng), BR (quy tắc nghiệp vụ), NFR (yêu cầu phi chức năng), AI (yêu cầu của module trí tuệ nhân tạo).';

module.exports.actors = [
  ['Tác nhân', 'Mô tả', 'Công việc chính trong hệ thống'],
  ['Quản trị (Admin/PM)', 'Quản lý dự án của đơn vị thi công; chịu trách nhiệm cuối cùng về chất lượng và tiến độ.', [
    'Tạo dự án, cấu hình công đoạn, biểu mẫu nhập liệu, chính sách chất lượng.',
    'Quản lý tài khoản, phân công, thu hồi việc.',
    'Chuẩn hóa dữ liệu, đóng gói, bàn giao; duyệt sản lượng chi trả.']],
  ['Hành chính (nhân viên nội bộ)', 'Nhân sự làm việc tại đơn vị, thao tác trên tài liệu giấy và file scan.', [
    'Chỉnh lý, lập mục lục hồ sơ; scan; kiểm tra scan.',
    'Nhập liệu và kiểm tra nhập liệu khi được phân công.']],
  ['Cộng tác viên (CTV)', 'Người làm việc từ xa qua Internet theo thời hạn hợp đồng.', [
    'Nhận hộp được giao, nhập metadata từng văn bản.',
    'Chỉ xem tài liệu trên trình duyệt, không tải file PDF về máy.']],
  ['Hệ thống OCR (tác nhân phụ)', 'Tiến trình chạy nền trên máy chủ nội bộ.', [
    'Kiểm tra chất lượng ảnh scan.',
    'Nhận dạng chữ và trích xuất 5 trường thông tin, ghi gợi ý kèm độ tin cậy.']],
  ['Đơn vị nhận bàn giao', 'Cơ quan chủ quản tài liệu (khách hàng).', [
    'Nhận gói bàn giao, kiểm tra và ký biên bản nghiệm thu (ngoài hệ thống).']],
];

module.exports.functional = [
  ['Mã', 'Nhóm', 'Yêu cầu', 'Ưu tiên'],
  ['FR-AUT-01', 'Tài khoản', 'Đăng nhập bằng tên đăng nhập và mật khẩu; khóa tạm khi nhập sai nhiều lần.', 'Bắt buộc'],
  ['FR-AUT-02', 'Tài khoản', 'Tài khoản CTV có ngày hết hạn; hết hạn tự động không đăng nhập được.', 'Bắt buộc'],
  ['FR-AUT-03', 'Tài khoản', 'Phân quyền theo vai trò (Admin, Hành chính, CTV) và theo phân công trong từng dự án.', 'Bắt buộc'],
  ['FR-PRJ-01', 'Dự án', 'Tạo dự án, khai báo phông, đơn vị giao, thời hạn, công đoạn được bật.', 'Bắt buộc'],
  ['FR-PRJ-02', 'Dự án', 'Cấu hình biểu mẫu nhập liệu (danh sách trường, kiểu dữ liệu, bắt buộc, danh mục chọn).', 'Bắt buộc'],
  ['FR-PRJ-03', 'Dự án', 'Cấu hình chính sách: ngưỡng lỗi cho phép, tỷ lệ lấy mẫu kiểm tra, hạn xử lý một hộp.', 'Bắt buộc'],
  ['FR-ARR-01', 'Chỉnh lý', 'Import mục lục hồ sơ từ Excel, mỗi dòng một hồ sơ; báo lỗi theo từng dòng.', 'Bắt buộc'],
  ['FR-ARR-02', 'Chỉnh lý', 'Ghi nhận giao nhận hồ sơ giấy giữa các bộ phận (người giao, người nhận, thời điểm, số lượng).', 'Nên có'],
  ['FR-SCN-01', 'Scan', 'Nộp gói scan theo hộp; hệ thống đọc cây thư mục và số trang từng file PDF.', 'Bắt buộc'],
  ['FR-SCN-02', 'Scan', 'So khớp đường dẫn thư mục hồ sơ với mục lục chỉnh lý; liệt kê thừa, thiếu, sai tên.', 'Bắt buộc'],
  ['FR-QCS-01', 'Check scan', 'Kiểm tra 100% file; ghi lỗi theo danh mục (mờ, nghiêng, thiếu trang, sai thứ tự…).', 'Bắt buộc'],
  ['FR-QCS-02', 'Check scan', 'Trả lại hộp kèm lý do; đếm số lần làm lại; không trả lại khi bước sau đã bắt đầu.', 'Bắt buộc'],
  ['FR-ENT-01', 'Nhập liệu', 'Giao hộp cho người nhập; thu hồi khi quá hạn; phân lại cho người khác.', 'Bắt buộc'],
  ['FR-ENT-02', 'Nhập liệu', 'Màn hình nhập: xem PDF và biểu mẫu song song; kiểm tra định dạng ngay khi nhập.', 'Bắt buộc'],
  ['FR-ENT-03', 'Nhập liệu', 'Hiển thị gợi ý OCR cho 5 trường; người nhập chấp nhận, sửa hoặc bỏ qua.', 'Bắt buộc'],
  ['FR-QCE-01', 'Check nhập liệu', 'Vòng 1 kiểm tra 100% bản ghi; vòng 2 lấy mẫu ngẫu nhiên theo tỷ lệ cấu hình.', 'Bắt buộc'],
  ['FR-QCE-02', 'Check nhập liệu', 'Tính tỷ lệ lỗi theo hộp; vượt ngưỡng thì trả lại toàn bộ hộp.', 'Bắt buộc'],
  ['FR-NRM-01', 'Chuẩn hóa', 'Làm sạch dữ liệu: chuẩn hóa khoảng trắng, ngày tháng, tên file, đường dẫn.', 'Bắt buộc'],
  ['FR-NRM-02', 'Chuẩn hóa', 'Chuyển PDF sang PDF/A; theo dõi trạng thái ký số từng file (xuất danh sách, nạp lại file đã ký).', 'Bắt buộc'],
  ['FR-NRM-03', 'Chuẩn hóa', 'Đóng gói SIP: file PDF/A đã ký, metadata, mã băm SHA-256, danh mục.', 'Bắt buộc'],
  ['FR-HND-01', 'Bàn giao', 'Sinh biên bản bàn giao tự động; ghi nhận nghiệm thu; khóa dữ liệu sau bàn giao.', 'Bắt buộc'],
  ['FR-HND-02', 'Bàn giao', 'Đối soát số liệu giữa các công đoạn (số hồ sơ, số file, số trang).', 'Nên có'],
  ['FR-KPI-01', 'Sản lượng', 'Tính sản lượng theo trang cho từng người, từng công đoạn; Admin nhập giờ công.', 'Bắt buộc'],
  ['FR-KPI-02', 'Sản lượng', 'Tổng hợp sản lượng được chi trả theo dự án sau khi Admin duyệt.', 'Nên có'],
  ['FR-DSH-01', 'Báo cáo', 'Bảng điều khiển tiến độ theo công đoạn, theo người, theo ngày.', 'Nên có'],
  ['FR-AUD-01', 'Truy vết', 'Ghi nhật ký mọi lần chuyển trạng thái (ai, khi nào, từ trạng thái nào sang trạng thái nào, lý do).', 'Bắt buộc'],
];

module.exports.ai = [
  ['Mã', 'Yêu cầu', 'Tiêu chí chấp nhận dự kiến'],
  ['AI-01', 'Kiểm tra chất lượng ảnh trang scan: mờ, nghiêng, trang trắng, độ phân giải thấp.', 'Phát hiện đúng ≥ 90% trang lỗi trên tập kiểm tra có nhãn.'],
  ['AI-02', 'Tiền xử lý ảnh: chỉnh nghiêng, khử nhiễu, nhị phân hóa trước khi OCR.', 'CER sau tiền xử lý thấp hơn CER trên ảnh gốc.'],
  ['AI-03', 'Nhận dạng chữ tiếng Việt có dấu trên trang đầu văn bản.', 'CER ≤ 5% trên văn bản in rõ.'],
  ['AI-04', 'Trích xuất 5 trường: tên loại, số và ký hiệu, ngày ban hành, cơ quan ban hành, trích yếu.', 'Độ chính xác khớp đúng ≥ 85% với trường có cấu trúc (số ký hiệu, ngày); điểm tương đồng ≥ 0,8 với trích yếu.'],
  ['AI-05', 'Trả về độ tin cậy cho từng trường; trường có độ tin cậy thấp được đánh dấu cho người nhập.', 'Độ tin cậy tương quan với tỷ lệ đúng (đường hiệu chuẩn).'],
  ['AI-06', 'Chạy nền, không chặn thao tác nhập liệu; toàn bộ xử lý trên máy chủ nội bộ.', 'Không gửi dữ liệu ra ngoài; thời gian xử lý ≤ 5 giây mỗi văn bản.'],
  ['AI-07', 'Ghi lại giá trị gợi ý và giá trị cuối cùng sau kiểm tra để làm dữ liệu đánh giá và cải tiến.', 'Có đủ cặp (gợi ý, giá trị đúng) cho mọi bản ghi đã qua kiểm tra.'],
];

module.exports.rules = [
  ['Mã', 'Quy tắc nghiệp vụ'],
  ['BR-01', 'Thư mục hồ sơ trong gói scan phải khớp với mục lục chỉnh lý; chưa khớp thì không được chuyển sang kiểm tra scan.'],
  ['BR-02', 'Công đoạn sau chỉ được bắt đầu khi công đoạn được bật liền trước đã hoàn thành.'],
  ['BR-03', 'Trả lại một công đoạn bắt buộc có lý do; mỗi lần trả lại tăng số lần làm lại của hộp.'],
  ['BR-04', 'Không ai được kiểm tra, duyệt kết quả do chính mình làm, kể cả Admin.'],
  ['BR-05', 'Không được trả lại hoặc mở lại một công đoạn khi công đoạn phía sau đã bắt đầu.'],
  ['BR-06', 'Một hộp nhập liệu có hạn xử lý 2 ngày; quá hạn thì Admin được thu hồi và giao lại.'],
  ['BR-07', 'Tỷ lệ lỗi nhập liệu của một hộp vượt 5% thì trả lại toàn bộ hộp.'],
  ['BR-08', 'Vòng kiểm tra thứ hai lấy mẫu ngẫu nhiên 30% số bản ghi của hộp.'],
  ['BR-09', 'Sản lượng tính theo số trang; chỉ phần đã qua kiểm tra mới được tính chi trả.'],
  ['BR-10', 'Công đoạn chuẩn hóa và bàn giao chỉ do Admin thực hiện.'],
  ['BR-11', 'CTV chỉ xem tài liệu trên trình duyệt, không được tải file PDF gốc.'],
  ['BR-12', 'Dữ liệu dự án đã bàn giao bị khóa, mọi thay đổi sau đó phải mở khóa có ghi nhật ký.'],
  ['BR-13', 'Gợi ý OCR chỉ là đề xuất; giá trị lưu vào hệ thống luôn do con người xác nhận.'],
];

module.exports.nonFunctional = [
  ['Mã', 'Nhóm', 'Yêu cầu'],
  ['NFR-01', 'Hiệu năng', 'Phục vụ khoảng 50 tài khoản nội bộ và 100 CTV truy cập đồng thời; thời gian phản hồi thao tác thông thường dưới 2 giây.'],
  ['NFR-02', 'Quy mô dữ liệu', 'Khoảng 20.000 file PDF mỗi dự án; danh sách có phân trang và lọc phía máy chủ.'],
  ['NFR-03', 'Bảo mật', 'HTTPS; mật khẩu băm; phiên đăng nhập có hạn; kiểm tra quyền ở mọi API; chính sách CSP chặn mã nhúng.'],
  ['NFR-04', 'Riêng tư dữ liệu', 'Máy chủ đặt tại đơn vị; dữ liệu và xử lý OCR không rời khỏi hạ tầng nội bộ.'],
  ['NFR-05', 'Sẵn sàng', 'Hoạt động trong giờ làm việc; bảo trì định kỳ trong khung 2h–4h sáng.'],
  ['NFR-06', 'Sao lưu', 'Sao lưu cơ sở dữ liệu hằng ngày; có kịch bản và kiểm thử khôi phục.'],
  ['NFR-07', 'Khả dụng', 'Giao diện tiếng Việt; chạy trên Chrome, Edge bản mới; thao tác nhập liệu dùng được hoàn toàn bằng bàn phím.'],
  ['NFR-08', 'Bảo trì', 'Mã nguồn chia lớp (router, service, repository); kiểm thử tự động; migration cơ sở dữ liệu có phiên bản.'],
  ['NFR-09', 'Truy vết', 'Nhật ký chuyển trạng thái chỉ ghi thêm, không sửa, không xóa.'],
];

module.exports.useCases = [
  ['Mã', 'Tên use case', 'Tác nhân', 'Yêu cầu liên quan'],
  ['UC-01', 'Đăng nhập, đổi mật khẩu', 'Tất cả', 'FR-AUT-01'],
  ['UC-02', 'Quản lý tài khoản và hạn sử dụng', 'Admin', 'FR-AUT-02, FR-AUT-03'],
  ['UC-03', 'Tạo và cấu hình dự án', 'Admin', 'FR-PRJ-01..03'],
  ['UC-04', 'Import mục lục chỉnh lý', 'Admin, Hành chính', 'FR-ARR-01'],
  ['UC-05', 'Nộp gói scan và so khớp đường dẫn', 'Hành chính', 'FR-SCN-01, FR-SCN-02, BR-01'],
  ['UC-06', 'Kiểm tra scan, trả lại làm lại', 'Hành chính', 'FR-QCS-01, FR-QCS-02, BR-03..05'],
  ['UC-07', 'Giao, thu hồi hộp nhập liệu', 'Admin', 'FR-ENT-01, BR-06'],
  ['UC-08', 'Nhập metadata có gợi ý OCR', 'Hành chính, CTV', 'FR-ENT-02, FR-ENT-03, AI-04, BR-13'],
  ['UC-09', 'Kiểm tra nhập liệu hai vòng', 'Admin, Hành chính', 'FR-QCE-01, FR-QCE-02, BR-07, BR-08'],
  ['UC-10', 'Chạy OCR và kiểm tra chất lượng ảnh', 'Hệ thống OCR', 'AI-01..AI-06'],
  ['UC-11', 'Chuẩn hóa, PDF/A, theo dõi ký số', 'Admin', 'FR-NRM-01, FR-NRM-02'],
  ['UC-12', 'Đóng gói SIP và bàn giao', 'Admin', 'FR-NRM-03, FR-HND-01, FR-HND-02'],
  ['UC-13', 'Nhập giờ công, xem sản lượng, duyệt chi trả', 'Admin', 'FR-KPI-01, FR-KPI-02, BR-09'],
  ['UC-14', 'Xem tiến độ và nhật ký truy vết', 'Admin', 'FR-DSH-01, FR-AUD-01'],
];

module.exports.useCaseSpecs = [
  {
    title: 'UC-05. Nộp gói scan và so khớp đường dẫn',
    rows: [
      ['Thành phần', 'Mô tả'],
      ['Tác nhân', 'Nhân viên hành chính được phân công công đoạn scan.'],
      ['Tiền điều kiện', 'Dự án đã bật công đoạn scan; mục lục chỉnh lý của hộp đã được import.'],
      ['Luồng chính', [
        '1. Người dùng chọn hộp và nộp gói scan (thư mục PDF xuất từ phần mềm máy scan).',
        '2. Hệ thống đọc cây thư mục, đếm số file và số trang từng file.',
        '3. Hệ thống so khớp từng thư mục hồ sơ với dòng mục lục tương ứng.',
        '4. Khớp hoàn toàn: công đoạn scan chuyển “hoàn thành”, hộp sẵn sàng kiểm tra scan.']],
      ['Luồng phụ', [
        '3a. Có thư mục thừa, thiếu hoặc sai tên: hệ thống liệt kê chênh lệch, giữ trạng thái “đang làm”.',
        '3b. Người dùng sửa và nộp lại; hệ thống so khớp lại từ đầu.']],
      ['Hậu điều kiện', 'Gói scan và kết quả so khớp được lưu; sự kiện chuyển trạng thái được ghi nhật ký.'],
      ['Quy tắc', 'BR-01, BR-02.'],
    ],
  },
  {
    title: 'UC-08. Nhập metadata có gợi ý OCR',
    rows: [
      ['Thành phần', 'Mô tả'],
      ['Tác nhân', 'Nhân viên hành chính hoặc CTV được giao hộp.'],
      ['Tiền điều kiện', 'Hộp đã qua kiểm tra scan và được giao cho người dùng; còn trong hạn xử lý.'],
      ['Luồng chính', [
        '1. Người dùng mở văn bản; hệ thống hiển thị trang PDF bên trái, biểu mẫu bên phải.',
        '2. Nếu đã có kết quả OCR, 5 trường được điền sẵn, tô màu theo độ tin cậy.',
        '3. Người dùng kiểm tra, sửa các trường sai, nhập các trường còn lại.',
        '4. Người dùng lưu; hệ thống kiểm tra định dạng, lưu bản ghi cùng giá trị gợi ý ban đầu.',
        '5. Hệ thống chuyển sang văn bản tiếp theo trong hộp.']],
      ['Luồng phụ', [
        '2a. OCR chưa chạy xong hoặc lỗi: biểu mẫu để trống, người dùng nhập thủ công.',
        '4a. Dữ liệu sai định dạng: hệ thống báo lỗi tại trường, không lưu.']],
      ['Hậu điều kiện', 'Bản ghi metadata ở trạng thái chờ kiểm tra; cặp (gợi ý, giá trị nhập) được lưu.'],
      ['Quy tắc', 'BR-06, BR-11, BR-13.'],
    ],
  },
  {
    title: 'UC-09. Kiểm tra nhập liệu hai vòng',
    rows: [
      ['Thành phần', 'Mô tả'],
      ['Tác nhân', 'Người kiểm tra được phân công (không phải người đã nhập hộp đó).'],
      ['Tiền điều kiện', 'Toàn bộ bản ghi của hộp đã được nhập và nộp.'],
      ['Luồng chính', [
        '1. Vòng 1: người kiểm tra duyệt 100% bản ghi, đánh dấu trường sai.',
        '2. Hệ thống tính tỷ lệ lỗi của hộp.',
        '3. Tỷ lệ lỗi không vượt ngưỡng: hệ thống chọn ngẫu nhiên 30% bản ghi cho vòng 2.',
        '4. Vòng 2 đạt: hộp chuyển “hoàn thành kiểm tra nhập liệu”, sẵn sàng chuẩn hóa.']],
      ['Luồng phụ', [
        '2a. Tỷ lệ lỗi vượt 5%: trả lại toàn bộ hộp cho người nhập, ghi lý do.',
        '1a. Người kiểm tra trùng người nhập: hệ thống từ chối thao tác.']],
      ['Hậu điều kiện', 'Kết quả kiểm tra là nhãn đúng cho bộ dữ liệu đánh giá OCR.'],
      ['Quy tắc', 'BR-04, BR-07, BR-08.'],
    ],
  },
];

module.exports.stages = [
  ['STT', 'Công đoạn', 'Loại', 'Vai trò được làm', 'Điều kiện hoàn thành'],
  ['1', 'Chỉnh lý', 'Thực hiện', 'Admin, Hành chính', 'Mục lục hồ sơ của hộp đã được import hợp lệ.'],
  ['2', 'Scan', 'Thực hiện', 'Admin, Hành chính', 'Gói scan khớp hoàn toàn với mục lục.'],
  ['3', 'Check scan', 'Kiểm tra', 'Admin, Hành chính', '100% file đạt; nếu trả lại thì công đoạn scan chuyển “bị trả lại”.'],
  ['4', 'Nhập liệu', 'Thực hiện', 'Admin, Hành chính, CTV', 'Mọi văn bản trong hộp đã có bản ghi metadata (suy ra từ dữ liệu nhập).'],
  ['5', 'Check nhập liệu', 'Kiểm tra', 'Admin, Hành chính', 'Qua vòng 1 và vòng 2, tỷ lệ lỗi dưới ngưỡng.'],
  ['6', 'Chuẩn hóa', 'Thực hiện', 'Admin', 'Dữ liệu đã làm sạch, file PDF/A đã ký số, gói SIP đã tạo.'],
  ['7', 'Bàn giao', 'Bàn giao', 'Admin', 'Biên bản đã sinh, nghiệm thu đã ghi nhận, dữ liệu đã khóa.'],
];

module.exports.transitions = [
  ['Trạng thái hiện tại', 'Sự kiện', 'Trạng thái mới', 'Điều kiện'],
  ['Chờ (pending)', 'Bắt đầu', 'Đang làm (in_progress)', 'Công đoạn bật liền trước đã hoàn thành; người thao tác có quyền.'],
  ['Đang làm', 'Hoàn thành', 'Hoàn thành (done)', 'Đạt điều kiện hoàn thành của công đoạn.'],
  ['Đang làm', 'Trả lại (từ bước kiểm tra)', 'Bị trả lại (rejected)', 'Có lý do; bước phía sau chưa bắt đầu.'],
  ['Bị trả lại', 'Làm lại', 'Đang làm', 'Tăng số lần làm lại.'],
  ['Hoàn thành', 'Mở lại', 'Đang làm', 'Chỉ Admin; bước phía sau chưa bắt đầu; ghi nhật ký.'],
];

module.exports.entities = [
  ['Thực thể', 'Thuộc tính chính', 'Ghi chú'],
  ['Người dùng (users)', 'tên đăng nhập, mật khẩu băm, vai trò, trạng thái, ngày hết hạn', 'Thông tin cá nhân tối thiểu.'],
  ['Dự án (projects)', 'tên, đơn vị giao, thời hạn, biểu mẫu, chính sách', 'Gốc của mọi dữ liệu nghiệp vụ.'],
  ['Hộp (project_cases)', 'mã hộp, dự án, người được giao, hạn xử lý', 'Đơn vị giao việc và theo dõi.'],
  ['Hồ sơ (dossiers)', 'mã hồ sơ, tiêu đề, thời gian, số tờ, hộp', 'Mỗi dòng mục lục chỉnh lý.'],
  ['File tài liệu (documents)', 'đường dẫn, số trang, mã băm, hồ sơ', 'File PDF từ gói scan.'],
  ['Cấu hình công đoạn (project_stages)', 'dự án, công đoạn, bật/tắt, thứ tự', 'Đã xây dựng ở Phase 0.'],
  ['Trạng thái công đoạn (case_stage_states)', 'hộp, công đoạn, trạng thái, người làm, số lần làm lại', 'Máy trạng thái của từng hộp.'],
  ['Nhật ký (case_stage_events)', 'hộp, công đoạn, từ, đến, người, thời điểm, lý do', 'Chỉ ghi thêm.'],
  ['Bản ghi metadata (submissions)', 'văn bản, giá trị các trường, người nhập, trạng thái', 'Kết quả nhập liệu.'],
  ['Kết quả kiểm tra (reviews)', 'bản ghi, vòng, trường sai, người kiểm tra', 'Nhãn đúng cho đánh giá OCR.'],
  ['Kết quả OCR (ocr_results)', 'văn bản, engine, văn bản nhận dạng, 5 trường gợi ý, độ tin cậy, thời gian xử lý', 'Bảng mới của module AI.'],
  ['Chất lượng ảnh (image_quality)', 'văn bản, trang, điểm mờ, góc nghiêng, tỷ lệ trắng, dpi, kết luận', 'Bảng mới của module AI.'],
  ['Giờ công, sản lượng (work_logs)', 'người, dự án, công đoạn, ngày, số trang, số giờ', 'Căn cứ KPI và chi trả.'],
  ['Gói bàn giao (handover_packages)', 'dự án, danh mục, mã băm, biên bản, trạng thái nghiệm thu', 'Đầu ra cuối cùng.'],
];

module.exports.ocrPipeline = [
  ['Bước', 'Xử lý', 'Công cụ dự kiến', 'Đầu ra'],
  ['1. Lấy ảnh', 'Lấy trang đầu (và trang cuối nếu cần phần ký) của văn bản, chuyển sang ảnh 300 dpi.', 'PyMuPDF', 'Ảnh trang.'],
  ['2. Kiểm tra chất lượng', 'Đo độ mờ (phương sai Laplacian), góc nghiêng, tỷ lệ điểm trắng, độ phân giải.', 'OpenCV', 'Điểm chất lượng, cờ cảnh báo.'],
  ['3. Tiền xử lý', 'Chỉnh nghiêng, khử nhiễu, cân bằng sáng, nhị phân hóa thích nghi.', 'OpenCV', 'Ảnh đã làm sạch.'],
  ['4. Phân vùng', 'Chia trang theo thể thức: vùng cơ quan ban hành và số ký hiệu (trên trái), vùng quốc hiệu và ngày tháng (trên phải), vùng tên loại và trích yếu (giữa).', 'Luật theo tọa độ, phát hiện dòng chữ', 'Các vùng ảnh có nhãn.'],
  ['5. Nhận dạng chữ', 'Nhận dạng từng vùng; so sánh nhiều engine.', 'Tesseract (vie), PaddleOCR, VietOCR', 'Văn bản theo vùng kèm độ tin cậy.'],
  ['6. Trích xuất trường', 'Biểu thức chính quy cho số ký hiệu, ngày tháng; từ điển tên loại và cơ quan; ghép dòng cho trích yếu.', 'Python, regex, từ điển', '5 trường có cấu trúc.'],
  ['7. Hậu xử lý', 'Chuẩn hóa dấu tiếng Việt, sửa lỗi nhận dạng thường gặp, đối chiếu với dữ liệu đã nhập trước trong cùng hồ sơ.', 'Python', 'Giá trị gợi ý cuối cùng và độ tin cậy.'],
];

module.exports.metrics = [
  ['Chỉ số', 'Cách tính', 'Áp dụng cho'],
  ['CER', 'Số phép sửa ký tự (chèn, xóa, thay) chia cho số ký tự của văn bản đúng.', 'Chất lượng nhận dạng chữ của từng engine.'],
  ['WER', 'Tương tự CER nhưng tính trên đơn vị từ.', 'Chất lượng nhận dạng chữ.'],
  ['Exact match', 'Tỷ lệ trường gợi ý trùng khớp hoàn toàn với giá trị sau kiểm tra.', 'Số ký hiệu, ngày ban hành, tên loại, cơ quan ban hành.'],
  ['Độ tương đồng chuỗi', 'Độ tương đồng chuẩn hóa (1 − khoảng cách Levenshtein / độ dài) giữa gợi ý và giá trị đúng.', 'Trích yếu.'],
  ['Precision, Recall, F1', 'Tính trên nhãn “ảnh lỗi” so với kết luận của người kiểm tra scan.', 'Module kiểm tra chất lượng ảnh.'],
  ['Thời gian nhập', 'Thời gian trung bình từ lúc mở đến lúc lưu một văn bản, có và không có gợi ý.', 'Hiệu quả hỗ trợ nhập liệu.'],
  ['Tỷ lệ chấp nhận gợi ý', 'Tỷ lệ trường người nhập giữ nguyên gợi ý.', 'Mức độ hữu ích thực tế.'],
  ['Tỷ lệ lỗi sau kiểm tra', 'Tỷ lệ trường sai ở vòng kiểm tra, có và không có gợi ý.', 'Ảnh hưởng của gợi ý đến chất lượng.'],
];

module.exports.risks = [
  ['Rủi ro', 'Ảnh hưởng', 'Biện pháp'],
  ['Thời gian thi công thật gấp (chạy thật từ 10/10/2026).', 'Thiếu thời gian cho phần OCR.', 'Chia hai giai đoạn: đưa phần quản lý quy trình vào vận hành trước; OCR làm trên dữ liệu thu được sau đó.'],
  ['Chất lượng ảnh scan không đồng đều.', 'OCR sai nhiều, gợi ý gây nhiễu.', 'Kiểm tra chất lượng ảnh trước OCR; không hiển thị gợi ý có độ tin cậy thấp.'],
  ['Dữ liệu nhạy cảm của khách hàng.', 'Không được dùng dịch vụ OCR đám mây, không được đưa dữ liệu thật vào báo cáo.', 'Toàn bộ xử lý trên máy chủ nội bộ; ảnh minh họa trong báo cáo được che thông tin hoặc dùng văn bản công khai.'],
  ['Thiếu dữ liệu có nhãn để đánh giá.', 'Không đủ số liệu cho Chương 5.', 'Lấy nhãn từ chính kết quả kiểm tra nhập liệu hai vòng; bổ sung bằng văn bản công khai trên cổng thông tin văn bản pháp luật.'],
  ['Hiệu năng khi 100 CTV truy cập đồng thời.', 'Chậm, gián đoạn nhập liệu.', 'Test tải trước khi chạy thật; OCR chạy nền ngoài giờ cao điểm; phân trang phía máy chủ.'],
  ['Thay đổi yêu cầu từ khách hàng trong quá trình thi công.', 'Phải sửa thiết kế.', 'Cấu hình hóa biểu mẫu, chính sách, công đoạn theo dự án thay vì viết cứng.'],
];

module.exports.deliverables = [
  ['Sản phẩm', 'Mô tả'],
  ['Mã nguồn hệ thống', 'Ứng dụng web (FastAPI, PostgreSQL, JavaScript) quản lý 7 công đoạn, lưu trên Git, kèm bộ kiểm thử tự động.'],
  ['Module OCR', 'Mã nguồn pipeline kiểm tra ảnh, tiền xử lý, nhận dạng và trích xuất 5 trường; tích hợp vào màn hình nhập liệu.'],
  ['Bộ dữ liệu đánh giá', 'Tập văn bản có nhãn (đã ẩn danh hoặc công khai) và kịch bản đo các chỉ số.'],
  ['Tài liệu đặc tả yêu cầu', 'Tài liệu BA có mã yêu cầu, quy tắc nghiệp vụ, use case.'],
  ['Tài liệu triển khai', 'Hướng dẫn cài đặt trên máy chủ nội bộ, sao lưu, khôi phục; hướng dẫn sử dụng theo vai trò.'],
  ['Báo cáo đồ án', 'Báo cáo theo cấu trúc tại Phần II, kèm số liệu thực nghiệm và kết quả vận hành thực tế.'],
];
