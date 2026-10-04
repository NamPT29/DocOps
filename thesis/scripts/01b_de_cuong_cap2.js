// Đề cương chi tiết dạng mục lục, đến đề mục cấp 2.
const { Paragraph, TextRun, AlignmentType } = require('docx');
const { p, h, titleBlock, build } = require('./lib');

const FONT = 'Times New Roman';
const line = (text, { bold = false, indent = 0 } = {}) => new Paragraph({
  children: [new TextRun({ text, bold, font: FONT, size: 26 })],
  indent: { left: indent },
  spacing: { before: bold ? 160 : 0, after: 60, line: 312 },
  alignment: AlignmentType.LEFT,
});

const outline = [
  ['MỞ ĐẦU', [
    'Lý do chọn đề tài',
    'Mục tiêu và nhiệm vụ của đề tài',
    'Đối tượng và phạm vi nghiên cứu',
    'Phương pháp thực hiện',
    'Bố cục báo cáo',
  ]],
  ['CHƯƠNG 1. TỔNG QUAN VỀ SỐ HÓA TÀI LIỆU LƯU TRỮ VÀ BÀI TOÁN TRÍCH XUẤT THÔNG TIN', [
    '1.1. Số hóa tài liệu lưu trữ và quy trình thi công số hóa',
    '1.2. Thể thức văn bản hành chính và metadata hồ sơ, tài liệu',
    '1.3. Hiện trạng và khó khăn tại đơn vị thi công số hóa',
    '1.4. Khảo sát các sản phẩm và công trình liên quan',
    '1.5. Phát biểu bài toán và hướng giải quyết',
  ]],
  ['CHƯƠNG 2. CƠ SỞ LÝ THUYẾT VÀ CÔNG NGHỆ', [
    '2.1. Kiến trúc ứng dụng web và các công nghệ xây dựng hệ thống',
    '2.2. Mô hình máy trạng thái trong quản lý quy trình',
    '2.3. Tiền xử lý ảnh tài liệu scan',
    '2.4. Nhận dạng ký tự quang học (OCR) cho tiếng Việt',
    '2.5. Trích xuất thông tin từ văn bản hành chính',
    '2.6. Các chuẩn lưu trữ: PDF/A, chữ ký số, gói tin SIP',
    '2.7. Phương pháp đánh giá: CER, độ chính xác theo trường',
  ]],
  ['CHƯƠNG 3. PHÂN TÍCH VÀ THIẾT KẾ HỆ THỐNG', [
    '3.1. Xác định tác nhân và yêu cầu hệ thống',
    '3.2. Mô hình hóa quy trình nghiệp vụ hiện tại và đề xuất',
    '3.3. Biểu đồ use case và đặc tả use case chính',
    '3.4. Thiết kế máy trạng thái cho quy trình 7 công đoạn',
    '3.5. Thiết kế cơ sở dữ liệu',
    '3.6. Thiết kế kiến trúc và giao diện lập trình (API)',
    '3.7. Thiết kế module OCR trích xuất thông tin văn bản hành chính',
    '3.8. Thiết kế giao diện người dùng',
  ]],
  ['CHƯƠNG 4. XÂY DỰNG VÀ TRIỂN KHAI HỆ THỐNG', [
    '4.1. Môi trường và công cụ phát triển',
    '4.2. Xây dựng các module quản lý quy trình số hóa',
    '4.3. Xây dựng module OCR và trích xuất thông tin',
    '4.4. Tích hợp gợi ý trích xuất vào màn hình nhập liệu',
    '4.5. Triển khai hệ thống trên máy chủ nội bộ',
    '4.6. Kết quả giao diện chương trình',
  ]],
  ['CHƯƠNG 5. THỰC NGHIỆM VÀ ĐÁNH GIÁ', [
    '5.1. Xây dựng bộ dữ liệu đánh giá',
    '5.2. So sánh các engine OCR tiếng Việt',
    '5.3. Đánh giá độ chính xác trích xuất theo từng trường',
    '5.4. Đánh giá hiệu quả hỗ trợ nhập liệu',
    '5.5. Kiểm thử chức năng và hiệu năng hệ thống',
    '5.6. Kết quả vận hành thực tế',
  ]],
  ['KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN', [
    'Kết quả đạt được',
    'Hạn chế',
    'Hướng phát triển',
  ]],
  ['TÀI LIỆU THAM KHẢO', []],
  ['PHỤ LỤC', [
    'Phụ lục A. Đặc tả yêu cầu nghiệp vụ',
    'Phụ lục B. Hướng dẫn cài đặt và sử dụng',
  ]],
];

const children = [
  ...titleBlock('ĐỀ CƯƠNG CHI TIẾT (ĐẾN ĐỀ MỤC CẤP 2)'),
  ...outline.flatMap(([chapter, items]) => [
    line(chapter, { bold: true }),
    ...items.map(item => line(item, { indent: 567 })),
  ]),
];

build(process.argv[2] || 'thesis/01_De_cuong_chi_tiet_cap2.docx', children);
