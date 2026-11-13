# LevelUp Gear — Website TMĐT B2C bán gaming gear

Đồ án môn **Thương mại điện tử (CO3027)** — HCMUT. Mã nguồn cho Part 3 (UI/UX), Part 4 (Implementation) và Part 5 (Advanced features) của đề bài.

- **Mô hình:** B2C — doanh nghiệp bán gaming gear chính hãng cho game thủ Việt Nam.
- **Công nghệ:** Python 3.11+ · Django 5.2 · SQLite (dev) / PostgreSQL (prod) · HTML/CSS/JS thuần (mobile-first, không phụ thuộc framework front-end) · Chart.js (dashboard) · Pillow · Gunicorn + WhiteNoise.
- **Chạy được ngay, không cần khoá API nào**: cổng thanh toán mô phỏng, chatbot offline, dữ liệu demo tự sinh.

---

## 1. Cài đặt & chạy (5 phút)

Yêu cầu: Python ≥ 3.11.

```bash
# 1) Tạo môi trường ảo
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2) Cài thư viện
pip install -r requirements.txt

# 3) Cấu hình (tuỳ chọn — mặc định đã chạy được)
cp .env.example .env          # Windows: copy .env.example .env

# 4) Tạo CSDL + dữ liệu demo (92 sản phẩm / 8 danh mục, 140 khách, ~700 đơn trong 6 tháng)
python manage.py migrate
python manage.py seed_demo

# 5) Chạy
python manage.py runserver
```

Mở http://127.0.0.1:8000

| Vai trò | Đăng nhập | Mật khẩu | Vào đâu |
|---|---|---|---|
| Quản trị / nhân viên | `admin` | `Admin@12345` (chỉ khi chạy local, `DJANGO_DEBUG=True`) | http://127.0.0.1:8000/quan-ly/ (dashboard); Django Admin mở từ nút “Django Admin” trong dashboard |
| Khách hàng demo | `demo` (hoặc `demo@levelupgear.vn`) | `Demo@12345` | có sẵn lịch sử đơn, địa chỉ, gợi ý cá nhân hoá |

> **Khi deploy (`DJANGO_DEBUG=False`):** mật khẩu `admin` lấy từ biến `DJANGO_SUPERUSER_PASSWORD`; nếu không đặt, tài khoản bị khoá đăng nhập (mật khẩu demo ở trên không bao giờ dùng trên server). Site cũng từ chối khởi động nếu `DJANGO_SECRET_KEY` còn là giá trị mẫu. Cổng thanh toán mô phỏng (VNPay khi chưa có key, MoMo) mặc định **tắt** ở production — bật bằng `ALLOW_MOCK_PAYMENTS=True` chỉ cho bản demo không bán thật.

Mã giảm giá demo: `WELCOME10` (đơn đầu tiên), `GAMER50K`, `FREESHIP`, `LEVELUP15`.

Làm mới dữ liệu demo: `python manage.py seed_demo --reset`
CSDL đã seed từ bản cũ: `python manage.py seed_demo --sync` đưa danh mục về đúng bản hiện tại — xoá các mẫu demo cũ không còn trong danh mục (đơn hàng cũ vẫn giữ tên/SKU đã lưu), thêm mẫu còn thiếu, cập nhật thông số/mô tả của mẫu đang bán (giữ nguyên giá, tồn kho), thay ảnh vẽ bằng ảnh thật, cập nhật banner trang chủ, xoá thương hiệu không còn sản phẩm; không đụng tới khách hàng hay ảnh do quản trị viên tải lên.
Mỗi sản phẩm demo có đúng một ảnh chụp thật của chính mẫu đó (giấy phép CC0 / CC BY / CC BY-SA, nguồn Wikimedia Commons và Flickr), nằm trong `apps/catalog/demo_photos/`; mẫu nào không tìm được ảnh đúng model thì không đưa vào danh mục. Danh sách tác giả và giấy phép có ở trang `/nguon-anh/`.
Chạy kiểm thử (145 test): `python manage.py test tests`

Tự huỷ đơn online quá hạn thanh toán (hoàn kho, trả lượt mã giảm giá): `python manage.py expire_unpaid_orders` — VNPay/MoMo sau `UNPAID_ORDER_TIMEOUT_MINUTES` (mặc định 60 phút), chuyển khoản sau 24 giờ. Docker/Render chạy lệnh này mỗi lần khởi động; khi vận hành thật nên đặt cron 5–10 phút/lần.

### Chạy bằng Docker (PostgreSQL)

```bash
cp .env.example .env
docker compose up --build      # http://localhost:8000
```

---

## 2. Kịch bản demo gợi ý (cho video/thuyết trình)

1. **Trang chủ** → banner, danh mục, Flash sale, khối “Dành riêng cho bạn” (AI).
2. **Tìm kiếm** “ban phim co” (không dấu vẫn ra) → gợi ý tự động khi gõ → kết quả nhóm theo danh mục (5 sản phẩm + “Xem thêm”) → chọn danh mục/khoảng giá/còn hàng ở cột trái, kết quả lọc ngay không cần bấm “Áp dụng”.
3. **Chi tiết sản phẩm** → ảnh, thông số, đánh giá đã xác thực, “Thường được mua cùng”, “Có thể bạn cũng thích”, So sánh, Yêu thích.
4. **Giỏ hàng** → đổi số lượng (cập nhật tức thì), thanh tiến độ freeship, mã `GAMER50K`.
5. **Thanh toán** → đổi tỉnh/thành → phí ship và các phương thức giao hàng tự cập nhật (Giao nhanh 2H chỉ HCM/HN) → chọn **VNPay** → trang cổng thanh toán mô phỏng → “Thanh toán thành công” → đơn tự chuyển “Đã xác nhận”.
6. Thử **Chuyển khoản** → trang mã VietQR (quét được bằng app ngân hàng; tài khoản nhận là tài khoản mẫu, đừng chuyển tiền thật) → bấm “Mô phỏng: ngân hàng báo đã nhận tiền” (chỉ có khi bật cổng mô phỏng), hoặc vào dashboard → chi tiết đơn → “Xác nhận đã nhận chuyển khoản”.
7. **LevelBot** (nút chat góc phải): “chuột fps dưới 1 triệu”, “phí ship bao nhiêu”, “có mã giảm giá không”, gửi mã đơn để tra cứu.
8. **Dashboard** `/quan-ly/` → KPI (doanh thu, AOV, chuyển đổi, giữ chân…), biểu đồ, từ khoá tìm không ra kết quả, câu hỏi bot chưa hiểu, tồn kho thấp → mở một đơn → chuyển trạng thái, nhập mã vận đơn, in hoá đơn → quản lý sản phẩm (thêm/sửa, upload ảnh, chỉnh tồn kho) → phân khúc khách hàng RFM.

---

## 3. Đối chiếu với yêu cầu đề bài

### Part 3 — System Design (UI/UX)
| Yêu cầu | Trang | File |
|---|---|---|
| Homepage | `/` | `templates/pages/home.html` |
| Product listing | `/san-pham/`, `/san-pham/danh-muc/<slug>/` | `templates/catalog/list.html` |
| Product details | `/san-pham/<slug>/` | `templates/catalog/detail.html` |
| Shopping cart | `/gio-hang/` | `templates/cart/detail.html` |
| Checkout process | `/don-hang/thanh-toan/` → cổng TT → kết quả → theo dõi đơn | `templates/orders/*`, `templates/payments/*` |

**Nguyên tắc thiết kế (3.2)** — áp dụng trong `static/css/main.css`:
- *Layout & navigation:* mobile-first, lưới 2→3→4 cột; header dính với tìm kiếm + giỏ hàng luôn trong tầm tay; menu danh mục ngang (desktop) / drawer (mobile); breadcrumb; thanh “Mua ngay” dính đáy trên mobile; chỉ báo tiến trình 3 bước khi mua.
- *Màu sắc:* nền tối (giảm mỏi mắt, hợp văn hoá game thủ), **tím** = thương hiệu/liên kết, **xanh lime** = CTA chính & giá — mỗi màu một vai trò; có chế độ sáng (nút mặt trời).
- *Typography:* Be Vietnam Pro (hiển thị dấu tiếng Việt chuẩn) cho nội dung, Chakra Petch (phong cách “tech/gaming”) cho tiêu đề & giá; cỡ chữ co giãn `clamp()`.
- *Usability:* tìm kiếm không dấu + gợi ý tức thì, bộ lọc giữ trạng thái, phí ship & tổng tiền hiển thị trước khi đặt, đặt hàng không cần tài khoản, huỷ đơn tự phục vụ, mọi tính năng vẫn chạy khi tắt JavaScript.
- *Accessibility (WCAG 2.1 AA):* tương phản ≥ 4.5:1, vùng chạm ≥ 44px, skip-link, `aria-*`, focus ring rõ, alt text, hỗ trợ `prefers-reduced-motion`, điều hướng bằng bàn phím (autocomplete, dropdown, Esc).

### Part 4.1 — System Deploy
| Yêu cầu | Hiện thực |
|---|---|
| Product management | Dashboard `/quan-ly/san-pham/`: thêm/sửa, upload nhiều ảnh, thông số động, giá vốn, ẩn/hiện, điều chỉnh tồn kho nhanh, cảnh báo sắp hết; Django Admin có sửa hàng loạt |
| Shopping cart | Giỏ theo session (khách) hoặc tài khoản, **tự gộp khi đăng nhập**, giới hạn theo tồn kho, giá luôn tính lại từ server, mã giảm giá |
| Payment method | COD · **VNPay** (sandbox thật khi có khoá, hoặc cổng mô phỏng) · MoMo (mô phỏng) · Chuyển khoản **VietQR chuẩn NAPAS/EMVCo** (mã QR quét được bằng app ngân hàng, điền sẵn số tiền + nội dung; tài khoản cấu hình qua biến `BANK_*`) — `apps/payments/gateway.py`, `apps/payments/vietqr.py`. Thanh toán về sau khi đơn đã huỷ được đánh dấu **hoàn tiền**, không “hồi sinh” đơn |
| Order management | Vòng đời 8 trạng thái với **ràng buộc chuyển trạng thái**, lịch sử ai đổi lúc nào, huỷ → hoàn kho/hoàn tiền tự động, COD tự “đã thanh toán” khi giao, xuất CSV, in hoá đơn, email thông báo mỗi bước |
| Delivery options | Địa chỉ theo **34 tỉnh/thành sau sắp xếp đơn vị hành chính (từ 01/07/2025)**, cấp Tỉnh → Phường/Xã (bỏ cấp quận/huyện; địa chỉ cũ tự quy đổi tên tỉnh, có migration chuyển dữ liệu) · Giao tiêu chuẩn (theo cân nặng + phụ phí vùng, freeship từ 1 triệu) · Giao nhanh 2H (chỉ HCM/HN) · Nhận tại cửa hàng; nhập mã vận đơn/đơn vị vận chuyển; khách xem tiến trình đơn |
| Security | Xem mục 5 |

**Framework (Django) cung cấp sẵn:** ORM + migrations, xác thực & băm mật khẩu PBKDF2, phân quyền staff, Django Admin, form validation, chống CSRF/XSS/SQL injection/clickjacking, session, sitemap, gửi email, i18n/timezone.

**Nhóm tự phát triển:** toàn bộ giao diện cửa hàng & dashboard; giỏ hàng gộp session; tính phí vận chuyển; mã giảm giá; đặt hàng có khoá dòng chống bán vượt tồn kho; quy trình trạng thái đơn; tích hợp cổng thanh toán (ký/xác thực HMAC-SHA512, IPN idempotent) + cổng mô phỏng; VietQR; tìm kiếm tiếng Việt không dấu; hệ gợi ý AI; chatbot; dashboard KPI; phân khúc RFM; các trang pháp lý và tính năng quyền dữ liệu cá nhân; sinh dữ liệu & ảnh demo.

**Hosting plan:**
- *Demo nộp bài:* Render.com (file `render.yaml`, gói free: web service + PostgreSQL) — push lên GitHub → New Blueprint → có URL HTTPS công khai. Gói free “ngủ” khi không có truy cập và ổ đĩa bị xoá mỗi lần deploy, nên blueprint đặt `MEDIA_STORAGE=database`: ảnh do quản trị viên tải lên được lưu trong PostgreSQL; ảnh sản phẩm mẫu được `seed_demo` khôi phục khi khởi động.
- *Vận hành thật:* VPS tại Việt Nam (độ trễ thấp, đáp ứng yêu cầu lưu trữ dữ liệu trong nước) chạy `docker compose` (Gunicorn + PostgreSQL), Nginx/Cloudflare làm reverse proxy + HTTPS + CDN cho ảnh, sao lưu CSDL hằng ngày; tên miền `.vn`.

### Part 4.2 — Demo Source Code
Mã nguồn: thư mục này · Database: tạo bằng `migrate` + `seed_demo` (có thể nộp kèm `db.sqlite3` sau khi seed) · Hướng dẫn cài đặt: mục 1.

### Part 5 — Advanced Features (E-commerce 4.0)
| Tính năng | Vì sao quan trọng | Cải thiện UX / kinh doanh | Mã nguồn |
|---|---|---|---|
| **Gợi ý sản phẩm AI (hybrid)** — lọc cộng tác item-item (đồng mua, chuẩn hoá Ochiai) + content-based (cosine trên danh mục/thương hiệu/tag/khoảng giá) + cá nhân hoá theo lịch sử xem/mua với suy giảm theo thời gian; dự phòng “trending” cho người mới | Gaming gear có nhiều sản phẩm bổ trợ (chuột + pad + tai nghe) | Tăng giá trị đơn (cross-sell “Thường được mua cùng”), giúp khách tìm đúng món nhanh hơn, giải quyết cold-start | `apps/recommendations/engine.py` |
| **Chatbot LevelBot** — hiểu tiếng Việt có/không dấu, trích xuất ngân sách (“dưới 1 triệu”, “tầm 1tr5”), danh mục, thương hiệu, nhu cầu (FPS/MOBA/không dây) theo **nguyên từ** (không nhầm “hỏng” trong “không”); **nhớ ngữ cảnh hội thoại** (“rẻ hơn chút”, “loại không dây thì sao?”); tra cứu đơn (có kiểm tra quyền), phí ship, đổi trả, khuyến mãi; FAQ chỉnh trong Admin; tuỳ chọn LLM Gemini có grounding | Khách thường không rành thông số | Tư vấn 24/7, giảm tải CSKH; câu hỏi bot chưa hiểu được thống kê để cải thiện | `apps/chatbot/engine.py`, `static/js/chatbot.js` |
| **Dashboard phân tích dữ liệu** — doanh thu, AOV, lợi nhuận gộp, tỷ lệ chuyển đổi, MAU, khách mới, tỷ lệ giữ chân & mua lại, tỷ lệ huỷ, theo danh mục/tỉnh/nguồn truy cập/phương thức TT, từ khoá tìm kiếm không có kết quả (cơ hội nhập hàng), tồn kho thấp, **phân khúc RFM** | Đo lường đúng các KPI của Part 2.4 | Ra quyết định nhập hàng, marketing dựa trên dữ liệu | `apps/dashboard/analytics.py` |
| **Mobile-first design** | Phần lớn người mua sắm online tại Việt Nam dùng điện thoại | Thanh mua dính đáy, drawer, vùng chạm lớn | `static/css/main.css` |

Định nghĩa KPI (dùng cho báo cáo Part 2.4 — “how results will be measured”) nằm ở đầu file `apps/dashboard/analytics.py`.

---

## 4. Tuân thủ pháp luật Việt Nam

- **Luật Thương mại điện tử số 122/2025/QH15** (hiệu lực 01/07/2026): thông tin người bán đầy đủ ở footer & trang Giới thiệu; thông tin sản phẩm, giá đã gồm VAT, phí vận chuyển hiển thị trước khi xác nhận; quy trình giao kết hợp đồng rõ ràng (tick đồng ý điều khoản); huy hiệu thông báo Bộ Công Thương (bản demo).
- **Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15** (hiệu lực 01/01/2026) & Nghị định 356/2025/NĐ-CP: checkbox đồng ý khi đăng ký (lưu thời điểm), opt-in email marketing riêng, banner cookie, trang Quyền riêng tư cho phép **tải dữ liệu (JSON)** và **xoá tài khoản** (ẩn danh hoá, giữ chứng từ kế toán), chính sách bảo mật.
- **Luật Bảo vệ quyền lợi người tiêu dùng số 19/2023/QH15:** chính sách đổi trả, bảo hành, cơ chế giải quyết khiếu nại, kiểm tra hàng trước khi nhận, huỷ đơn tự phục vụ.
- Các chính sách: `templates/pages/policies/`.

> Lưu ý: thông tin doanh nghiệp (MST, địa chỉ…) là dữ liệu mô phỏng cho mục đích học thuật — sửa trong `config/settings.py → BUSINESS_INFO`.

---

## 5. Bảo mật (Security considerations)

| Rủi ro | Biện pháp |
|---|---|
| Giả mạo kết quả thanh toán | Chữ ký **HMAC-SHA512** trên URL chuyển hướng, URL trả về và IPN; kiểm tra số tiền khớp đơn; IPN idempotent (không ghi nhận 2 lần) |
| Sửa giá phía client | Giá, phí ship, giảm giá luôn tính lại trên server từ CSDL |
| Bán vượt tồn kho (race condition) | `SELECT … FOR UPDATE` trong transaction khi đặt hàng |
| Dò mật khẩu | Khoá 15 phút sau 5 lần sai (theo IP + tài khoản); mật khẩu ≥ 8 ký tự, chặn mật khẩu phổ biến; băm PBKDF2 |
| Xem trộm đơn hàng | Chỉ chủ đơn/staff hoặc người có token bí mật (so sánh hằng thời gian); tra cứu đơn giới hạn tần suất; chatbot không lộ đơn của người khác |
| CSRF / XSS / Clickjacking / SQLi | Django CSRF token, auto-escape template, `X-Frame-Options: DENY`, **Content-Security-Policy**, ORM tham số hoá |
| Open redirect | Kiểm tra tham số `next` chỉ cho phép URL nội bộ |
| Upload độc hại | Chỉ nhận ảnh ≤ 5MB, chỉ staff được upload |
| Dò trang quản trị | Django Admin không nằm ở `/admin/` mà ở đường dẫn khó đoán (`DJANGO_ADMIN_URL`, hoặc tự sinh từ secret key); chỉ staff thấy liên kết trong dashboard |
| Spam | Honeypot ở form liên hệ, giới hạn tần suất chatbot |
| Truyền tải | Khi `DEBUG=False`: ép HTTPS, HSTS, cookie `Secure`/`HttpOnly`/`SameSite`. Chạy production trên HTTP thuần (vd. `docker compose` ở máy local) thì đặt `DJANGO_HTTPS=False` để cookie không bị gắn `Secure` (nếu không sẽ không đăng nhập/đặt hàng được) |
| Dữ liệu đầu vào bẩn | Tham số id trên URL được kiểm tra trước khi truy vấn; `Referer` ngoài domain bị bỏ qua khi chuyển hướng trong dashboard; trang lỗi 404/500 không phụ thuộc middleware |
| Lộ bí mật | Mọi khoá đọc từ biến môi trường (`.env`, không commit) |

---

## 6. Cấu hình VNPay sandbox thật (tuỳ chọn)

1. Đăng ký merchant test tại https://sandbox.vnpayment.vn/devreg/ để nhận `TMN_CODE` và `HASH_SECRET`.
2. Trong `.env`: `PAYMENT_MODE=vnpay`, `VNPAY_TMN_CODE=...`, `VNPAY_HASH_SECRET=...`, `SITE_URL=<URL công khai của bạn>`.
3. Khai báo IPN URL với VNPay: `<SITE_URL>/thanh-toan-online/ipn/`.
4. Thẻ test do VNPay cung cấp trong email đăng ký sandbox.

MoMo hiện chạy qua cổng mô phỏng (kiến trúc adapter cho phép thêm cổng thật tương tự VNPay).

---

## 7. Cấu trúc thư mục

```
config/            settings, urls, middleware bảo mật
apps/
  accounts/        tài khoản, địa chỉ, đăng nhập email/username, quyền dữ liệu cá nhân
  catalog/         danh mục, thương hiệu, sản phẩm, đánh giá, yêu thích, tìm kiếm, so sánh
     management/commands/seed_demo.py   sinh dữ liệu demo (ảnh sản phẩm: catalog/demo_photos/)
  cart/            giỏ hàng (session/user), gộp giỏ khi đăng nhập
  orders/          checkout, phí ship, mã giảm giá, vòng đời đơn hàng  (services.py)
  payments/        VNPay/MoMo/VietQR, cổng mô phỏng, IPN               (gateway.py)
  recommendations/ hệ gợi ý AI, log xem/tìm kiếm/truy cập               (engine.py)
  chatbot/         LevelBot                                             (engine.py)
  dashboard/       back-office: KPI, đơn hàng, sản phẩm, khách hàng     (analytics.py)
  pages/           trang chủ, giới thiệu, liên hệ, FAQ, chính sách, sitemap
templates/         giao diện (Django templates)
static/            CSS, JS, logo, Chart.js
tests/             145 test tự động
```
