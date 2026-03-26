cách chạy:
python start_backend.py - mở backend Temrminal A
python start_proxy.py - mở proxy Temrminal B
3) Mở UI
--------------------
Dùng browser (Chrome/Edge/Firefox):
A) Login page
   URL: http://127.0.0.1:8080/login.html
   Steps:
     - Gõ: username = admin, password = password
     - Submit.
   Expected:
     - Login succeeds → trang login sẽ dùng js script chuyển qua "/" (index).
     - Cookie được lấy (check DevTools → Application → Cookies).
B) Gated home page
   URL: http://127.0.0.1:8080/
   Steps:
     - Nếu logged in (auth cookie present) → index page loads.
     - nếu NOT logged in → shows 401 page with a link back to /login.html.
C) Chat (Client–Server)
   URL: http://127.0.0.1:8080/chat.html 
   Steps:
     - Phải logged in.
     - Pick/confirm a channel name (e.g., "general").
     - Gõ message và press Send.
     - Mở một tab khác cùng URL; Thấy history update sau khi refresh.
   Expected:
     - Message sẽ xuất hiện..
D) P2P signaling demo (Peer-to-Peer)
   URL: http://127.0.0.1:8080/p2p.html  
   Setup 2 tabs:
     - Tab A: set Peer ID = peerA
     - Tab B: set Peer ID = peerB
   Steps:
     1. Tab A: Click “Offer”.
     2. Tab B: Click “Poll Offer” -> “Answer”.
     3. Tab A: Click “Poll Answer”.
     4. Gửi messages qua DataChannel.
4) Logout (verify cookie-gate)
 `/api/logout` from the console.
   - Refresh http://127.0.0.1:8080/ → sẽ thấy 401 Unauthorized đến khi log in.
