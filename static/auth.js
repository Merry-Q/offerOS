/* Shared auth helpers */
const AUTH_TOKEN_KEY = "offeros.auth.token";
const AUTH_USER_KEY = "offeros.auth.user";

function offerosBase() {
  const raw = typeof window !== "undefined" && window.OFFEROS_BASE != null
    ? String(window.OFFEROS_BASE)
    : "";
  return raw.replace(/\/$/, "");
}

function offerosUrl(path) {
  const base = offerosBase();
  if (!path) return base || "/";
  if (/^https?:\/\//i.test(path)) return path;
  const p = path.startsWith("/") ? path : `/${path}`;
  if (base && (p === base || p.startsWith(`${base}/`))) return p;
  return `${base}${p}`;
}

function offerosPathname() {
  const base = offerosBase();
  let p = location.pathname;
  if (base && (p === base || p.startsWith(`${base}/`))) {
    p = p.slice(base.length) || "/";
  }
  return p;
}

const _nativeFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  if (typeof input === "string") input = offerosUrl(input);
  return _nativeFetch(input, init);
};

function getToken() {
  return localStorage.getItem(AUTH_TOKEN_KEY) || "";
}

function getUser() {
  try {
    return JSON.parse(localStorage.getItem(AUTH_USER_KEY) || "null");
  } catch {
    return null;
  }
}

function setAuth(token, user) {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

function clearAuth() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
}

function authHeaders(extra = {}) {
  const token = getToken();
  const headers = { ...extra };
  if (token) headers["X-Auth-Token"] = token;
  return headers;
}

async function apiAuth(path, options = {}) {
  const opts = { ...options };
  opts.headers = authHeaders(opts.headers || {});
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearAuth();
    const isAdmin = offerosPathname().startsWith("/admin");
    location.href = isAdmin ? offerosUrl("/admin/login") : offerosUrl("/");
    throw new Error(data.detail || "请先登录");
  }
  if (!res.ok) {
    const msg = data.detail || data.message || res.statusText || "请求失败";
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

async function enterDemo() {
  const res = await fetch("/api/auth/demo", { method: "POST", headers: authHeaders() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "演示入口暂不可用");
  }
  setAuth(data.token, data.user);
  return data;
}

async function requireLogin({ admin = false } = {}) {
  if (admin) {
    if (!getToken()) {
      location.href = offerosUrl("/admin/login");
      return null;
    }
  } else {
    try {
      const data = await enterDemo();
      window.__demoPresets = data.presets || [];
      window.__demoSampleAnswer = data.sample_answer || "";
      return { ...data.user, demo: true };
    } catch (err) {
      console.error(err);
      return null;
    }
  }
  if (!getToken()) {
    location.href = offerosUrl("/admin/login");
    return null;
  }
  try {
    const data = await apiAuth("/api/auth/me");
    setAuth(getToken(), data.user);
    if (admin && data.user.role !== "admin") {
      clearAuth();
      location.href = offerosUrl("/admin/login?error=" + encodeURIComponent("需要管理员账号"));
      return null;
    }
    return {
      ...data.user,
      must_change_password: !!data.must_change_password,
    };
  } catch {
    return null;
  }
}

async function logout(admin = false) {
  try {
    await apiAuth("/api/auth/logout", { method: "POST" });
  } catch (_) {}
  clearAuth();
  location.href = admin ? offerosUrl("/admin/login") : offerosUrl("/");
}

function ensurePasswordModal() {
  if (document.getElementById("pwdModal")) return;
  const mask = document.createElement("div");
  mask.id = "pwdModal";
  mask.style.cssText =
    "display:none;position:fixed;inset:0;background:rgba(20,28,34,.45);z-index:100;align-items:center;justify-content:center;padding:20px;";
  mask.innerHTML = `
    <div style="background:#fff;border-radius:16px;padding:22px;max-width:380px;width:100%;box-shadow:0 16px 40px rgba(0,0,0,.18);font-family:Manrope,system-ui,sans-serif;">
      <h3 style="margin:0 0 8px;font-size:18px;">修改密码</h3>
      <p style="margin:0 0 14px;font-size:13px;color:#667;">请设置新密码（至少 6 位）。修改后其它设备上的登录将失效。</p>
      <label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px;">当前密码</label>
      <input id="pwdOld" type="password" autocomplete="current-password" style="width:100%;padding:10px 12px;border:1px solid #d7dde3;border-radius:10px;margin-bottom:10px;box-sizing:border-box;">
      <label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px;">新密码</label>
      <input id="pwdNew" type="password" autocomplete="new-password" style="width:100%;padding:10px 12px;border:1px solid #d7dde3;border-radius:10px;margin-bottom:10px;box-sizing:border-box;">
      <label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px;">确认新密码</label>
      <input id="pwdNew2" type="password" autocomplete="new-password" style="width:100%;padding:10px 12px;border:1px solid #d7dde3;border-radius:10px;margin-bottom:12px;box-sizing:border-box;">
      <p id="pwdMsg" style="min-height:18px;font-size:13px;color:#c0392b;margin:0 0 10px;"></p>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button type="button" id="pwdCancel" style="padding:8px 14px;border-radius:999px;border:1px solid #d7dde3;background:#fff;cursor:pointer;">取消</button>
        <button type="button" id="pwdSave" style="padding:8px 14px;border-radius:999px;border:0;background:#0f766e;color:#fff;cursor:pointer;font-weight:600;">保存</button>
      </div>
    </div>`;
  document.body.appendChild(mask);
  mask.addEventListener("click", (e) => {
    if (e.target === mask && !mask.dataset.force) closePasswordModal();
  });
  document.getElementById("pwdCancel").onclick = () => {
    if (mask.dataset.force) return;
    closePasswordModal();
  };
  document.getElementById("pwdSave").onclick = submitPasswordChange;
}

function openPasswordModal({ force = false } = {}) {
  ensurePasswordModal();
  const mask = document.getElementById("pwdModal");
  mask.style.display = "flex";
  mask.dataset.force = force ? "1" : "";
  document.getElementById("pwdCancel").style.display = force ? "none" : "";
  document.getElementById("pwdMsg").textContent = force
    ? "当前管理员仍使用环境默认密码，请先修改后再继续。"
    : "";
  document.getElementById("pwdOld").value = "";
  document.getElementById("pwdNew").value = "";
  document.getElementById("pwdNew2").value = "";
}

function closePasswordModal() {
  const mask = document.getElementById("pwdModal");
  if (mask) mask.style.display = "none";
}

async function submitPasswordChange() {
  const msg = document.getElementById("pwdMsg");
  const oldP = document.getElementById("pwdOld").value;
  const n1 = document.getElementById("pwdNew").value;
  const n2 = document.getElementById("pwdNew2").value;
  if (n1.length < 6) {
    msg.textContent = "新密码至少 6 位";
    return;
  }
  if (n1 !== n2) {
    msg.textContent = "两次输入的新密码不一致";
    return;
  }
  msg.textContent = "保存中…";
  msg.style.color = "#667";
  try {
    await apiAuth("/api/auth/change-password", {
      method: "POST",
      body: { old_password: oldP, new_password: n1 },
    });
    msg.style.color = "#0f766e";
    msg.textContent = "已更新";
    const banner = document.getElementById("pwdWarnBanner");
    if (banner) banner.remove();
    setTimeout(closePasswordModal, 400);
  } catch (err) {
    msg.style.color = "#c0392b";
    msg.textContent = err.message || "修改失败";
  }
}

function showPasswordWarningBanner(forceModal = false) {
  if (document.getElementById("pwdWarnBanner")) {
    if (forceModal) openPasswordModal({ force: true });
    return;
  }
  const bar = document.createElement("div");
  bar.id = "pwdWarnBanner";
  bar.style.cssText =
    "position:sticky;top:0;z-index:90;background:#fff7e6;color:#8a5a00;padding:10px 16px;font-size:13px;font-family:Manrope,system-ui,sans-serif;display:flex;gap:12px;align-items:center;justify-content:space-between;border-bottom:1px solid #f0d9a8;";
  bar.innerHTML = `
    <span>检测到管理员仍使用环境默认密码，存在安全风险，请尽快修改。</span>
    <button type="button" style="padding:6px 12px;border-radius:999px;border:0;background:#d97706;color:#fff;cursor:pointer;font-weight:600;">立即改密</button>`;
  bar.querySelector("button").onclick = () => openPasswordModal({ force: forceModal });
  document.body.prepend(bar);
  if (forceModal) openPasswordModal({ force: true });
}
