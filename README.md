# CO3094 WeApRous - Quick Start

## Cách chạy
Mở 2 terminal riêng:

- **Terminal A (backend):**
  ```bash
  python start_backend.py
  ```
- **Terminal B (proxy):**
  ```bash
  python start_proxy.py
  ```

Sau khi chạy thành công, truy cập ứng dụng qua proxy tại `http://127.0.0.1:8080`.

---

## 1) Login page
- **URL:** `http://127.0.0.1:8080/login.html`
- **Steps:**
  - Nhập `username = admin`, `password = password`
  - Bấm Submit
- **Expected:**
  - Đăng nhập thành công
  - Trang login dùng JavaScript chuyển hướng về `/` (index)
  - Cookie được tạo (kiểm tra ở DevTools -> Application -> Cookies)

---

## 2) Gated home page
- **URL:** `http://127.0.0.1:8080/`
- **Behavior:**
  - Nếu đã đăng nhập (có auth cookie) -> index page load bình thường
  - Nếu chưa đăng nhập -> hiển thị `401 Unauthorized` và link quay lại `/login.html`

---

## 3) Chat (Client-Server)
- **URL:** `http://127.0.0.1:8080/chat.html`
- **Steps:**
  - Cần đăng nhập trước
  - Chọn/xác nhận channel (ví dụ: `general`)
  - Gõ message và nhấn **Send**
  - Mở thêm tab khác cùng URL; kiểm tra history sau khi refresh
- **Expected:**
  - Message hiển thị đúng

> Nếu dự án hiện tại không có `chat.html`, bạn có thể bỏ qua mục này hoặc dùng `p2p.html` để demo chat qua DataChannel.

---

## 4) P2P signaling demo (Peer-to-Peer)
- **URL:** `http://127.0.0.1:8080/p2p.html`
- **Setup 2 tabs:**
  - Tab A: đặt **Peer ID = `peerA`**
  - Tab B: đặt **Peer ID = `peerB`**

### Steps
1. Tab A: bấm **Offer**
2. Tab B: bấm **Poll Offer** -> **Answer**
3. Tab A: bấm **Poll Answer**
4. Gửi message qua DataChannel

---

## 5) Logout (verify cookie-gate)
- Gọi endpoint logout: `POST /api/logout` (ví dụ từ browser console)
- Refresh `http://127.0.0.1:8080/`
- **Expected:** thấy `401 Unauthorized` cho đến khi đăng nhập lại

---

## Ghi chú
- Proxy chạy ở cổng `8080`
- Login mẫu:
  - `username: admin`
  - `password: password`
