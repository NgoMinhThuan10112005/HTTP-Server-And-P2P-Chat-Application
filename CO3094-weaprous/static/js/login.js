(function () {
  const form = document.getElementById("login-form");
  const btn = document.getElementById("submit-btn");
  const msg = document.getElementById("msg");

  function show(text) {
    msg.textContent = text || "";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    show("");
    btn.disabled = true;

    // Send as application/x-www-form-urlencoded (matches your backend)
    const body = new URLSearchParams(new FormData(form)).toString();

    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        credentials: "include", // harmless on same-origin; good for cross-origin setups
        body,
      });

      if (res.ok) {
        // Session cookie set by server via Set-Cookie
        window.location.href = "/index.html";
        return;
      }

      // Try to surface backend error message if any
      const ct = res.headers.get("content-type") || "";
      const text = await res.text();
      if (res.status === 401) {
        show("Invalid username or password.");
      } else if (ct.includes("application/json")) {
        try {
          const data = JSON.parse(text);
          show(
            data.error
              ? `Login failed: ${data.error}`
              : `Login failed (${res.status}).`
          );
        } catch {
          show(`Login failed (${res.status}).`);
        }
      } else {
        show(text ? `Login failed: ${text}` : `Login failed (${res.status}).`);
      }
    } catch (err) {
      show("Network error. Please try again.");
      console.error(err);
    } finally {
      btn.disabled = false;
    }
  });
})();
