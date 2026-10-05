Đặc tả sửa 4b theo review c4e1a0f. Đặc tả gốc: mục 4b trong docs/plans/2026-10-01-digitization-pipeline-design.md.

L2 (logic dịch vụ + lỗi HTTP):
3a. "Bước Scan được bật": lấy danh sách bước bật bằng WorkflowRepository(db).stage_rows(project_id) (is_enabled), KHÔNG dựa vào việc hộp đã có dòng case_stage_states; thiếu dòng = 'pending'. Hiện hộp mới bị báo sai "Dự án không bật bước Scan".
3b. Khóa Check scan đúng là 'scan_qc' (không phải 'check_scan'): trạng thái khác 'pending' thì chặn (409). Sửa cả test (đang tạo bước 'check_scan' không tồn tại).
3c. assigned_user_id của bước Scan: SAU mỗi lần Nộp S luôn đặt = người khớp hoặc NULL, kể cả khi level=0 hoặc không đọc được tên (hiện chỉ đặt khi có tên nên người bấm vẫn là người phụ trách; engine gán người bấm khi START, workflow_service.py:500-504).
3d. Thứ tự: kiểm tra MỌI điều kiện (thư mục, số hộp, bước bật, trạng thái bước Scan, scan_qc, gói đang xử lý) TRƯỚC khi gọi transition_case_stage (hàm này commit); sau đó START (nếu cần) -> đặt assignee -> tạo gói với version lấy dưới khóa dòng hộp -> commit.
3e. Số hộp: so SỐ NGUYÊN (0020 == 20) giữa số hộp của hộp (dùng helper của import mục lục QC-16 nếu có; hộp chờ scan có khóa ::muc-luc/hop-N) và số trong tên thư mục hộp. Không dùng chuỗi con (hộp "Hộp 1" đang nhận thư mục "Hộp 11"). Không đọc được số ở một trong hai phía -> 409 có thông báo rõ.
3f. Tên người scan tính từ các thành phần đường dẫn TƯƠNG ĐỐI so với thư mục nguồn (level 1 = thư mục cha của thư mục hộp). Level vượt độ sâu, hoặc cha của hộp là chính thư mục gốc -> None + cảnh báo "chưa có tên người scan" (hiện lấy cả tên thư mục gốc hoặc thư mục ngoài gốc). source_path lưu dạng tương đối đã chuẩn hóa (posix).
3g. Quy đổi QC-06: trang A5 tính 1 (như A4). Bảng khổ (điểm): A0 2384x3370, A1 1684x2384, A2 1190x1684, A3 842x1190, A4 595x842, A5 420x595. Chọn khổ nhỏ nhất có diện tích x1,10 >= diện tích trang; nhỏ hơn A5 -> A5; lớn hơn A0 -> A0. Hiện A4+A5+A3 ra 3, đúng phải là 4. Xóa đoạn comment lan man. Test đúng ranh giới 110% (trong/vượt), trang xoay, trộn khổ.
3h. Lỗi nghiệp vụ trả HTTPException (404 không có dự án/hộp; 409 không bật Scan, trạng thái không cho phép, Check scan đã bắt đầu, đang có gói xử lý, số hộp lệch; 400 level < 0 hoặc đường dẫn không hợp lệ), không ValueError (đang thành HTTP 500). Test kiểm mã HTTP qua TestClient, kể cả 403 cho user thường (dùng cách các test khác trong repo kiểm 403 endpoint Admin).
3k. Chuẩn hóa tên: đ/Đ -> d trước khi bỏ dấu; full_name None không được làm crash.
3l. GET danh sách gói: kiểm tra hộp thuộc dự án (404 nếu không); trả warning_flags dạng danh sách.

L3 (xử lý nền + khởi động):
3i. Đặt total_files ngay khi bắt đầu (thanh tiến trình); xóa vòng lặp thừa có time.sleep(0.01) mỗi file; bọc toàn bộ xử lý trong try/except -> status='failed' + error_message (hiện lỗi bất ngờ làm gói kẹt 'processing' và chặn hộp tới khi khởi động lại); thiếu pypdf -> failed có lý do, không return im lặng.
3j. Dọn gói kẹt khi khởi động (server/main.py): dùng text() hoặc ORM (hiện SQL chuỗi thô gây ArgumentError), chuyển 'processing' -> 'failed' kèm lý do thay vì DELETE; đặt trong repository; có test.

L4 (giao diện, chưa có file frontend nào): nút "Nộp S" ở danh sách hộp trang quản trị; modal chọn thư mục bằng GET /documents/server-folders (KHÔNG ô gõ đường dẫn); ô "cấp thư mục tên người scan" (mặc định 1); poll tiến độ; hiển thị tên người scan + cảnh báo (chưa có tên, file chép dở, file lỗi, không phải PDF). JS đúng CSP (không inline handler, textContent), dùng lại formatVietnamDateTime có sẵn trong project_management.js (KHÔNG khai báo lại hàm toàn cục trùng tên ở file khác), nâng ?v= trong admin.html, selfcheck JS phải CHẠY hàm bằng vm, không chỉ khớp regex.

L5 (tài liệu): cập nhật mục 4b trong docs/plans/2026-10-01-digitization-pipeline-design.md cho khớp code; file docs MỚI phải `git add -f`.

Test bắt buộc xuyên suốt: gọi qua router/TestClient cho POST và GET; Admin-only (user thường 403); gating bước Scan (chờ/bị trả lại -> START, đang làm -> chỉ thêm gói, đã hoàn tất hoặc scan_qc đã bắt đầu -> chặn, không bật Scan -> 409); version tăng đúng và chặn hai gói processing cùng hộp; file cụt, file mã hóa, tệp không phải PDF; file chép dở (một thread ghi thêm byte giữa hai lần lấy mẫu); số hộp lệch -> 409; dọn gói kẹt khi khởi động. Dùng PDF sinh trong test, không dùng dữ liệu khách hàng thật.
