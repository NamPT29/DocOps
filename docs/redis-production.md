# Redis cho rate limit khi scale

Ứng dụng chỉ dùng Redis cho bộ đếm rate-limit đăng nhập. Không lưu mật khẩu,
JWT, nội dung hồ sơ hay dữ liệu nghiệp vụ trong Redis.

## Production

1. Tạo Redis managed trong cùng private network với API và tắt public network
   access.
2. Tạo ACL/credential riêng cho ứng dụng, chỉ cấp các lệnh cần thiết cho key
   `scan:login-rate-limit:*` (`GET`, `INCRBY`, `EXPIRE`, `TTL`, `DEL`).
3. Lưu endpoint và credential trong secret manager, rồi đặt `REDIS_URL` theo
   dạng `rediss://...`. Ứng dụng từ chối `redis://` khi `APP_ENV=production`.
4. Bật TLS, encryption at rest, backup mã hóa và theo dõi lỗi kết nối/429 ở
   nhà cung cấp. Không đưa `REDIS_URL` vào source control.

Ví dụ cấu hình (không dùng credential thật):

```env
APP_ENV=production
REDIS_URL=rediss://app-user:replace-me@redis.internal.example:6380/0
```

Khi `REDIS_URL` không được cấu hình, ứng dụng giữ limiter trong bộ nhớ cho
môi trường local. Chế độ đó không chia sẻ bộ đếm giữa các worker; production
scale cần Redis được cấu hình và giám sát hoạt động. Khi Redis đã được cấu
hình nhưng không thể truy cập, endpoint login trả `503` thay vì âm thầm giảm
về limiter cục bộ, để không làm yếu bảo vệ đa worker.

## Development

`compose.yaml` tạo Redis chỉ trong mạng Docker nội bộ và không publish port
ra host. Đây chỉ là cấu hình development; không dùng endpoint `redis://` đó
cho production.
