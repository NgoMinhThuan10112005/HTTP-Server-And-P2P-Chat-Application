document.addEventListener("DOMContentLoaded", () => {
  const go = (path) => {
    window.location.href = path;
  };

  const btnApp = document.getElementById("btnApp");
  const btnTool = document.getElementById("btnTool");

  if (btnApp) btnApp.addEventListener("click", () => go("/index.html"));
  if (btnTool) btnTool.addEventListener("click", () => go("/restool.html"));
});
