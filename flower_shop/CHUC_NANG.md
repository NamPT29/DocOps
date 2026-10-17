# Phần mềm quản lý shop hoa nhỏ — Danh sách chức năng (bản nháp)

Đối tượng: shop hoa nhỏ (1–5 người), ưu tiên quản lý.
Công nghệ dự kiến: Python FastAPI + SQLite + một trang HTML, chạy trên một máy ở shop.

## 1. Tổng quan (trang đầu)
- Doanh thu hôm nay / tháng này, chi phí tháng, lãi tạm tính.
- Tổng tiền khách còn nợ (đơn chưa thanh toán).
- Đơn cần giao hôm nay (sắp theo giờ), số đơn ngày mai.
- Cảnh báo hoa sắp hết (tồn ≤ mức tối thiểu).
- Cảnh báo hoa sắp héo (ngày nhập + số ngày tươi đã đến hạn).
- Khách có sinh nhật / kỷ niệm trong 7 ngày tới.

## 2. Đơn hàng
- Tạo đơn nhanh theo SĐT: tự nhận khách cũ, khách mới thì tự tạo.
- Người đặt, người nhận (có thể khác), địa chỉ, ngày + giờ giao, lời thiệp, ghi chú.
- Nhiều sản phẩm / đơn, phí ship, giảm giá, tự tính tổng.
- Trạng thái: Mới → Đang cắm → Đang giao → Đã giao, hoặc Hủy.
- Thanh toán: đã/chưa trả; tiền mặt / chuyển khoản / thẻ / ví.
- Lọc theo ngày giao, trạng thái, tên/SĐT.
- In phiếu đơn / thiếp.

## 3. Kho hoa
- Hoa và phụ liệu: đơn vị, tồn kho, giá nhập, mức tối thiểu, số ngày tươi.
- Nhập hoa: tăng tồn, cập nhật giá nhập, tự ghi khoản chi.
- Hủy hoa héo/dập: ghi hao hụt và tiền thiệt hại.
- Tự trừ kho khi tạo đơn theo công thức bó hoa; hủy đơn thì hoàn kho.
- Lịch sử nhập / xuất / hủy.

## 4. Sản phẩm (mẫu bó hoa)
- Tên, danh mục, giá bán, đang bán / ngừng bán.
- Công thức thành phần (vd: 10 hồng + 5 baby + 1 giấy gói).
- Tự tính giá vốn và lãi mỗi bó.

## 5. Khách hàng
- Tên, SĐT, địa chỉ, sinh nhật / ngày kỷ niệm, ghi chú.
- Số đơn, tổng chi tiêu, lịch sử đơn. Tìm theo tên / SĐT.

## 6. Thu chi
- Ghi chi phí theo loại: nhập hoa, mặt bằng, điện nước, lương, ship, quảng cáo…
- Xem theo tháng, theo loại.

## 7. Báo cáo tháng
- Doanh thu theo ngày, số đơn; top sản phẩm bán chạy.
- Chi phí theo loại; lãi = doanh thu − chi phí.
- Giá trị hoa hư hỏng.

## 8. Giai đoạn 2 (làm sau)
- Đăng nhập, phân quyền chủ shop / nhân viên.
- Phân công thợ cắm, shipper.
- Ảnh bó hoa trước khi giao.
- Giá theo mùa lễ (14/2, 8/3, 20/10).
- Xuất Excel, sao lưu dữ liệu.
- Thông báo đơn mới qua Zalo / Telegram.
