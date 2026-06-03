const form = document.getElementById("loginForm");
const error = document.getElementById("loginError");
const button = document.getElementById("loginSubmit");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Checking";
  const access_key = new FormData(form).get("accessKey");
  try {
    const response = await fetch("/admin/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_key }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Admin key was rejected.");
    }
    window.location.assign("/");
  } catch (err) {
    error.textContent = err.message;
  } finally {
    button.disabled = false;
    button.setAttribute("aria-busy", "false");
    button.textContent = "Open workspace";
  }
});
