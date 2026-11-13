# Hướng dẫn deploy bản demo lên Render (miễn phí)

Repo đã có sẵn `render.yaml` (Blueprint), nên deploy chỉ mất vài bước click. Bản demo bật **cổng thanh toán giả lập**: người chấm có thể thử VNPay / MoMo / chuyển khoản từ đầu đến cuối mà không tốn tiền thật.

## 1. Đưa code lên GitHub

Render đọc code từ GitHub và deploy từ nhánh `main`. Đẩy thay đổi lên nhánh này:

```bash
git push origin main
```

> Không commit file `db.sqlite3` và các file cấu hình cục bộ của máy: Render dùng PostgreSQL riêng và tự tạo dữ liệu mẫu bằng `seed_demo`.

## 2. Tạo Blueprint trên Render

1. Đăng nhập <https://dashboard.render.com> bằng tài khoản GitHub.
2. **New → Blueprint** → chọn repo `DatLDQ/E-commerce-platform` → chọn nhánh `main`.
3. Render đọc `render.yaml` và tạo 2 tài nguyên: web service `levelup-gear` và database PostgreSQL `levelup-db` (đều gói Free).
4. Render hỏi giá trị cho **`DJANGO_SUPERUSER_PASSWORD`**: nhập một mật khẩu mạnh, riêng cho bản demo. Đây là mật khẩu tài khoản quản trị `admin` (dashboard `/quan-ly/` và Django Admin). **Không** dùng lại mật khẩu demo trong README.
5. Bấm **Apply**. Lần build đầu mất khoảng 5–10 phút.

Các biến còn lại đã được cấu hình sẵn:

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `DJANGO_SECRET_KEY`, `MOCK_GATEWAY_SECRET` | tự sinh | không cần nhập |
| `DJANGO_DEBUG` | `False` | |
| `DJANGO_ALLOWED_HOSTS` | `.onrender.com` | hostname, CSRF origin và `SITE_URL` lấy tự động từ `RENDER_EXTERNAL_HOSTNAME` |
| `PAYMENT_MODE` / `ALLOW_MOCK_PAYMENTS` | `mock` / `True` | thanh toán giả lập cho bản demo |
| `MEDIA_STORAGE` | `database` | ảnh upload qua admin lưu trong PostgreSQL, không mất khi deploy lại |
| `CLIENT_IP_HEADER` / `TRUSTED_PROXY_COUNT` | `CF-Connecting-IP` / `1` | lấy IP thật của khách sau proxy của Render (ghi vào đơn hàng, chống dò mật khẩu). Kiểm tra: đặt thử một đơn, IP trong trang chi tiết đơn ở dashboard phải là IP của bạn, không phải `127.0.0.1` hay IP nội bộ |
| `DATABASE_URL` | từ `levelup-db` | |

Mỗi lần khởi động, service tự chạy `migrate` → `seed_demo` (đồng bộ danh mục, sản phẩm, banner, tài khoản) → `expire_unpaid_orders` → `gunicorn`.

## 3. Kiểm tra sau khi deploy

Mở URL dạng `https://levelup-gear-xxxx.onrender.com` rồi thử:

- Trang chủ, danh mục, tìm kiếm (thử gõ không dấu: `chuot logitech`), trang sản phẩm.
- Thêm vào giỏ → thanh toán bằng **VNPay** (cổng giả lập; số thẻ test hiện ngay trên trang) và **Chuyển khoản** (mã VietQR + nút "Mô phỏng: ngân hàng báo đã nhận tiền").
- Chatbot LevelBot (góc phải dưới): "chuột tầm 1tr5".
- Đăng nhập `admin` với mật khẩu ở bước 2.4 → `/quan-ly/` để xem dashboard. Django Admin **không** ở `/admin/` (trả 404) mà ở một đường dẫn khó đoán sinh từ secret key: bấm nút “Django Admin” trong menu dashboard, hoặc xem dòng `Django admin:` trong log khởi động trên Render. Muốn tự chọn đường dẫn, đặt biến `DJANGO_ADMIN_URL`.
- Tài khoản khách hàng demo: xem README.

## 4. Giới hạn của gói Free (nên ghi chú cho người chấm)

- **Web service ngủ sau 15 phút không có truy cập.** Lần mở đầu tiên sau đó mất khoảng 30–60 giây. Nên mở trang trước buổi chấm hoặc thuyết trình vài phút.
- **Database Free hết hạn sau 30 ngày** kể từ khi tạo. Hãy deploy gần ngày nộp (hạn 23h59 14/11/2026) để bản demo còn chạy trong thời gian chấm. Nếu database bị xoá, chỉ cần tạo lại Blueprint: `seed_demo` tự tạo lại dữ liệu mẫu.
- Ổ đĩa của web service bị xoá mỗi lần deploy hoặc khởi động lại, nên blueprint lưu ảnh upload trong PostgreSQL (`MEDIA_STORAGE=database`). Ảnh sản phẩm mẫu nằm trong repo và được khôi phục tự động khi khởi động.

## 5. Khi chạy thật (không phải demo)

- Đặt `ALLOW_MOCK_PAYMENTS=False`, `PAYMENT_MODE=vnpay`, và khai báo `VNPAY_TMN_CODE`, `VNPAY_HASH_SECRET` thật.
- Dùng tên miền riêng: thêm vào `DJANGO_ALLOWED_HOSTS` và cấu hình DNS / Cloudflare.
- Nâng database và web service lên gói trả phí, hoặc chuyển sang VPS tại Việt Nam như phân tích trong báo cáo (mục 4.1.4).
