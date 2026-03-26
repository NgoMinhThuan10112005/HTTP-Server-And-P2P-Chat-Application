document.addEventListener("DOMContentLoaded", () => {
  const logoutBtn = document.getElementById("logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        const r = await fetch("/api/logout", {
          method: "POST",
          credentials: "include",
        });
        if (r.ok) {
          location.href = "/login.html";
        } else {
          alert("Logout failed");
        }
      } catch {
        alert("Logout error");
      }
    });
  }
});
