// Đề cương chi tiết đầy đủ (đến đề mục cấp 2, có mô tả từng mục).
const { p, bullets, numbered, table, h, titleBlock, build } = require('./lib');
const part1 = require('./full/part1');
const part2 = require('./full/part2');
const part3 = require('./full/part3');
const part4 = require('./full/part4');

const chapters = [...part1.chapters, ...part2.chapters, ...part3.chapters];

function label(text) {
  return p(`**${text}**`, { indent: { left: 0 } });
}

function section([title, purpose, content, figures, result]) {
  const out = [
    h(3, title),
    label('Mục đích:'),
    p(purpose),
    label('Nội dung chính:'),
    ...bullets(content),
  ];
  if (figures && figures !== 'Không có') {
    out.push(label('Hình, bảng dự kiến:'));
    out.push(...bullets(figures.split('. ').map(s => s.replace(/\.$/, '') + '.')));
  }
  out.push(label('Kết quả cần đạt:'));
  out.push(p(result));
  return out;
}

// Danh mục hình, bảng dự kiến lấy từ các mục.
const figureRows = [['Chương', 'Hình, bảng dự kiến']];
chapters.forEach(([title, , sections]) => {
  sections.forEach(s => {
    if (s[3] && s[3] !== 'Không có') figureRows.push([s[0], s[3]]);
  });
});

const outlineRows = [['Chương', 'Các mục cấp 2']];
chapters.forEach(([title, , sections]) => outlineRows.push([title, sections.map(s => s[0])]));

const children = [
  ...titleBlock('ĐỀ CƯƠNG CHI TIẾT ĐỒ ÁN TỐT NGHIỆP'),

  h(1, 'PHẦN I. THÔNG TIN CHUNG'),
  h(2, '1. Tính cấp thiết của đề tài'),
  ...part1.front.urgency.map(t => p(t)),
  h(2, '2. Mục tiêu của đề tài'),
  p('**Mục tiêu tổng quát:** xây dựng hệ thống số hóa tài liệu tích hợp AI, quản lý khép kín quy trình thi công số hóa tài liệu lưu trữ, trong đó module OCR tự động trích xuất thông tin văn bản hành chính để hỗ trợ nhập liệu.'),
  p('**Mục tiêu cụ thể:**'),
  ...bullets(part1.front.goals),
  h(2, '3. Đối tượng và phạm vi nghiên cứu'),
  ...bullets(part1.front.scope),
  h(2, '4. Phương pháp thực hiện'),
  ...bullets(part1.front.methods),
  h(2, '5. Đóng góp dự kiến của đề tài'),
  ...bullets([
    '**Về thực tiễn:** một hệ thống chạy thật, thay thế việc quản lý bằng Excel tại đơn vị thi công số hóa, kiểm soát chất lượng tại nguồn và truy vết được toàn bộ quy trình.',
    '**Về kỹ thuật:** một pipeline OCR trích xuất thông tin văn bản hành chính tiếng Việt chạy hoàn toàn trên máy chủ nội bộ, khai thác thể thức văn bản để tăng độ chính xác.',
    '**Về đánh giá:** số liệu so sánh các engine OCR tiếng Việt và hiệu quả hỗ trợ nhập liệu trên dữ liệu thật, với nhãn đúng lấy từ chính quy trình kiểm tra của con người.',
  ]),

  h(1, 'PHẦN II. CẤU TRÚC BÁO CÁO (ĐẾN ĐỀ MỤC CẤP 2)'),
  p('Bảng dưới đây tóm tắt cấu trúc báo cáo. Nội dung chi tiết của từng mục được trình bày ở Phần III.'),
  table([3.4, 6.6], outlineRows),

  h(1, 'PHẦN III. NỘI DUNG CHI TIẾT TỪNG MỤC'),
  ...chapters.flatMap(([title, intro, sections]) => [
    h(2, title),
    p(intro, { run: { italics: true } }),
    ...sections.flatMap(section),
  ]),

  h(1, 'PHẦN IV. ĐẶC TẢ YÊU CẦU SƠ BỘ VÀ THIẾT KẾ DỰ KIẾN'),
  p(part4.intro),
  h(2, '1. Tác nhân của hệ thống'),
  table([2.2, 3.4, 4.4], part4.actors),
  h(2, '2. Yêu cầu chức năng'),
  p('Bảng dưới liệt kê các yêu cầu chức năng chính, nhóm theo công đoạn. Mức “Bắt buộc” phải có trong phiên bản chạy thật; mức “Nên có” được cắt trước nếu trễ tiến độ.'),
  table([1.6, 1.6, 5.6, 1.2], part4.functional),
  h(2, '3. Yêu cầu của module trí tuệ nhân tạo'),
  p('Các yêu cầu của module AI được tách riêng vì chúng là phần nghiên cứu chính của đề tài và được đánh giá định lượng ở Chương 5.'),
  table([1.0, 5.0, 4.0], part4.ai),
  h(2, '4. Quy tắc nghiệp vụ'),
  table([1.2, 8.8], part4.rules),
  h(2, '5. Yêu cầu phi chức năng'),
  table([1.2, 1.8, 7.0], part4.nonFunctional),
  h(2, '6. Danh sách use case'),
  table([1.1, 4.0, 2.2, 2.7], part4.useCases),
  h(2, '7. Đặc tả một số use case tiêu biểu'),
  ...part4.useCaseSpecs.flatMap(u => [h(3, u.title), table([2.2, 7.8], u.rows)]),
  h(2, '8. Thiết kế máy trạng thái quy trình 7 công đoạn'),
  p('Mỗi hộp tài liệu có một trạng thái riêng ở từng công đoạn. Dự án chọn bật những công đoạn cần dùng; công đoạn bị tắt được bỏ qua khi xét điều kiện “công đoạn liền trước”.'),
  table([0.7, 1.8, 1.4, 2.4, 3.7], part4.stages),
  p('Bảng chuyển trạng thái của một công đoạn:'),
  table([2.2, 2.2, 2.2, 3.4], part4.transitions),
  h(2, '9. Các thực thể dữ liệu chính'),
  table([2.8, 4.6, 2.6], part4.entities),
  h(2, '10. Pipeline OCR trích xuất thông tin dự kiến'),
  p('Pipeline khai thác thể thức văn bản hành chính theo Nghị định 30/2020/NĐ-CP: các thành phần như cơ quan ban hành, số ký hiệu, ngày tháng, tên loại, trích yếu nằm ở vị trí tương đối cố định trên trang đầu, nên có thể phân vùng trước rồi mới nhận dạng và trích xuất.'),
  table([1.6, 4.2, 2.2, 2.0], part4.ocrPipeline),
  h(2, '11. Chỉ số đánh giá dự kiến'),
  table([2.0, 5.0, 3.0], part4.metrics),
  h(2, '12. Rủi ro và biện pháp'),
  table([3.2, 2.6, 4.2], part4.risks),
  h(2, '13. Sản phẩm dự kiến'),
  table([2.6, 7.4], part4.deliverables),

  h(1, 'PHẦN V. KẾ HOẠCH THỰC HIỆN'),
  table([1.4, 5.6, 3.0], [['Thời gian', 'Công việc', 'Kết quả'], ...part3.plan]),
  p('Kế hoạch được chia thành hai giai đoạn: tuần 1–4 xây dựng và đưa hệ thống quản lý quy trình vào vận hành thật; tuần 5–10 nghiên cứu, xây dựng và đánh giá module OCR trên dữ liệu thu được từ vận hành; tuần 11–12 hoàn thiện báo cáo.'),

  h(1, 'PHẦN VI. DANH MỤC HÌNH, BẢNG DỰ KIẾN'),
  table([3.4, 6.6], figureRows),

  h(1, 'PHẦN VII. DANH MỤC TỪ VIẾT TẮT'),
  table([2.0, 8.0], [['Viết tắt', 'Ý nghĩa'], ...part3.abbreviations]),

  h(1, 'PHẦN VIII. TÀI LIỆU THAM KHẢO DỰ KIẾN'),
  ...numbered(part3.references),
];

build(process.argv[2] || 'thesis/01_De_cuong_chi_tiet_day_du.docx', children);
