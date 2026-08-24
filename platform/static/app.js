/* Virtual Company AI Agent Platform — frontend SPA */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Turn Windows file paths in (already escaped) text into clickable links that open the file
// Allows spaces inside folder names (e.g. "Generated Files"); stops at the file extension.
const PATH_LINK_RE = /[A-Za-z]:\\[^"'`|<>*?\r\n]+?\.[A-Za-z0-9]{1,6}(?![A-Za-z0-9.])/g;
const linkifyPaths = (html) => html.replace(PATH_LINK_RE, p =>
  `<a href="#" class="file-link" data-path="${p.trim()}" title="Open file">📎 ${p}</a>`);
// [[MAIL|acct|folder|uid]] tokens (from chat email listings) → clickable OPEN
// controls that show the full message right in a reader dialog.
const MAIL_TOKEN_RE = /\[\[MAIL\|([\w-]+)\|([^|\]]+)\|(\d+)\]\]/g;
const linkifyMail = (html) => html.replace(MAIL_TOKEN_RE, (_, acct, folder, uid) =>
  `<a href="#" class="mail-link" data-macct="${acct}" data-mfolder="${esc(folder)}" data-muid="${uid}" title="Open this email" style="font-family:Consolas,monospace;font-size:10px;letter-spacing:1px;border:1px solid #4f8ef7;color:#4f8ef7;border-radius:4px;padding:1px 7px;text-decoration:none;white-space:nowrap">📧 OPEN</a>`);
/* Lightweight markdown renderer for agent replies — enterprise report
   formatting: tables, bold/italic/strike, inline code, headers (__X__),
   rules, lists. Escapes first; injects only known-safe markup. */
function mdLite(src) {
  const lines = String(src ?? "").split("\n");
  const out = [];
  let i = 0;
  const inline = (s) => linkifyMail(linkifyPaths(esc(s)))
    .replace(/`([^`]+)`/g, "<code class=\"md-code\">$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/__([^_]+)__/g, "<span class=\"md-sect\">$1</span>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
    .replace(/~~([^~]+)~~/g, "<s>$1</s>");
  while (i < lines.length) {
    const ln = lines[i];
    // markdown table block
    if (/^\s*\|.*\|\s*$/.test(ln) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      const headCells = ln.trim().slice(1, -1).split("|").map(c => c.trim());
      i += 2;
      const body = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        body.push(lines[i].trim().slice(1, -1).split("|").map(c => c.trim()));
        i++;
      }
      out.push(`<div class="md-tbl-wrap"><table class="md-tbl"><thead><tr>${headCells.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (/^\s*[—-]{1,3}\s*$/.test(ln) && ln.trim().length <= 3 && ln.trim() !== "-") {
      out.push('<hr class="md-hr">'); i++; continue;
    }
    if (/^\s*[•·]\s+/.test(ln)) {
      out.push(`<div class="md-li">${inline(ln.replace(/^\s*[•·]\s+/, ""))}</div>`); i++; continue;
    }
    out.push(ln.trim() === "" ? '<div class="md-gap"></div>' : `<div>${inline(ln)}</div>`);
    i++;
  }
  return `<div class="md-body">${out.join("")}</div>`;
}
document.addEventListener("click", async (e) => {
  const a = e.target.closest(".mail-link");
  if (!a) return;
  e.preventDefault();
  openMailReader(a.dataset.macct, a.dataset.mfolder, a.dataset.muid);
});
async function openMailReader(acctId, folder, uid) {
  let msg;
  try { msg = await api(`/mail/accounts/${acctId}/messages/${uid}?folder=${encodeURIComponent(folder)}`); }
  catch (err) { toast(err.message, "err"); return; }
  const body = msg.text ? `<pre style="white-space:pre-wrap;font-family:inherit;font-size:13px;margin:0">${esc(msg.text)}</pre>`
    : (msg.html ? `<iframe sandbox="" style="width:100%;height:400px;border:1px solid var(--border);border-radius:8px;background:#fff" srcdoc="${esc(msg.html)}"></iframe>`
      : `<p class="muted">(empty body)</p>`);
  modal(msg.subject, `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
      <button type="button" class="btn small primary" id="mr-reply">↩ REPLY</button>
      <button type="button" class="btn small" id="mr-forward">↗ FORWARD</button>
      <span class="spacer" style="flex:1"></span>
      <button type="button" class="btn small" id="mr-unread">✉ MARK UNREAD</button>
      <button type="button" class="btn small danger" id="mr-delete">🗑 DELETE</button>
    </div>
    <div style="font-family:Consolas,monospace;font-size:11px;color:var(--muted);line-height:1.7;border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:12px">
      <span style="letter-spacing:1px">FROM</span>&nbsp;&nbsp;${esc(msg.from)}<br>
      <span style="letter-spacing:1px">TO</span>&nbsp;&nbsp;&nbsp;&nbsp;${esc(msg.to)}<br>
      <span style="letter-spacing:1px">DATE</span>&nbsp;&nbsp;${esc((msg.date || "").slice(0, 16).replace("T", " "))}
      ${msg.attachments.length ? `<br><span style="letter-spacing:1px">FILES</span>&nbsp;${msg.attachments.map(esc).join(", ")}` : ""}
    </div>
    <div style="max-height:420px;overflow:auto">${body}</div>
    <div id="mr-panel" class="hidden" style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px">
      <label id="mr-to-wrap" class="hidden">To <input id="mr-to" placeholder="recipient@example.com"></label>
      <label>Message <textarea id="mr-body" rows="5" placeholder="Write your message…"></textarea></label>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button type="button" class="btn small" id="mr-cancel">Cancel</button>
        <button type="button" class="btn small primary" id="mr-send">SEND ▸</button>
      </div>
    </div>`, null, null);
  let mode = "reply";
  const open = (m2, needTo) => { mode = m2; $("#mr-panel").classList.remove("hidden"); $("#mr-to-wrap").classList.toggle("hidden", !needTo); (needTo ? $("#mr-to") : $("#mr-body")).focus(); };
  $("#mr-reply").onclick = () => open("reply", false);
  $("#mr-forward").onclick = () => open("forward", true);
  $("#mr-cancel").onclick = () => $("#mr-panel").classList.add("hidden");
  $("#mr-send").onclick = async () => {
    const bodyTxt = $("#mr-body").value.trim(), toAddr = $("#mr-to").value.trim();
    if (!bodyTxt && mode !== "forward") { toast("Write a message first", "err"); return; }
    if (mode === "forward" && !toAddr) { toast("Enter a recipient address", "err"); return; }
    $("#mr-send").disabled = true; $("#mr-send").textContent = "SENDING…";
    try {
      await api(`/mail/accounts/${acctId}/send`, { method: "POST", body: { mode, folder, uid, to: toAddr, body: bodyTxt } });
      toast(mode === "forward" ? "Forwarded ✓" : "Reply sent ✓");
      $("#modal-root").innerHTML = "";
    } catch (err) { toast(err.message, "err"); $("#mr-send").disabled = false; $("#mr-send").textContent = "SEND ▸"; }
  };
  $("#mr-unread").onclick = async () => {
    try { await api(`/mail/accounts/${acctId}/messages/${uid}/action`, { method: "POST", body: { action: "unread", folder } }); toast("Marked unread ✓"); $("#modal-root").innerHTML = ""; }
    catch (err) { toast(err.message, "err"); }
  };
  $("#mr-delete").onclick = async () => {
    if (!confirm("Delete this email from the server?")) return;
    try { await api(`/mail/accounts/${acctId}/messages/${uid}/action`, { method: "POST", body: { action: "delete", folder } }); toast("Email deleted"); $("#modal-root").innerHTML = ""; }
    catch (err) { toast(err.message, "err"); }
  };
}
// Global handler: ANY 📎 file link anywhere in the app opens the file.
// • Browsing ON the server itself → open with the default desktop app.
// • Browsing from a remote CLIENT → the file lives on the server's disk, so
//   stream it down to this computer instead (saved via the browser).
const IS_SERVER_BROWSER = ["localhost", "127.0.0.1", "::1"].includes(location.hostname);
function downloadServerFile(path) {
  const a = document.createElement("a");
  a.href = "/api/download?path=" + encodeURIComponent(path);
  a.download = path.split(/[\\/]/).pop();
  document.body.appendChild(a); a.click(); a.remove();
}
document.addEventListener("click", async (e) => {
  const a = e.target.closest(".file-link");
  if (!a) return;
  e.preventDefault();
  const path = a.dataset.path;
  if (!IS_SERVER_BROWSER) {           // remote client → download to THIS computer
    downloadServerFile(path);
    toast("⬇ Downloading to this computer…", "ok");
    return;
  }
  try {
    await api("/open-file", { method: "POST", body: { path } });
    toast("Opening file…", "ok");
  } catch (err) { toast("Could not open file: " + err.message, "err"); }
});

/* ---- hover preview for file links ---- */
let _pvEl = null, _pvTimer = null, _pvPath = null;
const _pvCache = {};
function _fmtSize(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : b > 1024 ? Math.round(b / 1024) + " KB" : b + " B"; }
function _hidePreview() { clearTimeout(_pvTimer); _pvTimer = null; _pvPath = null; if (_pvEl) { _pvEl.remove(); _pvEl = null; } }
function _showPreview(a, d) {
  _hidePreview();
  _pvEl = document.createElement("div");
  _pvEl.className = "file-preview";
  const meta = `<div class="fp-meta">${esc(d.name)} · ${_fmtSize(d.size)} · ${new Date(d.modified).toLocaleString()}</div>`;
  if (d.kind === "image") {
    _pvEl.innerHTML = meta + `<img src="/api/image?path=${encodeURIComponent(a.dataset.path)}" alt="preview">`;
  } else if (d.kind === "text") {
    _pvEl.innerHTML = meta + `<pre>${esc(d.content)}</pre>`;
  } else if (d.kind === "pdf") {
    _pvEl.innerHTML = meta + `<div class="fp-big">📕 PDF${d.pages ? " — ~" + d.pages + " pages" : ""}<br><span class="fp-hint">click to open</span></div>`;
  } else {
    _pvEl.innerHTML = meta + `<div class="fp-big">📦 ${esc((d.name.split(".").pop() || "").toUpperCase())} file<br><span class="fp-hint">click to open</span></div>`;
  }
  document.body.appendChild(_pvEl);
  const r = a.getBoundingClientRect(), pw = _pvEl.offsetWidth, ph = _pvEl.offsetHeight;
  let x = Math.min(r.left, window.innerWidth - pw - 12);
  let y = r.bottom + 8;
  if (y + ph > window.innerHeight - 8) y = Math.max(8, r.top - ph - 8);
  _pvEl.style.left = Math.max(8, x) + "px";
  _pvEl.style.top = y + "px";
}
document.addEventListener("mouseover", (e) => {
  const a = e.target.closest(".file-link");
  if (!a) return;
  const path = a.dataset.path;
  _pvPath = path;
  clearTimeout(_pvTimer);
  _pvTimer = setTimeout(async () => {
    try {
      const d = _pvCache[path] || (_pvCache[path] = await api("/preview?path=" + encodeURIComponent(path)));
      if (_pvPath === path) _showPreview(a, d);
    } catch { /* file missing — no preview */ }
  }, 250);
});
document.addEventListener("mouseout", (e) => {
  if (e.target.closest && e.target.closest(".file-link")) _hidePreview();
});
document.addEventListener("scroll", _hidePreview, true);

const state = { user: null, companies: [], companyId: null, view: "dashboard", chatId: null, projectId: null, employees: [], identities: [], imageRef: null, chatQuery: "", searchHit: null };

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.textContent = msg;
  $("#toast-root").appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

/* Copy to clipboard that works EVERYWHERE — navigator.clipboard only exists
   on secure contexts (HTTPS/localhost); remote clients reach the server over
   plain http://LAN-IP, so fall back to a hidden textarea + execCommand. */
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;left:-9999px;top:0";
  ta.setAttribute("readonly", "");
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

/* ---------------- modal helper ---------------- */
function modal(title, bodyHtml, onSubmit, submitLabel = "Save") {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-label="${esc(title)}">
    <h3>${esc(title)}</h3><form id="modal-form">${bodyHtml}
    <div class="actions"><button type="button" class="btn" id="modal-cancel">${onSubmit ? t("Cancel") : t("Close window")}</button>
    ${onSubmit ? `<button type="submit" class="btn primary">${esc(submitLabel || "Save")}</button>` : ""}</div></form></div></div>`;
  $("#modal-cancel").onclick = () => (root.innerHTML = "");
  // Backdrop click must NEVER dismiss a data-entry form — an accidental
  // click outside (or a text-selection drag ending on the backdrop) would
  // silently destroy minutes of typed data. Forms close only via the
  // explicit Cancel / Save buttons. Info-only modals still close on a true
  // backdrop click (mousedown AND mouseup both on the backdrop).
  if (!onSubmit) {
    let downOnBackdrop = false;
    root.firstChild.addEventListener("mousedown", e => { downOnBackdrop = e.target === root.firstChild; });
    root.firstChild.addEventListener("click", e => {
      if (e.target === root.firstChild && downOnBackdrop) root.innerHTML = "";
      downOnBackdrop = false;
    });
  }
  $("#modal-form").onsubmit = async (e) => {
    e.preventDefault();
    if (!onSubmit) { root.innerHTML = ""; return; }
    const myForm = e.target;
    try {
      await onSubmit(new FormData(myForm));
      // only close if the handler didn't open a follow-up modal (e.g. a
      // one-time token / QR display) — otherwise we'd wipe it instantly
      if (root.contains(myForm)) root.innerHTML = "";
    }
    catch (err) { toast(err.message, "err"); }
  };
  const first = root.querySelector("input,textarea,select"); if (first) first.focus();
}

// ---- secure origin for device-facing links (stations, kiosks) ----
// Phones/tablets/bench laptops need the HTTPS listener (port 8443): browsers
// remove camera APIs on insecure HTTP pages, so every link we hand to a
// device must point at https://<server>:8443 — never the HTTP dev port.
const HTTPS_PORT = 8443;
function secureOrigin() {
  if (location.protocol === "https:") return location.origin;
  return "https://" + location.hostname + ":" + HTTPS_PORT;
}

// ---- persistent device role (station / kiosk provisioning) ----
// A deployed device (ChromeOS / Android / iPhone / iPad / bench laptop)
// remembers WHAT it is forever: the role is stored in BOTH localStorage and
// a never-expiring cookie (10-year max-age, the practical browser maximum —
// each read refreshes it, so it effectively never expires). If the device
// has no role yet, visiting the server shows the deployment menu.
const DEVICE_ROLE_KEY = "nexacrew_device_role";
function deviceRole() {
  let raw = "";
  try { raw = localStorage.getItem(DEVICE_ROLE_KEY) || ""; } catch { }
  if (!raw) {
    const m = document.cookie.match(new RegExp("(?:^|;\\s*)" + DEVICE_ROLE_KEY + "=([^;]*)"));
    if (m) { try { raw = decodeURIComponent(m[1]); } catch { } }
  }
  if (!raw) return null;
  try {
    const role = JSON.parse(raw);
    if (role && role.mode) { saveDeviceRole(role); return role; }  // refresh both stores
  } catch { }
  return null;
}
function saveDeviceRole(role) {
  const raw = JSON.stringify(role);
  try { localStorage.setItem(DEVICE_ROLE_KEY, raw); } catch { }
  document.cookie = DEVICE_ROLE_KEY + "=" + encodeURIComponent(raw)
    + ";path=/;max-age=315360000;SameSite=Lax"
    + (location.protocol === "https:" ? ";Secure" : "");
}
function clearDeviceRole() {
  try { localStorage.removeItem(DEVICE_ROLE_KEY); } catch { }
  document.cookie = DEVICE_ROLE_KEY + "=;path=/;max-age=0";
}

/* ---------------- auth ---------------- */
// ---- device registry beacon: report THIS device (type, OS, model, usage) so
// it appears in the admin Clients panel and on the client map. Runs from the
// LOGIN SCREEN onwards (?station=… pages) — no sign-in required to be listed.
let _beaconTimer = null;
function startDeviceBeacon(stationCode) {
  const send = () => {
    let uid = localStorage.getItem("nexacrew_device_uid");
    if (!uid || !/^dev-[A-Za-z0-9]{6,40}$/.test(uid)) {
      uid = "dev-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem("nexacrew_device_uid", uid);
    }
    const ua = navigator.userAgent || "";
    const iPad13 = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
    const os = /iPhone|iPod/.test(ua) ? "iOS" : (/iPad/.test(ua) || iPad13) ? "iPadOS"
      : /Android/.test(ua) ? ("Android" + ((/Android ([\d.]+)/.exec(ua) || [])[1] ? " " + (/Android ([\d.]+)/.exec(ua) || [])[1] : ""))
      : /CrOS/.test(ua) ? "ChromeOS" : /Windows/.test(ua) ? "Windows" : /Mac/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "?";
    const kind = /iPad/.test(ua) || iPad13 || (/Android/.test(ua) && !/Mobile/.test(ua)) ? "tablet"
      : /iPhone|iPod|Android/.test(ua) ? "mobile" : "desktop-browser";
    const model = (/\(([^)]*)\)/.exec(ua) || [])[1] || "";
    // NOTE: api() stringifies the body itself — pass a plain object here.
    // (Double JSON.stringify made the server reject the beacon with 422,
    // so kiosk phones/tablets never appeared in the admin Clients panel.)
    api("/client/device-register", { method: "POST", body: {
      device_uid: uid, kind, os, model: model.slice(0, 110), ua,
      usage: "station:" + stationCode } }).catch(() => { });
  };
  send();
  if (!_beaconTimer) _beaconTimer = setInterval(send, 60000);
}

async function initAuth() {
  // ---- device role routing (runs BEFORE anything else) ----
  const qs = new URLSearchParams(location.search);
  if (qs.has("deploy")) {
    // ?deploy — (re)provision this device: forget the stored role and show
    // the deployment menu after sign-in.
    clearDeviceRole();
    state._deployMenu = true;
  } else if (qs.get("station")) {
    // a ?station= link is SESSION-ONLY: it shows the station workbench for
    // this visit but never binds the browser. Permanent binding happens only
    // through the explicit ?deploy provisioning menu. (Previously the link
    // self-provisioned — a desktop browser that ever opened one was dragged
    // back into station mode on every normal sign-in.)
  } else {
    const role = deviceRole();
    if (role && role.mode === "kiosk" && role.path) {
      location.replace(role.path); return;      // kiosk pages run standalone
    }
    if (role && role.mode === "station" && role.code && role.provisioned) {
      history.replaceState(null, "", "/?station=" + encodeURIComponent(role.code));
    } else if (role && role.mode === "station" && !role.provisioned) {
      clearDeviceRole();   // stale self-provisioned binding from older versions
    }
  }
  // register station/kiosk devices immediately — even on the login screen —
  // so administrators see the device (e.g. an iPhone) in Clients at once
  const stationParam = new URLSearchParams(location.search).get("station") || "";
  if (stationParam) startDeviceBeacon(stationParam);
  const me = await api("/auth/me");
  if (me.user) { state.user = me.user; showApp(); return; }
  $("#auth-screen").classList.remove("hidden");
  const setup = me.needs_setup;
  $("#auth-title").textContent = setup ? "Create admin account" : "Sign in";
  $("#auth-btn").textContent = setup ? "Create account" : "Sign in";
  if (!setup) {
    // portal credentials also work: mapstudiousa.com NexaCrew customer accounts
    const hint = document.createElement("p");
    hint.className = "muted";
    hint.style.cssText = "font-size:11.5px;margin:6px 0 0;text-align:center";
    hint.textContent = "Local account or your mapstudiousa.com NexaCrew portal e-mail + password";
    $("#auth-btn").insertAdjacentElement("afterend", hint);
  }
  $("#auth-btn").onclick = async () => {
    const body = { username: $("#auth-user").value.trim(), password: $("#auth-pass").value };
    try {
      if (setup) await api("/auth/setup", { method: "POST", body });
      // operations-log attribution: silently grab one webcam frame (≤ 3 s,
      // never blocks login — the server verifies and stores it best-effort)
      if (!setup) body.face = await grabLoginFace().catch(() => "");
      const r = await api("/auth/login", { method: "POST", body });
      state.user = r.user;
      $("#auth-screen").classList.add("hidden");
      showApp();
    } catch (e) { $("#auth-err").textContent = e.message; $("#auth-err").classList.remove("hidden"); }
  };
  const badgeBtn = $("#auth-badge-btn");
  if (badgeBtn) { if (setup) badgeBtn.classList.add("hidden"); else badgeBtn.onclick = badgeLoginFlow; }
  $("#auth-pass").addEventListener("keydown", e => { if (e.key === "Enter") $("#auth-btn").click(); });
}

// Post-login camera watchdog: every 30 s grab one frame and verify the
// worker's face is visible (server-side OpenCV check). Two consecutive
// misses → persistent warning overlay until the face is visible again.
let _fwTimer = null, _fwMisses = 0, _fwOverlay = null, _fwBusy = false;
function startFaceWatchdog() {
  if (_fwTimer) return;
  const showWarn = () => {
    if (_fwOverlay) return;
    _fwOverlay = document.createElement("div");
    _fwOverlay.className = "biz-ocr-overlay";
    _fwOverlay.innerHTML = `
      <div class="biz-ocr-card" style="width:min(460px,94vw);border:2px solid #dc2626">
        <div class="biz-ocr-head"><span>⚠ ${t("Camera blocked")}</span></div>
        <div class="biz-ocr-hint" style="font-size:15px;padding:20px 16px;text-align:center">
          🚫📷 ${t("Do NOT block the camera — your face must stay visible while you are signed in. Remove any obstruction now.")}
        </div>
        <div class="biz-ocr-bar"><span class="biz-ocr-status">${esc((state.user && (state.user.display_name || state.user.username)) || "")}</span></div>
      </div>`;
    document.body.appendChild(_fwOverlay);
  };
  const hideWarn = () => { if (_fwOverlay) { _fwOverlay.remove(); _fwOverlay = null; } };
  const check = async () => {
    if (_fwBusy || document.hidden) return;
    _fwBusy = true;
    try {
      const img = await grabLoginFace(4000);
      if (img) {
        const r = await api("/auth/face-presence", {
          method: "POST", body: { image: img, alert: _fwMisses === 1 } });
        if (r.face) { _fwMisses = 0; hideWarn(); }
        else { _fwMisses++; if (_fwMisses >= 2) showWarn(); }
      }
      // camera unavailable/denied → no verdict; never nag on hardware absence
    } catch { /* network/API hiccup — skip this cycle */ }
    _fwBusy = false;
  };
  _fwTimer = setInterval(check, _fwOverlay ? 10000 : 30000);
  // faster re-check while blocked so the warning clears promptly
  setInterval(() => { if (_fwOverlay && !_fwBusy) check(); }, 10000);
  setTimeout(check, 15000);
}

// One silent webcam frame for login attribution. Resolves "" on any failure.
function grabLoginFace(timeoutMs = 3000) {  return new Promise(resolve => {
    let done = false, stream = null;
    const finish = v => { if (done) return; done = true;
      if (stream) stream.getTracks().forEach(t => t.stop()); resolve(v); };
    setTimeout(() => finish(""), timeoutMs);
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
        const v = document.createElement("video");
        v.muted = true; v.playsInline = true; v.srcObject = stream;
        await v.play();
        await new Promise(r => setTimeout(r, 700));   // exposure warm-up
        const c = document.createElement("canvas");
        c.width = v.videoWidth || 640; c.height = v.videoHeight || 480;
        c.getContext("2d").drawImage(v, 0, 0);
        finish(c.toDataURL("image/jpeg", 0.85));
      } catch { finish(""); }
    })();
  });
}

// Badge-QR sign-in: scan the worker badge (wb-… token), then capture the
// worker's face for the operations log and call /auth/badge-login.
// Silent operator face for CHAT-DRIVEN operations: one webcam frame is
// verified/stored server-side and its id is attached to every prompt, so
// register mutations made via chat carry the same face attribution as the
// Operations console. Cached 5 min — chatting stays instant. Best-effort:
// chat NEVER blocks when no camera/face is available.
async function grabOpsFaceId() {
  const now = Date.now();
  const c = window._opsFace;
  if (c && now - c.ts < 300000) return c.id;
  window._opsFace = { id: "", ts: now };        // one attempt per window
  try {
    const img = await grabLoginFace(3000);
    if (!img) return "";
    const res = await api("/business/face-capture", { method: "POST", body: { image: img } });
    if (res && res.ok && res.face_id) { window._opsFace = { id: res.face_id, ts: now }; return res.face_id; }
  } catch { }
  return "";
}

function badgeLoginFlow() {
  const err = m => { $("#auth-err").textContent = m; $("#auth-err").classList.remove("hidden"); };
  const ov = document.createElement("div");
  ov.className = "biz-ocr-overlay";
  ov.innerHTML = `
    <div class="biz-ocr-card" style="width:min(460px,94vw)">
      <div class="biz-ocr-head"><span>📷 Scan your worker badge QR</span></div>
      <video id="blf-v" muted playsinline style="width:100%;border-radius:8px;background:#000;aspect-ratio:4/3;object-fit:cover"></video>
      <div class="biz-ocr-hint" id="blf-hint">Hold the badge QR in front of the camera…</div>
      <div class="biz-ocr-bar">
        <input id="blf-manual" placeholder="…or type the badge token (wb-…)" style="flex:1;min-width:0">
        <button type="button" class="btn small" id="blf-go">Sign in</button>
        <button type="button" class="btn small" id="blf-x">✕ Cancel</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  let stream = null, timer = null, closed = false;
  const cleanup = () => { closed = true; clearInterval(timer);
    if (stream) stream.getTracks().forEach(t => t.stop()); ov.remove(); };
  ov.querySelector("#blf-x").onclick = cleanup;
  const video = ov.querySelector("#blf-v"), hint = ov.querySelector("#blf-hint");
  const submit = async (token) => {
    if (closed) return;
    clearInterval(timer);
    hint.textContent = "👤 Badge accepted — look at the camera…";
    // face for the ops log from the SAME camera (badge lowered, face shown)
    let face = "";
    try {
      await new Promise(r => setTimeout(r, 1500));
      const c = document.createElement("canvas");
      c.width = video.videoWidth || 640; c.height = video.videoHeight || 480;
      c.getContext("2d").drawImage(video, 0, 0);
      face = c.toDataURL("image/jpeg", 0.85);
    } catch { }
    hint.textContent = "⏳ Signing in…";
    try {
      const r = await api("/auth/badge-login", { method: "POST", body: { badge: token, face } });
      cleanup();
      state.user = r.user;
      $("#auth-screen").classList.add("hidden");
      showApp();
    } catch (e) { cleanup(); err(e.message || String(e)); }
  };
  ov.querySelector("#blf-go").onclick = () => {
    const tkn = ov.querySelector("#blf-manual").value.trim();
    if (tkn) submit(tkn); else hint.textContent = "Enter the badge token or show the QR.";
  };
  (async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 } }, audio: false });
      video.srcObject = stream;
      await video.play();
    } catch { hint.textContent = "📷 Camera unavailable — type the badge token instead."; return; }
    // primary: native BarcodeDetector; fallback: jsQR (same as check-in kiosk)
    let det = null, jsqr = null;
    if ("BarcodeDetector" in window) {
      try {
        const fmts = await window.BarcodeDetector.getSupportedFormats();
        if (fmts.includes("qr_code")) det = new window.BarcodeDetector({ formats: ["qr_code"] });
      } catch { }
    }
    if (!det) {
      try {
        await new Promise((res, rej) => {
          const s = document.createElement("script");
          s.src = "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js";
          s.onload = res; s.onerror = () => rej(new Error("jsQR load failed"));
          document.head.appendChild(s);
        });
        jsqr = window.jsQR;
      } catch { }
    }
    if (!det && !jsqr) {
      hint.textContent = "No QR decoder available (offline?) — type the badge token instead.";
      return;
    }
    const cnv = document.createElement("canvas");
    let busy = false;
    timer = setInterval(async () => {
      if (busy || closed || !video.videoWidth) return;
      busy = true;
      try {
        let v = "";
        if (det) {
          const codes = await det.detect(video);
          v = (codes.find(c => (c.rawValue || "").startsWith("wb-")) || {}).rawValue || "";
        } else {
          cnv.width = video.videoWidth; cnv.height = video.videoHeight;
          const ctx = cnv.getContext("2d", { willReadFrequently: true });
          ctx.drawImage(video, 0, 0);
          const img = ctx.getImageData(0, 0, cnv.width, cnv.height);
          const q = jsqr(img.data, img.width, img.height, { inversionAttempts: "dontInvert" });
          if (q && (q.data || "").startsWith("wb-")) v = q.data;
        }
        if (v) submit(v);
      } catch { }
      busy = false;
    }, 350);
  })();
}

// ---- camera role resolution (internal = face capture, external = serial scan) ----
// Candidate values in priority order: this computer's client program config
// (tray → Camera settings) → server-local config (/api/cameras, authoritative
// when browsing ON the server machine) → browser localStorage.
// Returns ALL candidates; cameraConstraints picks the first that matches a
// real device, so one stale entry can never hijack the selection.
function cameraPrefList(kind) {
  const key = "camera_" + kind;
  const out = [];
  // 1) THIS SESSION's kiosk/mobile camera setup (chosen on page entry —
  //    mobile devices must confirm cameras every time the page is opened)
  try { const v = sessionStorage.getItem("station_" + key); if (v) out.push(v); } catch { }
  const cl = window.clientInfo;
  if (cl && cl[key]) out.push(String(cl[key]));
  const sc = window.serverCameras;
  if (sc && sc[key]) out.push(String(sc[key]));
  try { const v = localStorage.getItem(key); if (v) out.push(v); } catch { }
  return out.filter((v, i) => v && out.indexOf(v) === i);
}

function cameraPref(kind) {   // first configured value (for UI preselection)
  return cameraPrefList(kind)[0] || "";
}

// ---- kiosk devices: ChromeOS / Android / iOS (iPad, iPhone) ----
// These cannot run the Python client program — the ?station= web page IS the
// kiosk client (installable as a PWA). Face capture and serial OCR run fully
// in the browser + server, so no local install is ever needed.
function isMobileKiosk() {
  const ua = navigator.userAgent || "";
  const iPad13 = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
  return /Android|iPhone|iPad|iPod|CrOS/i.test(ua) || iPad13;
}

// Camera setup screen — MANDATORY on kiosk devices at every page entry.
// Lists the device's cameras (OS-reported), live preview, and assigns the
// face-recognition camera and the serial-number camera for THIS session.
async function stationCameraSetup() {
  if (document.querySelector(".st-camsetup")) return;
  // iPhone/Android REMOVE camera APIs on insecure HTTP pages — cameras only
  // exist on HTTPS. Offer the server's secure 8443 link instead of failing.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    const httpsUrl = "https://" + location.hostname + ":8443" + location.pathname + location.search;
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.className = "biz-ocr-overlay st-camsetup";
      ov.innerHTML = `
      <div class="biz-ocr-card st-camsetup-card">
        <div class="biz-ocr-head"><span>🔒 ${t("Secure connection required for cameras")}</span></div>
        <div class="biz-ocr-hint">${t("Phones and tablets only allow camera access on a secure (HTTPS) page. Open the secure address below — accept the certificate warning once (Advanced → Continue), then the cameras will work.")}</div>
        <div class="st-camsetup-body">
          <a class="btn primary" style="text-align:center;text-decoration:none;font-size:15px" href="${httpsUrl}">🔒 ${t("Open the secure page")}</a>
          <div class="muted" style="font-size:12px;word-break:break-all;text-align:center">${esc(httpsUrl)}</div>
          <div class="st-camsetup-btns">
            <button class="btn" id="stc-skip">${t("Continue without cameras")}</button>
          </div>
        </div>
      </div>`;
      document.body.appendChild(ov);
      ov.querySelector("#stc-skip").onclick = () => { ov.remove(); resolve(); };
    });
  }
  let devs = [];
  try {
    // unlock device labels with a throwaway permission request
    try { (await navigator.mediaDevices.getUserMedia({ video: true })).getTracks().forEach(tr => tr.stop()); } catch { }
    devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
  } catch { }
  return new Promise((resolve) => {
    const ov = document.createElement("div");
    ov.className = "biz-ocr-overlay st-camsetup";
    const optHtml = (sel) => devs.map((d, i) =>
      `<option value="${esc(d.deviceId)}" ${d.deviceId === sel ? "selected" : ""}>${esc(d.label || t("Camera") + " " + (i + 1))}</option>`).join("")
      || `<option value="">${t("No camera found")}</option>`;
    const prevFace = sessionStorage.getItem("station_camera_internal") || (devs[0] && devs[0].deviceId) || "";
    const prevSer = sessionStorage.getItem("station_camera_external") || (devs[1] ? devs[1].deviceId : prevFace);
    ov.innerHTML = `
    <div class="biz-ocr-card st-camsetup-card">
      <div class="biz-ocr-head"><span>📷 ${t("Camera setup for this station")}</span></div>
      <div class="biz-ocr-hint">${t("Select which camera is used for face recognition and which for serial-number capture. This is asked every time the station page opens.")}</div>
      <div class="st-camsetup-body">
        <label><span class="noc-lbl">🧑 ${t("Face recognition camera")}</span>
          <select id="stc-face">${optHtml(prevFace)}</select></label>
        <label><span class="noc-lbl">🔢 ${t("Serial number camera")}</span>
          <select id="stc-serial">${optHtml(prevSer)}</select></label>
        <div class="st-camsetup-prev"><video id="stc-video" autoplay playsinline muted></video></div>
        <div class="st-camsetup-btns">
          <button class="btn" id="stc-test">▶ ${t("Preview")}</button>
          <button class="btn primary" id="stc-ok">✔ ${t("Use these cameras")}</button>
        </div>
      </div>
    </div>`;
    document.body.appendChild(ov);
    const video = ov.querySelector("#stc-video");
    let stream = null;
    const stop = () => { if (stream) { stream.getTracks().forEach(tr => tr.stop()); stream = null; } };
    const preview = async (id) => {
      stop();
      if (!id) return;
      try { stream = await navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: id } } }); video.srcObject = stream; } catch { }
    };
    ov.querySelector("#stc-test").onclick = () => preview(ov.querySelector("#stc-serial").value);
    ov.querySelector("#stc-face").onchange = (e) => preview(e.target.value);
    ov.querySelector("#stc-serial").onchange = (e) => preview(e.target.value);
    preview(prevFace);
    ov.querySelector("#stc-ok").onclick = () => {
      try {
        sessionStorage.setItem("station_camera_internal", ov.querySelector("#stc-face").value);
        sessionStorage.setItem("station_camera_external", ov.querySelector("#stc-serial").value);
      } catch { }
      stop();
      ov.remove();
      resolve();
    };
  });
}

// Build getUserMedia video constraints for the configured camera role.
// Tries every configured candidate against the browser's OS device list and
// pins capture to the first that exists; falls back to facingMode.
async function cameraConstraints(kind, extra) {
  const base = Object.assign({}, extra || {});
  if (!window.serverCameras) {   // config may still be loading — wait for it
    try { window.serverCameras = await (await fetch("/api/cameras")).json(); } catch { window.serverCameras = {}; }
  }
  const prefs = cameraPrefList(kind).map(p => p.trim().toLowerCase()).filter(Boolean);
  if (prefs.length && navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    try {
      let devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
      // labels are empty until camera permission has been granted once
      if (devs.length && devs.every(d => !d.label)) {
        try {
          const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
          tmp.getTracks().forEach(tr => tr.stop());
          devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
        } catch { }
      }
      for (const pref of prefs) {
        const hit = devs.find(d => d.deviceId === pref) ||
          devs.find(d => (d.label || "").toLowerCase().includes(pref)) ||
          devs.find(d => pref.includes((d.label || "").toLowerCase()) && d.label);
        if (hit) { base.deviceId = { exact: hit.deviceId }; return base; }
      }
    } catch { }
  }
  // no explicit assignment → sensible defaults
  base.facingMode = kind === "external" ? "environment" : "user";
  return base;
}

/* ---------------- device deployment menu (?deploy) ----------------
   Provision THIS device as a fixed-function terminal. Open
   https://<server>:8443/?deploy on the ChromeOS / Android / iPhone / iPad
   device, sign in, choose the role — the choice is stored permanently
   (localStorage + 10-year cookie) and the device keeps that role on every
   future visit. Re-provision any time by opening ?deploy again. */
async function showDeployMenu() {
  const KIOSKS = [
    ["checkin", "🕑", t("Worker Check-in Kiosk"), t("Badge QR clock in / out with face capture"), "/checkin"],
    ["visitor", "🎫", t("Visitor Kiosk"), t("Visitor registration, badges and QR scanning"), "/visitor"],
    ["pos", "🧾", t("POS Kiosk"), t("Point-of-sale terminal (requires device token)"), "/kiosk"],
  ];
  let regs = [];
  try {
    const ws = await api("/business/workspace");
    if (ws.active) regs = ws.modules;
  } catch { /* non-commercial mode — stations unavailable */ }
  const groups = {};
  for (const m of regs) (groups[m.grp || t("General")] = groups[m.grp || t("General")] || []).push(m);
  const regName = n => { const mm = /^(.*?)\s*\((FRM[^)]*|OP-[^)]*)\)\s*$/.exec(n); return { label: t(mm ? mm[1] : n), code: mm ? mm[2] : "" }; };
  modal("🚀 " + t("Deploy this device"), `
    <p class="muted" style="margin-top:0;font-size:12.5px">${t("Choose what THIS device will permanently be. The role is stored on the device and applied automatically on every future visit. To change it later, open")} <code>/?deploy</code></p>
    <div class="biz-sect"><span>🧾 ${t("Kiosk types")}</span></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin:10px 0 16px">
      ${KIOSKS.map(([k, emo, name, desc, path]) => `
        <button type="button" class="btn dep-kiosk" data-path="${path}" data-kind="${k}" style="display:block;text-align:left;padding:12px 14px;line-height:1.5">
          <span style="font-size:20px">${emo}</span> <b>${esc(name)}</b><br>
          <span class="muted" style="font-size:11.5px">${esc(desc)}</span></button>`).join("")}
    </div>
    <div class="biz-sect"><span>🖥 ${t("Workbench stations (one register, full-screen)")}</span></div>
    ${regs.length ? `
      <input type="text" id="dep-search" placeholder="${esc(t('Find a register…'))}" style="width:100%;margin:8px 0">
      <div id="dep-regs" style="max-height:300px;overflow:auto">
      ${Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0])).map(([g, gm]) => `
        <div class="dep-grp"><div style="font-size:11px;font-weight:800;letter-spacing:1.6px;color:#9db4d8;margin:10px 0 4px">${bizGrpEmoji(g)} ${esc(t(g))}</div>
        ${gm.map(m => { const nm = regName(m.name); return `
          <button type="button" class="btn small dep-station" data-code="${esc(m.key)}" data-name="${esc((m.name + " " + nm.label).toLowerCase())}" style="display:flex;width:100%;text-align:left;gap:8px;align-items:center;margin:3px 0">
            <span>${m.icon || "📄"}</span><span style="flex:1">${esc(nm.label)}</span>
            ${nm.code ? `<code style="font-size:10px;opacity:.65">${esc(nm.code)}</code>` : ""}</button>`; }).join("")}</div>`).join("")}
      </div>` : `<p class="muted">${t("Stations are available once the company profile is configured in Business.")}</p>`}`, null);
  const finish = (role, target) => {
    saveDeviceRole(role);
    toast("✔ " + t("Device provisioned — this device will keep this role permanently."));
    setTimeout(() => location.replace(target), 600);
  };
  $$("#modal-root .dep-kiosk").forEach(b => b.onclick = () =>
    finish({ mode: "kiosk", kind: b.dataset.kind, path: b.dataset.path }, b.dataset.path));
  $$("#modal-root .dep-station").forEach(b => b.onclick = () =>
    finish({ mode: "station", code: b.dataset.code, provisioned: true },
      "/?station=" + encodeURIComponent(b.dataset.code)));
  const s = $("#dep-search");
  if (s) s.oninput = () => {
    const q = s.value.trim().toLowerCase();
    $$("#modal-root .dep-station").forEach(b => b.style.display = !q || b.dataset.name.includes(q) ? "" : "none");
    $$("#modal-root .dep-grp").forEach(g => g.style.display = [...g.querySelectorAll(".dep-station")].some(b => b.style.display !== "none") ? "" : "none");
  };
}

/* ---------------- device deployment: end ---------------- */

async function showApp() {
  $("#app").classList.remove("hidden");
  // top-right operator identity — signed-in worker's full name + initials
  {
    const nm = (state.user && (state.user.display_name || state.user.username)) || "";
    const nEl = $("#whoami-name"), iEl = $("#whoami-ini");
    if (nEl) nEl.textContent = nm;
    if (iEl) iEl.textContent = nm.split(/\s+/).map(w => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
  }
  startFaceWatchdog();
  // ---- STATION MODE: dedicated workbench terminal for ONE register ----
  // Open http://<server>:8600/?station=FRM-CHR-TEST-001 on the bench laptop:
  // after sign-in only that register is shown, full-screen, no other menus.
  state.station = new URLSearchParams(location.search).get("station") || "";
  if (state.station) {
    document.body.classList.add("station-mode");
    state.view = "operations";
    // installable PWA (Android / iOS / ChromeOS “Add to Home Screen”)
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => { });
    }
    // kiosk devices must confirm the cameras at every page entry
    if (isMobileKiosk() && !sessionStorage.getItem("station_camera_internal")) {
      await stationCameraSetup();
    }
    // device registry beacon — shared with the login screen (initAuth);
    // re-invoking after sign-in attaches the operator name to the device
    startDeviceBeacon(state.station);
  }
  $("#logout-btn").onclick = async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch { }
    // drop the ?station= query: session-only station links end at sign-out;
    // deploy-provisioned terminals re-enter their role automatically
    location.replace(location.pathname);
  };
  $$(".nav-item[data-view]").forEach(b => b.onclick = () => nav(b.dataset.view));
  initNavSearch();
  initNavCollapse();
  // server-wide camera role defaults (Settings → Cameras) — client overrides win
  fetch("/api/cameras").then(r => r.json()).then(j => { window.serverCameras = j; }).catch(() => { });
  $("#company-select").onchange = async (e) => { state.companyId = e.target.value || null; state.projectId = null; await loadCompanyData(); render(); };
  if (!state.user.is_admin) {
    // admin-only areas: hidden in the UI and enforced server-side (403).
    // Skills and Backup are available to EVERY user (each sees only his own).
    // Setup stays VISIBLE — it asks for administrator credentials and then
    // shows only this computer's client-side settings.
    ["users", "clients", "cluster", "audit", "settings"].forEach(view => {
      const btn = document.querySelector(`.nav-item[data-view="${view}"]`);
      if (btn) btn.classList.add("hidden");
    });
    const adminSec = document.getElementById("nav-sec-admin");
    if (adminSec) adminSec.classList.add("hidden");
  }
  fillVersions();
  await refreshCompanies();
  await loadCompanyData();
  refreshBadge();
  refreshBusinessNav();
  setInterval(refreshBadge, 15000);
  checkSetup();
  render();
  if (state._deployMenu) { state._deployMenu = false; showDeployMenu(); }
}

async function checkSetup() {
  if (!state.user.is_admin) return;  // setup is an admin-only area
  try {
    const s = await api("/setup/status");
    const b = $("#setup-badge");
    if (b) b.classList.toggle("hidden", s.complete);
    if (!s.complete && !sessionStorage.getItem("setupWarned")) {
      sessionStorage.setItem("setupWarned", "1");
      toast(`⚠ Environment setup incomplete (${s.steps_done}/${s.steps_total}) — open 🛠️ Setup to install & login the agents`, "err");
      nav("setup");
    }
  } catch {}
}

async function refreshCompanies() {
  state.companies = await api("/companies");
  if (!state.companyId && state.companies.length) state.companyId = state.companies[0].id;
  const sel = $("#company-select");
  sel.innerHTML = state.companies.map(c =>
    `<option value="${c.id}" ${c.id === state.companyId ? "selected" : ""}>${esc(c.logo)} ${esc(c.name)}</option>`).join("")
    || `<option value="">— no companies —</option>`;
}

async function loadCompanyData() {
  if (!state.companyId) { state.employees = []; state.identities = []; return; }
  [state.employees, state.identities] = await Promise.all([
    api(`/companies/${state.companyId}/employees`),
    api(`/companies/${state.companyId}/identities`),
  ]);
}

async function refreshBadge() {
  try {
    const approvals = await api("/approvals");
    const n = approvals.filter(a => a.status === "pending").length;
    const b = $("#appr-badge");
    b.textContent = n; b.classList.toggle("hidden", n === 0);
  } catch {}
  notifyPendingVisits();
}

/* ---- visitor notifications ----
   Unattended reception: visits are auto-approved and checked in at the
   kiosk, so this poll notifies security/host of NEW self-service
   check-ins (toast + desktop notification). Informational only. */
let _seenVisits = null;   // null = first poll (no notifications yet)
async function notifyPendingVisits() {
  if (!state.user || !state.user.is_admin) return;
  let visits;
  try { visits = await api("/visitor/visits"); } catch { return; }
  const active = visits.filter(v => v.status === "checked_in" || v.status === "pending");
  if (_seenVisits !== null) {
    const fresh = active.filter(v => !_seenVisits.has(v.id));
    for (const v of fresh) {
      const line = `\ud83d\udec2 Visitor checked in: ${v.visitor_name}` +
        (v.company ? ` (${v.company})` : "") + (v.host ? ` \u2192 host ${v.host}` : "");
      toast(line, "warn");
      if (window.Notification && Notification.permission === "granted") {
        try { new Notification("Visitor on premises", {
          body: `${v.visitor_name}${v.company ? " \u2014 " + v.company : ""}\nPurpose: ${v.purpose || "\u2014"}`,
          tag: "visit-" + v.id }); } catch {}
      } else if (window.Notification && Notification.permission === "default") {
        try { Notification.requestPermission(); } catch {}
      }
    }
    if (fresh.length && state.view === "workforce") render();
  }
  _seenVisits = new Set(active.map(v => v.id));
}

/* Dynamic ERP menu — commercial mode injects the industry's enterprise
   modules (Inventory, POS, Workers, Invoicing, Accounting …) into the
   left nav, grouped by ERP domain. */
const BIZ_CAT_ORDER = ["OPERATIONS", "SALES", "SUPPLY", "HR", "FINANCE", "COMPLIANCE"];
const BIZ_CAT_LABEL = { OPERATIONS: "OPERATIONS", SALES: "SALES & CRM", SUPPLY: "SUPPLY CHAIN", HR: "HUMAN RESOURCES", FINANCE: "FINANCE", COMPLIANCE: "ISO COMPLIANCE" };
const BIZ_CAT_ICON = { OPERATIONS: "🏭", SALES: "🤝", SUPPLY: "📦", HR: "👥", FINANCE: "💰", COMPLIANCE: "🛡️" };
// Process-area emoji — A·RECEIVING … N·MANAGEMENT groups get a fixed visual
// anchor so workers recognise their area at a glance (same icon everywhere:
// nav, breadcrumb, process-flow map).
const BIZ_GRP_EMOJI = { A: "📥", B: "🏷️", C: "🔧", D: "🔩", E: "🔒", F: "🧹", G: "🔋", H: "🏭", I: "🚚", J: "✅", K: "🌱", L: "🦺", M: "♻️", N: "📊" };
function bizGrpEmoji(g) { return BIZ_GRP_EMOJI[(String(g || "").trim()[0] || "").toUpperCase()] || "📁"; }

/* ---------- 🧩 Operations Studio — externalized operations packages ------
   Operations (the industry A–N registers) are distributable JSON packages,
   NOT hard-coded to one company. Admins can: export the current operations
   as a package, import a package from another deployment/vendor, build or
   amend modules field-by-field, and revert to the built-in starter. The
   ERP core (Sales/HR/Finance) and ISO COMPLIANCE registers are universal
   and are never part of a package. ------------------------------------- */
async function showOpsStudio() {
  let info;
  try { info = await api("/business/ops-package"); }
  catch (e) { toast("❌ " + e.message); return; }
  let pkg = JSON.parse(JSON.stringify(info.package));       // working copy

  const fieldTypeHelp = "text · number · date · textarea · password · section · select:opt1,opt2";
  const closeModal = () => { $("#modal-root").innerHTML = ""; };

  const modRow = (m, i) => `
    <tr>
      <td style="white-space:nowrap">${esc(m.icon || "🏭")} <b>${esc(m.name)}</b><br>
        <code style="font-size:10px;opacity:.6">${esc(m.key)}</code></td>
      <td style="font-size:11px">${m.grp ? `${bizGrpEmoji(m.grp)} ${esc(m.grp)}` : "—"}</td>
      <td style="font-size:11px">${esc(m.iso || "—")}</td>
      <td class="num">${m.fields.filter(f => f[2] !== "section").length}</td>
      <td style="white-space:nowrap">
        <button type="button" class="btn small ops-edit" data-i="${i}">✏️</button>
        <button type="button" class="btn small ops-del" data-i="${i}" title="${t("Remove module (historic records are retained)")}">🗑</button>
      </td>
    </tr>`;

  function syncHead() {
    const n = $("#opk-name"), v = $("#opk-ver"), c = $("#opk-chat");
    if (n) pkg.name = n.value.trim();
    if (v) pkg.version = v.value.trim() || "1.0.0";
    if (c) pkg.chat_prompt = c.value;
  }

  function openStudio() {
    modal(`🧩 ${t("Operations Studio")} — ${(state.bizWs && state.bizWs.company_name) || ""}`, `
      <div style="font-size:11px;opacity:.65;line-height:1.6;margin-bottom:10px;padding:8px 12px;background:#0b1220;border:1px solid #22304e;border-radius:8px">
        🧩 ${t("ONE package holds ALL operations of this company — every register AND the operations chat directive. Export it for another site, import a vendor build, or edit it below.")}<br>
        ${t("ERP core (Sales · Supply · HR · Finance) and ISO compliance registers are universal and stay outside the package.")}</div>
      <div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:10px">
        <label style="flex:2;min-width:220px">${t("Package name")}
          <input id="opk-name" value="${esc(pkg.name || "")}" maxlength="120"></label>
        <label style="width:110px">${t("Version")}
          <input id="opk-ver" value="${esc(pkg.version || "1.0.0")}"></label>
        <span style="font-size:11px;opacity:.65;padding-bottom:8px">${info.installed
          ? "🧩 " + t("Custom package installed") : "🏭 " + t("Built-in starter") + ": " + esc(info.builtin_label)}</span>
      </div>
      <div style="max-height:34vh;overflow:auto"><table class="noc-table" style="width:100%">
        <tr><th>${t("MODULE / REGISTER")}</th><th>${t("GROUP")}</th><th>ISO</th><th>${t("FIELDS")}</th><th></th></tr>
        ${pkg.modules.map(modRow).join("") || `<tr><td colspan="5" class="empty">${t("No modules yet — add the first one.")}</td></tr>`}
      </table></div>
      <label style="display:block;margin-top:10px"><span class="noc-lbl">💬 ${t("OPERATIONS CHAT DIRECTIVE — governs how the AI talks about this company's operations in every chat")}</span>
        <textarea id="opk-chat" rows="5" maxlength="20000" style="font-family:Consolas,monospace;font-size:11.5px" placeholder="${t('e.g. Act as senior recycling-operations staff of ACME SUPPLIES. Use R2v3/ISO terminology… (leave empty to keep the AI-generated company directive)')}">${esc(pkg.chat_prompt || "")}</textarea>
        <span style="font-size:10px;opacity:.55">${t("Travels INSIDE the package — installing this build on another deployment installs the chat doctrine too. Empty = fall back to the AI-generated directive.")}</span></label>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
        <button type="button" class="btn small primary" id="opk-add">➕ ${t("Add module")}</button>
        <button type="button" class="btn small" id="opk-export">⬇ ${t("Export JSON")}</button>
        <button type="button" class="btn small" id="opk-import">⬆ ${t("Import JSON")}</button>
        ${state.user && state.user.is_developer ? `<button type="button" class="btn small" id="opk-exp-co">🏢 ${t("Export company")}</button>` : ""}
        ${state.user && (state.user.is_developer || state.user.is_admin) ? `<button type="button" class="btn small" id="opk-imp-co">🏬 ${t("Import company")}</button>` : ""}
        <span style="flex:1"></span>
        ${info.installed ? `<button type="button" class="btn small" id="opk-revert">↩ ${t("Revert to built-in")}</button>` : ""}
        <button type="button" class="btn small primary" id="opk-install">💾 ${t("Install package")}</button>
      </div>
      <div style="font-size:10.5px;opacity:.55;margin-top:8px">
        ${t("Limits")}: ${info.limits.max_modules} ${t("modules")} · ${info.limits.max_fields} ${t("fields/module")} · ${info.limits.max_kb} KB</div>`,
      null);
    wire();
  }

  function editModule(i) {
    const m = i >= 0 ? pkg.modules[i]
      : { key: "", name: "", icon: "🏭", grp: "", iso: "", fields: [["at", "Date", "date"]] };
    const lines = m.fields.map(f => `${f[0]} | ${f[1]} | ${f[2]}`).join("\n");
    modal(i >= 0 ? `✏️ ${t("Edit module")} — ${m.name}` : `➕ ${t("New operations module")}`, `
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <label style="flex:2;min-width:200px">${t("Register name")} *<input data-f="name" value="${esc(m.name)}" maxlength="120" required></label>
        <label style="width:150px">${t("Key")} * <span style="opacity:.5;font-size:10px">(a-z, _)</span><input data-f="key" value="${esc(m.key)}" pattern="[a-z][a-z0-9_]*" maxlength="40" required ${i >= 0 ? "readonly" : ""}></label>
        <label style="width:70px">${t("Emoji")}<input data-f="icon" value="${esc(m.icon || "🏭")}" maxlength="4"></label>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <label style="flex:1;min-width:180px">${t("Process group")} <span style="opacity:.5;font-size:10px">(${t("e.g.")} "A · RECEIVING")</span><input data-f="grp" value="${esc(m.grp || "")}" maxlength="80"></label>
        <label style="width:170px">${t("ISO clause")}<input data-f="iso" value="${esc(m.iso || "")}" maxlength="80" placeholder="9001 §8.5.1"></label>
      </div>
      <label>${t("Fields — one per line")}: <code style="font-size:10px">id | ${t("Label")} | ${t("type")}</code>
        <span style="display:block;font-size:10px;opacity:.55">${t("Types")}: ${fieldTypeHelp}</span>
        <textarea data-f="fields" rows="10" style="font-family:Consolas,monospace;font-size:12px" required>${esc(lines)}</textarea></label>`,
      async () => {
        const v = {}; $$("#modal-root [data-f]").forEach(el => v[el.dataset.f] = el.value);
        const fields = [];
        for (const ln of String(v.fields || "").split("\n")) {
          const s = ln.trim(); if (!s) continue;
          const parts = s.split("|").map(x => x.trim());
          if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2])
            throw new Error(`${t("Bad field line")}: "${s}" — ${t("expected")} id | Label | type`);
          fields.push(parts);
        }
        if (!fields.length) throw new Error(t("At least one field is required"));
        const nm = { key: String(v.key || "").trim(), name: String(v.name || "").trim(),
                     icon: String(v.icon || "").trim() || "🏭",
                     grp: String(v.grp || "").trim(), iso: String(v.iso || "").trim(), fields };
        if (!/^[a-z][a-z0-9_]{0,39}$/.test(nm.key)) throw new Error(t("Key must be lowercase snake_case"));
        if (i >= 0) pkg.modules[i] = nm;
        else {
          if (pkg.modules.some(x => x.key === nm.key)) throw new Error(t("Duplicate module key"));
          pkg.modules.push(nm);
        }
        openStudio();          // back to the studio with the change applied
      }, i >= 0 ? t("Apply") : t("Add"));
  }

  function wire() {
    $$("#modal-root .ops-edit").forEach(b => b.onclick = () => { syncHead(); editModule(+b.dataset.i); });
    $$("#modal-root .ops-del").forEach(b => b.onclick = () => {
      if (!confirm(t("Remove this module from the package? Historic records are retained in the database."))) return;
      syncHead(); pkg.modules.splice(+b.dataset.i, 1); openStudio();
    });
    $("#opk-add").onclick = () => { syncHead(); editModule(-1); };
    $("#opk-export").onclick = () => {
      syncHead();
      const blob = new Blob([JSON.stringify(pkg, null, 1)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (pkg.name || "operations").replace(/[^\w-]+/g, "_") + "_v" + (pkg.version || "1.0.0") + ".json";
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    };
    $("#opk-import").onclick = () => {
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = ".json,application/json";
      inp.onchange = async () => {
        const f = inp.files[0]; if (!f) return;
        if (f.size > info.limits.max_kb * 1024) { toast(`❌ ${t("File exceeds")} ${info.limits.max_kb} KB`); return; }
        try {
          const j = JSON.parse(await f.text());
          if (!j || !Array.isArray(j.modules)) throw new Error(t("not an operations package"));
          pkg = j; openStudio();
          toast(`📦 ${t("Loaded")} "${j.name || f.name}" — ${t("review, then Install")}`);
        } catch (e) { toast("❌ " + t("Invalid package JSON") + ": " + e.message, "err"); }
      };
      inp.click();
    };
    $("#opk-install").onclick = async () => {
      syncHead();
      try {
        const r = await api("/business/ops-package", { method: "POST", body: { package: pkg } });
        toast(`✅ ${t("Operations package installed")} — "${r.package.name}" v${r.package.version}`);
        closeModal(); state.bizWs = null; render();
      } catch (e) { toast("❌ " + e.message, "err"); }
    };
    const rv = $("#opk-revert");
    if (rv) rv.onclick = async () => {
      if (!confirm(t("Remove the custom package and revert to the built-in industry template? Records are retained."))) return;
      try {
        await api("/business/ops-package", { method: "DELETE" });
        toast("↩ " + t("Reverted to built-in template"));
        closeModal(); state.bizWs = null; render();
      } catch (e) { toast("❌ " + e.message, "err"); }
    };
    const expCo = $("#opk-exp-co");
    if (expCo) expCo.onclick = async () => {   // developer: export a chosen company as a portable bundle
      try {
        const { companies } = await api("/dev/companies");
        if (!companies.length) { toast("❌ " + t("No commercial companies on this server")); return; }
        let oid = companies[0].owner_id;
        if (companies.length > 1) {
          const menu = companies.map((c, i) => `${i + 1}. ${c.company_name}`).join("\n");
          const pick = prompt(t("Export which company?") + "\n" + menu, "1");
          if (pick === null) return;
          const idx = parseInt(pick, 10) - 1;
          if (!(idx >= 0 && idx < companies.length)) { toast("❌ " + t("Invalid choice")); return; }
          oid = companies[idx].owner_id;
        }
        const bundle = await api("/dev/company-export?owner_id=" + encodeURIComponent(oid));
        const blob = new Blob([JSON.stringify(bundle, null, 1)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "company_" + (bundle.company.company_name || "export").replace(/[^\w-]+/g, "_") + ".json";
        a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
        toast(`🏢 ${t("Company exported")} — "${bundle.company.company_name}"`);
      } catch (e) { toast("❌ " + e.message, "err"); }
    };
    const impCo = $("#opk-imp-co");
    if (impCo) impCo.onclick = () => {         // developer/admin: import a company bundle onto this server
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = ".json,application/json";
      inp.onchange = async () => {
        const f = inp.files[0]; if (!f) return;
        try {
          const j = JSON.parse(await f.text());
          if (!j || j.schema !== "nexacrew-company/1") throw new Error(t("not a company bundle"));
          if (!confirm(`${t("Import company")} "${j.company.company_name}"? ${t("This replaces YOUR company profile and Operations Package (records are retained).")}`)) return;
          const r = await api("/dev/company-import", { method: "POST", body: j });
          toast(`✅ ${t("Company imported")} — "${r.company_name}"`);
          closeModal(); state.bizWs = null; render();
        } catch (e) { toast("❌ " + t("Import failed") + ": " + e.message, "err"); }
      };
      inp.click();
    };
  }
  openStudio();
}
/* per-field mnemonic emoji — keyed by field key (fallback: input type) */
const BIZ_FIELD_EMOJI = {
  lot: "🏷️", asset_id: "🏷️", sku: "🏷️", serial: "🔢", at: "📅", date_out: "📅", expiry: "⏳",
  audit_at: "📅", next_audit: "🗓️", source: "🏢", vendor: "🏢", dest: "📍", location: "📍",
  bin: "🗃️", carrier: "🚚", po: "📄", manifest: "📄", transfer_ref: "📄", shipment_ref: "📄",
  shipment: "📦", equipment: "🖥️", model: "🖥️", pallets: "📦", weight: "⚖️", qty: "🔢",
  qty_in: "⬇️", qty_out: "⬆️", balance: "🧮", data_bearing: "💽", fm: "🔋", material: "🔋",
  condition: "🔍", routing: "➡️", status: "🚦", by: "👤", tech: "👨‍🔧", inspector: "🕵️",
  coordinator: "👤", worker: "👤", witnesses: "👥", approved_by: "✍️", released_by: "✍️",
  verified_by: "✍️", grade: "⭐", cosmetic: "✨", label: "🏷️", reset: "🔄", aue: "⏳",
  safety: "🦺", tests: "🧪", result: "📊", repairs: "🔧", sample: "🔬", functional: "⚙️",
  accessories: "🎒", labelling: "🏷️", wipe_verified: "🧹", decision: "⚖️", assets: "🖥️",
  hdd: "💽", batteries: "🔋", pcb: "🟩", materials: "♻️", media_secured: "🔒",
  segregation: "🗂️", type: "📂", locked: "🔒", seals: "🔐", coc: "🔗", cert: "📜",
  inspection: "🔍", age_check: "⏳", record: "📄", certs: "📜", fm_accepted: "🔋",
  contents: "📦", packing: "📦", docs: "📄", aisles: "🚶", floors: "🧽", containers: "🗃️",
  leaks: "💧", fire: "🧯", cleanup: "🧹", action: "🛠️", desc: "📝", hauler: "🚚",
  aspect: "🌡️", limit: "📏", compliant: "✅", root_cause: "🔎", capa: "🛠️",
  risk_updated: "⚠️", reported: "📢", permit: "📜", agency: "🏛️", scope: "📋",
};
const bizFieldEmoji = (k, type) => BIZ_FIELD_EMOJI[k] || (type === "date" ? "📅" : type === "number" ? "🔢" : type && type.startsWith("checks") ? "🧪" : "");
async function refreshBusinessNav() {
  const box = $("#nav-biz");
  if (!box) return;
  try {
    const ws = await api("/business/workspace");
    state.bizWs = ws;
    const opsBtn = $("#nav-operations");
    if (opsBtn) opsBtn.classList.toggle("hidden", !ws.active);
    if (!ws.active) { box.innerHTML = ""; return; }
    const navBtn = $("#nav-business");
    if (navBtn) navBtn.innerHTML = `${ws.icon} ${esc(ws.company_name || ws.label)}`;
    let html = "";
    // ERP registers are shown ONLY inside the Business workspace menu —
    // they are intentionally NOT injected into the global nav to keep it clean.
    // POS Server / Purchasing / Accounting — ONLY for restaurant & supermarket
    try {
      const pn = await api("/pos/nav");
      state.posNav = pn;
      if (pn.pos) {
        for (const sec of pn.sections) {
          html += `<div class="nav-sec" style="font-size:10px;letter-spacing:.12em;opacity:.55;padding:8px 14px 2px">${esc(sec.label)}</div>`;
          html += sec.items.map(it => `<button class="nav-item nav-pos-item" data-kind="${it.kind}" style="padding-left:22px;font-size:12.5px">${it.icon} ${esc(it.label)}</button>`).join("");
        }
        html += `<div class="nav-sec" style="font-size:10px;letter-spacing:.12em;opacity:.55;padding:8px 14px 2px">PURCHASING & FINANCE</div>`;
        html += `<button class="nav-item nav-goto" data-goto="purchasing" style="padding-left:22px;font-size:12.5px">🛒 Purchasing & Invoices</button>`;
        html += `<button class="nav-item nav-goto" data-goto="accounting" style="padding-left:22px;font-size:12.5px">📒 Accounting & Tax</button>`;
      }
    } catch { /* pos nav unavailable */ }
    // WORKFORCE & ACCESS is industry-agnostic: worker badges, the check-in
    // time-clock kiosk and visitor management exist for EVERY company
    // profile — not just POS (restaurant/supermarket) deployments.
    html += `<div class="nav-sec" style="font-size:10px;letter-spacing:.12em;opacity:.55;padding:8px 14px 2px">WORKFORCE & ACCESS</div>`;
    html += `<button class="nav-item nav-goto" data-goto="workforce" style="padding-left:22px;font-size:12.5px">🪪 Workforce & Visitors</button>`;
    box.innerHTML = html;
    $$(".nav-biz-item").forEach(b => b.onclick = () => {
      state.bizModule = b.dataset.mod;
      $$(".nav-item[data-view]").forEach(x => x.classList.remove("active"));
      $$("#nav-biz .nav-item").forEach(x => x.classList.toggle("active", x === b));
      state.view = "business";
      render();
    });
    $$(".nav-pos-item").forEach(b => b.onclick = () => {
      state.posKind = b.dataset.kind;
      $$(".nav-item[data-view]").forEach(x => x.classList.remove("active"));
      $$("#nav-biz .nav-item").forEach(x => x.classList.toggle("active", x === b));
      state.view = "pos";
      render();
    });
    $$(".nav-goto").forEach(b => b.onclick = () => {
      $$(".nav-item[data-view]").forEach(x => x.classList.remove("active"));
      $$("#nav-biz .nav-item").forEach(x => x.classList.toggle("active", x === b));
      state.view = b.dataset.goto;
      render();
    });
    applyNavFilter();
    applyNavCollapse();
  } catch { box.innerHTML = ""; }
}

/* ---- Collapsible sidebar categories: only the group headers show by
   default; clicking a header drops down its menu items. The group holding
   the active view opens automatically. State persists per browser. ---- */
const NAVCOL_KEY = "navGroupsOpen";
function navColState() { try { return JSON.parse(localStorage.getItem(NAVCOL_KEY) || "{}"); } catch { return {}; } }
function navGroups() {
  // ordered walk of every header + item (includes the injected #nav-biz nodes)
  const nodes = [...document.querySelectorAll(".sidebar .nav-group, .sidebar .nav-item, .sidebar .nav-sec")];
  const groups = []; let cur = null;
  for (const n of nodes) {
    if (n.id === "logout-btn") continue;                 // always visible
    if (n.classList.contains("nav-group")) { cur = { head: n, items: [] }; groups.push(cur); }
    else if (cur) cur.items.push(n);
  }
  return groups;
}
function applyNavCollapse() {
  const inp = $("#nav-search");
  if (inp && inp.value.trim()) return;                   // search rules while typing
  const st = navColState();
  // accordion: exactly ONE category may be open — the last one the user
  // clicked; if none was clicked, the one holding the active view.
  const groups = navGroups();
  let openKey = st.open || "";
  if (!groups.some(g => g.head.textContent.trim() === openKey))
    openKey = "";
  if (!openKey && !st.none) {
    const act = groups.find(g => g.items.some(el => el.classList.contains("active")));
    if (act) openKey = act.head.textContent.trim();
  }
  for (const g of groups) {
    const open = g.head.textContent.trim() === openKey;
    g.head.classList.add("nav-collapsible");
    g.head.classList.toggle("nav-closed", !open);
    for (const el of g.items)
      el.style.display = (open && !el.classList.contains("hidden")) ? "" : "none";
    g.head.style.display = "";
  }
}
function initNavCollapse() {
  document.querySelectorAll(".sidebar .nav-group").forEach(h => {
    h.classList.add("nav-collapsible");
    h.onclick = () => {
      const key = h.textContent.trim();
      const wasOpen = !h.classList.contains("nav-closed");
      // accordion: the clicked category opens, every other one collapses;
      // clicking the already-open category collapses it too
      const st = { open: wasOpen ? "" : key, none: wasOpen };
      try { localStorage.setItem(NAVCOL_KEY, JSON.stringify(st)); } catch { }
      applyNavCollapse();
    };
  });
  applyNavCollapse();
}

/* ---- Sidebar menu search: type to filter every nav entry (static views,
   ERP business modules, POS sections, workforce…) and hit Enter to open the
   first match. Ctrl+K / Cmd+K focuses the box from anywhere. ---- */
function applyNavFilter() {
  const inp = $("#nav-search");
  if (!inp) return;
  const q = inp.value.trim().toLowerCase();
  const sidebar = document.querySelector(".sidebar");
  if (!q) {                                    // empty search → collapsed-category view
    sidebar.querySelectorAll(".nav-item").forEach(b => b.classList.remove("nav-hit"));
    applyNavCollapse();
    return null;
  }
  let first = null;
  sidebar.querySelectorAll(".nav-item").forEach(b => {
    if (b.id === "logout-btn") return;
    const hit = !q || b.textContent.toLowerCase().includes(q);
    // don't resurrect admin-only items hidden for non-admins
    if (b.dataset.view && b.classList.contains("hidden") && !b.dataset.navHidden) return;
    b.style.display = hit ? "" : "none";
    b.classList.toggle("nav-hit", !!q && hit && !first);
    if (hit && !first) first = b;
  });
  // hide group headers whose entire section is filtered out
  sidebar.querySelectorAll(".nav-group, .nav-sec").forEach(h => {
    h.classList.remove("nav-closed");
    let el = h.nextElementSibling, any = false;
    while (el && !el.classList.contains("nav-group") && !el.classList.contains("nav-sec")) {
      if (el.classList.contains("nav-item") && el.style.display !== "none" && !el.classList.contains("hidden")) { any = true; break; }
      el = el.nextElementSibling;
    }
    h.style.display = (!q || any) ? "" : "none";
  });
  return first;
}
function initNavSearch() {
  const inp = $("#nav-search");
  if (!inp) return;
  inp.oninput = applyNavFilter;
  inp.onkeydown = (e) => {
    if (e.key === "Enter") {
      const first = applyNavFilter();
      if (first) { first.click(); inp.value = ""; applyNavFilter(); inp.blur(); }
    } else if (e.key === "Escape") { inp.value = ""; applyNavFilter(); inp.blur(); }
  };
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); inp.focus(); inp.select(); }
  });
}

function nav(view) {
  if (state.station && view !== "operations") return;   // station terminals are locked to their register
  state.view = view;
  $$(".nav-item[data-view]").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  // clear highlight on injected business/POS/workforce nav items — they are
  // rendered outside [data-view] and would otherwise stay marked forever
  $$("#nav-biz .nav-item").forEach(b => b.classList.remove("active"));
  applyNavCollapse();
  render();
}

function contextBanner() {
  const c = state.companies.find(x => x.id === state.companyId);
  $("#context-banner").textContent = c ? `${t("Active company:")} ${c.logo} ${c.name}` : t("No company selected");
}

async function render() {
  contextBanner();
  const v = $("#view");
  const titles = { dashboard: "Dashboard", chats: "Chats", projects: "Projects", companies: "Companies", employees: "Employees", tasks: "Tasks", approvals: "Approval Inbox", skills: "Skills", schedules: "Schedules", calendar: "Calendar", email: "Email", business: "Business", operations: "Operations", pos: "POS Server", purchasing: "Purchasing", accounting: "Accounting", teams: "Team Management", workflows: "Workflow Management", sops: "SOP Library", shifts: "Shift Roster", backup: "Backup & Restore", cluster: "Cluster Network", clients: "Client Connections", sysstatus: "System Status", usage: "Token Usage", users: "User Management", setup: "Environment Setup", audit: "Audit Log", settings: "Settings" };
  $("#page-title").textContent = t(titles[state.view] || state.view);
  v.innerHTML = `<div class="empty">Loading…</div>`;
  const fn = views[state.view];
  if (!fn) {
    // stale cached app.js — force-reload the fresh version once
    v.innerHTML = `<div class="empty"><div class="big">♻</div>New version available — reloading…</div>`;
    location.reload();
    return;
  }
  try { await fn(v); } catch (e) { v.innerHTML = `<div class="empty"><div class="big">⚠️</div>${esc(e.message)}</div>`; }
}

const views = {};

/* ---------------- Dashboard ---------------- */
views.dashboard = async (v) => {
  const d = await api("/dashboard");
  v.innerHTML = `
  <div class="grid cols-4">
    ${[["🏢","Companies",d.companies],["👥","Employees",d.employees],["📁","Projects",d.projects],["✅","Open tasks",d.open_tasks],["🔔","Pending approvals",d.pending_approvals],["⚠️","Failed runs",d.failed_runs]].map(([e,t,n]) =>
      `<div class="card"><div class="emoji">${e}</div><h3>${t}</h3><div class="stat">${n}</div></div>`).join("")}
  </div>
  <div class="toolbar" style="margin-top:22px">
    <button class="btn primary" id="qa-chat">+ New Chat</button>
    <button class="btn" id="qa-project">+ New Project</button>
    <button class="btn" id="qa-company">+ New Company</button>
    <button class="btn" id="qa-employee">+ New Employee</button>
    <span class="pill ${d.codex_available ? "done" : "error"}">Codex CLI: ${d.codex_available ? "available ✓" : "not found ✗"}</span>
  </div>
  <h3 style="margin-top:26px">Recent agent runs</h3>
  ${d.recent_runs.length ? `<table><tr><th>When</th><th>Prompt</th><th>Status</th></tr>${d.recent_runs.map(r =>
    `<tr><td>${new Date(r.created_at).toLocaleString()}</td><td>${esc(r.prompt.slice(0,90))}</td><td><span class="pill ${r.status}">${r.status}</span></td></tr>`).join("")}</table>`
    : `<div class="empty"><div class="big">🤖</div>No agent runs yet. Start a chat to put your virtual employees to work.</div>`}`;
  $("#qa-chat").onclick = () => nav("chats");
  $("#qa-project").onclick = () => { nav("projects"); setTimeout(() => $("#new-project")?.click(), 80); };
  $("#qa-company").onclick = () => { nav("companies"); setTimeout(() => $("#new-company")?.click(), 80); };
  $("#qa-employee").onclick = () => { nav("employees"); setTimeout(() => $("#new-employee")?.click(), 80); };
};

/* ---------------- Companies ---------------- */
views.companies = async (v) => {
  const list = state.companies;
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Companies</span><span class="v">${list.length}</span></div>
    <div class="noc-kpi"><span class="k">Active tenant</span><span class="v">${esc((list.find(c => c.id === state.companyId) || {}).name || "—")}</span></div>
    <span class="spacer"></span>
    <button class="btn primary" id="new-company">+ New company</button>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">VIRTUAL COMPANY REGISTRY</span><span class="spacer"></span><small>${list.length} TENANT(S)</small></div>
    <div class="noc-body" style="padding:0">
    ${list.length ? `<table class="noc-table"><thead><tr>
      <th style="width:40px"></th><th>COMPANY</th><th>INDUSTRY</th><th>TIME ZONE</th><th>STATE</th><th>MISSION</th><th style="width:210px"></th></tr></thead><tbody>
      ${list.map(c => `<tr>
        <td style="text-align:center;font-size:17px">${esc(c.logo)}</td>
        <td><b>${esc(c.name)}</b>${c.website ? `<div class="muted" style="font-size:10.5px;font-family:Consolas,monospace">${esc(c.website)}</div>` : ""}</td>
        <td>${esc(c.industry || "—")}</td>
        <td style="font-size:11px;font-family:Consolas,monospace">${esc(c.timezone)}</td>
        <td>${c.id === state.companyId
          ? `<span class="noc-led ok"></span><span style="font-size:10.5px;font-family:Consolas,monospace">ACTIVE</span>`
          : `<span class="noc-led off"></span><span class="muted" style="font-size:10.5px;font-family:Consolas,monospace">STANDBY</span>`}</td>
        <td class="muted" style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(c.mission || c.description || "")}">${esc(c.mission || c.description || "—")}</td>
        <td style="text-align:right;white-space:nowrap">
          ${c.id !== state.companyId ? `<button class="btn small" data-activate="${c.id}">ACTIVATE</button>` : ""}
          <button class="btn small" data-edit="${c.id}">CONFIGURE</button>
          <button class="btn small danger" data-del="${c.id}">DELETE</button>
        </td></tr>`).join("")}
      </tbody></table>`
      : `<div class="empty"><div class="big">🏢</div>No companies yet — create your first virtual company.</div>`}
    </div>
  </div>`;
  $("#new-company").onclick = () => companyWizard();
  $$("[data-activate]", v).forEach(b => b.onclick = async () => {
    state.companyId = b.dataset.activate;
    state.projectId = null;
    await refreshCompanies(); await loadCompanyData(); render();
    toast("Active company switched", "ok");
  });
  $$("[data-edit]", v).forEach(b => b.onclick = () => companyWizard(list.find(c => c.id === b.dataset.edit)));
  $$("[data-del]", v).forEach(b => b.onclick = () => {
    if (!confirm("Delete this company and hide all its data?")) return;
    api(`/companies/${b.dataset.del}`, { method: "DELETE" }).then(async () => {
      toast("Company deleted", "ok"); state.companyId = null; await refreshCompanies(); await loadCompanyData(); render();
    }).catch(e => toast(e.message, "err"));
  });
};

const wizSect = (icon, title, sub) => `<div class="wiz-sect">${/^\d+$/.test(icon)
    ? `<span class="wiz-sect-num">${icon}</span>` : `<span class="wiz-sect-ic">${icon}</span>`}
    <div><b>${title}</b>${sub ? `<small>${sub}</small>` : ""}</div></div>`;

const COMPANY_EMOJIS = ["🏢", "🏦", "🏭", "🏪", "🏨", "🏛️", "🚀", "💡", "🎯", "🎨", "🎬", "🎵",
  "📚", "📰", "🛒", "🍔", "☕", "🍽️", "✈️", "🚗", "⚡", "🌱", "🏗️", "⚕️", "⚖️", "🔬", "💻", "🌐"];

const TIMEZONES = ["UTC", "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York",
  "Europe/London", "Europe/Paris", "Europe/Berlin", "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Taipei",
  "Asia/Tokyo", "Asia/Singapore", "Australia/Sydney"];

function companyWizard(c = null) {
  const f = (n, d = "") => esc(c ? c[n] : d);
  const curLogo = c ? c.logo : "🏢";
  const curTz = c ? c.timezone : "America/Los_Angeles";
  modal(c ? "Configure company — " + c.name : "Provision new company", `
    ${wizSect("01", "COMPANY PROFILE", "Basic identity of the virtual company")}
    <div class="wiz-grid">
      <label>Name *<input name="name" required value="${f("name")}" placeholder="e.g. MAP Studio"></label>
      <label>Industry<input name="industry" value="${f("industry")}" placeholder="e.g. Media production"></label>
      <label>Website<input name="website" value="${f("website")}" placeholder="www.example.com"></label>
      <label>Time zone<select name="timezone">${TIMEZONES.map(tz =>
        `<option ${tz === curTz ? "selected" : ""}>${tz}</option>`).join("")}
        ${TIMEZONES.includes(curTz) ? "" : `<option selected>${esc(curTz)}</option>`}</select></label>
    </div>
    <label>Logo</label>
    <input type="hidden" name="logo" id="logo-input" value="${esc(curLogo)}">
    <div class="avatar-row">
      <span class="avatar-preview" id="logo-preview">${esc(curLogo)}</span>
      <button type="button" class="btn" id="logo-toggle">Change…</button>
    </div>
    <div class="emoji-grid hidden" id="logo-grid">${COMPANY_EMOJIS.map(em =>
      `<button type="button" class="emoji-opt${curLogo === em ? " selected" : ""}" data-emoji="${em}">${em}</button>`).join("")}</div>

    ${wizSect("02", "CORPORATE IDENTITY", "Shapes how every AI employee represents this company — all fields optional")}
    <label>Description<textarea name="description" placeholder="What the company does, its products and customers…">${f("description")}</textarea></label>
    <label>Mission<textarea name="mission" placeholder="The company's purpose and long-term goal…">${f("mission")}</textarea></label>
    <label>Brand voice<textarea name="brand_voice" placeholder="e.g. professional and trustworthy; playful and bold…">${f("brand_voice")}</textarea></label>

    ${wizSect("03", "AI DIRECTIVES", "Standing instructions applied to every task performed in this company")}
    <label>Company-wide AI instructions<textarea name="ai_instructions" placeholder="e.g. Always reply in English; cite sources; never contact clients directly…">${f("ai_instructions")}</textarea></label>`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (c) await api(`/companies/${c.id}`, { method: "PUT", body });
      else await api("/companies", { method: "POST", body });
      toast(c ? "Company updated" : "Company created", "ok");
      await refreshCompanies(); await loadCompanyData(); render();
    });
  $$("#logo-grid .emoji-opt").forEach(b => b.onclick = () => {
    $("#logo-input").value = b.dataset.emoji;
    $("#logo-preview").textContent = b.dataset.emoji;
    $$("#logo-grid .emoji-opt").forEach(x => x.classList.toggle("selected", x === b));
    $("#logo-grid").classList.add("hidden");
  });
  $("#logo-toggle").onclick = () => $("#logo-grid").classList.toggle("hidden");
}

/* ---------------- Employees ---------------- */
views.employees = async (v) => {
  if (!state.companyId) { v.innerHTML = `<div class="empty"><div class="big">🏢</div>Create/select a company first.</div>`; return; }
  const emps = state.employees;
  const nActive = emps.filter(e => e.status === "Active").length;
  const nIdent = emps.filter(e => state.identities.some(i => i.employee_id === e.id)).length;
  const stLed = (s) => ({ Active: "ok", "On Leave": "warn", Inactive: "off", Archived: "off" }[s] || "off");
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Workforce</span><span class="v">${emps.length}</span></div>
    <div class="noc-kpi"><span class="k">Active</span><span class="v" style="color:#22c55e">${nActive}</span></div>
    <div class="noc-kpi"><span class="k">Mail identities</span><span class="v">${nIdent}/${emps.length}</span></div>
    <span class="spacer"></span>
    <button class="btn" id="connect-email">Connect email identity</button>
    <button class="btn primary" id="new-employee">+ New employee</button>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">VIRTUAL EMPLOYEE DIRECTORY</span><span class="spacer"></span><small>${emps.length} RECORD(S)</small></div>
    <div class="noc-body" style="padding:0">
    ${emps.length ? `<table class="noc-table"><thead><tr>
      <th style="width:36px"></th><th>NAME</th><th>ROLE</th><th>REPORTS TO</th><th>STATE</th><th>MAIL IDENTITY</th><th style="width:180px">PERMISSIONS</th><th style="width:130px"></th></tr></thead><tbody>
      ${emps.map(e => {
        const ident = state.identities.filter(i => i.employee_id === e.id).slice(-1)[0];
        const mgr = emps.find(x => x.id === e.manager_id);
        const np = (() => { try { return JSON.parse(e.permissions || "[]").length; } catch { return 0; } })();
        return `<tr>
        <td style="text-align:center;font-size:17px">${esc(e.avatar)}</td>
        <td><b>${esc(e.full_name)}</b></td>
        <td>${esc(e.job_title || "—")}</td>
        <td class="muted">${mgr ? esc(mgr.full_name) : "—"}</td>
        <td><span class="noc-led ${stLed(e.status)}"></span><span style="font-size:11px;font-family:Consolas,monospace;letter-spacing:.8px">${esc(e.status.toUpperCase())}</span></td>
        <td>${ident
          ? `<span class="noc-led ok"></span><span style="font-family:Consolas,monospace;font-size:12px">${esc(ident.email_address)}</span>
             <button class="btn small" data-test-email="${e.id}" title="Send a test email to this address" style="margin-left:8px">TEST</button>`
          : `<span class="noc-led off"></span><span class="muted" style="font-size:11px;font-family:Consolas,monospace">NOT CONFIGURED</span>`}</td>
        <td><div style="display:flex;align-items:center;gap:7px">
          <div style="flex:1;height:5px;border-radius:3px;background:rgba(148,163,184,.15);overflow:hidden">
            <div style="width:${Math.round(np / 12 * 100)}%;height:100%;background:${np > 8 ? "#eab308" : "#4f8ef7"}"></div></div>
          <span style="font-size:10px;font-family:Consolas,monospace;color:var(--muted)">${np}/12</span></div></td>
        <td style="text-align:right"><button class="btn small" data-edit="${e.id}">CONFIGURE</button></td></tr>`; }).join("")}
      </tbody></table>`
      : `<div class="empty"><div class="big">👥</div>No employees yet — hire your first virtual employee.</div>`}
    </div>
  </div>`;
  $("#new-employee").onclick = () => employeeWizard();
  $("#connect-email").onclick = () => identityWizard();
  $$("[data-edit]", v).forEach(b => b.onclick = () => employeeWizard(emps.find(e => e.id === b.dataset.edit)));
  $$("[data-test-email]", v).forEach(a => a.onclick = async (ev) => {
    ev.preventDefault();
    a.textContent = "SENDING…"; a.disabled = true;
    try {
      const res = await api(`/employees/${a.dataset.testEmail}/test-email`, { method: "POST", body: {} });
      toast(res.detail, "ok");
    } catch (err) { toast(err.message || "Test email failed", "err"); }
    a.textContent = "TEST"; a.disabled = false;
  });
};

const AVATAR_EMOJIS = [
  "🧑‍💼", "👨‍💼", "👩‍💼", "🧑‍💻", "👨‍💻", "👩‍💻", "🧑‍🔧", "👨‍🔧", "👩‍🔧",
  "🧑‍🎨", "👨‍🎨", "👩‍🎨", "🧑‍🔬", "👨‍🔬", "👩‍🔬", "🧑‍🏫", "👨‍🏫", "👩‍🏫",
  "🧑‍⚖️", "👨‍⚖️", "👩‍⚖️", "🧑‍⚕️", "👨‍⚕️", "👩‍⚕️", "🧑‍🍳", "👨‍🍳", "👩‍🍳",
  "🤖", "🦸", "🦹", "👽", "🧠", "🦅", "🦊", "🐱", "🐶", "🐼", "🦁", "🐲",
  "⭐", "🚀", "💡", "🎯", "🔥", "💎"
];

const PERM_META = {
  view:               ["View",               "Read companies, projects and tasks"],
  create:             ["Create",             "Create new items and documents"],
  edit:               ["Edit",               "Modify existing content"],
  delete:             ["Delete",             "Remove items permanently"],
  archive:            ["Archive",            "Move items to the archive"],
  draft_external:     ["Draft external",     "Prepare outbound e-mails (drafts)"],
  send_external:      ["Send external",      "Send e-mails to outside recipients"],
  access_files:       ["Access files",       "Read and write workspace files"],
  execute_code:       ["Execute code",       "Run scripts and programs"],
  use_integrations:   ["Use integrations",   "Call connected external services"],
  manage_credentials: ["Manage credentials", "Store and change account secrets"],
  manage_org:         ["Manage organization","Change company structure and staff"],
};

async function employeeWizard(e = null) {
  const [templates, perms] = await Promise.all([api("/employee-templates"), api("/permissions")]);
  const f = (n, d = "") => esc(e ? e[n] : d);
  const curPerms = e ? JSON.parse(e.permissions || "[]") : ["view", "create", "edit", "draft_external"];
  modal(e ? "Configure employee — " + e.full_name : "Provision new employee", `
    ${e ? "" : `${wizSect("01", "ROLE TEMPLATE", "Pre-fills role, responsibilities and permissions — everything stays editable")}
    <label>Template<select name="template"><option value="">— custom —</option>
      ${Object.keys(templates).map(t => `<option>${esc(t)}</option>`).join("")}</select></label>`}

    ${wizSect("02", "IDENTITY", "Who this virtual employee is")}
    <div class="wiz-grid">
      <label>Full name *<input name="full_name" required value="${f("full_name")}" placeholder="e.g. Alex Chen"></label>
      <label>Job title<input name="job_title" value="${f("job_title")}" placeholder="e.g. Marketing Manager"></label>
      <label>Manager<select name="manager_id"><option value="">— none —</option>
        ${state.employees.filter(x => !e || x.id !== e.id).map(x => `<option value="${x.id}" ${e && e.manager_id === x.id ? "selected" : ""}>${esc(x.full_name)}</option>`).join("")}</select></label>
      <label>Status<select name="status">${["Active","Inactive","On Leave","Archived"].map(s => `<option ${e && e.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
    </div>
    <label>Avatar</label>
    <input type="hidden" name="avatar" id="avatar-input" value="${f("avatar","🧑‍💼")}">
    <div class="avatar-row">
      <span class="avatar-preview" id="avatar-preview">${f("avatar","🧑‍💼")}</span>
      <button type="button" class="btn" id="avatar-toggle">Change…</button>
    </div>
    <div class="emoji-grid hidden" id="avatar-grid">${AVATAR_EMOJIS.map(em =>
      `<button type="button" class="emoji-opt${(e ? e.avatar : "🧑‍💼") === em ? " selected" : ""}" data-emoji="${em}">${em}</button>`).join("")}</div>

    ${wizSect(e ? "02" : "03", "ROLE PROFILE", "Defines how the AI performs this role — all fields optional")}
    <label>Biography<textarea name="biography" placeholder="Background and experience of this employee…">${f("biography")}</textarea></label>
    <label>Responsibilities<textarea name="responsibilities" placeholder="Key duties, e.g. campaign planning, client communication…">${f("responsibilities")}</textarea></label>
    <label>Skills<textarea name="skills" placeholder="Competencies, e.g. copywriting, data analysis, Photoshop…">${f("skills")}</textarea></label>
    <label>Working style & tone<textarea name="working_style" placeholder="e.g. concise and formal; friendly and detailed…">${f("working_style")}</textarea></label>
    <label>System instructions<textarea name="system_instructions" placeholder="Extra directives always applied when this employee works…">${f("system_instructions")}</textarea></label>

    ${wizSect(e ? "03" : "04", "ACCESS CONTROL", "Least-privilege permission set — sensitive actions still require your approval")}
    <div class="perm-grid">${perms.map(p => {
      const [label, desc] = PERM_META[p] || [p.replace(/_/g, " "), ""];
      return `<label class="perm-item" title="${esc(desc)}"><input type="checkbox" name="perm" value="${p}" ${curPerms.includes(p) ? "checked" : ""}>
        <span class="perm-text"><b>${label}</b><small>${desc}</small></span></label>`;
    }).join("")}</div>`,
    async (fd) => {
      const body = Object.fromEntries([...fd.entries()].filter(([k]) => k !== "perm" && k !== "template"));
      body.permissions = [...fd.getAll("perm")];
      if (!body.manager_id) body.manager_id = null;
      if (e) await api(`/employees/${e.id}`, { method: "PUT", body });
      else await api(`/companies/${state.companyId}/employees`, { method: "POST", body });
      toast("Employee saved", "ok"); await loadCompanyData(); render();
    });
  const tmplSel = $('select[name="template"]');
  if (tmplSel) tmplSel.onchange = () => {
    const t = templates[tmplSel.value]; if (!t) return;
    $('input[name="job_title"]').value = t.job_title;
    $('textarea[name="responsibilities"]').value = t.responsibilities;
    $$('.perm-grid input').forEach(cb => cb.checked = t.permissions.includes(cb.value));
  };
  $$("#avatar-grid .emoji-opt").forEach(b => b.onclick = () => {
    $("#avatar-input").value = b.dataset.emoji;
    $("#avatar-preview").textContent = b.dataset.emoji;
    $$("#avatar-grid .emoji-opt").forEach(x => x.classList.toggle("selected", x === b));
    $("#avatar-grid").classList.add("hidden");
  });
  $("#avatar-toggle").onclick = () => $("#avatar-grid").classList.toggle("hidden");
}

function identityWizard() {
  modal("Connect email identity", `
    ${wizSect("01", "ASSIGNMENT", "Which virtual employee will own this mailbox")}
    <label>Employee *<select name="employee_id" required>
      ${state.employees.map(e => `<option value="${e.id}">${esc(e.full_name)}${e.job_title ? " · " + esc(e.job_title) : ""}</option>`).join("")}</select></label>
    ${wizSect("02", "MAILBOX", "Outbound identity used on all e-mail this employee sends")}
    <label>Email address *<input name="email_address" type="email" required placeholder="name@example.com"></label>
    <label>Display name<input name="display_name" placeholder="Shown as the sender name"></label>
    <label>Signature<textarea name="signature" placeholder="Appended to every outbound message…"></textarea></label>
    <div style="border:1px solid var(--border);border-radius:7px;padding:9px 12px;margin-top:6px">
      <div style="font-size:10px;font-family:Consolas,monospace;letter-spacing:1.2px;color:var(--muted);margin-bottom:4px">TRANSPORT PROVIDER</div>
      <div style="font-size:12px"><span class="noc-led warn"></span><b style="font-family:Consolas,monospace">local-dev</b>
        <span class="muted">— development adapter: simulated sends, clearly labeled; no real email is delivered.</span></div>
      <div class="muted" style="font-size:11px;margin-top:3px">Credentials for production providers are stored encrypted server-side (AES, at rest).</div>
    </div>`,
    async (fd) => {
      await api(`/companies/${state.companyId}/identities`, { method: "POST", body: Object.fromEntries(fd.entries()) });
      toast("Email identity connected & verified (local-dev)", "ok");
      await loadCompanyData(); render();
    }, "Connect");
}

/* ---------------- Projects ---------------- */
views.projects = async (v) => {
  if (!state.companyId) { v.innerHTML = `<div class="empty"><div class="big">🏢</div>Select a company first.</div>`; return; }
  if (state.projectId) return projectDetail(v, state.projectId);
  const projects = await api(`/companies/${state.companyId}/projects`);
  const active = projects.filter(p => p.status === "Active").length;
  const stLed = (s) => ({ Active: "ok", "On Hold": "warn", Completed: "ok", Archived: "off" }[s] || "off");
  const priCol = (x) => ({ Critical: "#ef4444", High: "#f97316", Medium: "#4f8ef7", Low: "#94a3b8" }[x] || "#94a3b8");
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Portfolio</span><span class="v">${projects.length}</span></div>
    <div class="noc-kpi"><span class="k">Active</span><span class="v" style="color:#22c55e">${active}</span></div>
    <span class="spacer"></span>
    <button class="btn primary" id="new-project">+ New project</button>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">PROJECT PORTFOLIO — ISO 21500 GOVERNED</span><span class="spacer"></span><small>${projects.length} PROJECT(S)</small></div>
    <div class="noc-body" style="padding:0">
    ${projects.length ? `<table class="noc-table"><thead><tr>
      <th>PROJECT</th><th style="width:100px">STATE</th><th style="width:100px">PRIORITY</th><th style="width:110px">DUE</th>
      <th>DESCRIPTION</th><th style="width:130px"></th></tr></thead><tbody>
      ${projects.map(p => `<tr data-project="${p.id}" style="cursor:pointer">
        <td><b>${esc(p.name)}</b></td>
        <td><span class="noc-led ${stLed(p.status)}"></span><span style="font-size:10.5px;font-family:Consolas,monospace">${esc(p.status.toUpperCase())}</span></td>
        <td><span style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;color:${priCol(p.priority)};border:1px solid ${priCol(p.priority)};border-radius:4px;padding:1.5px 7px">${esc(p.priority.toUpperCase())}</span></td>
        <td style="font-size:11px;font-family:Consolas,monospace;color:var(--muted)">${esc(p.due_date || "—")}</td>
        <td class="muted" style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.description || "—")}</td>
        <td style="text-align:right"><button class="btn small" data-project="${p.id}">WORKSPACE</button></td></tr>`).join("")}
      </tbody></table>`
      : `<div class="empty"><div class="big">📁</div>No projects yet.</div>`}
    </div>
  </div>`;
  $("#new-project").onclick = () => modal("Provision new project", `
    ${wizSect("01", "DEFINITION", "Name, priority and delivery target")}
    <label>Name *<input name="name" required></label>
    <label>Description<textarea name="description"></textarea></label>
    <div class="wiz-grid">
      <label>Priority<select name="priority"><option>Low</option><option selected>Medium</option><option>High</option><option>Critical</option></select></label>
      <label>Due date<input name="due_date" type="date"></label>
    </div>
    ${wizSect("02", "EXECUTION DIRECTIVES", "Given to every AI employee working in this project")}
    <label>Project instructions<textarea name="instructions"></textarea></label>
    <label>Goals<textarea name="goals"></textarea></label>`,
    async (fd) => {
      await api(`/companies/${state.companyId}/projects`, { method: "POST", body: Object.fromEntries(fd.entries()) });
      toast("Project created", "ok"); render();
    });
  $$("[data-project]", v).forEach(el => el.onclick = () => { state.projectId = el.dataset.project; render(); });
};

/* ---------------- Project workspace: cross-referenced conversations ---------------- */
async function projectDetail(v, pid) {
  let ov;
  try { ov = await api(`/projects/${pid}/overview`); }
  catch (e) { state.projectId = null; toast(e.message, "err"); render(); return; }
  const p = ov.project;
  const g = ov.governance || {};
  const comp = ov.compliance || { score: 0, phase: "Initiating", phases: [], subjects: [] };
  const fmt = (iso) => iso ? new Date(iso).toLocaleString() : "—";
  const doneTasks = ov.tasks.filter(t => t.status === "Completed").length;
  const compCol = comp.score >= 80 ? "#22c55e" : comp.score >= 50 ? "#eab308" : "#ef4444";
  v.innerHTML = `
  <div class="noc-topbar">
    <button class="btn" id="proj-back">← Projects</button>
    <div class="noc-kpi"><span class="k">Project</span><span class="v">${esc(p.name)}</span></div>
    <div class="noc-kpi"><span class="k">Status</span><span class="v"><span class="noc-led ${p.status === "Active" ? "ok" : "off"}"></span>${esc(p.status)}</span></div>
    <div class="noc-kpi"><span class="k">ISO 21500</span><span class="v" style="color:${compCol}">${comp.score}%</span></div>
    <div class="noc-kpi"><span class="k">Conversations</span><span class="v">${ov.chats.length}</span></div>
    <div class="noc-kpi"><span class="k">Messages</span><span class="v">${ov.total_messages}</span></div>
    <div class="noc-kpi"><span class="k">Tasks</span><span class="v">${doneTasks}/${ov.tasks.length} done</span></div>
    <span class="spacer"></span>
    <button class="btn" id="proj-edit">Configure</button>
    <button class="btn" id="proj-link-chat">Link conversation</button>
    <button class="btn primary" id="proj-new-chat">+ New conversation</button>
  </div>
  ${p.description ? `<p class="muted" style="margin:4px 2px 10px">${esc(p.description)}</p>` : ""}
  <div class="noc-panel" style="margin-bottom:14px">
    <div class="noc-head"><span class="noc-lbl">PROJECT GOVERNANCE — ISO 21500</span>
      <span class="spacer"></span><small>COMPLIANCE <b style="color:${compCol}">${comp.score}%</b> · ${comp.subjects.filter(s => s.ok).length}/10 SUBJECT GROUPS</small></div>
    <div class="noc-body">
      <div style="display:flex;gap:0;margin-bottom:12px;border:1px solid var(--border);border-radius:7px;overflow:hidden">
        ${comp.phases.map((ph, i) => {
          const cur = ph === comp.phase, past = comp.phases.indexOf(comp.phase) > i;
          return `<div class="gov-phase" data-phase="${ph}" style="flex:1;text-align:center;padding:7px 4px;cursor:pointer;font-size:10.5px;font-family:Consolas,monospace;letter-spacing:1px;
            background:${cur ? "rgba(79,142,247,.18)" : past ? "rgba(34,197,94,.08)" : "transparent"};
            color:${cur ? "#4f8ef7" : past ? "#22c55e" : "var(--muted)"};
            border-left:${i ? "1px solid var(--border)" : "none"};font-weight:${cur ? "800" : "400"}"
            title="Set process group">${past ? "✓ " : ""}${ph.toUpperCase()}</div>`; }).join("")}
      </div>
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px">
        ${comp.subjects.map(s => `<div class="gov-subj" data-subj="${esc(s.subject)}" style="border:1px solid var(--border);border-radius:6px;padding:7px 9px;cursor:pointer"
          title="${esc(s.requirement)} — click to ${s.ok ? "review" : "complete"}"
          onmouseover="this.style.borderColor='#4f8ef7'" onmouseout="this.style.borderColor='var(--border)'">
          <span class="noc-led ${s.ok ? "ok" : "off"}"></span>
          <span style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;color:${s.ok ? "var(--text)" : "var(--muted)"}">${esc(s.subject.toUpperCase())}</span></div>`).join("")}
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn small" id="gov-charter">CHARTER &amp; SCOPE</button>
        <button class="btn small" id="gov-stake">STAKEHOLDERS · ${(g.stakeholders || []).length}</button>
        <button class="btn small" id="gov-risk">RISK REGISTER · ${(g.risks || []).length}</button>
        <button class="btn small" id="gov-mile">MILESTONES · ${(g.milestones || []).length}</button>
        <button class="btn small" id="gov-cost">BUDGET</button>
        <button class="btn small" id="gov-plan">QUALITY · PROCUREMENT · COMMS</button>
        <button class="btn small" id="gov-lessons">LESSONS LEARNED · ${(g.lessons || []).length}</button>
      </div>
      ${(g.risks || []).length ? `<table class="noc-table" style="margin-top:12px"><thead><tr><th>Risk</th><th>P</th><th>I</th><th>Response</th><th>Owner</th><th>Status</th></tr></thead><tbody>
        ${g.risks.map(r => `<tr><td>${esc(r.title)}</td><td>${esc(r.probability || "—")}</td><td>${esc(r.impact || "—")}</td><td>${esc(r.response || "—")}</td><td>${esc(r.owner || "—")}</td><td><span class="noc-led ${r.status === "Closed" ? "ok" : "warn"}"></span>${esc(r.status || "Open")}</td></tr>`).join("")}</tbody></table>` : ""}
      ${(g.milestones || []).length ? `<table class="noc-table" style="margin-top:10px"><thead><tr><th>Milestone</th><th>Date</th><th>Status</th></tr></thead><tbody>
        ${g.milestones.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.date || "—")}</td><td><span class="noc-led ${m.status === "Done" ? "ok" : "warn"}"></span>${esc(m.status || "Planned")}</td></tr>`).join("")}</tbody></table>` : ""}
    </div>
  </div>
  <div class="noc-panel" style="margin-bottom:14px">
    <div class="noc-head"><span class="noc-lbl">CROSS-REFERENCE SEARCH — ALL PROJECT CONVERSATIONS</span></div>
    <div class="noc-body">
      <input id="proj-search" placeholder="Search every message across the ${ov.chats.length} conversation(s) in this project…" style="width:100%">
      <div id="proj-search-out"></div>
    </div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">LINKED CONVERSATIONS</span><span class="spacer"></span><small>${ov.chats.length} LINKED</small></div>
    <div class="noc-body">
    ${ov.chats.length ? `<table class="noc-table"><thead><tr>
      <th>Conversation</th><th>Participants</th><th>Msgs</th><th>Last activity</th><th>Last message</th><th></th></tr></thead><tbody>
      ${ov.chats.map(c => `<tr>
        <td><a href="#" data-open-chat="${c.id}" style="font-weight:600">${esc(c.title)}</a></td>
        <td>${c.participants.map(x => esc(x.avatar + " " + x.name)).join(", ") || "—"}</td>
        <td>${c.message_count}</td>
        <td class="muted">${fmt(c.last_message_at)}</td>
        <td class="muted" style="max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.last_message)}</td>
        <td><button class="btn small" data-unlink="${c.id}" title="Remove from project">UNLINK</button></td>
      </tr>`).join("")}</tbody></table>`
      : `<div class="empty"><div class="big">💬</div>No conversations linked yet — right-click any chat → “Add to project…”, or use the buttons above.</div>`}
    </div>
  </div>`;

  $("#proj-back").onclick = () => { state.projectId = null; render(); };

  // ---------- ISO 21500 governance handlers ----------
  const gov = async (patch) => {
    await api(`/projects/${pid}/governance`, { method: "PUT", body: patch });
    toast("Governance updated", "ok"); render();
  };
  $$(".gov-phase", v).forEach(el => el.onclick = () => gov({ phase: el.dataset.phase }));
  $("#gov-charter").onclick = () => modal("Integration & Scope — ISO 21500", `
    <label>Project sponsor<input name="sponsor" value="${esc(g.sponsor || "")}"></label>
    <label>Project manager<input name="manager" value="${esc(g.manager || "")}"></label>
    <label>Project charter / business case<textarea name="charter" rows="5">${esc(g.charter || "")}</textarea></label>
    <label>Scope statement (deliverables, boundaries, exclusions)<textarea name="scope_statement" rows="4">${esc(g.scope_statement || "")}</textarea></label>`,
    (fd) => gov(Object.fromEntries(fd.entries())));
  $("#gov-stake").onclick = () => {
    const rows = (g.stakeholders || []).map((s, i) =>
      `<tr><td>${esc(s.name)}</td><td>${esc(s.role || "—")}</td><td>${esc(s.influence || "—")}</td><td><button class="btn small" data-rm-st="${i}">✕</button></td></tr>`).join("");
    modal("Stakeholder register — ISO 21500", `
      ${rows ? `<table class="noc-table"><thead><tr><th>Name</th><th>Role</th><th>Influence</th><th></th></tr></thead><tbody>${rows}</tbody></table><br>` : ""}
      <label>Name *<input name="name" required></label>
      <label>Role / interest<input name="role"></label>
      <label>Influence<select name="influence"><option>Low</option><option selected>Medium</option><option>High</option></select></label>
      <label>Engagement approach<input name="engagement"></label>`,
      (fd) => gov({ stakeholders: [...(g.stakeholders || []), Object.fromEntries(fd.entries())] }), "Add");
    $$("[data-rm-st]").forEach(b => b.onclick = () =>
      gov({ stakeholders: g.stakeholders.filter((_, i) => i !== +b.dataset.rmSt) }));
  };
  $("#gov-risk").onclick = () => {
    const rows = (g.risks || []).map((r, i) =>
      `<tr><td>${esc(r.title)}</td><td>${esc(r.probability || "—")}/${esc(r.impact || "—")}</td><td>${esc(r.status || "Open")}</td><td><button class="btn small" data-rm-rk="${i}">✕</button></td></tr>`).join("");
    modal("Risk register — ISO 21500", `
      ${rows ? `<table class="noc-table"><thead><tr><th>Risk</th><th>P/I</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table><br>` : ""}
      <label>Risk description *<input name="title" required></label>
      <label>Probability<select name="probability"><option>Low</option><option selected>Medium</option><option>High</option></select></label>
      <label>Impact<select name="impact"><option>Low</option><option selected>Medium</option><option>High</option></select></label>
      <label>Response (avoid / mitigate / transfer / accept)<input name="response"></label>
      <label>Owner<input name="owner"></label>
      <label>Status<select name="status"><option selected>Open</option><option>Monitoring</option><option>Closed</option></select></label>`,
      (fd) => gov({ risks: [...(g.risks || []), Object.fromEntries(fd.entries())] }), "Add");
    $$("[data-rm-rk]").forEach(b => b.onclick = () =>
      gov({ risks: g.risks.filter((_, i) => i !== +b.dataset.rmRk) }));
  };
  $("#gov-mile").onclick = () => {
    const rows = (g.milestones || []).map((m, i) =>
      `<tr><td>${esc(m.name)}</td><td>${esc(m.date || "—")}</td><td>${esc(m.status || "Planned")}</td><td><button class="btn small" data-rm-ml="${i}">✕</button></td></tr>`).join("");
    modal("Milestones / schedule — ISO 21500", `
      ${rows ? `<table class="noc-table"><thead><tr><th>Milestone</th><th>Date</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table><br>` : ""}
      <label>Milestone *<input name="name" required></label>
      <label>Target date<input name="date" type="date"></label>
      <label>Status<select name="status"><option selected>Planned</option><option>At Risk</option><option>Done</option></select></label>`,
      (fd) => gov({ milestones: [...(g.milestones || []), Object.fromEntries(fd.entries())] }), "Add");
    $$("[data-rm-ml]").forEach(b => b.onclick = () =>
      gov({ milestones: g.milestones.filter((_, i) => i !== +b.dataset.rmMl) }));
  };
  $("#gov-cost").onclick = () => modal("Cost management — ISO 21500", `
    <label>Currency<input name="currency" value="${esc((g.budget || {}).currency || "USD")}"></label>
    <label>Planned budget<input name="planned" value="${esc((g.budget || {}).planned || "")}"></label>
    <label>Actual spend to date<input name="actual" value="${esc((g.budget || {}).actual || "")}"></label>`,
    (fd) => gov({ budget: Object.fromEntries(fd.entries()) }));
  $("#gov-plan").onclick = () => modal("Quality · Procurement · Communication — ISO 21500", `
    <label>Quality / acceptance criteria<textarea name="quality_criteria" rows="3">${esc(g.quality_criteria || "")}</textarea></label>
    <label>Procurement approach<textarea name="procurement" rows="3">${esc(g.procurement || "")}</textarea></label>
    <label>Communication plan (who, what, when, how)<textarea name="comms_plan" rows="3">${esc(g.comms_plan || "")}</textarea></label>`,
    (fd) => gov(Object.fromEntries(fd.entries())));
  $("#gov-lessons").onclick = () => {
    const rows = (g.lessons || []).map((l, i) =>
      `<tr><td>${esc(l.note)}</td><td class="muted">${esc(l.at || "")}</td><td><button class="btn small" data-rm-ls="${i}">✕</button></td></tr>`).join("");
    modal("Lessons learned — ISO 21500 (Closing)", `
      ${rows ? `<table class="noc-table"><thead><tr><th>Lesson</th><th>When</th><th></th></tr></thead><tbody>${rows}</tbody></table><br>` : ""}
      <label>Lesson learned *<textarea name="note" required rows="3"></textarea></label>`,
      (fd) => gov({ lessons: [...(g.lessons || []), { note: fd.get("note"), at: new Date().toISOString().slice(0, 10) }] }), "Add");
    $$("[data-rm-ls]").forEach(b => b.onclick = () =>
      gov({ lessons: g.lessons.filter((_, i) => i !== +b.dataset.rmLs) }));
  };

  // subject-group grid → click opens the editor that satisfies that group
  const SUBJ_TO_BTN = {
    Integration: "gov-charter", Scope: "gov-charter", Resource: "gov-charter",
    Stakeholder: "gov-stake", Risk: "gov-risk", Time: "gov-mile", Cost: "gov-cost",
    Quality: "gov-plan", Procurement: "gov-plan", Communication: "gov-plan",
  };
  $$(".gov-subj", v).forEach(el => el.onclick = () => {
    const btn = $("#" + (SUBJ_TO_BTN[el.dataset.subj] || "gov-charter"));
    if (btn) btn.click();
  });

  $("#proj-edit").onclick = () => modal("Configure project — " + p.name, `
    ${wizSect("01", "DEFINITION", "Name, state, priority and delivery target")}
    <label>Name *<input name="name" required value="${esc(p.name)}"></label>
    <label>Description<textarea name="description">${esc(p.description || "")}</textarea></label>
    <div class="wiz-grid">
      <label>Status<select name="status">${["Active","On Hold","Completed","Archived"].map(s => `<option ${p.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
      <label>Priority<select name="priority">${["Low","Medium","High","Critical"].map(x => `<option ${p.priority === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
    </div>
    <label>Due date<input name="due_date" type="date" value="${esc(p.due_date || "")}"></label>
    ${wizSect("02", "EXECUTION DIRECTIVES", "Given to every AI employee working in this project")}
    <label>Project instructions<textarea name="instructions">${esc(p.instructions || "")}</textarea></label>
    <label>Goals<textarea name="goals">${esc(p.goals || "")}</textarea></label>`,
    async (fd) => {
      await api(`/projects/${pid}`, { method: "PUT", body: Object.fromEntries(fd.entries()) });
      toast("Project updated", "ok"); render();
    });

  // open a linked conversation in the chat view
  $$("[data-open-chat]", v).forEach(a => a.onclick = (e) => {
    e.preventDefault();
    state.chatId = a.dataset.openChat;
    nav("chats");
  });

  // unlink a conversation from the project
  $$("[data-unlink]", v).forEach(b => b.onclick = async () => {
    const c = ov.chats.find(x => x.id === b.dataset.unlink);
    await api(`/chats/${c.id}`, { method: "PUT", body: {
      title: c.title, company_id: c.company_id, project_id: null,
      active_employee_id: c.active_employee_id } });
    toast("Conversation unlinked", "ok"); render();
  });

  // link an existing conversation
  $("#proj-link-chat").onclick = async () => {
    const all = await api("/chats");
    const linked = new Set(ov.chats.map(c => c.id));
    const candidates = all.filter(c => !linked.has(c.id));
    if (!candidates.length) { toast("All your conversations are already linked", "err"); return; }
    modal("Link conversation to project", `
      <label>Conversation<select name="cid">
        ${candidates.map(c => `<option value="${c.id}">💬 ${esc(c.title)}${c.project_id ? " (in another project)" : ""}</option>`).join("")}
      </select></label>`,
      async (fd) => {
        const c = candidates.find(x => x.id === fd.get("cid"));
        await api(`/chats/${c.id}`, { method: "PUT", body: {
          title: c.title, company_id: c.company_id || state.companyId,
          project_id: pid, active_employee_id: c.active_employee_id } });
        toast("Conversation linked to project", "ok"); render();
      }, "Link");
  };

  // start a new conversation already attached to this project
  $("#proj-new-chat").onclick = async () => {
    const c = await api("/chats", { method: "POST", body: {
      title: `${p.name} — discussion`, company_id: p.company_id, project_id: pid } });
    state.chatId = c.id;
    nav("chats");
  };

  // cross-reference search across all project conversations
  let t = null;
  $("#proj-search").oninput = (e) => {
    clearTimeout(t);
    const q = e.target.value.trim();
    t = setTimeout(async () => {
      const out = $("#proj-search-out");
      if (q.length < 2) { out.innerHTML = ""; return; }
      const hits = await api(`/projects/${pid}/search?q=${encodeURIComponent(q)}`);
      out.innerHTML = hits.length ? `<table class="noc-table" style="margin-top:10px"><thead><tr>
        <th>Conversation</th><th>Speaker</th><th>Match</th><th>When</th></tr></thead><tbody>
        ${hits.map(h => `<tr style="cursor:pointer" data-hit-chat="${h.chat_id}" data-hit-msg="${h.message_id}">
          <td>💬 ${esc(h.chat_title)}</td><td>${esc(h.speaker)}</td>
          <td style="max-width:420px">${esc(h.snippet)}</td>
          <td class="muted">${fmt(h.at)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="muted" style="margin-top:10px">No matches for “${esc(q)}” in this project's conversations.</p>`;
      $$("[data-hit-chat]", out).forEach(r => r.onclick = () => {
        state.chatId = r.dataset.hitChat;
        state.searchHit = { term: q, messageId: r.dataset.hitMsg };
        nav("chats");
      });
    }, 300);
  };
}

/* ---------------- Tasks ---------------- */
const TASK_STATUSES = ["Backlog","Ready","In Progress","Waiting for Approval","Blocked","Completed","Failed","Cancelled"];
views.tasks = async (v) => {
  if (!state.companyId) { v.innerHTML = `<div class="empty"><div class="big">🏢</div>Select a company first.</div>`; return; }
  const tasks = await api(`/companies/${state.companyId}/tasks`);
  v.innerHTML = `<div class="toolbar"><button class="btn primary" id="new-task">+ New Task</button></div>
  <div class="board">${TASK_STATUSES.map(s => `<div class="board-col"><h4>${s} (${tasks.filter(t => t.status === s).length})</h4>
    ${tasks.filter(t => t.status === s).map(t => {
      const emp = state.employees.find(e => e.id === t.assignee_id);
      return `<div class="task-card" data-task="${t.id}"><b>${esc(t.title)}</b><br>
      <span class="muted">${emp ? esc(emp.avatar + " " + emp.full_name) : "unassigned"} · ${esc(t.priority)}</span></div>`; }).join("")}
  </div>`).join("")}</div>`;
  const taskModal = (t = null) => modal(t ? "Edit task" : "New task", `
    <label>Title *<input name="title" required value="${t ? esc(t.title) : ""}"></label>
    <label>Description<textarea name="description">${t ? esc(t.description) : ""}</textarea></label>
    <label>Status<select name="status">${TASK_STATUSES.map(s => `<option ${t && t.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
    <label>Priority<select name="priority">${["Low","Medium","High","Critical"].map(p => `<option ${t && t.priority === p ? "selected" : (!t && p === "Medium" ? "selected" : "")}>${p}</option>`).join("")}</select></label>
    <label>Assignee<select name="assignee_id"><option value="">— unassigned —</option>
      ${state.employees.map(e => `<option value="${e.id}" ${t && t.assignee_id === e.id ? "selected" : ""}>${esc(e.full_name)}</option>`).join("")}</select></label>`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (!body.assignee_id) body.assignee_id = null;
      if (t) await api(`/tasks/${t.id}`, { method: "PUT", body });
      else await api(`/companies/${state.companyId}/tasks`, { method: "POST", body });
      toast("Task saved", "ok"); render();
    });
  $("#new-task").onclick = () => taskModal();
  $$("[data-task]", v).forEach(el => el.onclick = () => taskModal(tasks.find(t => t.id === el.dataset.task)));
};

/* ============ Operations suite: Teams · Workflows · SOPs · Shift roster ============ */
const needCompany = (v) => {
  if (state.companyId) return false;
  v.innerHTML = `<div class="empty"><div class="big">🏢</div>Select a company first.</div>`;
  return true;
};
const opsApi = (kind) => `/companies/${state.companyId}/ops/${kind}`;
const jArr = (s) => { try { const x = JSON.parse(s || "[]"); return Array.isArray(x) ? x : []; } catch { return []; } };
const empName = (id) => { const e = state.employees.find(x => x.id === id); return e ? `${e.avatar} ${e.full_name}` : "—"; };
const empOptions = (sel) => `<option value="">— none —</option>` +
  state.employees.map(e => `<option value="${e.id}" ${sel === e.id ? "selected" : ""}>${esc(e.full_name)}${e.job_title ? " · " + esc(e.job_title) : ""}</option>`).join("");
const statusLed = (s) => ({ Active: "ok", Approved: "ok", Draft: "warn", "In Review": "warn",
  Standby: "warn", Paused: "warn", Disabled: "off", Retired: "off", Archived: "off" }[s] || "off");

/* ---------------- Teams ---------------- */
views.teams = async (v) => {
  if (needCompany(v)) return;
  const teams = await api(opsApi("teams"));
  const active = teams.filter(t => t.status === "Active").length;
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Teams</span><span class="v">${teams.length}</span></div>
    <div class="noc-kpi"><span class="k">Active</span><span class="v" style="color:#22c55e">${active}</span></div>
    <div class="noc-kpi"><span class="k">Staff assigned</span><span class="v">${new Set(teams.flatMap(t => jArr(t.member_ids))).size}</span></div>
    <span class="spacer"></span>
    <button class="btn primary" id="new-team">➕ New team</button>
  </div>
  <div class="grid cols-3">${teams.map(t => {
    const members = jArr(t.member_ids);
    return `<div class="card" data-team="${t.id}" style="cursor:pointer">
      <h3>${esc(t.icon)} ${esc(t.name)} <span class="pill"><span class="noc-led ${statusLed(t.status)}"></span>${esc(t.status)}</span></h3>
      <p class="muted" style="font-size:12.5px;min-height:32px">${esc(t.mission || "No mission statement")}</p>
      <p style="font-size:12.5px">Lead: <b>${empName(t.lead_id)}</b></p>
      <p class="muted" style="font-size:12px">👥 ${members.length} member(s): ${members.slice(0, 5).map(empName).join(", ")}${members.length > 5 ? "…" : ""}</p>
    </div>`; }).join("")
    || `<div class="empty"><div class="big">🤝</div>No teams yet — group employees into cross-project units with a lead and mission.</div>`}</div>`;
  const teamModal = (t = null) => modal(t ? "Edit team" : "New team", `
    ${wizSect("🤝", "Team identity", "A named unit of virtual employees")}
    <div class="wiz-grid">
      <label>Team name *<input name="name" required value="${t ? esc(t.name) : ""}" placeholder="e.g. Content Production"></label>
      <label>Status<select name="status">${["Active", "Standby", "Archived"].map(s => `<option ${t && t.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
    </div>
    <label>Mission<textarea name="mission" placeholder="What this team is responsible for…">${t ? esc(t.mission) : ""}</textarea></label>
    ${wizSect("🪪", "Staffing", "Lead and members")}
    <label>Team lead<select name="lead_id">${empOptions(t?.lead_id)}</select></label>
    <label>Members</label>
    <div class="perm-grid" style="grid-template-columns:1fr 1fr">
      ${state.employees.map(e => `<label class="perm-item"><input type="checkbox" name="m" value="${e.id}"
        ${t && jArr(t.member_ids).includes(e.id) ? "checked" : ""}>
        <span class="perm-text"><b>${esc(e.avatar)} ${esc(e.full_name)}</b><small>${esc(e.job_title || "")}</small></span></label>`).join("")
        || '<p class="muted">No employees yet — create them in 👥 Employees.</p>'}
    </div>
    ${t ? `<div class="actions" style="justify-content:flex-start;margin-top:10px"><button type="button" class="btn danger" id="team-del">🗑 Delete team</button></div>` : ""}`,
    async (fd) => {
      const body = { name: fd.get("name"), status: fd.get("status"), mission: fd.get("mission"),
        lead_id: fd.get("lead_id") || null, member_ids: fd.getAll("m") };
      if (t) await api(`/ops/teams/${t.id}`, { method: "PUT", body });
      else await api(opsApi("teams"), { method: "POST", body });
      toast("Team saved", "ok"); render();
    });
  $("#new-team").onclick = () => teamModal();
  $$("[data-team]", v).forEach(el => el.onclick = () => {
    teamModal(teams.find(t => t.id === el.dataset.team));
    const del = $("#team-del");
    if (del) del.onclick = async () => {
      if (!confirm("Delete this team?")) return;
      await api(`/ops/teams/${el.dataset.team}`, { method: "DELETE" });
      $("#modal-root").innerHTML = ""; toast("Team deleted", "ok"); render();
    };
  });
};

/* ---------------- Workflows ---------------- */
views.workflows = async (v) => {
  if (needCompany(v)) return;
  const [wfs, teams] = await Promise.all([api(opsApi("workflows")), api(opsApi("teams"))]);
  if (state.wfDesign !== undefined && state.wfDesign !== null)
    return wfDesigner(v, state.wfDesign === "new" ? null : wfs.find(w => w.id === state.wfDesign), teams);
  const ownerName = (st) => st.owner_kind === "team"
    ? "🤝 " + (teams.find(t => t.id === st.owner_id)?.name || "—")
    : empName(st.owner_id);
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Workflows</span><span class="v">${wfs.length}</span></div>
    <div class="noc-kpi"><span class="k">Active</span><span class="v" style="color:#22c55e">${wfs.filter(w => w.status === "Active").length}</span></div>
    <div class="noc-kpi"><span class="k">Total stages</span><span class="v">${wfs.reduce((a, w) => a + jArr(w.stages).length, 0)}</span></div>
    <span class="spacer"></span>
    <button class="btn" id="new-wf">➕ Quick create</button>
    <button class="btn primary" id="new-wf-designer">🧩 Flow-chart designer</button>
  </div>
  ${wfs.map(w => {
    const stages = jArr(w.stages);
    const hasDiagram = !!(w.diagram && w.diagram !== "{}" && jArr(JSON.parse(w.diagram || "{}").nodes || "[]"));
    return `<div class="noc-panel" style="margin-bottom:14px" data-wf="${w.id}">
      <div class="noc-head" style="cursor:pointer"><span class="noc-led ${statusLed(w.status)}"></span>
        <b>${esc(w.icon)} ${esc(w.name)}</b><span class="spacer"></span>
        <small>${esc(w.trigger).toUpperCase()} TRIGGER · ${stages.length} STAGE(S) · ${esc(w.status).toUpperCase()}</small>
        <button class="btn" data-design="${w.id}" style="padding:3px 10px;font-size:12px;margin-left:10px">🧩 Designer</button></div>
      <div class="noc-body" style="display:flex;gap:0;align-items:stretch;overflow-x:auto;padding:14px">
        ${stages.map((st, i) => `
          <div style="display:flex;align-items:center">
            <div style="min-width:170px;border:1px solid var(--border);border-radius:10px;padding:9px 12px;background:var(--panel2)">
              <div style="font-size:10px;color:var(--muted);font-family:Consolas,monospace;letter-spacing:1px">STAGE ${i + 1}${st.approval_required ? " · 🔒 APPROVAL" : ""}</div>
              <b style="font-size:13px">${esc(st.name || "—")}</b>
              <div class="muted" style="font-size:11.5px;margin-top:2px">${esc(ownerName(st))}</div>
            </div>
            ${i < stages.length - 1 ? '<span style="color:#4f8ef7;font-size:17px;padding:0 8px">➜</span>' : ""}
          </div>`).join("")
          || '<span class="muted">No stages defined yet — click to edit.</span>'}
      </div>
    </div>`; }).join("")
    || `<div class="empty"><div class="big">🔁</div>No workflows yet — open the 🧩 Flow-chart designer to draw your process (drag &amp; drop elements), or use quick create.</div>`}`;
  const stageRow = (st = {}, i = 0) => `
    <div class="wf-stage" style="display:grid;grid-template-columns:1.2fr 1fr 1.2fr auto auto;gap:8px;align-items:center;margin-top:8px">
      <input class="st-name" placeholder="Stage name *" value="${esc(st.name || "")}">
      <select class="st-kind"><option value="employee" ${st.owner_kind !== "team" ? "selected" : ""}>👤 Employee</option>
        <option value="team" ${st.owner_kind === "team" ? "selected" : ""}>🤝 Team</option></select>
      <select class="st-owner">${st.owner_kind === "team"
        ? `<option value="">— team —</option>` + teams.map(t => `<option value="${t.id}" ${st.owner_id === t.id ? "selected" : ""}>${esc(t.name)}</option>`).join("")
        : empOptions(st.owner_id)}</select>
      <label style="display:flex;align-items:center;gap:5px;margin:0;font-size:12px;white-space:nowrap">
        <input type="checkbox" class="st-appr" style="width:auto" ${st.approval_required ? "checked" : ""}>🔒 approval</label>
      <button type="button" class="btn st-del" style="padding:4px 9px">✕</button>
    </div>`;
  const wfModal = (w = null) => {
    modal(w ? "Edit workflow" : "New workflow", `
      ${wizSect("🔁", "Workflow", "A repeatable multi-stage process")}
      <div class="wiz-grid">
        <label>Name *<input name="name" required value="${w ? esc(w.name) : ""}" placeholder="e.g. Content publication"></label>
        <label>Status<select name="status">${["Active", "Draft", "Disabled"].map(s => `<option ${w && w.status === s ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label>Trigger<select name="trigger">${[["manual", "Manual"], ["schedule", "On schedule"], ["task_created", "When a task is created"]].map(([val, lb]) => `<option value="${val}" ${w && w.trigger === val ? "selected" : ""}>${lb}</option>`).join("")}</select></label>
      </div>
      <label>Description<textarea name="description" placeholder="What this process achieves…">${w ? esc(w.description) : ""}</textarea></label>
      ${wizSect("🪜", "Stages", "Executed in order — each stage is owned by a team or an employee")}
      <div id="wf-stages">${jArr(w?.stages).map(stageRow).join("")}</div>
      <button type="button" class="btn" id="wf-add" style="margin-top:8px">➕ Add stage</button>
      ${w ? `<div class="actions" style="justify-content:flex-start;margin-top:10px"><button type="button" class="btn danger" id="wf-del">🗑 Delete workflow</button></div>` : ""}`,
      async (fd) => {
        const stages = [...document.querySelectorAll("#wf-stages .wf-stage")].map(r => ({
          name: r.querySelector(".st-name").value.trim(),
          owner_kind: r.querySelector(".st-kind").value,
          owner_id: r.querySelector(".st-owner").value || null,
          approval_required: r.querySelector(".st-appr").checked,
        })).filter(s => s.name);
        const body = { name: fd.get("name"), status: fd.get("status"), trigger: fd.get("trigger"),
          description: fd.get("description"), stages };
        if (w) await api(`/ops/workflows/${w.id}`, { method: "PUT", body });
        else await api(opsApi("workflows"), { method: "POST", body });
        toast("Workflow saved", "ok"); render();
      });
    const wire = () => {
      $$("#wf-stages .st-del").forEach(b => b.onclick = () => { b.closest(".wf-stage").remove(); });
      $$("#wf-stages .st-kind").forEach(sel => sel.onchange = () => {
        const owner = sel.closest(".wf-stage").querySelector(".st-owner");
        owner.innerHTML = sel.value === "team"
          ? `<option value="">— team —</option>` + teams.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join("")
          : empOptions("");
      });
    };
    $("#wf-add").onclick = () => { $("#wf-stages").insertAdjacentHTML("beforeend", stageRow()); wire(); };
    wire();
    if (w) { const del = $("#wf-del"); if (del) del.onclick = async () => {
      if (!confirm("Delete this workflow?")) return;
      await api(`/ops/workflows/${w.id}`, { method: "DELETE" });
      $("#modal-root").innerHTML = ""; toast("Workflow deleted", "ok"); render(); }; }
  };
  $("#new-wf").onclick = () => wfModal();
  $("#new-wf-designer").onclick = () => { state.wfDesign = "new"; render(); };
  $$("[data-design]", v).forEach(b => b.onclick = (e) => { e.stopPropagation(); state.wfDesign = b.dataset.design; render(); });
  $$("[data-wf] .noc-head", v).forEach(el => el.onclick = (e) => {
    if (e.target.closest("[data-design]")) return;
    wfModal(wfs.find(w => w.id === el.closest("[data-wf]").dataset.wf));
  });
};

/* ============ Flow-chart workflow designer — drag & drop process engineering ============ */
/* Full ISO 5807 flowchart symbol set (terminator, process, decision, predefined
   process, preparation, manual input/operation, data I/O, document, multi-doc,
   database, stored data, internal storage, display, delay, card, merge,
   connector, off-page connector, approval gate). */
const WF_TYPES = {
  start:      { label: "START",        col: "#22c55e", shape: "term",     w: 132, h: 46, desc: "Entry terminator" },
  process:    { label: "PROCESS",      col: "#4f8ef7", shape: "rect",     w: 192, h: 76, desc: "Work step / task" },
  decision:   { label: "DECISION",     col: "#eab308", shape: "diamond",  w: 176, h: 96, desc: "Condition · N branches" },
  approval:   { label: "APPROVAL",     col: "#a78bfa", shape: "rect",     w: 192, h: 76, desc: "Sign-off gate" },
  subprocess: { label: "SUBPROCESS",   col: "#94a3b8", shape: "sub",      w: 192, h: 76, desc: "Predefined process" },
  prep:       { label: "PREPARATION",  col: "#10b981", shape: "hex",      w: 184, h: 66, desc: "Setup / initialize" },
  data:       { label: "DATA / I-O",   col: "#06b6d4", shape: "para",     w: 184, h: 62, desc: "Input / output" },
  maninput:   { label: "MANUAL INPUT", col: "#38bdf8", shape: "maninput", w: 176, h: 62, desc: "Keyed-in by a person" },
  manop:      { label: "MANUAL OP",    col: "#fb7185", shape: "manop",    w: 176, h: 62, desc: "Hand-performed step" },
  document:   { label: "DOCUMENT",     col: "#f97316", shape: "doc",      w: 184, h: 70, desc: "Produces a document" },
  multidoc:   { label: "MULTI-DOC",    col: "#fb923c", shape: "multidoc", w: 184, h: 72, desc: "Set of documents" },
  database:   { label: "DATABASE",     col: "#14b8a6", shape: "cyl",      w: 150, h: 76, desc: "Direct data storage" },
  stored:     { label: "STORED DATA",  col: "#818cf8", shape: "stored",   w: 170, h: 62, desc: "Generic stored data" },
  intstore:   { label: "INT STORAGE",  col: "#22d3ee", shape: "intstore", w: 170, h: 66, desc: "Internal / memory" },
  display:    { label: "DISPLAY",      col: "#e879f9", shape: "disp",     w: 172, h: 64, desc: "Show to a user" },
  delay:      { label: "DELAY",        col: "#f59e0b", shape: "delay",    w: 160, h: 60, desc: "Wait / hold state" },
  card:       { label: "CARD",         col: "#fbbf24", shape: "card",     w: 160, h: 60, desc: "Punched card / form" },
  merge:      { label: "MERGE",        col: "#f472b6", shape: "tri",      w: 150, h: 72, desc: "Combine into one flow" },
  connector:  { label: "CONNECTOR",    col: "#94a3b8", shape: "circ",     w: 60,  h: 60, desc: "On-page jump point" },
  offpage:    { label: "OFF-PAGE",     col: "#64748b", shape: "pent",     w: 130, h: 74, desc: "Continues elsewhere" },
  end:        { label: "END",          col: "#ef4444", shape: "term",     w: 132, h: 46, desc: "Exit terminator" },
};
/* One geometry renderer shared by the canvas and the palette thumbnails —
   all coordinates are centred on (0,0). */
function wfShape(shape, w, h, col, sw, fill) {
  const hw = w / 2, hh = h / 2, S = `${fill} stroke="${col}" stroke-width="${sw}"`;
  switch (shape) {
    case "term":     return `<rect x="${-hw}" y="${-hh}" width="${w}" height="${h}" rx="${hh}" ${S}/>`;
    case "diamond":  return `<polygon points="0,${-hh} ${hw},0 0,${hh} ${-hw},0" ${S}/>`;
    case "para":     return `<polygon points="${-hw + 16},${-hh} ${hw},${-hh} ${hw - 16},${hh} ${-hw},${hh}" ${S}/>`;
    case "doc":      return `<path d="M ${-hw} ${-hh} H ${hw} V ${hh - 9} Q ${hw / 2} ${hh + 9} 0 ${hh - 9} T ${-hw} ${hh - 9} Z" ${S}/>`;
    case "multidoc": return `<path d="M ${-hw + 10} ${-hh} H ${hw} V ${hh - 15} Q ${hw / 2} ${hh + 1} 5 ${hh - 15} T ${-hw + 10} ${hh - 15} Z" fill="none" stroke="${col}" stroke-width="1" transform="translate(5,-6)"/>
      <path d="M ${-hw} ${-hh + 6} H ${hw - 10} V ${hh - 9} Q ${hw / 2 - 10} ${hh + 7} -5 ${hh - 9} T ${-hw} ${hh - 9} Z" ${S}/>`;
    case "sub":      return `<rect x="${-hw}" y="${-hh}" width="${w}" height="${h}" rx="5" ${S}/>
      <line x1="${-hw + 9}" y1="${-hh}" x2="${-hw + 9}" y2="${hh}" stroke="${col}" stroke-width="1"/>
      <line x1="${hw - 9}" y1="${-hh}" x2="${hw - 9}" y2="${hh}" stroke="${col}" stroke-width="1"/>`;
    case "hex":      return `<polygon points="${-hw + 18},${-hh} ${hw - 18},${-hh} ${hw},0 ${hw - 18},${hh} ${-hw + 18},${hh} ${-hw},0" ${S}/>`;
    case "maninput": return `<polygon points="${-hw},${-hh + 16} ${hw},${-hh} ${hw},${hh} ${-hw},${hh}" ${S}/>`;
    case "manop":    return `<polygon points="${-hw},${-hh} ${hw},${-hh} ${hw - 20},${hh} ${-hw + 20},${hh}" ${S}/>`;
    case "delay":    return `<path d="M ${-hw} ${-hh} H ${hw - hh} A ${hh} ${hh} 0 0 1 ${hw - hh} ${hh} H ${-hw} Z" ${S}/>`;
    case "cyl":      return `<path d="M ${-hw} ${-hh + 10} A ${hw} 10 0 0 1 ${hw} ${-hh + 10} V ${hh - 10} A ${hw} 10 0 0 1 ${-hw} ${hh - 10} Z" ${S}/>
      <path d="M ${-hw} ${-hh + 10} A ${hw} 10 0 0 0 ${hw} ${-hh + 10}" fill="none" stroke="${col}" stroke-width="1"/>`;
    case "stored":   return `<path d="M ${-hw + 12} ${-hh} H ${hw} A 14 ${hh} 0 0 0 ${hw} ${hh} H ${-hw + 12} A 14 ${hh} 0 0 1 ${-hw + 12} ${-hh} Z" ${S}/>`;
    case "intstore": return `<rect x="${-hw}" y="${-hh}" width="${w}" height="${h}" ${S}/>
      <line x1="${-hw}" y1="${-hh + 13}" x2="${hw}" y2="${-hh + 13}" stroke="${col}" stroke-width="1"/>
      <line x1="${-hw + 13}" y1="${-hh}" x2="${-hw + 13}" y2="${hh}" stroke="${col}" stroke-width="1"/>`;
    case "disp":     return `<path d="M ${-hw + 18} ${-hh} H ${hw - 16} Q ${hw} ${-hh} ${hw} 0 Q ${hw} ${hh} ${hw - 16} ${hh} H ${-hw + 18} L ${-hw} 0 Z" ${S}/>`;
    case "card":     return `<polygon points="${-hw + 16},${-hh} ${hw},${-hh} ${hw},${hh} ${-hw},${hh} ${-hw},${-hh + 16}" ${S}/>`;
    case "tri":      return `<polygon points="${-hw},${-hh} ${hw},${-hh} 0,${hh}" ${S}/>`;
    case "circ":     return `<circle r="${hh}" ${S}/>`;
    case "pent":     return `<polygon points="${-hw},${-hh} ${hw},${-hh} ${hw},${hh * 0.25} 0,${hh} ${-hw},${hh * 0.25}" ${S}/>`;
    default:         return `<rect x="${-hw}" y="${-hh}" width="${w}" height="${h}" rx="6" ${S}/>`;
  }
}
const WF_EDGE_COLORS = ["#4f8ef7", "#22c55e", "#eab308", "#ef4444", "#a78bfa", "#94a3b8"];
const WF_DASH = { solid: "", dashed: "7 5", dotted: "2 4" };

function wfGeneratePrompt(name, description, nodes, edges) {
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const outs = (id) => edges.filter(e => e.from === id);
  const start = nodes.find(n => n.type === "start") || nodes[0];
  const order = [], seen = new Set();
  const qq = start ? [start.id] : [];
  while (qq.length) {
    const id = qq.shift();
    if (seen.has(id) || !byId[id]) continue;
    seen.add(id); order.push(id);
    outs(id).forEach(e => qq.push(e.to));
  }
  nodes.forEach(n => { if (!seen.has(n.id)) { order.push(n.id); seen.add(n.id); } });
  const num = Object.fromEntries(order.map((id, i) => [id, i + 1]));
  const who = (n) => {
    const parts = [];
    if (n.owner) parts.push(`in charge: ${n.owner}`);
    if (n.dept) parts.push(`department: ${n.dept}`);
    return parts.length ? ` — ${parts.join(" · ")}` : "";
  };
  const det = (n) => n.details ? `\n    Details: ${n.details.replace(/\n/g, "\n    ")}` : "";
  const lines = order.map(id => {
    const n = byId[id];
    const o = outs(id);
    const goto = (e) => `step ${num[e.to] ?? "?"} (${byId[e.to]?.label || "?"})`;
    if (n.type === "start") return `${num[id]}. [START] ${n.label || "Begin"}${o[0] ? ` → proceed to ${goto(o[0])}` : ""}${det(n)}`;
    if (n.type === "end") return `${num[id]}. [END] ${n.label || "Process complete"}${det(n)}`;
    if (n.type === "decision") {
      const conds = (n.conditions || []).length ? n.conditions : o.map(e => ({ label: e.label || "yes", reason: "" }));
      const branchLines = conds.map(c => {
        const e = o.find(x => (x.label || "").toLowerCase() === (c.label || "").toLowerCase());
        return `\n    • IF "${c.label}"${c.reason ? ` (${c.reason})` : ""} → ${e ? goto(e) : "branch not connected yet"}`;
      }).join("");
      return `${num[id]}. [DECISION] ${n.label || "?"}${who(n)} — evaluate the condition and branch:${branchLines}${det(n)}`;
    }
    const kindMap = { approval: "APPROVAL GATE", data: "DATA / INPUT-OUTPUT", document: "DOCUMENT",
      subprocess: "SUBPROCESS", prep: "PREPARATION", maninput: "MANUAL INPUT", manop: "MANUAL OPERATION",
      multidoc: "DOCUMENTS", database: "DATABASE OPERATION", stored: "STORED DATA", intstore: "INTERNAL STORAGE",
      display: "DISPLAY TO USER", delay: "DELAY / WAIT", card: "FORM / CARD", merge: "MERGE FLOWS",
      connector: "CONNECTOR", offpage: "OFF-PAGE REFERENCE" };
    const kind = kindMap[n.type] || "PROCESS";
    const next = o[0] ? ` When complete, continue to ${goto(o[0])}.` : "";
    const appr = n.type === "approval" ? " Work MUST pause here until explicit sign-off is given." : "";
    return `${num[id]}. [${kind}] ${n.label || "?"}${who(n)}.${appr}${det(n)}${next}`;
  });
  return `WORKFLOW REFERENCE — ${name || "Untitled workflow"}
OBJECTIVE: ${description || "(no description)"}
ELEMENTS: ${nodes.length} node(s), ${edges.length} connection(s)

PROCEDURE (follow the steps and branches exactly):
${lines.join("\n")}

EXECUTION RULES:
- Execute steps strictly in the order and branches defined above.
- Every step lists its in-charge person/department — that owner performs the work and is accountable for it.
- At every APPROVAL GATE, stop and request sign-off before continuing.
- At every DECISION, evaluate each condition in the stated order and follow ONLY the matching branch.
- Report which step you are on while working, and confirm completion of the final END step.`;
}

async function wfDesigner(v, wf, teams) {
  let d = { nodes: [], edges: [] };
  try { const p = JSON.parse(wf?.diagram || "{}"); if (Array.isArray(p.nodes)) d = { nodes: p.nodes, edges: p.edges || [] }; } catch { /* fresh */ }
  if (!d.nodes.length && wf && jArr(wf.stages).length) {   // seed diagram from legacy stages
    const st = jArr(wf.stages);
    d.nodes.push({ id: "n_s", type: "start", label: "Start", x: 120, y: 90 });
    st.forEach((s, i) => d.nodes.push({ id: "n" + i, type: s.approval_required ? "approval" : "process",
      label: s.name || "Stage " + (i + 1), owner: "", x: 120 + (i + 1) * 220, y: 90 }));
    d.nodes.push({ id: "n_e", type: "end", label: "Done", x: 120 + (st.length + 1) * 220, y: 90 });
    const ids = d.nodes.map(n => n.id);
    for (let i = 0; i < ids.length - 1; i++) d.edges.push({ from: ids[i], to: ids[i + 1], label: "" });
  }
  let meta = { name: wf?.name || "", description: wf?.description || "",
               trigger: wf?.trigger || "manual", status: wf?.status || "Active" };
  let sel = null, selEdge = null, nid = Date.now() % 100000;
  const W = 2400, H = 1400;
  let vb = [0, 0, 1200, 700];

  const palThumb = (k, t) => {
    const pad = 8;
    return `<svg width="58" height="32" viewBox="${-t.w / 2 - pad} ${-t.h / 2 - pad} ${t.w + pad * 2} ${t.h + pad * 2}" preserveAspectRatio="xMidYMid meet" style="flex:none">${wfShape(t.shape, t.w, t.h, t.col, Math.max(2, t.w / 34), 'fill="rgba(148,163,184,.06)"')}</svg>`;
  };
  v.innerHTML = `
  <div class="noc-topbar">
    <button class="btn" id="wfd-back">← Workflows</button>
    <div class="noc-kpi"><span class="k">Designer</span><span class="v">${wf ? "EDIT" : "NEW"}</span></div>
    <input id="wfd-name" placeholder="Workflow name *" value="${esc(meta.name)}" style="width:240px;font-weight:700">
    <select id="wfd-status">${["Active", "Draft", "Disabled"].map(s => `<option ${meta.status === s ? "selected" : ""}>${s}</option>`).join("")}</select>
    <div class="noc-kpi"><span class="k">Nodes</span><span class="v" id="wfd-nn">${d.nodes.length}</span></div>
    <div class="noc-kpi"><span class="k">Links</span><span class="v" id="wfd-ne">${d.edges.length}</span></div>
    <span class="spacer"></span>
    <button class="btn" id="wfd-prompt">📝 Generate prompt</button>
    <button class="btn primary" id="wfd-save">💾 Save workflow</button>
  </div>
  <div style="display:grid;grid-template-columns:200px 1fr 260px;gap:12px;height:calc(100vh - 190px);min-height:480px">
    <div class="noc-panel" style="overflow:auto">
      <div class="noc-head"><span class="noc-lbl">SHAPE LIBRARY</span><span class="spacer"></span><small>ISO 5807</small></div>
      <div class="noc-body" style="display:flex;flex-direction:column;gap:4px;padding:8px">
        ${Object.entries(WF_TYPES).map(([k, t]) => `
          <div class="wfd-pal" draggable="true" data-type="${k}" title="Drag onto the canvas"
            style="display:flex;align-items:center;gap:10px;border:1px solid transparent;border-radius:6px;padding:5px 8px;cursor:grab;user-select:none"
            onmouseover="this.style.borderColor='var(--border)';this.style.background='var(--panel2)'"
            onmouseout="this.style.borderColor='transparent';this.style.background='transparent'">
            ${palThumb(k, t)}
            <div style="min-width:0">
              <div style="font-size:10px;font-family:Consolas,monospace;letter-spacing:1.2px;color:${t.col}">${t.label}</div>
              <div class="muted" style="font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.desc}</div>
            </div>
          </div>`).join("")}
        <div style="border-top:1px solid var(--border);margin-top:8px;padding-top:8px">
          <div class="noc-lbl" style="margin:0 0 6px">CONTROLS</div>
          <table style="width:100%;font-size:10px;font-family:Consolas,monospace;color:var(--muted);border-collapse:collapse">
            ${[["DRAG SHAPE", "place element"], ["DRAG BODY", "move node"], ["DRAG ● PORT", "draw connector"], ["CLICK", "properties"], ["SCROLL", "zoom"], ["DRAG CANVAS", "pan"], ["DEL", "remove selection"]].map(([a, b]) =>
              `<tr><td style="padding:2.5px 0;color:#94a3b8;white-space:nowrap">${a}</td><td style="padding:2.5px 0 2.5px 8px">${b}</td></tr>`).join("")}
          </table>
        </div>
      </div>
    </div>
    <div class="noc-panel" style="overflow:hidden;display:flex;flex-direction:column">
      <div class="noc-head"><span class="noc-lbl">PROCESS CANVAS</span>
        <span class="spacer"></span>
        <button class="btn" id="wfd-zoom-out" title="Zoom out" style="padding:2px 10px">−</button>
        <span id="wfd-zoom" style="font-size:10.5px;font-family:Consolas,monospace;color:var(--muted);min-width:44px;text-align:center">100%</span>
        <button class="btn" id="wfd-zoom-in" title="Zoom in" style="padding:2px 10px">+</button>
        <button class="btn" id="wfd-fit" title="Fit diagram" style="padding:2px 10px">⛶ Fit</button>
        <small style="margin-left:10px">GRID 20px · SNAP ON</small></div>
      <div class="netmap-wrap" id="wfd-wrap" style="flex:1;padding:0;position:relative">
        <svg id="wfd-svg" style="width:100%;height:100%"></svg>
        <div id="wfd-empty" style="position:absolute;inset:0;display:${d.nodes.length ? "none" : "flex"};align-items:center;justify-content:center;pointer-events:none">
          <div style="text-align:center;color:var(--muted)">
            <div style="font-size:12px;font-family:Consolas,monospace;letter-spacing:2px;margin-bottom:8px">CANVAS EMPTY</div>
            <div style="font-size:12.5px">Drag a <b style="color:#22c55e">START</b> terminator from the shape library to begin,<br>then add process steps and connect them with the ● ports.</div>
          </div>
        </div>
      </div>
    </div>
    <div class="noc-panel" style="overflow:auto">
      <div class="noc-head"><span class="noc-lbl">PROPERTIES</span><span class="spacer"></span><small id="wfd-selinfo">NO SELECTION</small></div>
      <div class="noc-body" id="wfd-props"><p class="muted" style="font-size:12px">Select a node or connection.</p></div>
    </div>
  </div>`;

  const svg = $("#wfd-svg"), wrap = $("#wfd-wrap");
  const zoomLbl = $("#wfd-zoom");
  const setVB = () => {
    svg.setAttribute("viewBox", vb.join(" "));
    if (zoomLbl) zoomLbl.textContent = Math.round(1200 / vb[2] * 100) + "%";
  };
  setVB();
  const SNAP = 20;
  const snap = (x) => Math.round(x / SNAP) * SNAP;
  const zoomBy = (f) => {
    const ncx = vb[0] + vb[2] / 2, ncy = vb[1] + vb[3] / 2;
    const nw = Math.min(Math.max(vb[2] * f, 300), W * 1.5);
    const nh = vb[3] * (nw / vb[2]);
    vb = [ncx - nw / 2, ncy - nh / 2, nw, nh]; setVB();
  };
  $("#wfd-zoom-in").onclick = () => zoomBy(1 / 1.25);
  $("#wfd-zoom-out").onclick = () => zoomBy(1.25);
  $("#wfd-fit").onclick = () => {
    if (!d.nodes.length) { vb = [0, 0, 1200, 700]; setVB(); return; }
    const xs = d.nodes.map(n => n.x), ys = d.nodes.map(n => n.y);
    const pad = 160;
    const x0 = Math.min(...xs) - pad, y0 = Math.min(...ys) - pad;
    const w = Math.max(...xs) - Math.min(...xs) + pad * 2, h = Math.max(...ys) - Math.min(...ys) + pad * 2;
    const ar = 1200 / 700;
    vb = w / h > ar ? [x0, y0 - (w / ar - h) / 2, w, w / ar] : [x0 - (h * ar - w) / 2, y0, h * ar, h];
    setVB();
  };
  const toWorld = (cx, cy) => {
    const r = svg.getBoundingClientRect();
    return [vb[0] + (cx - r.left) / r.width * vb[2], vb[1] + (cy - r.top) / r.height * vb[3]];
  };
  const byId = (id) => d.nodes.find(n => n.id === id);

  const nodeSvg = (n) => {
    const t = WF_TYPES[n.type] || WF_TYPES.process;
    const hw = t.w / 2, hh = t.h / 2, seld = sel === n.id;
    const sw = seld ? 2.6 : 1.5, fill = 'fill="var(--panel2,#141b2d)"';
    const shape = wfShape(t.shape, t.w, t.h, t.col, sw, fill);
    const isTerm = t.shape === "term" || t.shape === "circ" || t.h < 56;
    const info = [];
    if (n.owner) info.push("👤 " + n.owner.slice(0, 20));
    if (n.dept) info.push("🏬 " + n.dept.slice(0, 16));
    const nConds = n.type === "decision" ? (n.conditions || []).length : 0;
    return `<g class="wfd-node" data-nid="${n.id}" transform="translate(${n.x},${n.y})" style="cursor:move">
      ${seld ? `<rect x="${-hw - 6}" y="${-hh - 6}" width="${t.w + 12}" height="${t.h + 12}" rx="9" fill="none" stroke="${t.col}" stroke-width="1" stroke-dasharray="4 4" opacity=".6"/>` : ""}
      ${shape}
      ${n.type === "approval" ? `<text x="${-hw + 10}" y="${-hh + 17}" font-size="11">🔒</text>` : ""}
      <text text-anchor="middle" y="${isTerm ? 4 : (info.length ? -8 : 0)}" font-size="12" font-weight="700" fill="var(--text,#e2e8f0)">${esc((n.label || t.label).slice(0, 24))}</text>
      ${!isTerm && info.length ? `<text text-anchor="middle" y="9" font-size="9.5" fill="#94a3b8" font-family="Consolas,monospace">${esc(info.join("  "))}</text>` : ""}
      ${!isTerm && n.details ? `<text text-anchor="middle" y="${hh - 8}" font-size="8.5" fill="#64748b" font-family="Consolas,monospace">▤ ${esc(n.details.split("\n")[0].slice(0, 28))}…</text>` : ""}
      ${nConds ? `<g transform="translate(${hw - 4},${-hh + 4})"><circle r="9" fill="${t.col}"/><text text-anchor="middle" y="3.5" font-size="10" font-weight="800" fill="#10131c">${nConds}</text></g>` : ""}
      <text text-anchor="middle" y="${-hh - 7}" font-size="8" fill="${t.col}" font-family="Consolas,monospace" letter-spacing="1.5">${t.label}</text>
      <circle class="wfd-port" data-port="${n.id}" cx="${hw}" cy="0" r="6" fill="${t.col}" stroke="var(--panel2)" stroke-width="2" style="cursor:crosshair"/>
      <circle class="wfd-port" data-port="${n.id}" cx="0" cy="${hh}" r="6" fill="${t.col}" stroke="var(--panel2)" stroke-width="2" style="cursor:crosshair"/>
    </g>`;
  };
  const anchor = (n, other) => {
    const t = WF_TYPES[n.type] || WF_TYPES.process;
    const dx = other.x - n.x, dy = other.y - n.y;
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? [n.x + t.w / 2, n.y, "h"] : [n.x - t.w / 2, n.y, "h"];
    return dy >= 0 ? [n.x, n.y + t.h / 2, "v"] : [n.x, n.y - t.h / 2, "v"];
  };
  const edgePath = (e) => {
    const a = byId(e.from), b = byId(e.to);
    if (!a || !b) return "";
    const [x1, y1, o1] = anchor(a, b), [x2, y2] = anchor(b, a);
    const st = e.style || "ortho";
    if (st === "straight") return `M ${x1} ${y1} L ${x2} ${y2}`;
    if (st === "curve") {
      if (o1 === "h") { const mx = (x1 + x2) / 2; return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`; }
      const my = (y1 + y2) / 2; return `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`;
    }
    if (o1 === "h") { const mx = (x1 + x2) / 2; return `M ${x1} ${y1} L ${mx} ${y1} L ${mx} ${y2} L ${x2} ${y2}`; }
    const my = (y1 + y2) / 2; return `M ${x1} ${y1} L ${x1} ${my} L ${x2} ${my} L ${x2} ${y2}`;
  };
  const draw = () => {
    svg.innerHTML = `
      <defs>${WF_EDGE_COLORS.map((c, i) => `
        <marker id="wfd-arr${i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="${c}"/></marker>`).join("")}</defs>
      ${d.edges.map((e, i) => {
        const a = byId(e.from), b = byId(e.to);
        if (!a || !b) return "";
        const col = e.color || "#4f8ef7";
        const ci = Math.max(0, WF_EDGE_COLORS.indexOf(col));
        const dash = WF_DASH[e.dash || "solid"];
        return `<g class="wfd-edge" data-eid="${i}" style="cursor:pointer">
          <path d="${edgePath(e)}" fill="none" stroke="transparent" stroke-width="14"/>
          <path d="${edgePath(e)}" fill="none" stroke="${selEdge === i ? "#fff" : col}" stroke-width="${selEdge === i ? 2.6 : 1.7}"${dash ? ` stroke-dasharray="${dash}"` : ""} marker-end="url(#wfd-arr${ci})"/>
          ${e.label ? `<g><rect x="${(a.x + b.x) / 2 - e.label.length * 3.4 - 5}" y="${(a.y + b.y) / 2 - 19}" width="${e.label.length * 6.8 + 10}" height="15" rx="7" fill="var(--panel2,#141b2d)" stroke="${col}" stroke-width=".8"/>
            <text x="${(a.x + b.x) / 2}" y="${(a.y + b.y) / 2 - 8}" text-anchor="middle" font-size="10" fill="${col}" font-family="Consolas,monospace">${esc(e.label)}</text></g>` : ""}
        </g>`; }).join("")}
      ${d.nodes.map(nodeSvg).join("")}
      <g id="wfd-temp"></g>`;
    $("#wfd-nn").textContent = d.nodes.length;
    $("#wfd-ne").textContent = d.edges.length;
    const emp = $("#wfd-empty");
    if (emp) emp.style.display = d.nodes.length ? "none" : "flex";
    const si = $("#wfd-selinfo");
    if (si) si.textContent = selEdge != null ? "CONNECTION" : sel ? (WF_TYPES[byId(sel)?.type]?.label || "NODE") + " · " + String(sel).toUpperCase() : "NO SELECTION";
  };
  const props = () => {
    const box = $("#wfd-props");
    if (selEdge != null) {
      const e = d.edges[selEdge];
      const src = byId(e.from);
      const condOpts = src?.type === "decision" && (src.conditions || []).length
        ? `<div class="wfp-field"><span class="wfp-lbl">Branch condition</span>
           <select id="wfp-elabel-sel"><option value="">— custom label —</option>
            ${src.conditions.map(c => `<option ${e.label === c.label ? "selected" : ""}>${esc(c.label)}</option>`).join("")}
          </select></div>` : "";
      box.innerHTML = `
        <div class="wfp-sect"><span class="t" style="color:#4f8ef7">■ CONNECTION</span></div>
        <p class="muted" style="font-size:11.5px;margin:8px 0 0;font-family:Consolas,monospace">${esc(src?.label || "?")} → ${esc(byId(e.to)?.label || "?")}</p>
        ${condOpts}
        <div class="wfp-field"><span class="wfp-lbl">Label${condOpts ? " (custom)" : " — e.g. yes / no / on error"}</span>
          <input id="wfp-elabel" value="${esc(e.label || "")}"></div>
        <div class="wfp-sect"><span class="t" style="color:#94a3b8">LINE STYLE</span></div>
        <div class="wfp-field"><span class="wfp-lbl">Routing</span>
          <select id="wfp-estyle">
          ${[["ortho", "⌗ Orthogonal (elbow)"], ["curve", "∿ Curved"], ["straight", "╱ Straight"]].map(([val, lb]) => `<option value="${val}" ${(e.style || "ortho") === val ? "selected" : ""}>${lb}</option>`).join("")}
        </select></div>
        <div class="wfp-field"><span class="wfp-lbl">Stroke</span>
          <select id="wfp-edash">
          ${[["solid", "─── Solid"], ["dashed", "┈┈┈ Dashed"], ["dotted", "··· Dotted"]].map(([val, lb]) => `<option value="${val}" ${(e.dash || "solid") === val ? "selected" : ""}>${lb}</option>`).join("")}
        </select></div>
        <div class="wfp-field"><span class="wfp-lbl">Color</span>
          <div style="display:flex;gap:7px">
          ${WF_EDGE_COLORS.map(c => `<span class="wfp-col" data-c="${c}" style="width:24px;height:24px;border-radius:6px;background:${c};cursor:pointer;border:2px solid ${(e.color || "#4f8ef7") === c ? "#fff" : "transparent"}"></span>`).join("")}
        </div></div>
        <div class="wfp-sect"></div>
        <button class="btn danger" id="wfp-edel" style="width:100%">🗑 Delete connection</button>`;
      const sel2 = $("#wfp-elabel-sel");
      if (sel2) sel2.onchange = () => { if (sel2.value) { e.label = sel2.value; $("#wfp-elabel").value = sel2.value; draw(); } };
      $("#wfp-elabel").oninput = (ev) => { e.label = ev.target.value; draw(); };
      $("#wfp-estyle").onchange = (ev) => { e.style = ev.target.value; draw(); };
      $("#wfp-edash").onchange = (ev) => { e.dash = ev.target.value; draw(); };
      $$(".wfp-col", box).forEach(s => s.onclick = () => { e.color = s.dataset.c; draw(); props(); });
      $("#wfp-edel").onclick = () => { d.edges.splice(selEdge, 1); selEdge = null; draw(); props(); };
      return;
    }
    const n = byId(sel);
    if (!n) { box.innerHTML = `<p class="muted" style="font-size:12px">Select a node or connection.</p>`; return; }
    const t = WF_TYPES[n.type];
    const isTerm = ["start", "end"].includes(n.type);
    const condRow = (c = { label: "", reason: "" }) => `
      <div class="wfp-cond" style="border:1px solid var(--border);border-left:3px solid ${t.col};border-radius:7px;padding:8px 10px;margin-top:8px;background:var(--panel2)">
        <div style="display:flex;gap:6px;align-items:center">
          <input class="wfp-clabel" placeholder="Condition — e.g. approved" value="${esc(c.label)}" style="flex:1;font-size:12px">
          <button type="button" class="btn wfp-cdel" style="padding:2px 8px" title="Remove condition">✕</button>
        </div>
        <input class="wfp-creason" placeholder="Why / when does this branch apply?" value="${esc(c.reason || "")}" style="width:100%;margin-top:6px;font-size:11.5px">
      </div>`;
    box.innerHTML = `
      <div class="wfp-sect"><span class="t" style="color:${t.col}">■ ${t.label} NODE</span><span class="s">ID ${esc(n.id).toUpperCase()}</span></div>
      <div class="wfp-field"><span class="wfp-lbl">Label / title</span>
        <input id="wfp-label" value="${esc(n.label || "")}" placeholder="${isTerm ? (n.type === "start" ? "e.g. Request received" : "e.g. Process complete") : "e.g. Draft the article"}"></div>
      ${isTerm ? "" : `
      <div class="wfp-field"><span class="wfp-lbl">Work details</span>
        <textarea id="wfp-details" placeholder="Describe exactly what is done in this step — inputs, actions, outputs, quality criteria…" style="min-height:88px">${esc(n.details || "")}</textarea></div>
      <div class="wfp-sect"><span class="t" style="color:#94a3b8">RESPONSIBILITY</span></div>
      <div class="wfp-field"><span class="wfp-lbl">In charge — person / team</span>
        <select id="wfp-owner"><option value="">— unassigned —</option>
          ${state.employees.map(e => `<option ${n.owner === e.full_name ? "selected" : ""}>${esc(e.full_name)}</option>`).join("")}
          ${teams.map(tm => `<option ${n.owner === "Team " + tm.name ? "selected" : ""}>Team ${esc(tm.name)}</option>`).join("")}
        </select></div>
      <div class="wfp-field"><span class="wfp-lbl">In charge — department</span>
        <input id="wfp-dept" value="${esc(n.dept || "")}" placeholder="e.g. Marketing"></div>`}
      ${n.type === "decision" ? `
      <div class="wfp-sect"><span class="t" style="color:${t.col}">CONDITIONS</span><span class="s">${(n.conditions || []).length} BRANCH(ES)</span></div>
      <p class="muted" style="font-size:10.5px;margin:6px 0 0;line-height:1.55">Each condition is one outgoing branch. Drag from the node's ● port to a target box — the next unused condition labels the new line automatically.</p>
      <div id="wfp-conds">${(n.conditions || []).map(condRow).join("")}</div>
      <button type="button" class="btn" id="wfp-cadd" style="margin-top:10px;width:100%">➕ Add condition</button>` : ""}
      <div class="wfp-sect"></div>
      <button class="btn danger" id="wfp-del" style="width:100%">🗑 Delete node</button>`;
    $("#wfp-label").oninput = (ev) => { n.label = ev.target.value; draw(); };
    const det = $("#wfp-details"); if (det) det.oninput = (ev) => { n.details = ev.target.value; draw(); };
    const ow = $("#wfp-owner"); if (ow) ow.onchange = () => { n.owner = ow.value; draw(); };
    const dp = $("#wfp-dept"); if (dp) dp.oninput = (ev) => { n.dept = ev.target.value; draw(); };
    const syncConds = () => {
      n.conditions = $$("#wfp-conds .wfp-cond").map(r => ({
        label: r.querySelector(".wfp-clabel").value.trim(),
        reason: r.querySelector(".wfp-creason").value.trim(),
      })).filter(c => c.label);
      draw();
    };
    const wireConds = () => {
      $$("#wfp-conds input").forEach(inp => inp.oninput = syncConds);
      $$("#wfp-conds .wfp-cdel").forEach(b => b.onclick = () => { b.closest(".wfp-cond").remove(); syncConds(); });
    };
    wireConds();
    const cadd = $("#wfp-cadd");
    if (cadd) cadd.onclick = () => {
      $("#wfp-conds").insertAdjacentHTML("beforeend", condRow({ label: "", reason: "" }));
      wireConds();
      $("#wfp-conds .wfp-cond:last-child .wfp-clabel").focus();
    };
    $("#wfp-del").onclick = () => {
      d.edges = d.edges.filter(e => e.from !== n.id && e.to !== n.id);
      d.nodes = d.nodes.filter(x => x.id !== n.id);
      sel = null; draw(); props();
    };
  };
  draw(); props();

  /* palette drag & drop */
  $$(".wfd-pal", v).forEach(p => p.ondragstart = (e) => e.dataTransfer.setData("text/wfd", p.dataset.type));
  wrap.ondragover = (e) => e.preventDefault();
  wrap.ondrop = (e) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("text/wfd");
    if (!WF_TYPES[type]) return;
    const [x, y] = toWorld(e.clientX, e.clientY);
    const n = { id: "n" + (nid++), type, label: "", details: "", owner: "", dept: "",
      conditions: type === "decision" ? [{ label: "yes", reason: "" }, { label: "no", reason: "" }] : undefined,
      x: snap(x), y: snap(y) };
    d.nodes.push(n); sel = n.id; selEdge = null; draw(); props();
  };

  /* canvas interactions: move node, connect from port, pan, zoom, select */
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    const port = e.target.closest(".wfd-port");
    const node = e.target.closest(".wfd-node");
    const edge = e.target.closest(".wfd-edge");
    if (port) drag = { kind: "connect", from: port.dataset.port };
    else if (node) {
      const n = byId(node.dataset.nid);
      const [wx, wy] = toWorld(e.clientX, e.clientY);
      drag = { kind: "node", n, dx: wx - n.x, dy: wy - n.y, moved: false };
      sel = n.id; selEdge = null; draw(); props();
    } else if (edge) {
      selEdge = Number(edge.dataset.eid); sel = null; draw(); props();
    } else {
      drag = { kind: "pan", cx0: e.clientX, cy0: e.clientY, vb0: [...vb] };
      sel = null; selEdge = null; draw(); props();
    }
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (drag.kind === "node") {
      const [wx, wy] = toWorld(e.clientX, e.clientY);
      drag.n.x = snap(wx - drag.dx); drag.n.y = snap(wy - drag.dy);
      drag.moved = true; draw();
    } else if (drag.kind === "pan") {
      const r = svg.getBoundingClientRect();
      vb[0] = drag.vb0[0] - (e.clientX - drag.cx0) / r.width * drag.vb0[2];
      vb[1] = drag.vb0[1] - (e.clientY - drag.cy0) / r.height * drag.vb0[3];
      setVB();
    } else if (drag.kind === "connect") {
      const a = byId(drag.from);
      const [wx, wy] = toWorld(e.clientX, e.clientY);
      const ta = WF_TYPES[a.type];
      $("#wfd-temp").innerHTML = `<path d="M ${a.x + ta.w / 2} ${a.y} L ${wx} ${wy}" stroke="#eab308" stroke-width="1.6" stroke-dasharray="5 4" fill="none"/>`;
    }
  });
  svg.addEventListener("pointerup", (e) => {
    if (drag?.kind === "connect") {
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest(".wfd-node");
      const to = el?.dataset.nid;
      if (to && to !== drag.from && !d.edges.some(x => x.from === drag.from && x.to === to)) {
        const src = byId(drag.from);
        let label = "";
        if (src?.type === "decision") {
          const used = d.edges.filter(x => x.from === drag.from).map(x => (x.label || "").toLowerCase());
          const conds = (src.conditions || []).map(c => c.label).filter(Boolean);
          label = conds.find(c => !used.includes(c.toLowerCase()))
               || (used.includes("yes") ? (used.includes("no") ? "else" : "no") : "yes");
        }
        d.edges.push({ from: drag.from, to, label, style: "ortho", dash: "solid", color: "#4f8ef7" });
        selEdge = d.edges.length - 1; sel = null; props();
      }
      $("#wfd-temp").innerHTML = ""; draw();
    }
    drag = null;
  });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [mx, my] = toWorld(e.clientX, e.clientY);
    const nw = Math.min(Math.max(vb[2] * (e.deltaY > 0 ? 1.15 : 1 / 1.15), 300), W * 1.5);
    const s = nw / vb[2];
    vb = [mx - (mx - vb[0]) * s, my - (my - vb[1]) * s, nw, vb[3] * s];
    setVB();
  }, { passive: false });
  document.onkeydown = (e) => {
    if (e.key !== "Delete" || $("#modal-root").innerHTML) return;
    if (selEdge != null) { d.edges.splice(selEdge, 1); selEdge = null; draw(); props(); }
    else if (sel) { d.edges = d.edges.filter(x => x.from !== sel && x.to !== sel);
      d.nodes = d.nodes.filter(x => x.id !== sel); sel = null; draw(); props(); }
  };

  /* toolbar */
  $("#wfd-back").onclick = () => { state.wfDesign = null; document.onkeydown = null; render(); };
  const derivedStages = () => {                        // keep pipeline view in sync
    const start = d.nodes.find(n => n.type === "start");
    const seq = []; const seen = new Set(); let cur = start;
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      if (["process", "approval", "decision", "data", "document", "subprocess"].includes(cur.type))
        seq.push({ name: cur.label || WF_TYPES[cur.type].label, owner_kind: "employee",
                   owner_id: state.employees.find(e => e.full_name === cur.owner)?.id || null,
                   approval_required: cur.type === "approval" });
      cur = byId((d.edges.find(e => e.from === cur.id) || {}).to);
    }
    return seq;
  };
  $("#wfd-save").onclick = async () => {
    meta.name = $("#wfd-name").value.trim();
    meta.status = $("#wfd-status").value;
    if (!meta.name) { toast("Give the workflow a name first", "err"); return; }
    if (!d.nodes.length) { toast("The canvas is empty — drag elements from the palette", "err"); return; }
    const body = { name: meta.name, status: meta.status, trigger: meta.trigger,
      description: meta.description, stages: derivedStages(), diagram: d };
    if (wf) await api(`/ops/workflows/${wf.id}`, { method: "PUT", body });
    else { const r = await api(opsApi("workflows"), { method: "POST", body }); state.wfDesign = r.id; wf = r; }
    toast("Workflow saved", "ok");
  };
  $("#wfd-prompt").onclick = () => {
    const name = $("#wfd-name").value.trim() || meta.name;
    const text = wfGeneratePrompt(name, meta.description, d.nodes, d.edges);
    modal("Generated workflow prompt", `
      <p class="muted" style="font-size:12px;margin-top:0">Engineering-grade procedure derived from your flow chart —
      copy it, or send it straight into a chat as the working brief for your virtual employees.</p>
      <textarea id="wfp-text" style="min-height:320px;font-family:Consolas,monospace;font-size:12px">${esc(text)}</textarea>
      <div class="actions" style="justify-content:flex-start;margin-top:10px">
        <button type="button" class="btn" id="wfp-copy">⧉ Copy to clipboard</button>
        <button type="button" class="btn primary" id="wfp-chat">💬 Use in chat</button>
      </div>`, async () => {}, "Close");
    $("#wfp-copy").onclick = async () => {
      const ok = await copyText($("#wfp-text").value);
      toast(ok ? "Prompt copied" : "Copy failed", ok ? "ok" : "err");
    };
    $("#wfp-chat").onclick = () => {
      localStorage.setItem("ncChatPrefill", $("#wfp-text").value);
      $("#modal-root").innerHTML = "";
      state.wfDesign = null; document.onkeydown = null;
      nav("chats");
      toast("Prompt loaded into the chat box — pick a conversation and send", "ok");
    };
  };
}

/* ---------------- SOPs (controlled documents) ---------------- */
views.sops = async (v) => {
  if (needCompany(v)) return;
  const sops = await api(opsApi("sops"));
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Documents</span><span class="v">${sops.length}</span></div>
    <div class="noc-kpi"><span class="k">Approved</span><span class="v" style="color:#22c55e">${sops.filter(s => s.status === "Approved").length}</span></div>
    <div class="noc-kpi"><span class="k">In review</span><span class="v" style="color:#eab308">${sops.filter(s => s.status === "In Review").length}</span></div>
    <div class="noc-kpi"><span class="k">Draft</span><span class="v">${sops.filter(s => s.status === "Draft").length}</span></div>
    <span class="spacer"></span>
    <button class="btn primary" id="new-sop">➕ New SOP</button>
  </div>
  ${sops.length ? `<div class="noc-panel">
    <div class="noc-head"><b>📘 Standard Operating Procedures</b><span class="spacer"></span><small>CONTROLLED DOCUMENTS · AUTO-VERSIONED ON CONTENT CHANGE</small></div>
    <table class="noc-table"><thead><tr>
      <th>Code</th><th>Title</th><th>Category</th><th>Rev</th><th>Status</th><th>Owner</th><th>Next review</th><th>Updated</th>
    </tr></thead><tbody>
    ${sops.map(s => `<tr data-sop="${s.id}" style="cursor:pointer">
      <td class="num"><b>${esc(s.code || "—")}</b></td>
      <td>${esc(s.title)}</td>
      <td>${esc(s.category)}</td>
      <td class="num">v${s.version || 1}</td>
      <td><span class="noc-led ${statusLed(s.status)}"></span>${esc(s.status)}</td>
      <td>${empName(s.owner_id)}</td>
      <td class="num">${esc(s.review_date || "—")}</td>
      <td class="num muted">${s.updated_at ? new Date(s.updated_at + "Z").toLocaleDateString() : "—"}</td>
    </tr>`).join("")}</tbody></table></div>`
    : `<div class="empty"><div class="big">📘</div>No SOPs yet — document your standard procedures so every AI employee follows the same playbook.</div>`}`;
  const sopModal = (s = null) => modal(s ? `${s.code} — rev v${s.version}` : "New SOP", `
    ${wizSect("📘", "Document control", "Code is assigned automatically; revision increments when content changes")}
    <div class="wiz-grid">
      <label>Title *<input name="title" required value="${s ? esc(s.title) : ""}" placeholder="e.g. Customer complaint handling"></label>
      <label>Category<input name="category" value="${s ? esc(s.category) : "General"}" placeholder="General / Quality / Safety / IT…"></label>
      <label>Status<select name="status">${["Draft", "In Review", "Approved", "Retired"].map(x => `<option ${s && s.status === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label>Owner<select name="owner_id">${empOptions(s?.owner_id)}</select></label>
      <label>Next review date<input name="review_date" type="date" value="${s ? esc(s.review_date) : ""}"></label>
    </div>
    ${wizSect("🎯", "Purpose & scope", "Why this procedure exists and where it applies")}
    <label>Purpose<textarea name="purpose">${s ? esc(s.purpose) : ""}</textarea></label>
    <label>Scope<textarea name="scope">${s ? esc(s.scope) : ""}</textarea></label>
    ${wizSect("🪜", "Procedure", "Numbered steps — AI employees follow these exactly")}
    <label>Steps<textarea name="procedure" rows="8" placeholder="1. …&#10;2. …&#10;3. …" style="font-family:Consolas,monospace;font-size:12.5px">${s ? esc(s.procedure) : ""}</textarea></label>
    ${s ? `<div class="actions" style="justify-content:flex-start;margin-top:10px"><button type="button" class="btn danger" id="sop-del">🗑 Delete SOP</button></div>` : ""}`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (!body.owner_id) body.owner_id = null;
      if (s) await api(`/ops/sops/${s.id}`, { method: "PUT", body });
      else await api(opsApi("sops"), { method: "POST", body });
      toast("SOP saved", "ok"); render();
    });
  $("#new-sop").onclick = () => sopModal();
  $$("[data-sop]", v).forEach(el => el.onclick = () => {
    const s = sops.find(x => x.id === el.dataset.sop);
    sopModal(s);
    const del = $("#sop-del");
    if (del) del.onclick = async () => {
      if (!confirm("Delete this SOP?")) return;
      await api(`/ops/sops/${s.id}`, { method: "DELETE" });
      $("#modal-root").innerHTML = ""; toast("SOP deleted", "ok"); render();
    };
  });
};

/* ---------------- Shift roster (worker schedule) ---------------- */
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
views.shifts = async (v) => {
  if (needCompany(v)) return;
  const shifts = await api(opsApi("shifts"));
  const active = shifts.filter(s => s.status === "Active");
  const byDay = (d) => active.filter(s => !s.date && jArr(s.days).includes(d));
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Shifts</span><span class="v">${shifts.length}</span></div>
    <div class="noc-kpi"><span class="k">Active</span><span class="v" style="color:#22c55e">${active.length}</span></div>
    <div class="noc-kpi"><span class="k">Staff rostered</span><span class="v">${new Set(active.map(s => s.employee_id)).size}</span></div>
    <span class="spacer"></span>
    <button class="btn primary" id="new-shift">➕ New shift</button>
  </div>
  <div class="noc-panel" style="margin-bottom:14px">
    <div class="noc-head"><b>🕑 Weekly roster</b><span class="spacer"></span><small>RECURRING SHIFTS · AGENTS WORK THEIR ASSIGNED WINDOWS</small></div>
    <div class="noc-body" style="display:grid;grid-template-columns:repeat(7,1fr);gap:8px">
      ${DAY_NAMES.map((dn, d) => `<div>
        <div class="noc-lbl" style="margin-top:0;text-align:center">${dn}</div>
        ${byDay(d).sort((a, b) => a.start_time.localeCompare(b.start_time)).map(s => `
          <div data-shift="${s.id}" style="cursor:pointer;border:1px solid var(--border);border-left:3px solid #4f8ef7;border-radius:7px;padding:6px 8px;margin-bottom:6px;background:var(--panel2)">
            <div style="font-size:11px;font-family:Consolas,monospace;color:#4f8ef7">${esc(s.start_time)}–${esc(s.end_time)}</div>
            <div style="font-size:12px;font-weight:600">${esc(empName(s.employee_id))}</div>
            ${s.role ? `<div class="muted" style="font-size:10.5px">${esc(s.role)}</div>` : ""}
          </div>`).join("") || '<div class="muted" style="text-align:center;font-size:11px;padding:8px 0">—</div>'}
      </div>`).join("")}
    </div>
  </div>
  ${shifts.length ? `<div class="noc-panel">
    <div class="noc-head"><b>Roster inventory</b><span class="spacer"></span><small>${shifts.length} ENTRIES</small></div>
    <table class="noc-table"><thead><tr>
      <th>Status</th><th>Employee</th><th>Shift</th><th>Days / date</th><th>Hours</th><th>Duty</th>
    </tr></thead><tbody>
    ${shifts.map(s => `<tr data-shift="${s.id}" style="cursor:pointer">
      <td><span class="noc-led ${statusLed(s.status)}"></span>${esc(s.status)}</td>
      <td><b>${esc(empName(s.employee_id))}</b></td>
      <td>${esc(s.name || "—")}</td>
      <td>${s.date ? esc(s.date) : jArr(s.days).map(d => DAY_NAMES[d]).join(" ") || "—"}</td>
      <td class="num">${esc(s.start_time)}–${esc(s.end_time)}</td>
      <td>${esc(s.role || "—")}</td>
    </tr>`).join("")}</tbody></table></div>` : ""}`;
  const shiftModal = (s = null) => modal(s ? "Edit shift" : "New shift", `
    ${wizSect("🕑", "Shift assignment", "Who works when — recurring weekly or a one-off date")}
    <div class="wiz-grid">
      <label>Employee *<select name="employee_id" required>${empOptions(s?.employee_id).replace('value=""', 'value="" disabled')}</select></label>
      <label>Shift name<input name="name" value="${s ? esc(s.name) : ""}" placeholder="e.g. Morning duty"></label>
      <label>Start<input name="start_time" type="time" value="${s ? esc(s.start_time) : "09:00"}"></label>
      <label>End<input name="end_time" type="time" value="${s ? esc(s.end_time) : "17:00"}"></label>
      <label>One-off date (optional)<input name="date" type="date" value="${s ? esc(s.date) : ""}"></label>
      <label>Status<select name="status">${["Active", "Paused"].map(x => `<option ${s && s.status === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
    </div>
    <label>Recurring days (ignored when a one-off date is set)</label>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      ${DAY_NAMES.map((dn, d) => `<label class="perm-item" style="padding:6px 12px"><input type="checkbox" name="d" value="${d}"
        ${s && jArr(s.days).includes(d) ? "checked" : (!s && d < 5 ? "checked" : "")}><span class="perm-text"><b>${dn}</b></span></label>`).join("")}
    </div>
    <label style="margin-top:10px">Duty during the shift<input name="role" value="${s ? esc(s.role) : ""}" placeholder="e.g. Customer support inbox"></label>
    <label>Notes<textarea name="notes">${s ? esc(s.notes) : ""}</textarea></label>
    ${s ? `<div class="actions" style="justify-content:flex-start;margin-top:10px"><button type="button" class="btn danger" id="shift-del">🗑 Delete shift</button></div>` : ""}`,
    async (fd) => {
      const body = { employee_id: fd.get("employee_id"), name: fd.get("name"),
        start_time: fd.get("start_time"), end_time: fd.get("end_time"),
        date: fd.get("date"), status: fd.get("status"), role: fd.get("role"),
        notes: fd.get("notes"), days: fd.getAll("d").map(Number) };
      if (!body.employee_id) throw new Error("Please choose an employee");
      if (s) await api(`/ops/shifts/${s.id}`, { method: "PUT", body });
      else await api(opsApi("shifts"), { method: "POST", body });
      toast("Shift saved", "ok"); render();
    });
  $("#new-shift").onclick = () => shiftModal();
  $$("[data-shift]", v).forEach(el => el.onclick = () => {
    const s = shifts.find(x => x.id === el.dataset.shift);
    shiftModal(s);
    const del = $("#shift-del");
    if (del) del.onclick = async () => {
      if (!confirm("Delete this shift?")) return;
      await api(`/ops/shifts/${s.id}`, { method: "DELETE" });
      $("#modal-root").innerHTML = ""; toast("Shift deleted", "ok"); render();
    };
  });
};

/* ---------------- Chats ---------------- */
function timelineGroup(dateStr) {
  const d = new Date(dateStr);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.floor((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  if (days < 30) return "This month";
  if (d.getFullYear() === now.getFullYear())
    return d.toLocaleString(undefined, { month: "long" });
  return d.toLocaleString(undefined, { month: "short", year: "numeric" });
}

views.chats = async (v) => {
  const q = state.chatQuery.trim();
  let chats = await api("/chats" + (q ? `?q=${encodeURIComponent(q)}` : ""));
  if (q) { // search can return one row per matching message — dedupe for the sidebar
    const seen = new Set();
    chats = chats.filter(c => !seen.has(c.id) && seen.add(c.id));
  }
  const chat = chats.find(c => c.id === state.chatId) || chats[0] || null;
  state.chatId = chat ? chat.id : null;

  // group by timeline buckets (chats are already newest-first)
  const groups = [];
  for (const c of chats) {
    const label = timelineGroup(c.updated_at || c.created_at);
    let g = groups[groups.length - 1];
    if (!g || g.label !== label) { g = { label, items: [] }; groups.push(g); }
    g.items.push(c);
  }

  v.innerHTML = `<div class="chat-layout">
    <div class="chat-list">
      <button class="btn primary" id="new-chat" style="width:100%;margin-bottom:8px">+ New conversation</button>
      <div class="chat-search">
        <input id="chat-search" type="search" placeholder="Search conversations…" value="${esc(state.chatQuery)}" aria-label="Search chats by keyword">
        ${q ? `<button class="mini-btn" id="chat-search-clear" title="Clear search">✕</button>` : ""}
      </div>
      ${q ? `<div class="muted" style="font-size:10.5px;font-family:Consolas,monospace;margin:2px 4px 6px">${chats.length} MATCH${chats.length === 1 ? "" : "ES"} · TITLES + MESSAGES</div>` : ""}
      ${groups.map(g => `
        <div class="tl-label">${esc(g.label)}</div>
        ${g.items.map(c => `<div class="chat-item ${c.id === state.chatId ? "active" : ""}" data-chat="${c.id}" title="${esc(c.title)}${c.project_id ? " · linked to a project" : ""}">
          <span style="display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:8px;vertical-align:1px;background:${c.project_id ? "#4f8ef7" : "rgba(148,163,184,.45)"}"></span>${esc(c.title)}</div>`).join("")}`).join("")
        || `<div class="empty" style="padding:30px 10px">${q ? "No chats match your search." : "No chats yet."}</div>`}
      <div class="muted" style="font-size:9.5px;font-family:Consolas,monospace;letter-spacing:.8px;padding:10px 6px 4px;border-top:1px solid var(--border);margin-top:8px">
        <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#4f8ef7;margin-right:5px;vertical-align:1px"></span>PROJECT-LINKED
      </div>
    </div>
    <div class="chat-main" id="chat-main"></div></div>`;

  // search box behaviour:
  //  - typing filters the sidebar list inline (debounced, keeps focus)
  //  - Enter opens the results dialog (or jumps straight if only 1 match)
  const searchInput = $("#chat-search");
  let debounce;
  searchInput.oninput = () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      state.chatQuery = searchInput.value;
      render().then(() => {
        const si = $("#chat-search");
        if (si) { si.focus(); si.setSelectionRange(si.value.length, si.value.length); }
      });
    }, 300);
  };
  searchInput.onkeydown = async (e) => {
    if (e.key === "Escape") { state.chatQuery = ""; render(); return; }
    if (e.key !== "Enter") return;
    e.preventDefault();
    clearTimeout(debounce);
    const term = searchInput.value.trim();
    if (!term) return;
    const results = await api(`/chats?q=${encodeURIComponent(term)}`);
    if (results.length === 0) {
      toast(`No chats match “${term}”`, "err");
    } else if (results.length === 1) {
      state.chatQuery = "";
      state.chatId = results[0].id;
      state.searchHit = { term, messageId: results[0].match_message_id || null };
      render();
      toast(`Jumped to “${results[0].title}”`, "ok");
    } else {
      showSearchResultsDialog(term, results);
    }
  };
  $("#chat-search-clear") && ($("#chat-search-clear").onclick = () => { state.chatQuery = ""; render(); });
  $("#new-chat").onclick = () => modal("New chat", `
    <label>Title<input name="title" value="New chat"></label>
    <label>Company<select name="company_id">${state.companies.map(c => `<option value="${c.id}" ${c.id === state.companyId ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>
    <label>Acting employee<select name="active_employee_id"><option value="">— choose —</option>
      ${state.employees.map(e => `<option value="${e.id}">${esc(e.avatar)} ${esc(e.full_name)} — ${esc(e.job_title)}</option>`).join("")}</select></label>`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (!body.active_employee_id) body.active_employee_id = null;
      const c = await api("/chats", { method: "POST", body });
      state.chatId = c.id; render();
    }, "Create");
  $$("[data-chat]", v).forEach(el => {
    el.onclick = () => { state.chatId = el.dataset.chat; render(); };
    el.oncontextmenu = (e) => {
      e.preventDefault();
      const c = chats.find(x => x.id === el.dataset.chat);
      if (c) showChatContextMenu(e.pageX, e.pageY, c);
    };
  });
  if (chat) renderChatMain(chat);
  else $("#chat-main").innerHTML = `<div class="empty"><div class="big">💬</div>No chats yet — create one to start working with your virtual employees.</div>`;
};

async function renderChatMain(chat) {
  const main = $("#chat-main");
  // The operator <select> shows the first employee even when the chat has no
  // active_employee_id yet — the UI looked configured while the server
  // rejected every prompt with 400. Persist the displayed default for real.
  if (!chat.active_employee_id && state.employees.length) {
    const first = state.employees.find(e => e.status === "Active") || state.employees[0];
    try {
      await api(`/chats/${chat.id}`, { method: "PUT", body: {
        title: chat.title, company_id: chat.company_id,
        project_id: chat.project_id, active_employee_id: first.id } });
      chat.active_employee_id = first.id;
    } catch { }
  }
  const msgs = await api(`/chats/${chat.id}/messages`);
  const emp = state.employees.find(e => e.id === chat.active_employee_id);
  const company = state.companies.find(c => c.id === chat.company_id);
  const ident = emp ? state.identities.find(i => i.employee_id === emp.id) : null;
  let projects = [];
  try { projects = state.companyId ? await api(`/companies/${state.companyId}/projects`) : []; } catch { /* none */ }
  main.innerHTML = `
    <div class="chat-head">
      <div style="min-width:0">
        <b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(chat.title)}</b>
        <div style="display:flex;gap:14px;margin-top:2px;font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;color:var(--muted)">
          <span>TENANT <b style="color:var(--text)">${company ? esc(company.name.toUpperCase()) : "—"}</b></span>
          ${chat.project_id ? `<span id="chat-proj-pill" style="cursor:pointer;color:#4f8ef7" title="Open project workspace — cross-reference all conversations">OPEN WORKSPACE ↗</span>` : ""}
          <span>MAIL ${ident ? `<b style="color:#22c55e">${esc(ident.email_address)}</b>` : `<span style="color:var(--muted)">NOT CONFIGURED</span>`}</span>
        </div>
      </div>
      <span class="spacer" style="flex:1"></span>
      <label class="muted" style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;display:flex;align-items:center;gap:7px" title="Reference project — its instructions and goals are injected into every task in this conversation, and the conversation appears in that project's workspace">PROJECT
      <select id="chat-proj" style="font-family:inherit;max-width:180px">
        <option value="">— none —</option>
        ${projects.map(p => `<option value="${p.id}" ${p.id === chat.project_id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}
      </select></label>
      <label class="muted" style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;display:flex;align-items:center;gap:7px">OPERATOR
      <select id="chat-emp" style="font-family:inherit">${state.employees.map(e => `<option value="${e.id}" ${e.id === chat.active_employee_id ? "selected" : ""}>${esc(e.avatar)} ${esc(e.full_name)}</option>`).join("") || "<option value=''>— none —</option>"}</select></label>
      <button class="btn small danger" id="del-chat">DELETE</button>
    </div>
    <div class="chat-body">
    <div class="chat-msgs" id="chat-msgs">
      ${msgs.map(m => {
        const who = m.role === "user" ? "You" : (state.employees.find(e => e.id === m.employee_id)?.full_name || "Employee");
        const mProj = m.project_id ? projects.find(p => p.id === m.project_id) : null;
        const ctx = `<span style="font-size:9px;font-family:Consolas,monospace;letter-spacing:.8px;color:${mProj ? "#4f8ef7" : "var(--muted)"};margin-left:8px" title="${mProj ? "Produced under project “" + esc(mProj.name) + "”" : "No project context — general conversation"}">${mProj ? "■ " + esc(mProj.name.toUpperCase()) : "□ GENERAL"}</span>`;
        const actions = m.role === "user"
          ? `<div class="msg-actions"><button class="mini-btn" data-copy="${m.id}" title="Copy prompt">⧉ Copy</button>
             <button class="mini-btn" data-editmsg="${m.id}" title="Edit & resend">✎ Edit</button></div>` : "";
        let atts = [];
        try { atts = JSON.parse(m.attachments || "[]"); } catch {}
        const imgs = atts.map(p =>
          `<div class="att-wrap"><img class="att-img" src="/api/image?path=${encodeURIComponent(p)}" data-img="${esc(p)}" alt="generated image" title="Click to view full size">
           <div class="att-bar"><button class="mini-btn" data-view="${esc(p)}">🔍 View</button>
           <button class="mini-btn" data-imgedit="${esc(p)}">✎ Edit image</button></div></div>`).join("");
        return `<div class="msg ${m.role}" data-msg="${m.id}"><div class="who">${esc(who)}${ctx}</div><span class="msg-content">${m.role === "user" ? linkifyMail(linkifyPaths(esc(m.content))) : mdLite(m.content)}</span>${imgs}${actions}</div>`; }).join("")
        || `<div class="empty">Say hello to ${emp ? esc(emp.full_name) : "your employee"} 👋</div>`}
    </div>
    <div class="chat-history" id="chat-history">
      <div class="ch-title" style="font-family:Consolas,monospace;letter-spacing:1.2px;font-size:10px">SESSION LOG · ${msgs.filter(m => m.role === "user").length}</div>
      ${msgs.filter(m => m.role === "user").map(m => `
        <button class="ch-item" data-jump="${m.id}" title="${esc(m.content.slice(0, 300))}">
          <span class="ch-text">${esc(m.content.length > 60 ? m.content.slice(0, 60) + "…" : m.content)}</span>
          <span class="ch-time">${new Date(m.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
        </button>`).join("") || `<div class="muted" style="font-size:11px;padding:6px">No prompts yet</div>`}
    </div>
    </div>
    <div id="img-ref-bar" class="img-ref-bar hidden"></div>
    <div id="queue-panel" class="queue-panel hidden"></div>
    <div class="chat-input">
      <button class="btn" id="attach-btn" title="Attach one or more images / files as reference" style="align-self:center">📎</button>
      <input type="file" id="attach-file" class="hidden" multiple accept=".png,.jpg,.jpeg,.gif,.webp,.bmp,.txt,.md,.pdf,.csv,.json,.docx,.xlsx">
      <textarea id="chat-text" placeholder="Ask a question or assign a task… (e.g. 'Send an email to client@example.com about the project status')"></textarea>
      <button class="btn primary" id="chat-send">Send</button>
    </div>`;
  const box = $("#chat-msgs");
  if (state.searchHit) {
    const { term, messageId } = state.searchHit;
    const needle = (term || "").toLowerCase();
    state.searchHit = null;
    const target = (messageId && msgs.find(m => m.id === messageId))
      || msgs.find(m => (m.content || "").toLowerCase().includes(needle));
    const el = target ? box.querySelector(`[data-msg="${target.id}"]`) : null;
    if (el) {
      // highlight the keyword inside the message text
      const span = el.querySelector(".msg-content");
      if (span) {
        try {
          const rx = new RegExp("(" + needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
          span.innerHTML = span.innerHTML.replace(rx, "<mark>$1</mark>");
        } catch {}
      }
      el.classList.add("msg-hit");
      el.scrollIntoView({ block: "center" });
      setTimeout(() => el.classList.remove("msg-hit"), 3500);
    } else {
      box.scrollTop = box.scrollHeight;
    }
  } else {
    box.scrollTop = box.scrollHeight;
  }
  const msgById = (id) => msgs.find(m => m.id === id);
  $$("[data-copy]", main).forEach(b => b.onclick = async () => {
    const m = msgById(b.dataset.copy); if (!m) return;
    const ok = await copyText(m.content);
    toast(ok ? "Prompt copied to clipboard" : "Copy failed — select the text manually", ok ? "ok" : "err");
  });
  $$("[data-editmsg]", main).forEach(b => b.onclick = () => {
    const m = msgById(b.dataset.editmsg); if (!m) return;
    const ta = $("#chat-text");
    ta.value = m.content;
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    toast("Prompt loaded into the input — edit and press Send", "ok");
  });
  const openViewer = (p) => openImageViewer(p);
  $$(".att-img", main).forEach(img => img.onclick = () => openViewer(img.dataset.img));
  $$("[data-view]", main).forEach(b => b.onclick = () => openViewer(b.dataset.view));
  $$("[data-imgedit]", main).forEach(b => b.onclick = () => setImageRef(b.dataset.imgedit));
  $$("[data-jump]", main).forEach(b => b.onclick = () => {
    const el = box.querySelector(`[data-msg="${b.dataset.jump}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("msg-hit");
    setTimeout(() => el.classList.remove("msg-hit"), 2500);
  });
  // file links handled globally (see delegated handler at bottom)
  updateImgRefBar();

  // attachment upload — multiple files supported; every file is uploaded and
  // referenced in the prompt so the AI model receives all of them
  $("#attach-btn").onclick = () => $("#attach-file").click();
  $("#attach-file").onchange = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    let okCount = 0;
    for (const f of files) {
      const fd = new FormData();
      fd.append("file", f);
      try {
        const res = await fetch("/api/upload", { method: "POST", body: fd, credentials: "same-origin" });
        if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
        const up = await res.json();
        if (up.is_image && files.length === 1) {
          setImageRef(up.path);
        } else {
          const ta = $("#chat-text");
          ta.value = (ta.value ? ta.value + "\n" : "") + `[Attached file: ${up.path}] Please use this file as reference.`;
        }
        okCount++;
      } catch (err) { toast(`Upload failed (${f.name}): ` + err.message, "err"); }
    }
    if (okCount) {
      $("#chat-text").focus();
      toast(okCount === 1 ? `File attached: ${files[0].name}`
                          : `${okCount} files attached as reference`, "ok");
    }
    e.target.value = "";
  };
  $("#chat-emp").onchange = async (e) => {
    await api(`/chats/${chat.id}`, { method: "PUT", body: { title: chat.title, company_id: chat.company_id, project_id: chat.project_id, active_employee_id: e.target.value } });
    toast("Acting employee switched", "ok"); render();
  };
  $("#chat-proj").onchange = async (e) => {
    const pid = e.target.value || null;
    await api(`/chats/${chat.id}`, { method: "PUT", body: { title: chat.title, company_id: chat.company_id, project_id: pid, active_employee_id: chat.active_employee_id } });
    toast(pid ? "Conversation linked — the project's instructions & goals now apply here" : "Project reference removed", "ok");
    render();
  };
  const projPill = $("#chat-proj-pill");
  if (projPill) projPill.onclick = () => { state.projectId = chat.project_id; nav("projects"); };
  $("#del-chat").onclick = async () => {
    if (!confirm("Delete this chat?")) return;
    await api(`/chats/${chat.id}`, { method: "DELETE" }); state.chatId = null; render();
  };
  /* ---- prompt queue: send without waiting; revise/cancel pending items;
     progress survives navigation because it is rebuilt from server state ---- */
  let lastMsgCount = msgs.length;
  let progEl = null, liveRunId = null;

  const ensureProgressBubble = (runningItem) => {
    if (progEl && progEl.isConnected) return;
    box.querySelector(".empty")?.remove();
    const curProj = chat.project_id ? projects.find(p => p.id === chat.project_id) : null;
    progEl = document.createElement("div");
    progEl.className = "msg employee clickable";
    progEl.title = "Click to open the live pipeline monitor";
    progEl.innerHTML = `<div class="who">${esc(emp ? emp.full_name : "Agent")}
      <span style="font-size:9px;font-family:Consolas,monospace;letter-spacing:.8px;color:${curProj ? "#4f8ef7" : "var(--muted)"};margin-left:8px">${curProj ? "■ " + esc(curProj.name.toUpperCase()) : "□ GENERAL"}</span></div>
      <div style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;color:var(--muted);margin-bottom:5px">PROCESSING FOR ${curProj ? `PROJECT <b style="color:#4f8ef7">${esc(curProj.name.toUpperCase())}</b>` : "<b>GENERAL CONVERSATION</b> (no project)"}</div>
      <span class="spinner">⏳</span> <span class="prog-text">Working on: ${esc(runningItem.content.slice(0, 80))}…</span>
      <div class="prog-stages muted" style="margin-top:8px;font-size:12px"></div>
      <div class="muted" style="margin-top:6px;font-size:11px">Click here to watch the pipeline in detail</div>`;
    progEl.onclick = () => { if (liveRunId) openRunMonitor(liveRunId); else toast("Pipeline is starting — try again in a second", ""); };
    box.appendChild(progEl);
    box.scrollTop = box.scrollHeight;
  };

  const renderQueuePanel = (items) => {
    const panel = $("#queue-panel");
    if (!panel) return;
    const pending = items.filter(i => i.status === "queued");
    const running = items.find(i => i.status === "running");
    panel.classList.toggle("hidden", !pending.length && !running);
    if (!pending.length && !running) { panel.innerHTML = ""; return; }
    panel.innerHTML = `
      <div class="qp-head">Prompt queue — ${running ? "1 running" : "idle"} · ${pending.length} waiting
        <span style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;color:${chat.project_id ? "#4f8ef7" : "var(--muted)"};margin-left:10px">${(() => { const cp = chat.project_id ? projects.find(p => p.id === chat.project_id) : null; return cp ? "■ " + esc(cp.name.toUpperCase()) : "□ GENERAL"; })()}</span>
        <span class="muted" style="font-size:11px">prompts run in order; you can edit or remove any that hasn't started</span></div>
      ${items.filter(i => i.status !== "done").map((i, idx) => `
        <div class="qp-item ${i.status}">
          <span class="qp-status">${i.status === "running" ? "🔄" : i.status === "error" ? "❌" : `#${idx}`}</span>
          <span class="qp-text" title="${esc(i.content.slice(0, 500))}">${esc(i.content.length > 90 ? i.content.slice(0, 90) + "…" : i.content)}</span>
          ${i.status === "queued" ? `
            <button class="mini-btn" data-qedit="${i.id}" title="Revise this prompt">✎ Edit</button>
            <button class="mini-btn" data-qdel="${i.id}" title="Remove from queue">✖</button>` : ""}
          ${i.status === "error" ? `<span class="muted" style="font-size:11px">${esc(i.error || "failed")}</span>` : ""}
        </div>`).join("")}`;
    $$("[data-qedit]", panel).forEach(b => b.onclick = () => {
      const it = items.find(x => x.id === b.dataset.qedit); if (!it) return;
      modal("✎ Revise queued prompt", `
        <label>Prompt (not started yet — you can still change it)
        <textarea name="content" required style="min-height:140px">${esc(it.content)}</textarea></label>`,
        async (fd) => {
          try {
            await api(`/chats/${chat.id}/queue/${it.id}`, { method: "PUT", body: { content: fd.get("content") } });
            toast("Queued prompt revised ✓", "ok");
          } catch (e) { toast(e.message, "err"); }
        }, "Save");
    });
    $$("[data-qdel]", panel).forEach(b => b.onclick = async () => {
      try { await api(`/chats/${chat.id}/queue/${b.dataset.qdel}`, { method: "DELETE" }); toast("Removed from queue", "ok"); }
      catch (e) { toast(e.message, "err"); }
    });
  };

  const poll = async () => {
    // stop polling when the user is looking at another chat/page
    if (state.view !== "chats" || state.chatId !== chat.id || !main.isConnected) {
      clearInterval(window._chatQPoller); return;
    }
    try {
      const { items } = await api(`/chats/${chat.id}/queue`);
      renderQueuePanel(items);
      const running = items.find(i => i.status === "running");
      if (running) {
        ensureProgressBubble(running);
        const p = await api(`/chats/${chat.id}/progress`);
        if (p.run_id) liveRunId = p.run_id;
        const stagesEl = progEl.querySelector(".prog-stages");
        const txtEl = progEl.querySelector(".prog-text");
        const secs = running.started_at ? Math.max(0, Math.round((Date.now() - new Date(running.started_at + "Z").getTime()) / 1000)) : 0;
        if (p.stages && p.stages.length) {
          stagesEl.innerHTML = p.stages.map(s =>
            `${s.status === "done" ? "✅" : s.status === "error" ? "❌" : "🔄"} ${esc(s.label)} — ${esc(s.status)}`).join("<br>");
          const active = p.stages.find(s => s.status === "running");
          txtEl.textContent = active ? `Working on: ${active.label} (${secs}s elapsed)` : `Pipeline running… (${secs}s elapsed)`;
        } else {
          txtEl.textContent = `🧠 ${running.content.slice(0, 60)}… (${secs}s elapsed)`;
        }
      }
      // when a response lands, refresh messages without losing the typed text
      const m = await api(`/chats/${chat.id}/messages`);
      if (m.length !== lastMsgCount) {
        lastMsgCount = m.length;
        const draft = $("#chat-text") ? $("#chat-text").value : "";
        await renderChatMain(chat);
        const ta = $("#chat-text");
        if (ta && draft) { ta.value = draft; }
        refreshBadge();
      }
    } catch { /* transient */ }
  };
  clearInterval(window._chatQPoller);
  window._chatQPoller = setInterval(poll, 2500);
  poll();  // rebuild running-progress immediately when returning to this page

  const send = async () => {
    const text = $("#chat-text").value.trim(); if (!text) return;
    $("#chat-text").value = "";
    const body = { content: text };
    if (state.imageRef) { body.image_ref = state.imageRef; state.imageRef = null; updateImgRefBar(); }
    // show the prompt instantly — no waiting for anything
    box.querySelector(".empty")?.remove();
    const userEl = document.createElement("div");
    userEl.className = "msg user";
    userEl.innerHTML = `<div class="who">You</div>${linkifyPaths(esc(text))}`;
    box.appendChild(userEl);
    lastMsgCount += 1;   // account for the user message the server will store
    box.scrollTop = box.scrollHeight;
    try {
      const face = await grabOpsFaceId();      // operator attribution (≤ 3 s, cached)
      if (face) body.face = face;
      await api(`/chats/${chat.id}/queue`, { method: "POST", body });
      poll();
    } catch (e) { toast(e.message, "err"); }
    $("#chat-text").focus();
  };
  $("#chat-send").onclick = send;
  $("#chat-text").addEventListener("keydown", e => { if (e.key === "Enter" && e.ctrlKey) send(); });
  // prefill handoff (e.g. a workflow prompt generated in the flow-chart designer)
  const prefill = localStorage.getItem("ncChatPrefill");
  if (prefill) {
    localStorage.removeItem("ncChatPrefill");
    const ta = $("#chat-text");
    ta.value = prefill;
    ta.focus();
    ta.scrollIntoView({ block: "nearest" });
  }
}

/* ---------------- Approvals ---------------- */
/* ---------------- Business (personal vs commercial, industry workspace) ---------------- */
views.business = async (v) => {
  const [prof, types, ws] = await Promise.all([
    api("/business/profile"), api("/business/types"), api("/business/workspace")]);
  const commercial = prof.usage_mode === "commercial";
  const stLed = prof.prompt_status === "ready" ? "ok" : prof.prompt_status === "generating" ? "warn" : prof.prompt_status === "error" ? "err" : "";
  const stTxt = prof.prompt_status === "ready" ? "PROMPT ACTIVE" : prof.prompt_status === "generating" ? "GENERATING…" : prof.prompt_status === "error" ? "GENERATION ERROR" : "NOT GENERATED";
  const typeOpts = types.map(t => `<option value="${t.key}" ${prof.company_type === t.key ? "selected" : ""}>${esc(t.label)}</option>`).join("")
    + `<option value="custom" ${prof.company_type === "custom" ? "selected" : ""}>Custom industry…</option>`;
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="noc-lbl">Deployment mode</span><b>${commercial ? "Commercial" : "Personal"}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">Industry profile</span><b>${ws.active ? esc(ws.label) : "Not configured"}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">Company directive</span><b><span class="noc-led ${stLed}"></span> ${stTxt}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">SOP / ISO documents</span><b>${prof.docs.length} document${prof.docs.length === 1 ? "" : "s"} · ${(prof.docs_chars / 1000).toFixed(1)}k chars</b></div>
    <div class="noc-kpi"><span class="noc-lbl">Standards alignment</span><b>ISO 9001 · 14001 · 45001 · 25010</b></div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">Organization Profile</span></div>
    <div class="bp-body">
      <div class="bp-row">
        <span class="bizf-lbl">Deployment mode</span>
        <div class="bp-seg">
          <label class="bp-seg-opt ${!commercial ? "on" : ""}"><input type="radio" name="bp-mode" value="personal" ${!commercial ? "checked" : ""}> Personal</label>
          <label class="bp-seg-opt ${commercial ? "on" : ""}"><input type="radio" name="bp-mode" value="commercial" ${commercial ? "checked" : ""}> Commercial / Enterprise</label>
        </div>
      </div>
      <div id="bp-comm" class="${commercial ? "" : "hidden"}" style="display:grid;gap:14px">
        <div class="bp-grid3">
          <label class="bizf"><span class="bizf-lbl">Industry <em class="bizf-req">*</em></span><select id="bp-type"><option value="">Select industry…</option>${typeOpts}</select></label>
          <label class="bizf ${prof.company_type === "custom" ? "" : "hidden"}" id="bp-custom-wrap"><span class="bizf-lbl">Custom industry</span><input id="bp-custom" value="${esc(prof.custom_type)}" placeholder="e.g. Landscaping Services"></label>
          <label class="bizf"><span class="bizf-lbl">Legal / trading name <em class="bizf-req">*</em></span><input id="bp-name" value="${esc(prof.company_name)}" placeholder="Company name"></label>
        </div>
        <label class="bizf"><span class="bizf-lbl">Business description</span><textarea id="bp-desc" rows="3" placeholder="Activities, market, size, specialties — used by AI to tailor the company directive">${esc(prof.company_desc)}</textarea></label>
      </div>
      <div class="bp-actions">
        <button class="btn primary" id="bp-save">${t("Save profile")}</button>
        <button class="btn ${commercial ? "" : "hidden"}" id="bp-gen">${prof.generated_prompt ? "Regenerate" : "Generate"} company directive (AI)</button>
        <button class="btn ${prof.generated_prompt ? "" : "hidden"}" id="bp-view">Review directive</button>
      </div>
    </div>
  </div>
  <div class="noc-panel ${commercial ? "" : "hidden"}">
    <div class="noc-head"><span class="noc-lbl">Procedure Library — SOP Handbooks &amp; ISO Documents</span>
      <button class="btn small" id="bp-doc-add">Upload document</button></div>
    <div style="padding:10px 14px">
      ${prof.docs.length ? `<table class="noc-table"><tr><th>DOCUMENT</th><th>SIZE</th><th>LEARNED TEXT</th><th>UPLOADED</th><th></th></tr>
        ${prof.docs.map((d, i) => `<tr><td>${esc(d.name)}</td><td>${(d.size / 1024).toFixed(1)} KB</td><td>${(d.chars / 1000).toFixed(1)}k chars</td><td>${esc((d.at || "").slice(0, 10))}</td><td><button class="btn small danger bp-doc-del" data-i="${i}">Remove</button></td></tr>`).join("")}</table>`
      : `<div class="empty">No documents in the procedure library. Upload TXT, MD, PDF, DOCX, CSV or JSON — procedures are analyzed and embedded into the company directive.</div>`}
    </div>
  </div>
  <div id="bp-ws"></div>`;

  $$("input[name=bp-mode]").forEach(r => r.onchange = () => {
    $("#bp-comm").classList.toggle("hidden", r.value !== "commercial" || !r.checked);
    $$(".bp-seg-opt").forEach(o => o.classList.toggle("on", o.querySelector("input").checked));
  });
  const typeSel = $("#bp-type");
  if (typeSel) typeSel.onchange = () => $("#bp-custom-wrap").classList.toggle("hidden", typeSel.value !== "custom");

  const saveProfile = async () => api("/business/profile", { method: "PUT", body: {
    usage_mode: document.querySelector("input[name=bp-mode]:checked").value,
    company_type: typeSel ? typeSel.value : "",
    custom_type: $("#bp-custom") ? $("#bp-custom").value.trim() : "",
    company_name: $("#bp-name") ? $("#bp-name").value.trim() : "",
    company_desc: $("#bp-desc") ? $("#bp-desc").value.trim() : "",
  } });
  $("#bp-save").onclick = async () => { try { await saveProfile(); toast("Profile saved"); refreshBusinessNav(); render(); } catch (e) { toast(e.message, "err"); } };
  const genBtn = $("#bp-gen");
  if (genBtn) genBtn.onclick = async () => {
    genBtn.disabled = true; genBtn.textContent = "Generating — analyzing industry, ISO requirements and procedure library…";
    try { await saveProfile(); await api("/business/generate", { method: "POST" }); toast("Company directive generated — active in all chats"); refreshBusinessNav(); render(); }
    catch (e) { toast(e.message, "err"); render(); }
  };
  const viewBtn = $("#bp-view");
  if (viewBtn) viewBtn.onclick = () => modal("Company Directive — applied to every chat",
    `<label><span class="bizf-lbl">Directive (editable)</span><textarea id="bpm-prompt" rows="18" style="font-family:Consolas,monospace;font-size:12px">${esc(prof.generated_prompt)}</textarea></label>`,
    async () => { await api("/business/prompt", { method: "PUT", body: { prompt: $("#bpm-prompt").value } }); toast("Directive updated"); render(); }, "Save directive");
  const docAdd = $("#bp-doc-add");
  if (docAdd) docAdd.onclick = () => {
    const inp = document.createElement("input"); inp.type = "file"; inp.accept = ".txt,.md,.pdf,.docx,.csv,.json";
    inp.onchange = async () => {
      if (!inp.files[0]) return;
      const fd = new FormData(); fd.append("file", inp.files[0]);
      toast("⏳ Uploading and learning document…");
      const r = await fetch("/api/business/docs", { method: "POST", body: fd, credentials: "same-origin" });
      if (!r.ok) { const d = await r.json().catch(() => ({})); toast("❌ " + (d.detail || "Upload failed"), "err"); return; }
      toast("✅ Document learned — regenerate the prompt to apply it"); render();
    };
    inp.click();
  };
  $$(".bp-doc-del").forEach(b => b.onclick = async () => {
    if (!confirm("Remove this document from the learned corpus?")) return;
    await api("/business/docs/" + b.dataset.i, { method: "DELETE" }); toast("🗑 Document removed"); render();
  });

  if (ws.active) {
    $("#bp-ws").innerHTML = `<div class="noc-panel"><div style="padding:14px;display:flex;justify-content:space-between;align-items:center;gap:12px">
    <span style="font-size:13px;color:var(--muted)">The enterprise registers (Operations, Sales, Supply Chain, HR, Finance, ISO Compliance) are managed in the <b>Operations</b> workspace.</span>
    <button class="btn primary" id="bp-open-ops">Open Operations</button></div></div>`;
    $("#bp-open-ops").onclick = () => nav("operations");
  }
};

/* ---------------- Operations — enterprise ERP workspace ---------------- */
views.operations = async (v) => {
  const ws = state.bizWs && state.bizWs.active ? state.bizWs : await api("/business/workspace");
  state.bizWs = ws;
  if (!ws.active) {
    if (ws.license_required) { renderLicenseRequired(v, ws); return; }
    v.innerHTML = `<div class="empty"><div class="big">🏭</div>Operations is available in commercial mode — configure the company profile in 🏢 Business first.</div>`;
    return;
  }
  if (state.station) {
    // station terminal: pin the workspace to the register named in the URL
    // (match by form code, module key or name substring)
    const q = state.station.trim().toLowerCase();
    const hit = ws.modules.find(m => m.key.toLowerCase() === q) ||
      ws.modules.find(m => (m.name || "").toLowerCase().includes(q));
    if (!hit) {
      v.innerHTML = `<div class="empty"><div class="big">🔍</div>${esc(t("Station register not found:"))} <code>${esc(state.station)}</code></div>`;
      return;
    }
    state.bizModule = hit.key;
  }
  renderBusinessWorkspace(v, ws);
};

function renderLicenseRequired(root, ws) {
  // Multi-company server: each commercial company must be bound to its own
  // license key before the Operations workspace unlocks (per-tenant billing).
  const owner = !!ws.is_owner || !!(state.user && state.user.is_admin);
  root.innerHTML = `<div class="noc-panel" style="max-width:640px;margin:60px auto;padding:26px">
    <h3 style="margin:0 0 6px">🔑 ${t("Company license required")}</h3>
    <p class="muted" style="font-size:13px">${esc(ws.company_name || "")} — ${t("this server hosts multiple companies; each company must be bound to its own license key before Operations unlocks.")}</p>
    ${owner ? `<div style="display:flex;gap:8px;margin-top:14px">
      <input id="lic-key" class="mono" style="flex:1" placeholder="${esc(t('License key'))}" autocomplete="off">
      <button class="btn primary" id="lic-bind">${t("Bind license")}</button></div>
      <p class="muted" style="font-size:12px;margin-top:10px">${t("Keys are issued under Administration ▸ Licenses. A key can license only one company.")}</p>`
      : `<p class="muted" style="font-size:13px;margin-top:12px">${t("Contact your administrator to bind a license for this company.")}</p>`}
  </div>`;
  const btn = $("#lic-bind");
  if (btn) btn.onclick = async () => {
    const key = ($("#lic-key").value || "").trim();
    if (!key) { toast("⚠ " + t("Enter a license key"), "err"); return; }
    try {
      await api("/business/license", { method: "POST", body: { key } });
      toast("✅ " + t("License bound — Operations unlocked"));
      state.bizWs = null; nav("operations");
    } catch (e) { toast("⚠ " + (e.message || e), "err"); }
  };
}

function renderBusinessWorkspace(root, ws) {
  // Split "Register Name (FRM-XXX-001)" — translate the human label, keep the
  // controlled form code verbatim for audit traceability.
  const bizModName = (name) => {
    const mm = /^(.*?)\s*\((FRM[^)]*|OP-[^)]*)\)\s*$/.exec(name);
    const label = t(mm ? mm[1] : name), code = mm ? mm[2] : "";
    return { label, code, full: label + (code ? ` (${code})` : "") };
  };
  const special = state.bizModule === "__oplog" || state.bizModule === "__invmap" || state.bizModule === "__flow";
  const mod = special ? null
    : (ws.modules.find(m => m.key === state.bizModule) || ws.modules[0]);
  if (!special) state.bizModule = mod ? mod.key : "__oplog";
  const isMap = state.bizModule === "__invmap";
  const isFlow = state.bizModule === "__flow";
  const totalRecords = ws.modules.reduce((s, m) => s + (m.count || 0), 0);
  const openItems = ws.modules.reduce((s, m) => s + (m.open || 0), 0);
  // Collapsible navigation — strict accordion: only ONE category (and inside
  // it, one sub-group) is open at a time. Clicking another category collapses
  // the previously open one automatically.
  const openSt = state.bizNavOpen || (state.bizNavOpen = {});
  const activeCat = mod ? (mod.cat || "OPERATIONS") : isMap ? "__MAP" : isFlow ? "__FLOW" : "__LOG";
  const activeGrp = mod ? (mod.grp || "") : "";
  const catOpen = c => ("openCat" in openSt ? openSt.openCat : activeCat) === c;
  const grpOpen = g => ("openGrp" in openSt ? openSt.openGrp : activeGrp) === g;
  const navItem = m => {
    const nm = bizModName(m.name);
    return `<button class="biz-nav-item ${mod && m.key === mod.key ? "active" : ""}" data-mod="${m.key}" data-name="${esc((m.name + " " + nm.label).toLowerCase())}" title="${esc(nm.full)} — ISO ${esc(m.iso)}">
      <span class="biz-nav-ico">${m.icon || "📄"}</span>
      <span class="biz-nav-txt"><span class="biz-nav-name">${esc(nm.label)}</span>${nm.code ? `<span class="biz-nav-code">${esc(nm.code)}</span>` : ""}</span>
      ${m.open ? `<span class="biz-nav-count" title="${m.open} open item${m.open === 1 ? "" : "s"}">${m.open}</span>` : ""}</button>`;
  };
  const navGroups = `
    <div class="biz-nav-group" data-cat="__FLOW">
      <button class="biz-nav-item ${isFlow ? "active" : ""}" data-mod="__flow" data-name="${esc(("process flow " + t("Process Flow")).toLowerCase())}" title="${esc(t("Process Flow"))}">
        <span class="biz-nav-ico">🧭</span>
        <span class="biz-nav-txt"><span class="biz-nav-name">${esc(t("Process Flow"))}</span><span class="biz-nav-code">OP-FLOW-001</span></span>
      </button>
    </div>` + BIZ_CAT_ORDER.map(cat => {
    const mods = ws.modules.filter(m => (m.cat || "OPERATIONS") === cat);
    if (!mods.length) return "";
    // Sub-group by process area (m.grp) when the template defines it —
    // e.g. IMS sections A·RECEIVING … N·IMS for R2 recyclers. Each sub-group
    // is its own dropdown so the menu shows only topics first.
    let inner = "";
    if (mods.some(m => m.grp)) {
      const seen = [];
      for (const m of mods) { const g = m.grp || "GENERAL"; if (!seen.includes(g)) seen.push(g); }
      seen.sort((a, b) => a.localeCompare(b));
      inner = seen.map(g => {
        const gm = mods.filter(m => (m.grp || "GENERAL") === g);
        const gOpen = grpOpen(g);
        const gEmo = bizGrpEmoji(g);
        return `<div class="biz-nav-sub ${gOpen ? "" : "closed"}" data-sub="${esc(g)}">
        <div class="biz-nav-subhead" data-toggle-grp="${esc(g)}"><span>${gEmo} ${esc(t(g))}</span><span class="biz-nav-chev">${gOpen ? "▾" : "▸"}</span></div>
        <div class="biz-nav-subbody">${gm.map(navItem).join("")}</div></div>`;
      }).join("");
    } else {
      inner = mods.map(navItem).join("");
    }
    const cOpen = catOpen(cat);
    return `<div class="biz-nav-group ${cOpen ? "" : "closed"}" data-cat="${cat}">
      <div class="biz-nav-cat" data-toggle-cat="${cat}"><span>${BIZ_CAT_ICON[cat] || ""} ${t(BIZ_CAT_LABEL[cat] || cat)}</span><span class="biz-nav-cat-n">${mods.length}</span><span class="biz-nav-chev">${cOpen ? "▾" : "▸"}</span></div>
      <div class="biz-nav-body">${inner}</div></div>`;
  }).join("") + `
    <div class="biz-nav-group ${catOpen("__MAP") ? "" : "closed"}" data-cat="__MAP">
      <div class="biz-nav-cat" data-toggle-cat="__MAP"><span>🏗️ ${t("FACILITIES")}</span><span class="biz-nav-cat-n">1</span><span class="biz-nav-chev">${catOpen("__MAP") ? "▾" : "▸"}</span></div>
      <div class="biz-nav-body">
      <button class="biz-nav-item ${isMap ? "active" : ""}" data-mod="__invmap" data-name="${esc(("inventory map " + t("Inventory Map")).toLowerCase())}" title="${esc(t("Inventory Map"))}">
        <span class="biz-nav-ico">🗺️</span>
        <span class="biz-nav-txt"><span class="biz-nav-name">${esc(t("Inventory Map"))}</span><span class="biz-nav-code">WMS-MAP-001</span></span>
      </button>
      </div>
    </div>
    <div class="biz-nav-group ${catOpen("__LOG") ? "" : "closed"}" data-cat="__LOG">
      <div class="biz-nav-cat" data-toggle-cat="__LOG"><span>📜 ${t("GOVERNANCE")}</span><span class="biz-nav-cat-n">1</span><span class="biz-nav-chev">${catOpen("__LOG") ? "▾" : "▸"}</span></div>
      <div class="biz-nav-body">
      <button class="biz-nav-item ${!mod && !isMap && !isFlow ? "active" : ""}" data-mod="__oplog" data-name="${esc(("operations log " + t("Operations Log")).toLowerCase())}" title="${esc(t("Operations Log"))}">
        <span class="biz-nav-ico">📜</span>
        <span class="biz-nav-txt"><span class="biz-nav-name">${esc(t("Operations Log"))}</span><span class="biz-nav-code">AUDIT-TRAIL</span></span>
      </button>
      </div>
    </div>`;
  const isoRefs = mod ? String(mod.iso).split("·").map(s => "ISO " + s.trim()).join(" · ") : "ISO 9001 §7.5.3 · §9.2";
  const cat = mod ? (mod.cat || "OPERATIONS") : "__LOG";
  const stationBar = state.station && mod ? `
  <div class="station-bar">
    <span class="st-ico">${mod.icon || "🛠"}</span>
    <div>
      <div class="st-name">${esc(bizModName(mod.name).full)}</div>
      <div class="st-sub">${t("WORKBENCH STATION")} · ${esc(ws.company_name || "")} · ${esc(isoRefs)}</div>
    </div>
    <div class="st-user">
      <select id="station-lang" class="st-lang" aria-label="Language">${Object.entries(LANGS).map(([code, name]) =>
        `<option value="${code}" ${code === CUR_LANG ? "selected" : ""}>${name}</option>`).join("")}</select>
      <button class="btn small" id="station-cams" title="${t('Camera setup for this station')}">📷</button>
      👤 ${esc(state.user.display_name || state.user.username)}
      <button class="btn small" id="station-logout">⏻ ${t("Sign out")}</button></div>
  </div>` : "";
  root.innerHTML = `
  ${stationBar}
  <div class="noc-topbar" style="flex-wrap:nowrap;overflow-x:auto">
    <div class="noc-kpi"><span class="noc-lbl">${t("Organization")}</span><b>${esc(ws.company_name || "—")}</b>${!state.station && state.user.is_admin ? `<select id="biz-actas" class="st-lang" style="margin-left:8px" title="${t('Administrator — switch to any company deployed on this server')}"><option value="">…</option></select>` : ""}</div>
    <div class="noc-kpi"><span class="noc-lbl">${t("Industry profile")}</span><b>${esc(t(ws.label))}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">${t("Registers")}</span><b>${ws.modules.length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">${t("Total records")}</span><b>${totalRecords}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">${t("Open items")}</span><b>${openItems ? `<span class="noc-led warn"></span> ` : ""}${openItems}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">${t("Standards")}</span><b>ISO 9001 · 14001 · 45001</b></div>
    ${!state.station && state.user.is_admin ? `
    <div class="noc-kpi" style="border-right:none;flex-shrink:0"><span class="noc-lbl">${t("Operations Package")}</span>
      <b style="display:flex;align-items:center;gap:6px;white-space:nowrap">
        <span class="noc-led ${ws.ops_package ? "ok" : "off"}"></span>
        ${ws.ops_package ? `${esc(ws.ops_package.name)} <small style="font-weight:400;opacity:.6">v${esc(ws.ops_package.version)}</small>` : t("Built-in template")}
      </b></div>
    <div style="margin-left:auto;align-self:center">
      <button class="btn small" id="biz-ops-studio" title="${t('Design, import or export this company&#39;s operations as a distributable package')}">🧩 ${t("Operations Studio")}</button>
    </div>` : ""}
  </div>
  <div class="noc-panel">
    <div class="biz-ws">
      <nav class="biz-nav">
        <div class="biz-nav-search"><input id="biz-nav-filter" type="search" placeholder="${t('Find a register…')}" autocomplete="off"></div>
        <div id="biz-tabs">${navGroups}</div>
      </nav>
      <section class="biz-main">
        <div class="biz-crumb">${mod ? `${BIZ_CAT_ICON[cat] || ""} ${esc(t(BIZ_CAT_LABEL[cat] || cat))}${mod.grp ? ` <span class=\"biz-crumb-sep\">/</span> ${bizGrpEmoji(mod.grp)} ${esc(t(mod.grp))}` : ""} <span class="biz-crumb-sep">/</span> ${mod.icon || ""} ${esc(bizModName(mod.name).full)}` : isMap ? `🏗️ ${t("FACILITIES")} <span class="biz-crumb-sep">/</span> 🗺️ ${esc(t("Inventory Map"))}` : isFlow ? `🧭 ${esc(t("PROCESS FLOW"))}` : `📜 ${t("GOVERNANCE")} <span class="biz-crumb-sep">/</span> ${esc(t("Operations Log"))}`}</div>
        <header class="biz-main-head">
          ${mod ? "" : `<div>
            <h4 class="biz-main-title">${isMap ? `🗺️ ${esc(t("Inventory Map"))} (WMS-MAP-001)` : isFlow ? `🧭 ${esc(t("Process Flow"))} (OP-FLOW-001)` : `📜 ${esc(t("Operations Log"))}`}</h4>
            <span class="biz-main-sub">${isMap ? t("Facility layout · slotting · location addressing") : isFlow ? t("Operational sequence — perform the procedures in this order. Click a register to open it.") : t("Tamper-evident · operator face attribution")}</span>
          </div>`}
          <div class="biz-main-tools">
            ${(isMap || isFlow) ? "" : `<input id="biz-search" type="search" placeholder="${mod ? t('Search records…') : t('Search log…')}" autocomplete="off">`}
            ${mod ? `<select id="biz-status">
              <option value="">${t("All statuses")}</option>
              <option value="open">${t("Open")}</option>
              <option value="done">${t("Closed")}</option>
              <option value="archived">${t("Archived")}</option>
            </select>
            <button class="btn small" id="biz-filter" title="${t('Per-column filters — narrow the register by any field')}">🔎 ${t("Filter")}</button>
            ${mod.key === "qc" ? `<button class="btn small" id="biz-kpi">📊 ${t("KPI")}</button>` : ""}
            ${!state.station && state.user.is_admin ? `<button class="btn small" id="biz-station" title="${t('Copy a dedicated workbench-terminal link for this register — open it on the bench laptop; only this register is shown.')}">🖥 ${t("Station link")}</button>` : ""}
            <button class="btn small primary" id="biz-add">+ ${t("New record")}</button>` : (isMap || isFlow) ? "" : `<button class="btn small" id="biz-log-refresh">⟳ ${t("Refresh")}</button>`}
          </div>
        </header>
        <div id="biz-rows"><div class="empty">${t("Loading…")}</div></div>
      </section>
    </div>
  </div>`;
  const opsBtn = $("#biz-ops-studio");
  if (opsBtn) opsBtn.onclick = () => showOpsStudio();
  const actAs = $("#biz-actas");
  if (actAs) {
    api("/business/companies").then(cos => {
      actAs.innerHTML = cos.map(c =>
        `<option value="${esc(c.owner_id)}" ${c.mine ? "selected" : ""}>🏢 ${esc(c.company_name)}${c.licensed ? "" : " ⚠"}</option>`).join("") ||
        `<option value="">${t("No companies deployed")}</option>`;
      actAs.onchange = async () => {
        try {
          await api("/business/act-as", { method: "POST", body: { owner_id: actAs.value } });
          toast("🏢 " + t("Acting company switched"), "ok");
          delete state.bizModule; render();
        } catch (e) { toast(e.message, "err"); }
      };
    }).catch(() => { actAs.style.display = "none"; });
  }
  $$("#biz-tabs button").forEach(b => b.onclick = () => {
    state.bizModule = b.dataset.mod;
    // follow the selection: the accordion opens the category/group that
    // holds the newly active register (important after a search jump)
    delete openSt.openCat; delete openSt.openGrp;
    renderBusinessWorkspace(root, ws);
  });
  document.querySelectorAll("#biz-tabs [data-toggle-cat]").forEach(h => h.onclick = () => {
    const c = h.dataset.toggleCat;
    openSt.openCat = catOpen(c) ? "" : c;      // open clicked, close the rest
    openSt.openGrp = "";                       // reset sub-group accordion
    renderBusinessWorkspace(root, ws);
  });
  document.querySelectorAll("#biz-tabs [data-toggle-grp]").forEach(h => h.onclick = (e) => {
    e.stopPropagation();
    const g = h.dataset.toggleGrp;
    openSt.openGrp = grpOpen(g) ? "" : g;      // one sub-group at a time
    renderBusinessWorkspace(root, ws);
  });
  const navFilter = $("#biz-nav-filter");
  navFilter.oninput = () => {
    const q = navFilter.value.trim().toLowerCase();
    $("#biz-tabs").classList.toggle("searching", !!q);
    $$("#biz-tabs .biz-nav-item").forEach(b => b.classList.toggle("hidden", q && !b.dataset.name.includes(q)));
    $$("#biz-tabs .biz-nav-sub").forEach(s => s.classList.toggle("hidden",
      ![...s.querySelectorAll(".biz-nav-item")].some(b => !b.classList.contains("hidden"))));
    $$("#biz-tabs .biz-nav-group").forEach(g => g.classList.toggle("hidden",
      ![...g.querySelectorAll(".biz-nav-item")].some(b => !b.classList.contains("hidden"))));
  };
  const addBtn = $("#biz-add");
  if (addBtn && mod) addBtn.onclick = () => businessRecordModal(mod, null, () => renderBusinessWorkspace(root, ws));
  const kpiBtn = $("#biz-kpi");
  if (kpiBtn && mod) kpiBtn.onclick = () => bizTechKpi(mod);
  const stBtn = $("#biz-station");
  if (stBtn && mod) stBtn.onclick = async () => {
    // dedicated workbench-terminal link: only this register, no other menus
    const code = (/\((FRM[^)]*|OP-[^)]*)\)/.exec(mod.name) || [])[1] || mod.key;
    const url = secureOrigin() + "/?station=" + encodeURIComponent(code);
    try { await navigator.clipboard.writeText(url); toast("🖥 " + t("Station link copied — open it on the workbench laptop:") + " " + url); }
    catch { prompt(t("Copy this station link and open it on the workbench laptop:"), url); }
  };
  const stOut = $("#station-logout");
  if (stOut) stOut.onclick = async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch { }
    location.replace(location.pathname);     // drop ?station= → normal login
  };
  const stLang = $("#station-lang");
  if (stLang) stLang.onchange = (e) => {
    CUR_LANG = e.target.value;
    localStorage.setItem("nexacrew_lang", CUR_LANG);
    applyI18n();
    render();
  };
  const stCams = $("#station-cams");
  if (stCams) stCams.onclick = async () => { await stationCameraSetup(); toast("📷 " + t("Camera setup saved for this session")); };
  if (mod) loadBusinessRows(mod, root, ws);
  else if (isMap) loadInventoryMap(root, ws);
  else if (isFlow) loadBusinessFlow(root, ws);
  else loadBusinessOplog(root, ws);
}

/* ---------- Process Flow (OP-FLOW-001) — visual order of procedures.
   Main reuse/resale lane (steps 1…n), the dismantle · data-destruction ·
   recycle branch (splits after testing, steps 3.x), and continuous support
   processes. Every register chip navigates to that register. ---------- */
function loadBusinessFlow(root, ws) {
  const box = $("#biz-rows");
  const byLetter = {};
  for (const m of ws.modules) {
    const mm = /^([A-Z])\s*·/.exec(m.grp || "");
    const L = mm ? mm[1] : "•";
    (byLetter[L] = byLetter[L] || []).push(m);
  }
  const nm = name => { const mm = /^(.*?)\s*\((FRM[^)]*|OP-[^)]*)\)\s*$/.exec(name); return t(mm ? mm[1] : name); };
  const card = (L, stepLbl) => {
    const mods = byLetter[L] || [];
    if (!mods.length) return "";
    return `<div class="flow-card">
      <div class="flow-step">${esc(String(stepLbl))}</div>
      <div class="flow-grp">${bizGrpEmoji(mods[0].grp)} ${esc(t(mods[0].grp || ""))}</div>
      <div class="flow-regs">${mods.map(m => `<button class="flow-reg" data-mod="${m.key}" title="ISO ${esc(m.iso || "")}">${m.icon || "📄"} ${esc(nm(m.name))}</button>`).join("")}</div>
    </div>`;
  };
  const arrow = `<div class="flow-arrow">↓</div>`;
  const MAIN = ["A", "B", "C", "J", "I"], BRANCH = ["D", "E", "F", "G", "M"], SUPPORT = ["H", "K", "L", "N"];
  const lane = (letters, lbl) => letters.filter(L => byLetter[L])
    .map((L, i, arr) => card(L, lbl(i)) + (i < arr.length - 1 ? arrow : "")).join("");
  const other = Object.keys(byLetter).filter(L => ![...MAIN, ...BRANCH, ...SUPPORT].includes(L));
  box.innerHTML = `<div class="flow-wrap">
    <div class="flow-lane">
      <div class="flow-lane-title">🔁 ${t("Main flow — reuse / resale path")}</div>
      ${lane(MAIN, i => i + 1)}
    </div>
    <div class="flow-lane">
      <div class="flow-lane-title">♻️ ${t("Branch after step 3 — dismantle · data destruction · recycle")}</div>
      ${lane(BRANCH, i => "3." + (i + 1))}
    </div>
    <div class="flow-lane flow-support">
      <div class="flow-lane-title">🛡️ ${t("Support — continuous processes (daily / periodic)")}</div>
      ${[...SUPPORT, ...other].filter(L => byLetter[L]).map(L => card(L, "∞")).join("")}
    </div>
  </div>`;
  box.querySelectorAll(".flow-reg").forEach(b => b.onclick = () => {
    state.bizModule = b.dataset.mod; renderBusinessWorkspace(root, ws);
  });
}

/* ---------- Inventory / Facility Map — WMS-grade drag-and-drop designer.
   Multi-warehouse, multi-zone, infinite canvas (wheel zoom, space+drag pan).
   Building structure (walls, rooms with draggable doors, entrances, exits,
   roads, utility rooms) plus storage topology: racks with aisle/bay/level/lot
   addressing, per-slot naming, virtual-location splits, purpose tagging and
   multi-select merge. Location codes:  AISLE-BAY-LEVEL  (e.g. A01-03-L2). ---------- */
const INVMAP_TYPES = {
  rack:     { name: "Rack",              ico: "🗄️", w: 240, h: 80,  min: 60,  grp: "STORAGE" },
  bench:    { name: "Working bench",     ico: "🛠️", w: 160, h: 60,  min: 40,  grp: "STORAGE" },
  dock:     { name: "Dock door",         ico: "🚛", w: 100, h: 20,  min: 60,  grp: "STORAGE" },
  staging:  { name: "Staging",           ico: "📦", w: 200, h: 120, min: 60,  grp: "STORAGE" },
  wall:     { name: "Wall",              ico: "🧱", w: 300, h: 12,  min: 20,  grp: "STRUCTURE" },
  room:     { name: "Room",              ico: "🚪", w: 220, h: 160, min: 80,  grp: "STRUCTURE" },
  door:     { name: "Door",              ico: "🚪", w: 60,  h: 14,  min: 30,  grp: "STRUCTURE" },
  entrance: { name: "Main entrance",     ico: "🏬", w: 120, h: 22,  min: 60,  grp: "STRUCTURE" },
  exit:     { name: "Emergency exit",    ico: "🟩", w: 90,  h: 20,  min: 50,  grp: "STRUCTURE" },
  road:     { name: "Road / lane",       ico: "🛣️", w: 400, h: 80,  min: 60,  grp: "STRUCTURE" },
  zone:     { name: "Zone area",         ico: "▦",  w: 320, h: 220, min: 80,  grp: "AREAS" },
  subzone:  { name: "Sub zone",          ico: "◫",  w: 180, h: 120, min: 50,  grp: "AREAS" },
  office:   { name: "Office",            ico: "🏢", w: 160, h: 120, min: 60,  grp: "AREAS" },
  elec:     { name: "Electricity room",  ico: "⚡", w: 120, h: 100, min: 50,  grp: "AREAS" },
  restroom: { name: "Restroom",          ico: "🚻", w: 110, h: 100, min: 50,  grp: "AREAS" },
  spare:    { name: "Spare parts area",  ico: "🧰", w: 200, h: 140, min: 60,  grp: "AREAS" },
  disposal: { name: "Disposal area",     ico: "♻️", w: 200, h: 140, min: 60,  grp: "AREAS" },
  recycle:  { name: "Recycle storage",   ico: "🏪", w: 240, h: 160, min: 60,  grp: "AREAS" },
  label:    { name: "Text label",        ico: "🔤", w: 140, h: 28,  min: 40,  grp: "AREAS" },
};
const INVMAP_GRID = 20;

/* ---- shared location index: every addressable slot on every map, used by
   the Asset Registration "Storage location" picker and the click-to-locate
   links. Cached for 30 s. ---- */
async function invMapLocationIndex(force) {
  const c = state._imIdx;
  if (!force && c && Date.now() - c.at < 30000) return c.idx;
  const idx = [];
  try {
    const list = await api("/business/maps");
    for (const meta of list) {
      const full = await api("/business/maps/" + meta.id);
      let doc = {};
      try { doc = JSON.parse(full.data || "{}"); } catch { }
      for (const el of (doc.elements || [])) {
        // named operational areas (spare parts / disposal / recycle storage /
        // staging) are addressable locations too — FRM-SPARE-001 / FRM-RCY-00x
        if (["spare", "disposal", "recycle", "staging"].includes(el.type)) {
          const label = (el.props || {}).label || INVMAP_TYPES[el.type].name.toUpperCase();
          idx.push({ code: label, mapId: meta.id, warehouse: meta.warehouse, zone: meta.zone, areaId: el.id });
          continue;
        }
        if (el.type !== "rack") continue;
        const p = el.props || {};
        const bays = Math.max(1, +p.bays || 1), lvls = Math.max(1, +p.levels || 1);
        const cells = p.cells || {}, merges = p.merges || {};
        const seenMerge = new Set();
        for (let b = 1; b <= bays; b++)
          for (let l = 1; l <= lvls; l++) {
            const k = `${b}|${l}`, cell = cells[k] || {};
            const base = `${p.aisle || "A01"}-${String(b).padStart(2, "0")}-L${l}${p.lot ? "·" + p.lot : ""}`;
            const push = code => idx.push({ code, mapId: meta.id, warehouse: meta.warehouse, zone: meta.zone, rackId: el.id, bay: b, level: l });
            if (cell.merge) {
              if (seenMerge.has(cell.merge)) { push((merges[cell.merge] || {}).name || base); continue; }
              seenMerge.add(cell.merge);
              push((merges[cell.merge] || {}).name || base);
              continue;
            }
            const label = cell.name || base;
            const virt = Math.max(1, +cell.virt || 1);
            if (virt > 1) for (let v = 1; v <= virt; v++) push(`${label}-V${v}`);
            else push(label);
          }
      }
    }
  } catch { }
  state._imIdx = { at: Date.now(), idx };
  return idx;
}

/* Navigate to the inventory map and blink the slot holding `code`. */
async function invMapLocate(code, root, ws) {
  const idx = await invMapLocationIndex(true);
  const hit = idx.find(o => o.code === code) ||
              idx.find(o => o.code.toLowerCase() === String(code).toLowerCase());
  if (!hit) { toast("⚠ " + t("Location not found on any facility map") + ": " + code, "err"); return; }
  state.invMap = state.invMap || {};
  const S = state.invMap;
  S.cur = hit.mapId;
  S.tool = "select";
  if (hit.areaId) {
    S.sel = hit.areaId; S.selCells = [];
    S.blink = { areaId: hit.areaId, code, warehouse: hit.warehouse, zone: hit.zone };
  } else {
    S.sel = hit.rackId; S.selCells = [hit.rackId + "|" + hit.bay + "|" + hit.level];
    S.blink = { rackId: hit.rackId, k: `${hit.bay}|${hit.level}`, code, warehouse: hit.warehouse, zone: hit.zone };
  }
  state.bizModule = "__invmap";
  renderBusinessWorkspace(root, ws);
}

/* ── Facility Map — enterprise tutorial & worked example ─────────────── */
function invMapExampleElements() {
  const id = () => "el" + Math.random().toString(36).slice(2, 9);
  const rack = (x, y, aisle) => ({ id: id(), type: "rack", x, y, w: 480, h: 120, rot: 0,
    props: { aisle, bays: 6, levels: 4, lot: "", name: "", cells: {}, merges: {} } });
  const r1 = rack(200, 200, "A01"), r2 = rack(200, 400, "A02"), r3 = rack(200, 600, "A03");
  r1.props.cells["1|1"] = { name: "FAST-PICK-01" };
  r1.props.cells["2|1"] = { name: "FAST-PICK-02" };
  r2.props.cells["1|2"] = { virt: 3 };
  const gid = "m" + Date.now();
  r3.props.merges = { [gid]: { name: "BULK-OVERSIZE", cells: ["5|1", "6|1"] } };
  r3.props.cells["5|1"] = { merge: gid }; r3.props.cells["6|1"] = { merge: gid };
  return [
    { id: id(), type: "wall", x: 100, y: 100, w: 1400, h: 20, rot: 0, props: {} },
    { id: id(), type: "wall", x: 100, y: 100, w: 20, h: 800, rot: 0, props: {} },
    { id: id(), type: "wall", x: 1480, y: 100, w: 20, h: 800, rot: 0, props: {} },
    { id: id(), type: "wall", x: 100, y: 880, w: 1400, h: 20, rot: 0, props: {} },
    { id: id(), type: "entrance", x: 700, y: 880, w: 160, h: 20, rot: 0, props: { name: "MAIN ENTRANCE" } },
    { id: id(), type: "exit", x: 100, y: 440, w: 20, h: 100, rot: 0, props: { name: "EMERGENCY EXIT E1" } },
    { id: id(), type: "dock", x: 1180, y: 120, w: 300, h: 140, rot: 0, props: { name: "DOCK D1 — RECEIVING" } },
    { id: id(), type: "staging", x: 860, y: 120, w: 300, h: 140, rot: 0, props: { name: "INBOUND STAGING" } },
    { id: id(), type: "road", x: 760, y: 120, w: 80, h: 740, rot: 0, props: { name: "MHE LANE 1" } },
    { id: id(), type: "zone", x: 160, y: 160, w: 580, h: 620, rot: 0, props: { name: "ZONE A — RESERVE" } },
    r1, r2, r3,
    { id: id(), type: "bench", x: 900, y: 320, w: 220, h: 100, rot: 0, props: { name: "QC BENCH 1" } },
    { id: id(), type: "office", x: 1240, y: 320, w: 220, h: 160, rot: 0, props: { name: "OPS OFFICE" } },
    { id: id(), type: "elec", x: 1240, y: 520, w: 160, h: 120, rot: 0, props: { name: "ELEC ROOM" } },
    { id: id(), type: "restroom", x: 1240, y: 680, w: 160, h: 120, rot: 0, props: { name: "RESTROOM" } },
    { id: id(), type: "room", x: 900, y: 480, w: 300, h: 220, rot: 0, props: { name: "COLD ROOM CR-1", doors: [{ side: "s", off: 0.5 }] } },
    { id: id(), type: "label", x: 600, y: 60, w: 400, h: 30, rot: 0, props: { name: "DC-LAX-01 · RECEIVING HALL" } },
  ];
}

function invMapTutorial(S, boot, curMeta, markDirty) {
  const ch = (n, ttl, body) => `<div class="im-tut-ch"><div class="im-tut-h"><span class="im-tut-n">${n}</span>${ttl}</div><div class="im-tut-b">${body}</div></div>`;
  const kbd = k => `<kbd class="im-kbd">${k}</kbd>`;
  const html = `
  <div class="im-tut">
    <div class="im-tut-intro">🎓 <b>${t("Facility & Inventory Map — Operator Certification Guide")}</b> (WMS-MAP-001)<br>
    ${t("This guide follows the standard commissioning workflow used for data-center-grade facility layouts: structure → flow → storage → slotting → integration → publication.")}</div>
    ${ch(1, t("Create the map"), t("Use <b>＋ Zone</b> in the toolbar to register a Warehouse / Zone pair (e.g. <b>DC-LAX-01 / RECEIVING</b>). Each zone is a separate, independently audited layout document."))}
    ${ch(2, t("Navigate like a CAD system"), `${t("Mouse wheel")} = ${t("zoom to cursor")} · ${kbd("Space")} + ${t("drag")} = ${t("pan (infinite canvas)")} · ⛶ = ${t("fit to contents")} · ${kbd("V")} ${t("returns to Select")}.`)}
    ${ch(3, t("Draw the building structure"), t("From <b>STRUCTURE</b>, draw the perimeter with <b>Wall</b>, then place <b>Main Entrance</b>, <b>Emergency Exit</b>, <b>Dock</b>, and a <b>Road</b> lane for material-handling equipment. <b>Room</b> objects carry a draggable door — drag the door block along any side."))}
    ${ch(4, t("Place & configure storage"), t("From <b>STORAGE</b>, drop a <b>Rack</b>. Click the ⚙ gear (top-right of the rack) to open its properties: <b>Aisle</b>, <b>Bays</b>, <b>Levels</b>, <b>Lot</b>. The rack renders a live bay×level grid with the level rail (L1…Ln) on the flank."))}
    ${ch(5, t("Slotting (right-click)"), `${t("Click a slot to select it; right-click for the location menu: <b>Name this location</b>, <b>Split into virtual locations</b> (V1…Vn), <b>Purpose</b>.")} ${kbd("Ctrl")}+${t("click selects multiple slots — right-click → <b>Merge</b> creates one named bulk location.")}`)}
    ${ch(6, t("Precision editing"), `${t("8 resize handles on every object.")} ${kbd("Shift")} = ${t("constrain aspect")} · ${kbd("Alt")} = ${t("resize from center")} · ${t("live size badge in px & meters")} · ⟳ ${t("handle rotates (15° snap)")} · ${kbd("R")} = 90° · ${kbd("Ctrl+Z")}/${kbd("Ctrl+Y")} = ${t("undo/redo (100 steps)")} · ${kbd("Del")} = ${t("remove")} · ${t("arrows nudge")} (${kbd("Shift")}×5).`)}
    ${ch(7, t("ERP integration"), t("Every named slot becomes a selectable <b>Storage location</b> in Asset Registration & Inventory (🗺️ picker in the record form). 📍 links in the registers jump back here and blink the exact slot."))}
    ${ch(8, t("Publish"), t("The layout autosaves (LED in the toolbar). <b>🖼 Export JPG</b> produces a print-grade drawing with an ISO 9001 §7.1.3 title block; <b>📍 Location schedule</b> lists every commissioned location code."))}
    <div class="im-tut-ex">
      <b>💡 ${t("Worked example")}</b> — ${t("insert a complete reference layout (perimeter, dock, staging, MHE lane, 3 racks A01–A03 with named / split / merged slots, QC bench, cold room, offices) into the current zone map. Fully editable afterwards.")}
      <div style="margin-top:8px"><button type="button" class="btn small" id="im-tut-ex-btn">📐 ${t("Insert example layout")}</button></div>
    </div>
  </div>`;
  modal("🎓 " + t("Inventory Map Tutorial"), html, null);
  const b = $("#im-tut-ex-btn");
  if (b) b.onclick = () => {
    if (!S.cur) { toast("⚠ " + t("Create or select a zone map first."), "err"); return; }
    if (S.doc.elements.length && !confirm(t("The example will be added to the existing layout. Continue?"))) return;
    S.doc.elements.push(...invMapExampleElements());
    markDirty(); toast("📐 " + t("Example layout inserted"));
    $("#modal-root").innerHTML = "";
    boot();
  };
}

function loadInventoryMap(root, ws) {
  const host = $("#biz-rows");
  const S = state.invMap = state.invMap || {
    cur: null, tool: "select", sel: null, selCells: [], dirty: false,
    vb: { x: -100, y: -100, w: 1800, h: 1150 }, space: false,
  };
  S.selMulti = S.selMulti || [];

  const snap = v => Math.round(v / INVMAP_GRID) * INVMAP_GRID;
  const cellKey = (b, l) => `${b}|${l}`;

  /* ---- location code resolution: names, virtual splits, merges ---- */
  const locCodes = el => {
    const p = el.props || {};
    const bays = Math.max(1, +p.bays || 1), lvls = Math.max(1, +p.levels || 1);
    const cells = p.cells || {}, merges = p.merges || {};
    const seenMerge = new Set();
    const out = [];
    for (let b = 1; b <= bays; b++)
      for (let l = 1; l <= lvls; l++) {
        const c = cells[cellKey(b, l)] || {};
        const base = `${p.aisle || "A01"}-${String(b).padStart(2, "0")}-L${l}${p.lot ? "·" + p.lot : ""}`;
        if (c.merge) {
          if (seenMerge.has(c.merge)) continue;
          seenMerge.add(c.merge);
          const g = merges[c.merge] || {};
          out.push((g.name || base + "+MERGED") + ` [${(g.cells || []).length}⧉]`);
          continue;
        }
        const label = c.name || base;
        const virt = Math.max(1, +c.virt || 1);
        if (virt > 1) for (let v = 1; v <= virt; v++) out.push(`${label}-V${v}`);
        else out.push(label + (c.purpose ? ` ⚙${c.purpose}` : ""));
      }
    return out;
  };

  const saveDoc = async (silent) => {
    if (!S.cur) return;
    await api("/business/maps/" + S.cur, { method: "PUT", body: { data: JSON.stringify(S.doc) } });
    S.dirty = false;
    const led = $("#im-save-led");
    if (led) { led.className = "im-led ok"; $("#im-save-txt").textContent = t("Saved"); }
    if (!silent) toast("💾 " + t("Map committed to server"));
  };
  let saveTimer = null;
  /* ---- undo / redo history (Ctrl+Z / Ctrl+Y) — coalesced snapshots ---- */
  let histTimer = null;
  const pushHist = (immediate) => {
    clearTimeout(histTimer);
    const commit = () => {
      const snap2 = JSON.stringify(S.doc);
      S.hist = S.hist || []; S.histPos = S.histPos ?? -1;
      if (S.hist[S.histPos] === snap2) return;
      S.hist = S.hist.slice(0, S.histPos + 1);
      S.hist.push(snap2);
      if (S.hist.length > 100) S.hist.shift();
      S.histPos = S.hist.length - 1;
      updateHistBtns();
    };
    if (immediate) commit(); else histTimer = setTimeout(commit, 450);
  };
  const restoreHist = (pos) => {
    if (!S.hist || pos < 0 || pos >= S.hist.length) return;
    S.histPos = pos;
    S.doc = JSON.parse(S.hist[pos]);
    S.sel = null; S.selCells = [];
    S.dirty = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveDoc(true), 1200);
    drawEls(); drawProps(); updateHistBtns();
    const led = $("#im-save-led");
    if (led) { led.className = "im-led warn"; $("#im-save-txt").textContent = t("Unsaved changes"); }
  };
  const undo = () => { if ((S.histPos ?? 0) > 0) { restoreHist(S.histPos - 1); toast("↶ " + t("Undo")); } };
  const redo = () => { if (S.hist && S.histPos < S.hist.length - 1) { restoreHist(S.histPos + 1); toast("↷ " + t("Redo")); } };
  const updateHistBtns = () => {
    const u = $("#im-undo"), r = $("#im-redo");
    if (u) u.disabled = !(S.hist && S.histPos > 0);
    if (r) r.disabled = !(S.hist && S.histPos < S.hist.length - 1);
  };
  const markDirty = () => {
    S.dirty = true;
    const led = $("#im-save-led");
    if (led) { led.className = "im-led warn"; $("#im-save-txt").textContent = t("Unsaved changes"); }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveDoc(true), 2000);
    pushHist();
  };

  const boot = async () => {
    let list;
    try {
      list = await api("/business/maps");
    } catch (e) {
      host.innerHTML = `<div class="empty" style="padding:40px"><div class="big">⚠️</div>
        <p>${t("Could not load facility maps")}: ${esc(String(e && e.message || e))}</p>
        <button class="btn" id="im-retry">⟳ ${t("Refresh")}</button></div>`;
      $("#im-retry").onclick = () => { host.innerHTML = `<div class="empty">${t("Loading…")}</div>`; boot(); };
      return;
    }
    S.list = list;
    if (!list.length) {
      host.innerHTML = `<div class="empty" style="padding:40px"><div class="big">🗺️</div>
        <p>${t("No facility maps yet. Create the first warehouse zone map to start slotting.")}</p>
        <button class="btn primary" id="im-first">+ ${t("Create map")}</button></div>`;
      $("#im-first").onclick = () => newMapModal();
      return;
    }
    if (!S.cur || !list.some(m => m.id === S.cur)) S.cur = list[0].id;
    const full = await api("/business/maps/" + S.cur);
    try { S.doc = JSON.parse(full.data || "{}"); } catch { S.doc = {}; }
    if (!S.doc.elements) S.doc = { elements: [] };
    S.meta = full;
    S.hist = [JSON.stringify(S.doc)]; S.histPos = 0;
    draw();
  };

  const newMapModal = (presetWh) => modal(t("New facility map"),
    `<label><span class="bizf-lbl">${t("Warehouse")}</span><input id="im-nw-wh" value="${esc(presetWh || "Warehouse 1")}"></label>
     <label><span class="bizf-lbl">${t("Zone")}</span><input id="im-nw-zn" value="Zone A"></label>`,
    async () => {
      const r = await api("/business/maps", { method: "POST", body: { warehouse: $("#im-nw-wh").value, zone: $("#im-nw-zn").value } });
      S.cur = r.id; toast("✅ " + t("Map created")); boot();
    }, t("Create"));

  const vbAttr = () => `${S.vb.x} ${S.vb.y} ${S.vb.w} ${S.vb.h}`;
  const applyVb = () => {
    const svg = $("#im-svg");
    if (!svg) return;
    svg.setAttribute("viewBox", vbAttr());
    const bg = $("#im-bg1"), bg5 = $("#im-bg5");
    for (const r of [bg, bg5]) if (r) {
      r.setAttribute("x", S.vb.x - INVMAP_GRID * 5); r.setAttribute("y", S.vb.y - INVMAP_GRID * 5);
      r.setAttribute("width", S.vb.w + INVMAP_GRID * 10); r.setAttribute("height", S.vb.h + INVMAP_GRID * 10);
    }
    const z = $("#im-zoom-pct");
    if (z) z.textContent = Math.round(1800 / S.vb.w * 100) + "%";
  };

  function draw() {
    const whs = {};
    for (const m of S.list) (whs[m.warehouse] = whs[m.warehouse] || []).push(m);
    const curMeta = S.list.find(m => m.id === S.cur) || {};
    const palGroups = ["STORAGE", "STRUCTURE", "AREAS"];
    const palette = palGroups.map(g => `<div class="im-pal-grp">${t(g)}</div>` +
      Object.entries(INVMAP_TYPES).filter(([, d]) => d.grp === g).map(([k, d]) =>
        `<button class="im-tool ${S.tool === k ? "active" : ""}" data-tool="${k}" title="${t(d.name)}">${d.ico}<span>${t(d.name)}</span></button>`).join("")).join("");
    host.innerHTML = `
    <div class="im-bar">
      <select id="im-map-sel" title="${t("Warehouse / zone")}">
        ${Object.entries(whs).map(([wh, zs]) => `<optgroup label="🏭 ${esc(wh)}">
          ${zs.map(z => `<option value="${z.id}" ${z.id === S.cur ? "selected" : ""}>${esc(z.zone)}</option>`).join("")}</optgroup>`).join("")}
      </select>
      <button class="btn small" id="im-new">+ ${t("Zone / warehouse")}</button>
      <button class="btn small" id="im-rename">✏ ${t("Rename")}</button>
      <button class="btn small danger" id="im-del">🗑</button>
      <span class="im-sep"></span>
      <button class="btn small" id="im-locs">📍 ${t("Location schedule")}</button>
      <button class="btn small" id="im-export">🖼 ${t("Export JPG")}</button>
      <button class="btn small" id="im-tut">🎓 ${t("Tutorial")}</button>
      <span class="im-sep"></span>
      <button class="btn small" id="im-undo" title="${t("Undo")} (Ctrl+Z)">↶</button>
      <button class="btn small" id="im-redo" title="${t("Redo")} (Ctrl+Y)">↷</button>
      <span class="im-sep"></span>
      <button class="btn small" id="im-zout">−</button>
      <span class="im-zoom" id="im-zoom-pct">100%</span>
      <button class="btn small" id="im-zin">+</button>
      <button class="btn small" id="im-zfit" title="${t("Fit contents")}">⛶</button>
      <span class="im-spacer"></span>
      <span class="im-savebox"><span id="im-save-led" class="im-led ok"></span><span id="im-save-txt">${t("Saved")}</span></span>
      <button class="btn small primary" id="im-save">💾 ${t("Save")}</button>
    </div>
    <div class="im-body">
      <div class="im-palette im-ps">
        <div class="im-tool-grid">
        <button class="im-tool ${S.tool === "select" ? "active" : ""}" data-tool="select" title="${t("Select / move")} (V)">🖱️<span>${t("Select")}</span></button>
        ${palette}
        </div>
        <div class="im-pal-head">${t("HELP")}</div>
        <div class="im-pal-note">${t("Wheel = zoom · Space+drag = pan")}<br>${t("Ctrl+click = multi-select")}<br>${t("Right-click = location menu")}<br>${t("Shift = aspect · Alt = center")}<br>${t("Ctrl+Z / Ctrl+Y = undo / redo")}</div>
      </div>
      <div class="im-canvas-wrap" id="im-wrap">
        <svg id="im-svg" viewBox="${vbAttr()}" preserveAspectRatio="xMidYMid slice">
          <defs>
            <pattern id="im-grid" width="${INVMAP_GRID}" height="${INVMAP_GRID}" patternUnits="userSpaceOnUse">
              <path d="M ${INVMAP_GRID} 0 L 0 0 0 ${INVMAP_GRID}" fill="none" stroke="rgba(120,160,220,.10)" stroke-width="1"/>
            </pattern>
            <pattern id="im-grid5" width="${INVMAP_GRID * 5}" height="${INVMAP_GRID * 5}" patternUnits="userSpaceOnUse">
              <path d="M ${INVMAP_GRID * 5} 0 L 0 0 0 ${INVMAP_GRID * 5}" fill="none" stroke="rgba(120,160,220,.20)" stroke-width="1"/>
            </pattern>
          </defs>
          <rect id="im-bg1" fill="url(#im-grid)"/>
          <rect id="im-bg5" fill="url(#im-grid5)"/>
          <g id="im-els"></g>
        </svg>
      </div>
      <div class="im-props" id="im-props"></div>
    </div>`;
    $("#im-map-sel").onchange = e => { S.cur = e.target.value; S.sel = null; S.selCells = []; boot(); };
    $("#im-new").onclick = () => newMapModal(curMeta.warehouse);
    $("#im-rename").onclick = () => modal(t("Rename map"),
      `<label><span class="bizf-lbl">${t("Warehouse")}</span><input id="im-rn-wh" value="${esc(curMeta.warehouse || "")}"></label>
       <label><span class="bizf-lbl">${t("Zone")}</span><input id="im-rn-zn" value="${esc(curMeta.zone || "")}"></label>`,
      async () => { await api("/business/maps/" + S.cur, { method: "PUT", body: { warehouse: $("#im-rn-wh").value, zone: $("#im-rn-zn").value } }); toast("✏ " + t("Renamed")); boot(); }, t("Save"));
    $("#im-del").onclick = async () => {
      if (!confirm(t("Delete this zone map? The layout is unrecoverable (deletion is audited)."))) return;
      await api("/business/maps/" + S.cur, { method: "DELETE" }); S.cur = null; toast("🗑 " + t("Map deleted")); boot();
    };
    $("#im-tut").onclick = () => invMapTutorial(S, boot, curMeta, markDirty);
    $("#im-save").onclick = () => saveDoc(false);
    $("#im-export").onclick = () => {
      // export the full layout (fit-to-contents) as a print-grade JPG with a
      // professional title block: warehouse / zone / timestamp / scale.
      const els = S.doc.elements;
      if (!els.length) { toast("⚠ " + t("Nothing to export — the map is empty."), "err"); return; }
      const x0 = Math.min(...els.map(e => e.x)) - 60, y0 = Math.min(...els.map(e => e.y)) - 60;
      const x1 = Math.max(...els.map(e => e.x + e.w)) + 60, y1 = Math.max(...els.map(e => e.y + e.h)) + 60;
      const w = Math.max(800, x1 - x0), h = Math.max(500, y1 - y0);
      const svgNode = $("#im-svg").cloneNode(true);
      svgNode.setAttribute("viewBox", `${x0} ${y0} ${w} ${h}`);
      svgNode.setAttribute("width", w); svgNode.setAttribute("height", h);
      svgNode.querySelectorAll(".im-handle,.im-rot").forEach(n => n.remove());
      // inline the css classes the JPG needs (external css doesn't apply inside the image)
      const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
      style.textContent = `.im-txt{fill:#cfe0f5;font-size:12px;font-family:Consolas,monospace}.im-txt.sm{font-size:9px}.im-txt.xs{font-size:8px;fill:rgba(220,235,255,.8)}.im-txt.zone{font-size:14px;font-weight:700;fill:rgba(160,200,255,.85);letter-spacing:.08em}.im-txt.lbl{font-size:14px;fill:#e8eef8}.im-txt.cell{fill:#eaf2ff}.im-txt.cell.named{fill:#d9ffe142;fill:#dfffe9}.im-txt.rackhead{font-size:11px;fill:#bcd8ff;font-weight:700}`;
      svgNode.insertBefore(style, svgNode.firstChild);
      const bgs = svgNode.querySelectorAll("#im-bg1,#im-bg5");
      bgs.forEach(r => { r.setAttribute("x", x0); r.setAttribute("y", y0); r.setAttribute("width", w); r.setAttribute("height", h); });
      const xml = new XMLSerializer().serializeToString(svgNode);
      const img = new Image();
      const scale = Math.min(3, Math.max(1.5, 2600 / w));
      img.onload = () => {
        const HEAD = 64 * scale;
        const cv = document.createElement("canvas");
        cv.width = Math.round(w * scale); cv.height = Math.round(h * scale + HEAD);
        const cx2 = cv.getContext("2d");
        cx2.fillStyle = "#0b1220"; cx2.fillRect(0, 0, cv.width, cv.height);
        // title block
        cx2.fillStyle = "#101a2e"; cx2.fillRect(0, 0, cv.width, HEAD);
        cx2.strokeStyle = "rgba(120,170,240,.4)"; cx2.lineWidth = 1 * scale;
        cx2.strokeRect(0.5, 0.5, cv.width - 1, HEAD - 1);
        cx2.fillStyle = "#dbe8fb"; cx2.font = `700 ${15 * scale}px Segoe UI, Arial`;
        cx2.fillText(`🏭 ${curMeta.warehouse || ""}  /  ${curMeta.zone || ""} — ${t("Facility & Inventory Map")} (WMS-MAP-001)`, 14 * scale, 24 * scale);
        cx2.fillStyle = "#8ba0bd"; cx2.font = `${10.5 * scale}px Segoe UI, Arial`;
        const racks = els.filter(e => e.type === "rack");
        const nloc = racks.reduce((s, r) => s + locCodes(r).length, 0);
        cx2.fillText(`${t("Racks")}: ${racks.length}   ·   ${t("Addressable locations")}: ${nloc}   ·   ${t("Grid")}: ${INVMAP_GRID}px ≈ 0.5 m   ·   ${t("Generated")}: ${new Date().toLocaleString()}   ·   ISO 9001 §7.1.3`, 14 * scale, 44 * scale);
        cx2.drawImage(img, 0, HEAD, cv.width, cv.height - HEAD);
        const a = document.createElement("a");
        a.download = `${(curMeta.warehouse || "warehouse").replace(/\W+/g, "_")}-${(curMeta.zone || "zone").replace(/\W+/g, "_")}-map.jpg`;
        a.href = cv.toDataURL("image/jpeg", 0.92);
        a.click();
        toast("🖼 " + t("Map exported as JPG"));
      };
      img.onerror = () => toast("❌ " + t("Export failed — the SVG could not be rasterized."), "err");
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
    };
    const zoomBy = f => {
      const cx = S.vb.x + S.vb.w / 2, cy = S.vb.y + S.vb.h / 2;
      S.vb.w = Math.min(40000, Math.max(200, S.vb.w * f)); S.vb.h = S.vb.w * 0.64;
      S.vb.x = cx - S.vb.w / 2; S.vb.y = cy - S.vb.h / 2; applyVb();
    };
    $("#im-zin").onclick = () => zoomBy(0.8);
    $("#im-zout").onclick = () => zoomBy(1.25);
    $("#im-undo").onclick = undo;
    $("#im-redo").onclick = redo;
    updateHistBtns();
    $("#im-zfit").onclick = () => {
      const els = S.doc.elements;
      if (!els.length) { S.vb = { x: -100, y: -100, w: 1800, h: 1150 }; applyVb(); return; }
      const x0 = Math.min(...els.map(e => e.x)) - 80, y0 = Math.min(...els.map(e => e.y)) - 80;
      const x1 = Math.max(...els.map(e => e.x + e.w)) + 80, y1 = Math.max(...els.map(e => e.y + e.h)) + 80;
      S.vb.w = Math.max(600, x1 - x0); S.vb.h = Math.max(400, y1 - y0);
      S.vb.x = x0; S.vb.y = y0; applyVb();
    };
    $("#im-locs").onclick = () => {
      const racks = S.doc.elements.filter(e => e.type === "rack");
      const rows = racks.map(r => {
        const codes = locCodes(r);
        return `<tr><td><b>${esc((r.props || {}).aisle || "A01")}</b></td><td>${(r.props || {}).bays || 1}</td><td>${(r.props || {}).levels || 1}</td><td>${esc((r.props || {}).lot || "—")}</td><td>${codes.length}</td><td style="font-family:Consolas,monospace;font-size:11px">${codes.slice(0, 10).map(esc).join(", ")}${codes.length > 10 ? " …" : ""}</td></tr>`;
      }).join("");
      modal("📍 " + t("Location schedule") + ` — ${esc(curMeta.warehouse)}/${esc(curMeta.zone)}`,
        racks.length ? `<div style="max-height:420px;overflow:auto"><table class="md-tbl" style="width:100%"><thead><tr>
          <th>${t("Aisle")}</th><th>${t("Bays")}</th><th>${t("Levels")}</th><th>${t("Lot")}</th><th>#</th><th>${t("Location codes")}</th></tr></thead><tbody>${rows}</tbody></table>
          <p style="color:var(--muted);font-size:12px;margin-top:8px">${t("Total addressable locations")}: <b>${racks.reduce((s, r) => s + locCodes(r).length, 0)}</b></p></div>`
        : `<div class="empty">${t("No racks on this map yet — draw racks to generate the slotting schedule.")}</div>`,
        null, null);
    };
    $$(".im-tool").forEach(b => b.onclick = () => { S.tool = b.dataset.tool; S.sel = null; S.selCells = []; draw(); });
    drawEls();
    bindCanvas();
    drawProps();
    applyVb();
    if (S.blink) {
      const bl = S.blink;
      const tgt = S.doc.elements.find(e => e.id === (bl.rackId || bl.areaId));
      if (tgt) {
        // zoom the viewport onto the target and show the locate banner
        S.vb.w = Math.max(700, tgt.w * 3); S.vb.h = S.vb.w * 0.64;
        S.vb.x = tgt.x + tgt.w / 2 - S.vb.w / 2; S.vb.y = tgt.y + tgt.h / 2 - S.vb.h / 2;
        applyVb();
        const wrap = $("#im-wrap");
        const ban = document.createElement("div");
        ban.className = "im-locate-banner";
        const path = bl.rackId
          ? `${esc((tgt.props || {}).name || (tgt.props || {}).aisle || "")} · ${t("Bay")} ${bl.k.split("|")[0]} · ${t("Level")} ${bl.k.split("|")[1]}`
          : `${INVMAP_TYPES[tgt.type] ? INVMAP_TYPES[tgt.type].ico + " " + esc(t(INVMAP_TYPES[tgt.type].name)) : ""}`;
        ban.innerHTML = `<span class="im-locate-dot"></span>
          <b>📍 ${esc(bl.code)}</b>
          <span class="im-locate-path">🏭 ${esc(bl.warehouse)} <span class="biz-crumb-sep">/</span> ${esc(bl.zone)} <span class="biz-crumb-sep">/</span> ${path}</span>
          <button class="btn small" id="im-locate-x">✕ ${t("Dismiss")}</button>`;
        wrap.appendChild(ban);
        $("#im-locate-x").onclick = () => { S.blink = null; ban.remove(); drawEls(); };
        setTimeout(() => { if (S.blink === bl) { S.blink = null; if (ban.parentNode) ban.remove(); drawEls(); } }, 45000);
      } else { S.blink = null; }
    }
  }

  /* ---- SVG per element ---- */
  function elSvg(el) {
    const sel = S.sel === el.id;
    const p = el.props || {};
    const stroke = sel ? "var(--accent, #4da3ff)" : "rgba(160,190,230,.55)";
    let body = "";
    if (el.type === "rack") {
      const bays = Math.max(1, +p.bays || 1), lvls = Math.max(1, +p.levels || 1);
      const cw = el.w / bays, chh = el.h / lvls;
      let cellsSvg = "";
      const fitTxt = (txt, maxW, maxH) => {
        // fitted, centered slot label — font scales with the cell box
        const fs = Math.max(6, Math.min(13, maxW / Math.max(4, txt.length) * 1.7, maxH * 0.42));
        return { fs, show: fs >= 6 && maxH >= 12 };
      };
      for (let b = 1; b <= bays; b++)
        for (let l = 1; l <= lvls; l++) {
          const k = cellKey(b, l), c = (p.cells || {})[k] || {};
          const selCell = S.selCells.includes(el.id + "|" + k);
          const isBlink = S.blink && S.blink.rackId === el.id && S.blink.k === k;
          let fill = "rgba(50,90,150,.40)";
          if (c.merge) fill = "rgba(150,110,220,.45)";
          else if (c.purpose) fill = "rgba(240,170,60,.40)";
          else if (c.name) fill = "rgba(60,170,140,.40)";
          if (selCell) fill = "rgba(80,160,255,.65)";
          const cx = cw * (b - 1), cy = chh * (lvls - l);
          cellsSvg += `<rect class="im-cell${isBlink ? " im-blink" : ""}" data-rack="${el.id}" data-bay="${b}" data-level="${l}"
            x="${cx}" y="${cy}" width="${cw}" height="${chh}"
            fill="${fill}" stroke="rgba(120,160,220,.5)" stroke-width="${selCell ? 1.6 : 0.6}"/>`;
          // slot label: custom name > merged name > short code B-L
          const mg = c.merge ? (p.merges || {})[c.merge] || {} : null;
          const slotTxt = (mg && mg.name) ? mg.name
            : c.name ? c.name
            : `${String(b).padStart(2, "0")}-L${l}`;
          const f = fitTxt(slotTxt, cw - 4, chh);
          if (f.show) cellsSvg += `<text x="${cx + cw / 2}" y="${cy + chh / 2 + f.fs * 0.36}" text-anchor="middle" class="im-txt cell${c.name || mg ? " named" : ""}" font-size="${f.fs}" pointer-events="none">${esc(slotTxt.length > 22 ? slotTxt.slice(0, 21) + "…" : slotTxt)}</text>`;
          if (c.virt > 1) cellsSvg += `<text x="${cx + 2}" y="${cy + 9}" class="im-txt xs" pointer-events="none">⧈${c.virt}</text>`;
          if (c.purpose) cellsSvg += `<text x="${cx + cw - 3}" y="${cy + 9}" text-anchor="end" class="im-txt xs" pointer-events="none">⚙</text>`;
        }
      const rackTitle = `${p.name ? p.name + " · " : ""}${p.aisle || "A01"} · ${bays}B×${lvls}L${p.lot ? " · " + p.lot : ""}`;
      // level rail — every storage level labeled on the left flank (top = highest)
      let rail = "";
      if (chh >= 10) {
        for (let l = 1; l <= lvls; l++) {
          const ry = chh * (lvls - l);
          const fs = Math.max(7, Math.min(11, chh * 0.4));
          rail += `<rect x="-24" y="${ry}" width="22" height="${chh}" fill="rgba(18,30,52,.85)" stroke="rgba(120,170,240,.3)" stroke-width="0.6"/>
            <text x="-13" y="${ry + chh / 2 + fs * 0.36}" text-anchor="middle" class="im-txt lvl" font-size="${fs}" pointer-events="none">L${l}</text>`;
        }
      }
      // level summary strip across the rack top: L1…Ln — tells the operator
      // instantly how many working levels this rack has
      const lvlStrip = Array.from({ length: lvls }, (_, i) => "L" + (lvls - i)).join(" · ");
      body = `<rect x="-25" y="-18" width="${Math.max(el.w + 26, rackTitle.length * 6.6 + 12)}" height="16" rx="3" fill="rgba(18,30,52,.92)" stroke="rgba(120,170,240,.35)" stroke-width="0.8"/>
        <text x="-19" y="-5.5" class="im-txt rackhead">🗄 ${esc(rackTitle)}</text>
        <text x="${Math.max(el.w + 26, rackTitle.length * 6.6 + 12) - 30}" y="-5.5" text-anchor="end" class="im-txt lvlstrip">${esc(lvlStrip)}</text>
        <rect width="${el.w}" height="${el.h}" rx="2" fill="rgba(30,50,85,.5)" stroke="${stroke}" stroke-width="${sel ? 2 : 1.2}"/>
        ${rail}${cellsSvg}
        <g class="im-gear" data-id="${el.id}"><circle cx="${el.w - 2}" cy="-10" r="8" fill="rgba(20,35,60,.95)" stroke="rgba(130,180,250,.6)" stroke-width="1.2"/><text x="${el.w - 2}" y="-6.6" text-anchor="middle" font-size="9.5" pointer-events="none">⚙️</text><title>${t("Rack configuration")}</title></g>`;
    } else if (el.type === "bench") {
      // workbench: tabletop with 4 legs + tool rail — reads instantly as furniture
      const lw = Math.max(4, Math.min(10, el.w * 0.05)), lh = Math.max(5, el.h * 0.28);
      body = `<rect width="${el.w}" height="${el.h}" fill="transparent" stroke="none"/>
        <rect y="${el.h - lh}" width="${lw}" height="${lh}" fill="rgba(140,100,60,.9)"/>
        <rect x="${el.w - lw}" y="${el.h - lh}" width="${lw}" height="${lh}" fill="rgba(140,100,60,.9)"/>
        <rect x="${el.w * 0.30}" y="${el.h - lh}" width="${lw}" height="${lh}" fill="rgba(140,100,60,.7)"/>
        <rect x="${el.w * 0.65}" y="${el.h - lh}" width="${lw}" height="${lh}" fill="rgba(140,100,60,.7)"/>
        <rect width="${el.w}" height="${el.h - lh + 3}" rx="4" fill="rgba(170,130,80,.5)" stroke="${stroke}" stroke-width="${sel ? 2 : 1.1}"/>
        <line x1="4" y1="9" x2="${el.w - 4}" y2="9" stroke="rgba(220,190,140,.55)" stroke-width="2" stroke-dasharray="8 5"/>
        <text x="6" y="${(el.h - lh) / 2 + 8}" class="im-txt">🛠 ${esc(p.label || "BENCH")}</text>`;
    } else if (el.type === "wall") {
      // wall: solid slab with architectural diagonal hatching
      const horiz = el.w >= el.h;
      let hatch = "";
      const step = 14, n = Math.ceil((el.w + el.h) / step);
      for (let i = 1; i < n; i++) {
        const d = i * step;
        const x1 = Math.min(d, el.w), y1 = d > el.w ? d - el.w : 0;
        const x2 = d > el.h ? d - el.h : 0, y2 = Math.min(d, el.h);
        hatch += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(90,100,120,.55)" stroke-width="1"/>`;
      }
      body = `<rect width="${el.w}" height="${el.h}" fill="rgba(185,195,215,.8)" stroke="${sel ? stroke : "rgba(120,130,150,.9)"}" stroke-width="${sel ? 2 : 1}"/>${hatch}`;
      void horiz;
    } else if (el.type === "door") {
      // door: architectural leaf + quarter-circle swing arc
      const horiz = el.w >= el.h;
      const L = horiz ? el.w : el.h;
      body = horiz
        ? `<rect width="${el.w}" height="${el.h}" fill="transparent" stroke="none"/>
           <path d="M 0 ${el.h} A ${L} ${L} 0 0 1 ${L} ${el.h - L}" fill="rgba(90,200,140,.12)" stroke="rgba(90,200,140,.7)" stroke-width="1.2" stroke-dasharray="4 3"/>
           <line x1="0" y1="${el.h}" x2="${L * 0.72}" y2="${el.h - L * 0.72}" stroke="rgba(120,230,170,.95)" stroke-width="3.5" stroke-linecap="round"/>
           <circle cx="0" cy="${el.h}" r="3.5" fill="#2fae52" stroke="${stroke}"/>`
        : `<rect width="${el.w}" height="${el.h}" fill="transparent" stroke="none"/>
           <path d="M ${el.w} 0 A ${L} ${L} 0 0 1 ${el.w - L} ${L}" fill="rgba(90,200,140,.12)" stroke="rgba(90,200,140,.7)" stroke-width="1.2" stroke-dasharray="4 3"/>
           <line x1="${el.w}" y1="0" x2="${el.w - L * 0.72}" y2="${L * 0.72}" stroke="rgba(120,230,170,.95)" stroke-width="3.5" stroke-linecap="round"/>
           <circle cx="${el.w}" cy="0" r="3.5" fill="#2fae52" stroke="${stroke}"/>`;
    } else if (el.type === "entrance") {
      // main entrance: double sliding doors under an awning, inbound arrows
      const mid = el.w / 2;
      body = `<rect width="${el.w}" height="${el.h}" rx="2" fill="rgba(80,180,255,.30)" stroke="${sel ? stroke : "rgba(90,190,255,.9)"}" stroke-width="${sel ? 2 : 1.4}"/>
        <rect x="-6" y="-6" width="${el.w + 12}" height="7" rx="3" fill="rgba(80,180,255,.85)"/>
        <line x1="${mid}" y1="1" x2="${mid}" y2="${el.h - 1}" stroke="rgba(200,235,255,.9)" stroke-width="2"/>
        <path d="M ${mid - 16} ${el.h + 12} l 6 -9 l 6 9 z" fill="rgba(80,180,255,.9)"/>
        <path d="M ${mid + 4} ${el.h + 12} l 6 -9 l 6 9 z" fill="rgba(80,180,255,.9)"/>
        <text x="4" y="${el.h - 5}" class="im-txt sm">🏬 ${esc(p.label || "MAIN ENTRANCE")}</text>`;
    } else if (el.type === "exit") {
      // emergency exit: green escape chevron pointing outward
      const horiz = el.w >= el.h;
      const arrow = horiz
        ? `<path d="M 4 ${el.h / 2} L ${el.w * 0.55} 3 L ${el.w * 0.55} ${el.h * 0.3} L ${el.w - 3} ${el.h * 0.3} L ${el.w - 3} ${el.h * 0.7} L ${el.w * 0.55} ${el.h * 0.7} L ${el.w * 0.55} ${el.h - 3} Z" transform="rotate(180 ${el.w / 2} ${el.h / 2})" fill="rgba(20,90,45,.85)"/>`
        : `<path d="M ${el.w / 2} 4 L ${el.w - 3} ${el.h * 0.55} L ${el.w * 0.7} ${el.h * 0.55} L ${el.w * 0.7} ${el.h - 3} L ${el.w * 0.3} ${el.h - 3} L ${el.w * 0.3} ${el.h * 0.55} L 3 ${el.h * 0.55} Z" fill="rgba(20,90,45,.85)"/>`;
      body = `<rect width="${el.w}" height="${el.h}" rx="3" fill="rgba(60,200,90,.9)" stroke="${sel ? stroke : "#2fae52"}" stroke-width="${sel ? 2 : 1.2}"/>${arrow}
        <text x="4" y="${el.h - 5}" class="im-txt sm" fill="#08331a">🏃 ${esc(p.label || "EXIT")}</text>`;
    } else if (el.type === "road") {
      // traffic lane: curbs, dashed centerline, direction chevrons
      const horiz = el.w >= el.h;
      let chev = "";
      if (horiz) {
        const cy = el.h / 2, s = Math.min(10, el.h * 0.3);
        for (let x = 40; x < el.w - 20; x += 90)
          chev += `<path d="M ${x} ${cy - s} L ${x + s * 1.4} ${cy} L ${x} ${cy + s}" fill="none" stroke="rgba(240,220,90,.55)" stroke-width="2.5"/>`;
      } else {
        const cx = el.w / 2, s = Math.min(10, el.w * 0.3);
        for (let y = 40; y < el.h - 20; y += 90)
          chev += `<path d="M ${cx - s} ${y} L ${cx} ${y + s * 1.4} L ${cx + s} ${y}" fill="none" stroke="rgba(240,220,90,.55)" stroke-width="2.5"/>`;
      }
      const center = horiz
        ? `<line x1="6" y1="${el.h / 2}" x2="${el.w - 6}" y2="${el.h / 2}" stroke="rgba(240,220,90,.8)" stroke-width="3" stroke-dasharray="18 14"/>
           <line x1="0" y1="1.5" x2="${el.w}" y2="1.5" stroke="rgba(200,205,220,.7)" stroke-width="3"/>
           <line x1="0" y1="${el.h - 1.5}" x2="${el.w}" y2="${el.h - 1.5}" stroke="rgba(200,205,220,.7)" stroke-width="3"/>`
        : `<line x1="${el.w / 2}" y1="6" x2="${el.w / 2}" y2="${el.h - 6}" stroke="rgba(240,220,90,.8)" stroke-width="3" stroke-dasharray="18 14"/>
           <line x1="1.5" y1="0" x2="1.5" y2="${el.h}" stroke="rgba(200,205,220,.7)" stroke-width="3"/>
           <line x1="${el.w - 1.5}" y1="0" x2="${el.w - 1.5}" y2="${el.h}" stroke="rgba(200,205,220,.7)" stroke-width="3"/>`;
      body = `<rect width="${el.w}" height="${el.h}" fill="rgba(70,75,90,.7)" stroke="${stroke}" stroke-width="${sel ? 2 : 0.8}"/>${center}${chev}
        <text x="6" y="14" class="im-txt sm">${esc(p.label || "LANE")}</text>`;
    } else if (el.type === "dock") {
      // dock door: hazard-striped leveller + roll-up door slats + truck badge
      const rampH = Math.min(14, el.h * 0.25);
      let stripes = "";
      for (let x = 0; x < el.w; x += 16)
        stripes += `<path d="M ${x} ${el.h} l 10 -${rampH} l 8 0 l -10 ${rampH} z" fill="rgba(20,22,28,.75)"/>`;
      let slats = "";
      for (let y = 8; y < el.h - rampH - 4; y += 9)
        slats += `<line x1="3" y1="${y}" x2="${el.w - 3}" y2="${y}" stroke="rgba(120,95,30,.5)" stroke-width="1.4"/>`;
      body = `<rect width="${el.w}" height="${el.h}" rx="2" fill="rgba(240,180,60,.8)" stroke="${sel ? stroke : "rgba(200,145,40,.95)"}" stroke-width="${sel ? 2 : 1.4}"/>
        ${slats}
        <rect y="${el.h - rampH}" width="${el.w}" height="${rampH}" fill="rgba(240,200,70,.95)"/>
        <g clip-path="none">${stripes}</g>
        <text x="4" y="${Math.min(18, el.h - rampH - 4)}" class="im-txt sm">🚛 ${esc(p.label || "DOCK")}</text>`;
    } else if (el.type === "zone" || el.type === "subzone") {
      const sub = el.type === "subzone";
      // zone: dashed area with CAD-style corner brackets so it reads as a region
      const B = Math.min(26, el.w / 4, el.h / 4), bs = sub ? "rgba(110,220,180,.8)" : "rgba(130,180,250,.8)";
      const corners = `
        <path d="M 0 ${B} L 0 0 L ${B} 0"                              fill="none" stroke="${bs}" stroke-width="2.5"/>
        <path d="M ${el.w - B} 0 L ${el.w} 0 L ${el.w} ${B}"           fill="none" stroke="${bs}" stroke-width="2.5"/>
        <path d="M ${el.w} ${el.h - B} L ${el.w} ${el.h} L ${el.w - B} ${el.h}" fill="none" stroke="${bs}" stroke-width="2.5"/>
        <path d="M ${B} ${el.h} L 0 ${el.h} L 0 ${el.h - B}"           fill="none" stroke="${bs}" stroke-width="2.5"/>`;
      body = `<rect width="${el.w}" height="${el.h}" rx="6" fill="${p.color || (sub ? "rgba(90,220,170,.10)" : "rgba(90,140,220,.12)")}" stroke="${sel ? stroke : sub ? "rgba(110,220,180,.45)" : "rgba(120,170,240,.4)"}" stroke-dasharray="${sub ? "3 3" : "6 4"}" stroke-width="${sel ? 2 : 1.2}"/>${corners}
        <text x="8" y="20" class="im-txt zone">${esc(p.label || (sub ? "SUB ZONE" : "ZONE"))}</text>`;
    } else if (["office", "elec", "restroom", "staging", "room", "spare", "disposal", "recycle"].includes(el.type)) {
      const fills = { office: "rgba(150,120,220,.25)", elec: "rgba(250,210,70,.22)", restroom: "rgba(110,190,240,.22)", staging: "rgba(90,200,200,.18)", room: "rgba(140,155,180,.16)",
                      spare: "rgba(230,150,60,.22)", disposal: "rgba(230,90,90,.20)", recycle: "rgba(100,210,130,.18)" };
      const icons = { office: "🏢", elec: "⚡", restroom: "🚻", staging: "📦", room: "", spare: "🧰", disposal: "♻️", recycle: "🏪" };
      const strokes = { spare: "rgba(240,170,80,.6)", disposal: "rgba(255,120,120,.65)", recycle: "rgba(110,220,150,.6)" };
      const badges = { spare: "FRM-SPARE-001", disposal: "→ FRM-RCY-001", recycle: "FRM-RCY-002 · R2" };
      /* per-type interior motif so each area is recognizable at a glance */
      let motif = "";
      if (el.type === "staging") {
        // pallet footprints: grid of small squares with slats
        const pw = 34, ph = 26, gx = 10, gy = 10;
        for (let y = 24; y + ph < el.h - 6; y += ph + gy)
          for (let x = 8; x + pw < el.w - 6; x += pw + gx)
            motif += `<rect x="${x}" y="${y}" width="${pw}" height="${ph}" rx="2" fill="rgba(90,200,200,.14)" stroke="rgba(120,210,210,.5)" stroke-width="0.9"/>
              <line x1="${x + 3}" y1="${y + ph / 2}" x2="${x + pw - 3}" y2="${y + ph / 2}" stroke="rgba(120,210,210,.4)" stroke-width="0.8"/>`;
      } else if (el.type === "elec") {
        // hazard tape on top edge + big lightning bolt
        let tape = "";
        for (let x = 0; x < el.w; x += 14)
          tape += `<path d="M ${x} 6 l 7 -6 l 7 0 l -7 6 z" fill="rgba(30,30,35,.8)"/>`;
        motif = `<rect width="${el.w}" height="6" fill="rgba(250,210,70,.9)"/>${tape}
          <path d="M ${el.w / 2 + 6} ${el.h * 0.30} L ${el.w / 2 - 8} ${el.h * 0.58} L ${el.w / 2 - 1} ${el.h * 0.58} L ${el.w / 2 - 6} ${el.h * 0.82} L ${el.w / 2 + 9} ${el.h * 0.52} L ${el.w / 2 + 1} ${el.h * 0.52} Z" fill="rgba(250,210,70,.55)" stroke="rgba(250,210,70,.9)" stroke-width="1"/>`;
      } else if (el.type === "restroom") {
        // architectural restroom: center partition splits M/F sides, toilet
        // stalls along the top of each side, a sink counter with basins at
        // the bottom, and large person pictograms — unmistakable at a glance
        const W = el.w, H = el.h, mid = W / 2;
        const stallW = Math.max(18, Math.min(30, W / 6)), stallH = Math.max(16, Math.min(26, H * 0.24));
        const stCol = "rgba(110,190,240,.65)";
        let stalls = "";
        for (const x0 of [4, mid + 4]) {
          for (let x = x0; x + stallW < (x0 < mid ? mid : W) - 2; x += stallW + 3) {
            stalls += `<rect x="${x}" y="22" width="${stallW}" height="${stallH}" fill="rgba(110,190,240,.10)" stroke="${stCol}" stroke-width="1"/>
              <ellipse cx="${x + stallW / 2}" cy="${22 + stallH * 0.45}" rx="${stallW * 0.24}" ry="${stallH * 0.26}" fill="none" stroke="${stCol}" stroke-width="1.2"/>
              <rect x="${x + stallW / 2 - stallW * 0.18}" y="${22 + stallH * 0.68}" width="${stallW * 0.36}" height="${stallH * 0.18}" rx="1.5" fill="${stCol}" opacity=".7"/>
              <line x1="${x + 3}" y1="${22 + stallH}" x2="${x + stallW * 0.55}" y2="${22 + stallH}" stroke="${stCol}" stroke-width="1.6"/>`;
          }
        }
        // sink counter with basins along the bottom
        const sinkY = H - Math.max(12, Math.min(18, H * 0.16));
        let sinks = `<rect x="4" y="${sinkY}" width="${W - 8}" height="${H - sinkY - 3}" rx="2" fill="rgba(110,190,240,.12)" stroke="${stCol}" stroke-width="1"/>`;
        for (let x = 14; x + 10 < W - 10; x += 26)
          sinks += `<circle cx="${x}" cy="${sinkY + (H - sinkY - 3) / 2}" r="4.5" fill="none" stroke="${stCol}" stroke-width="1.3"/>`;
        // big M / F pictograms in the middle of each half
        const py = 22 + stallH + (sinkY - 22 - stallH) / 2;
        const ps = Math.max(8, Math.min(15, H * 0.13));
        const person = (cx, skirt) => `
          <circle cx="${cx}" cy="${py - ps * 0.9}" r="${ps * 0.32}" fill="${stCol}"/>
          ${skirt
            ? `<path d="M ${cx} ${py - ps * 0.5} L ${cx - ps * 0.5} ${py + ps * 0.55} L ${cx + ps * 0.5} ${py + ps * 0.55} Z" fill="${stCol}"/>`
            : `<rect x="${cx - ps * 0.3}" y="${py - ps * 0.5}" width="${ps * 0.6}" height="${ps * 1.05}" rx="${ps * 0.18}" fill="${stCol}"/>`}
          <rect x="${cx - ps * 0.22}" y="${py + ps * 0.55}" width="${ps * 0.16}" height="${ps * 0.5}" fill="${stCol}"/>
          <rect x="${cx + ps * 0.06}" y="${py + ps * 0.55}" width="${ps * 0.16}" height="${ps * 0.5}" fill="${stCol}"/>`;
        motif = `${stalls}${sinks}
          <line x1="${mid}" y1="20" x2="${mid}" y2="${sinkY - 2}" stroke="rgba(110,190,240,.8)" stroke-width="2"/>
          ${person(mid / 2, false)}${person(mid + mid / 2, true)}`;
      } else if (el.type === "office") {
        // desk (L-shape) + chair dot
        const dx = el.w * 0.14, dy = el.h * 0.38;
        motif = `<rect x="${dx}" y="${dy}" width="${el.w * 0.42}" height="10" rx="2" fill="rgba(180,150,240,.5)"/>
          <rect x="${dx}" y="${dy}" width="10" height="${el.h * 0.34}" rx="2" fill="rgba(180,150,240,.5)"/>
          <circle cx="${dx + el.w * 0.28}" cy="${dy + 24}" r="7" fill="none" stroke="rgba(180,150,240,.6)" stroke-width="1.6"/>`;
      } else if (el.type === "spare") {
        // small parts bins along the walls
        let bins = "";
        for (let x = 8; x + 22 < el.w - 6; x += 26)
          bins += `<rect x="${x}" y="24" width="22" height="14" rx="2" fill="rgba(240,170,80,.22)" stroke="rgba(240,170,80,.6)" stroke-width="0.9"/>`;
        motif = bins;
      } else if (el.type === "disposal") {
        // diagonal red hatch = restricted / outbound waste
        let hx = "";
        for (let d = 18; d < el.w + el.h; d += 26) {
          const x1 = Math.min(d, el.w), y1 = d > el.w ? d - el.w : 0;
          const x2 = d > el.h ? d - el.h : 0, y2 = Math.min(d, el.h);
          hx += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(255,120,120,.28)" stroke-width="5"/>`;
        }
        motif = hx;
      } else if (el.type === "recycle") {
        // triangular chasing-arrows motif
        const cx = el.w / 2, cy = el.h / 2 + 6, r = Math.min(el.w, el.h) * 0.22;
        const pt = a => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
        motif = `<polygon points="${pt(-Math.PI / 2)} ${pt(Math.PI / 6)} ${pt(5 * Math.PI / 6)}" fill="none" stroke="rgba(110,220,150,.6)" stroke-width="3" stroke-linejoin="round" stroke-dasharray="${r * 1.2} ${r * 0.5}"/>`;
      }
      let doors = "";
      if (["room", "office", "elec", "restroom", "spare", "disposal", "recycle"].includes(el.type)) {
        doors = (p.doors || []).map((d, i) => {
          const L = 42;
          let x = 0, y = 0, w = L, h = 8;
          if (d.side === "n") { x = d.off; y = -4; }
          else if (d.side === "s") { x = d.off; y = el.h - 4; }
          else if (d.side === "w") { x = -4; y = d.off; w = 8; h = L; }
          else { x = el.w - 4; y = d.off; w = 8; h = L; }
          return `<rect class="im-roomdoor" data-el="${el.id}" data-i="${i}" x="${x}" y="${y}" width="${w}" height="${h}" fill="rgba(90,220,140,.95)" stroke="#1d7a44" rx="2"><title>${t("Drag along the wall to reposition the door")}</title></rect>`;
        }).join("");
      }
      const areaBlink = S.blink && S.blink.areaId === el.id;
      body = `<rect ${areaBlink ? 'class="im-blink"' : ""} width="${el.w}" height="${el.h}" rx="3" fill="${fills[el.type]}" stroke="${sel ? stroke : (strokes[el.type] || stroke)}" stroke-width="${sel ? 2 : 1.2}" ${["spare", "disposal", "recycle"].includes(el.type) ? 'stroke-dasharray="7 4"' : ""}/>
        <g pointer-events="none">${motif}</g>
        <text x="6" y="18" class="im-txt">${icons[el.type]} ${esc(p.label || INVMAP_TYPES[el.type].name.toUpperCase())}</text>
        ${badges[el.type] ? `<text x="6" y="${el.h - 7}" class="im-txt xs" pointer-events="none">${badges[el.type]}</text>` : ""}${doors}`;
    } else {
      body = `<text x="0" y="16" class="im-txt lbl">${esc(p.label || "Label")}</text>`;
    }
    const H = 10, h2 = H / 2;
    const handlePts = [
      ["nw", 0, 0], ["n", el.w / 2, 0], ["ne", el.w, 0],
      ["w", 0, el.h / 2], ["e", el.w, el.h / 2],
      ["sw", 0, el.h], ["s", el.w / 2, el.h], ["se", el.w, el.h],
    ];
    const handles = sel ? handlePts.map(([dir, hx, hy]) =>
      `<rect class="im-handle im-h-${dir}" data-id="${el.id}" data-dir="${dir}" x="${hx - h2}" y="${hy - h2}" width="${H}" height="${H}" fill="var(--accent,#4da3ff)" stroke="#0b1220" stroke-width="1" rx="2"/>`).join("") + `
      <line x1="${el.w / 2}" y1="0" x2="${el.w / 2}" y2="-26" stroke="var(--accent,#4da3ff)" stroke-dasharray="3 2"/>
      <circle class="im-rot" data-id="${el.id}" cx="${el.w / 2}" cy="-32" r="9" fill="rgba(20,35,60,.9)" stroke="var(--accent,#4da3ff)" stroke-width="1.5"/>
      <text x="${el.w / 2 - 5}" y="-27.5" class="im-txt sm" pointer-events="none">⟳</text>` : "";
    return `<g class="im-el ${S.selMulti.includes(el.id) ? "im-msel" : ""}" data-id="${el.id}" transform="translate(${el.x},${el.y}) rotate(${el.rot || 0} ${el.w / 2} ${el.h / 2})">${body}${handles}</g>`;
  }

  /* ---- multi-select / group helpers ---- */
  const membersOf = ids => S.doc.elements.filter(e => ids.includes(e.id));
  const groupOf = gid => S.doc.elements.filter(e => e.grp === gid).map(e => e.id);
  const bboxOf = ids => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const el of membersOf(ids)) {
      const th = (el.rot || 0) * Math.PI / 180, c = Math.cos(th), s = Math.sin(th);
      const cx = el.x + el.w / 2, cy = el.y + el.h / 2;
      for (const [px, py] of [[el.x, el.y], [el.x + el.w, el.y], [el.x, el.y + el.h], [el.x + el.w, el.y + el.h]]) {
        const rx = cx + (px - cx) * c - (py - cy) * s, ry = cy + (px - cx) * s + (py - cy) * c;
        x0 = Math.min(x0, rx); y0 = Math.min(y0, ry); x1 = Math.max(x1, rx); y1 = Math.max(y1, ry);
      }
    }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  };
  function groupOverlay() {
    if (S.selMulti.length < 2) return "";
    const b = bboxOf(S.selMulti);
    if (!isFinite(b.x)) return "";
    const H = 10, h2 = H / 2, M = 6;
    const bx = b.x - M, by = b.y - M, bw = b.w + M * 2, bh = b.h + M * 2;
    const pts = [["nw", bx, by], ["n", bx + bw / 2, by], ["ne", bx + bw, by],
                 ["w", bx, by + bh / 2], ["e", bx + bw, by + bh / 2],
                 ["sw", bx, by + bh], ["s", bx + bw / 2, by + bh], ["se", bx + bw, by + bh]];
    const grps = new Set(membersOf(S.selMulti).map(e => e.grp || ""));
    const isGroup = grps.size === 1 && [...grps][0];
    return `<g id="im-gbox">
      <rect x="${bx}" y="${by}" width="${bw}" height="${bh}" fill="none" stroke="${isGroup ? "#7fd7a8" : "var(--accent,#4da3ff)"}" stroke-width="1.4" stroke-dasharray="6 4" pointer-events="none"/>
      <text x="${bx}" y="${by - 8}" class="im-txt sm" pointer-events="none" fill="${isGroup ? "#7fd7a8" : "#8fc2ff"}">${isGroup ? "⧉ " + t("GROUP") : "⬚"} · ${S.selMulti.length}</text>
      ${pts.map(([dir, hx, hy]) => `<rect class="im-ghandle im-h-${dir}" data-dir="${dir}" x="${hx - h2}" y="${hy - h2}" width="${H}" height="${H}" fill="${isGroup ? "#4fc98a" : "var(--accent,#4da3ff)"}" stroke="#0b1220" stroke-width="1" rx="2"/>`).join("")}
    </g>`;
  }

  function drawEls() {
    const g = $("#im-els");
    if (g) g.innerHTML = S.doc.elements.map(elSvg).join("") + groupOverlay();
  }

  /* ---- properties panel ---- */
  function drawProps() {
    const box = $("#im-props");
    if (!box) return;
    if (S.selCells.length) {
      const byRack = {};
      for (const key of S.selCells) {
        const [rid, b, l] = key.split("|");
        (byRack[rid] = byRack[rid] || []).push([+b, +l]);
      }
      box.innerHTML = `<div class="im-pal-head">${t("SLOT SELECTION")}</div>
        <div class="im-pal-note"><b>${S.selCells.length}</b> ${t("slot(s) selected across")} ${Object.keys(byRack).length} ${t("rack(s)")}.<br><br>
        ${t("Right-click for the location menu: name, split into virtual locations, purpose, or merge.")}</div>`;
      return;
    }
    if (S.selMulti.length > 1) {
      const grps = new Set(membersOf(S.selMulti).map(e => e.grp || ""));
      const isGroup = grps.size === 1 && [...grps][0];
      box.innerHTML = `<div class="im-pal-head im-props-title">${isGroup ? "⧉ " + t("GROUP") : "⬚ " + t("MULTI-SELECTION")}</div>
        <div class="im-pal-note"><b>${S.selMulti.length}</b> ${t("object(s) selected")}.<br><br>
        ${isGroup ? t("This is a grouped object — drag to move, use the handles to resize, or right-click → Ungroup.")
                  : t("Drag to move all together, use the handles to resize, or right-click → Group Together.")}</div>
        <div class="im-prop-btns">
          ${isGroup ? `<button class="btn small" id="imp-ungroup">⧉ ${t("Ungroup")}</button>`
                    : `<button class="btn small primary" id="imp-group">⧉ ${t("Group Together")}</button>`}
          <button class="btn small danger" id="imp-gdel">🗑 ${t("Remove")}</button>
        </div>`;
      const gb = $("#imp-group"); if (gb) gb.onclick = () => groupSelection();
      const ub = $("#imp-ungroup"); if (ub) ub.onclick = () => ungroupSelection();
      $("#imp-gdel").onclick = () => {
        S.doc.elements = S.doc.elements.filter(e => !S.selMulti.includes(e.id));
        S.selMulti = []; S.sel = null;
        markDirty(); drawEls(); drawProps();
      };
      return;
    }
    const el = S.doc.elements.find(e => e.id === S.sel);
    if (!el) {
      box.innerHTML = `<div class="im-pal-head">${t("PROPERTIES")}</div>
        <div class="im-pal-note">${t("Select an element, or pick a draw tool and click the canvas.")}<br><br>
        <b>${t("Racks")}</b>: ${S.doc.elements.filter(e => e.type === "rack").length} ·
        <b>${t("Locations")}</b>: ${S.doc.elements.filter(e => e.type === "rack").reduce((s, r) => s + locCodes(r).length, 0)}</div>`;
      return;
    }
    const p = el.props = el.props || {};
    const F = (lbl, id, val, type = "text") => `<label class="im-f"><span>${lbl}</span><input id="${id}" type="${type}" value="${esc(String(val ?? ""))}"></label>`;
    let fields = "";
    if (el.type === "rack") {
      fields = F(t("Aisle code"), "imp-aisle", p.aisle || "A01") + F(t("Bays"), "imp-bays", p.bays || 4, "number") +
               F(t("Levels"), "imp-levels", p.levels || 3, "number") + F(t("Lot / batch prefix"), "imp-lot", p.lot || "") +
               F(t("Rack name"), "imp-name", p.name || "");
    } else if (!["wall", "door"].includes(el.type)) {
      fields = F(t("Label"), "imp-label", p.label || "");
      if (el.type === "zone" || el.type === "subzone") fields += F(t("Fill color"), "imp-color", p.color || "");
    }
    const isRoomLike = ["room", "office", "elec", "restroom", "spare", "disposal", "recycle"].includes(el.type);
    const sec = (title, inner, open = true) => `<div class="im-sec ${open ? "open" : ""}">
      <button class="im-sec-h" type="button"><span class="im-sec-tri">▸</span>${title}</button>
      <div class="im-sec-b">${inner}</div></div>`;
    const TF = (lbl, id, val) => `<label class="im-tf"><span>${lbl}</span><input id="${id}" type="number" step="${INVMAP_GRID}" value="${val}"></label>`;
    box.innerHTML = `<div class="im-pal-head im-props-title">${INVMAP_TYPES[el.type].ico} ${t(INVMAP_TYPES[el.type].name).toUpperCase()}</div>
      ${sec("⇱ " + t("TRANSFORM"), `<div class="im-tf-grid">
        ${TF("X", "imp-x", el.x)}${TF("Y", "imp-y", el.y)}
        ${TF("W", "imp-w", el.w)}${TF("H", "imp-h", el.h)}
        <label class="im-tf"><span>∠</span><input id="imp-r" type="number" step="15" value="${el.rot || 0}"></label>
        <button class="btn small" id="imp-rot" title="${t("Rotate 90°")}">⟳ 90°</button>
      </div>`)}
      ${fields ? sec("🏷 " + t("IDENTIFICATION"), fields) : ""}
      ${sec("⚙ " + t("ACTIONS"), `<div class="im-prop-btns">
        <button class="btn small" id="imp-dup">⧉ ${t("Duplicate")}</button>
        ${isRoomLike ? `<button class="btn small" id="imp-door">🚪 + ${t("Door")}</button>` : ""}
        <button class="btn small danger" id="imp-del">🗑 ${t("Remove")}</button>
      </div>`)}
      ${el.type === "rack" ? sec("📍 " + t("WMS ADDRESSING"), `<div class="im-pal-note">${t("Addressable locations")}: <b>${locCodes(el).length}</b><br>
        <span style="font-family:Consolas,monospace;font-size:10.5px">${locCodes(el).slice(0, 6).map(esc).join("<br>")}${locCodes(el).length > 6 ? "<br>…" : ""}</span><br><br>
        ${t("Click a slot to select it · Ctrl+click = multi · right-click = menu")}</div>`) : ""}
      ${isRoomLike && (p.doors || []).length ? `<div class="im-pal-note" style="margin-top:6px">🚪 ${(p.doors || []).length} ${t("door(s) — drag them along the walls")}</div>` : ""}`;
    box.querySelectorAll(".im-sec-h").forEach(h => h.onclick = () => h.parentElement.classList.toggle("open"));
    const bindF = (id, key, num) => { const i = $("#" + id); if (i) i.oninput = () => { p[key] = num ? +i.value : i.value; markDirty(); drawEls(); }; };
    bindF("imp-aisle", "aisle"); bindF("imp-bays", "bays", 1); bindF("imp-levels", "levels", 1);
    bindF("imp-lot", "lot"); bindF("imp-label", "label"); bindF("imp-color", "color"); bindF("imp-name", "name");
    const bindT = (id, key, min) => { const i = $("#" + id); if (i) i.onchange = () => {
      let v = Math.round(+i.value / (key === "rot" ? 1 : INVMAP_GRID)) * (key === "rot" ? 1 : INVMAP_GRID);
      if (min !== undefined) v = Math.max(min, v);
      if (key === "rot") v = ((v % 360) + 360) % 360;
      el[key] = v; i.value = v; markDirty(); drawEls();
    }; };
    bindT("imp-x", "x"); bindT("imp-y", "y"); bindT("imp-w", "w", INVMAP_GRID); bindT("imp-h", "h", INVMAP_GRID); bindT("imp-r", "rot");
    $("#imp-rot").onclick = () => { el.rot = ((el.rot || 0) + 90) % 360; markDirty(); drawEls(); drawProps(); };
    const doorBtn = $("#imp-door");
    if (doorBtn) doorBtn.onclick = () => {
      (p.doors = p.doors || []).push({ side: "s", off: Math.max(0, el.w / 2 - 21) });
      markDirty(); drawEls(); drawProps();
    };
    $("#imp-dup").onclick = () => {
      const c = JSON.parse(JSON.stringify(el)); c.id = "e" + Date.now(); c.x += INVMAP_GRID * 2; c.y += INVMAP_GRID * 2;
      S.doc.elements.push(c); S.sel = c.id; markDirty(); drawEls(); drawProps();
    };
    $("#imp-del").onclick = () => {
      S.doc.elements = S.doc.elements.filter(e => e.id !== el.id); S.sel = null;
      markDirty(); drawEls(); drawProps();
    };
  }

  /* ---- right-click context menu (rack / bay / level / lot slots) ---- */
  function invMapTutorial(S2, boot2, curMeta) {
    const steps = [
      { ico: "🏭", title: t("1 · Concepts — how the map is organized"), body: `
        <p>${t("The Facility & Inventory Map is a WMS-grade addressing system. Every physical storage position gets one unique location code that the entire platform (Asset Registration, Inventory, Inbound, Audit) can reference.")}</p>
        <table class="im-tut-tbl"><tr><th>${t("Level")}</th><th>${t("Example")}</th><th>${t("Meaning")}</th></tr>
        <tr><td>${t("Warehouse")}</td><td>Warehouse 1</td><td>${t("A physical building")}</td></tr>
        <tr><td>${t("Zone")}</td><td>Zone A</td><td>${t("One map = one zone of a warehouse")}</td></tr>
        <tr><td>${t("Rack / Aisle")}</td><td>A01</td><td>${t("A rack with its aisle code")}</td></tr>
        <tr><td>${t("Bay")}</td><td>02</td><td>${t("Column position inside the rack")}</td></tr>
        <tr><td>${t("Level")}</td><td>L3</td><td>${t("Shelf height (L1 = floor)")}</td></tr></table>
        <p class="im-tut-ex">📍 ${t("Full location code")}: <b>Warehouse 1 · Zone A · A01-02-L3</b></p>` },
      { ico: "🗺", title: t("2 · Create a warehouse & zone"), body: `
        <ol><li>${t("Click")} <b>+ ${t("Zone / warehouse")}</b> ${t("in the top toolbar.")}</li>
        <li>${t("Enter the warehouse name (e.g. “Warehouse 1”) and the zone (e.g. “Zone A — Dry Storage”).")}</li>
        <li>${t("Each zone is a separate drawing. Switch between them with the selector at the top left.")}</li></ol>
        <p class="im-tut-ex">💡 ${t("Recommended: one zone per fire section or per operational area (Dry, Chilled, Frozen, Returns).")}</p>` },
      { ico: "🧱", title: t("3 · Draw the building structure"), body: `
        <ol><li>${t("Pick")} <b>🧱 ${t("Wall")}</b> ${t("from the toolbox and click the canvas to place segments — drag the side handles to stretch them into the building outline.")}</li>
        <li>${t("Add")} <b>🚪 ${t("Rooms / Office / Electrical / Restroom")}</b> — ${t("then press")} <b>🚪 + ${t("Door")}</b> ${t("in the Properties panel and drag the door along a wall.")}</li>
        <li>${t("Place")} <b>🟩 ${t("Entrance")}</b>, <b>🟥 ${t("Exit")}</b> ${t("and")} <b>🛣 ${t("Roads")}</b> ${t("for forklift traffic flow.")}</li></ol>
        <p class="im-tut-ex">📐 ${t("Grid scale: 1 square ≈ 0.5 m. Everything snaps to the grid.")}</p>` },
      { ico: "🗄", title: t("4 · Place & configure racks"), body: `
        <ol><li>${t("Pick")} <b>🗄 ${t("Rack")}</b> ${t("and click where the rack stands.")}</li>
        <li>${t("In Properties → IDENTIFICATION set:")} <b>${t("Aisle code")}</b> (A01), <b>${t("Bays")}</b> (4), <b>${t("Levels")}</b> (3), <b>${t("Lot / batch prefix")}</b>.</li>
        <li>${t("The rack instantly renders every bay × level slot with its code — a 4-bay × 3-level rack = 12 addressable locations (A01-01-L1 … A01-04-L3).")}</li></ol>
        <p class="im-tut-ex">💡 ${t("Duplicate a configured rack (⧉ or right-click) — the aisle code auto-increments: A01 → A02.")}</p>` },
      { ico: "🏷", title: t("5 · Name, split, merge & purpose slots"), body: `
        <p><b>${t("Right-click any slot")}:</b></p>
        <ul><li><b>🏷 ${t("Name this location")}</b> — ${t("give it a human name (“Tomato Sauce Pallets”). The name shows on the map.")}</li>
        <li><b>⧈ ${t("Split into Virtual Locations")}</b> — ${t("one physical slot becomes A01-02-L3-V1 … -Vn for mixed-SKU shelves.")}</li>
        <li><b>⚙ ${t("Purpose")}</b> — ${t("mark a slot for non-storage use (charging, QC hold, tools).")}</li>
        <li><b>⧉ ${t("Merge")}</b> — ${t("Ctrl+click several slots, right-click → Merge: one code spans multiple bays (oversized pallets).")}</li></ul>` },
      { ico: "🔗", title: t("6 · Link with Asset Registration & Inventory"), body: `
        <ol><li>${t("In Asset Registration, the “Storage location” field offers every map code — or press the 🗺️ button to pick from a grouped list.")}</li>
        <li>${t("Stored records render the location as a")} <b>📍 ${t("link")}</b>.</li>
        <li>${t("Clicking the link opens the map, zooms to the rack and blinks the exact slot with a banner (Warehouse · Zone · Rack · Bay · Level).")}</li></ol>
        <p class="im-tut-ex">✅ ${t("This gives every worker turn-by-turn findability for any asset in the facility.")}</p>` },
      { ico: "⌨", title: t("7 · Toolbox & shortcuts"), body: `
        <table class="im-tut-tbl"><tr><th>${t("Action")}</th><th>${t("How")}</th></tr>
        <tr><td>${t("Zoom")}</td><td>${t("Mouse wheel (to cursor)")}</td></tr>
        <tr><td>${t("Pan")}</td><td>${t("Space + drag, or middle button")}</td></tr>
        <tr><td>${t("Move")}</td><td>${t("Drag, or arrow keys")}</td></tr>
        <tr><td>${t("Resize")}</td><td>${t("8 handles · Shift = keep aspect · Alt = from center")}</td></tr>
        <tr><td>${t("Rotate")}</td><td>${t("Drag ⟳ handle (15° snap) or R key")}</td></tr>
        <tr><td>${t("Undo / Redo")}</td><td>Ctrl+Z / Ctrl+Y</td></tr>
        <tr><td>${t("Delete")}</td><td>Del</td></tr>
        <tr><td>${t("Multi-select slots")}</td><td>Ctrl + ${t("click")}</td></tr></table>` },
      { ico: "🖼", title: t("8 · Save, export & audit"), body: `
        <ul><li>${t("Autosave runs 2 s after every change — the LED at the top right shows the state.")}</li>
        <li><b>🖼 ${t("Export JPG")}</b> ${t("produces a print-grade drawing with an ISO 9001 §7.1.3 title block for posting at the facility entrance.")}</li>
        <li><b>📍 ${t("Location schedule")}</b> ${t("lists every addressable code for cycle-count sheets.")}</li>
        <li>${t("Every create / update / delete of a map is written to the immutable audit chain.")}</li></ul>
        <p class="im-tut-ex">🎓 ${t("Press “Load example layout” below to insert a complete worked example (building, rooms, racks A01–A03, dock, staging) into this zone — then explore it.")}</p>` },
    ];
    let step = 0;
    modal("🎓 " + t("Inventory Map — Operator Tutorial"), `<div id="im-tut-box"></div>`, null);
    const render = () => {
      const bx = $("#im-tut-box"); if (!bx) return;
      const s = steps[step];
      bx.innerHTML = `<div class="im-tut-steps">${steps.map((x, i) =>
          `<button class="im-tut-dot ${i === step ? "on" : i < step ? "done" : ""}" data-i="${i}" title="${esc(x.title)}">${x.ico}</button>`).join("")}</div>
        <div class="im-tut-title">${esc(s.title)}</div>
        <div class="im-tut-body">${s.body}</div>
        <div class="im-tut-nav">
          <button class="btn small" id="im-tut-prev" ${step === 0 ? "disabled" : ""}>← ${t("Back")}</button>
          <span class="im-tut-pg">${step + 1} / ${steps.length}</span>
          ${step === steps.length - 1
            ? `<button class="btn small primary" id="im-tut-ex-btn">📦 ${t("Load example layout")}</button>`
            : `<button class="btn small primary" id="im-tut-next">${t("Next")} →</button>`}
        </div>`;
      bx.querySelectorAll(".im-tut-dot").forEach(d => d.onclick = () => { step = +d.dataset.i; render(); });
      const pv = $("#im-tut-prev"); if (pv) pv.onclick = () => { step = Math.max(0, step - 1); render(); };
      const nx = $("#im-tut-next"); if (nx) nx.onclick = () => { step = Math.min(steps.length - 1, step + 1); render(); };
      const exb = $("#im-tut-ex-btn"); if (exb) exb.onclick = async () => {
        if (S2.doc.elements.length && !confirm(t("This zone already has elements. Add the example layout on top of them?"))) return;
        loadExampleLayout();
        $("#modal-root").innerHTML = "";
        toast("📦 " + t("Example layout loaded — explore the racks, right-click the slots, then try Export JPG."));
      };
    };
    function loadExampleLayout() {
      const G = INVMAP_GRID; let n = Date.now();
      const mk = (type, x, y, w, h, props = {}, rot = 0) => ({ id: "e" + (n++), type, x: x * G, y: y * G, w: w * G, h: h * G, rot, props });
      const ex = [
        mk("wall", 2, 2, 46, 1), mk("wall", 2, 30, 46, 1), mk("wall", 2, 2, 1, 29), mk("wall", 47, 2, 1, 29),
        mk("entrance", 20, 30, 6, 1, { label: t("Main Entrance") }),
        mk("exit", 42, 2, 5, 1, { label: t("Emergency Exit") }),
        mk("road", 3, 15, 44, 4, { label: t("Forklift Lane") }),
        mk("office", 3, 3, 8, 6, { label: t("Shift Office"), doors: [{ side: "s", off: 60 }] }),
        mk("elec", 3, 24, 5, 5, { label: t("Electrical"), doors: [{ side: "e", off: 30 }] }),
        mk("restroom", 42, 24, 5, 5, { label: t("Restroom"), doors: [{ side: "w", off: 30 }] }),
        mk("dock", 3, 10, 6, 4, { label: t("Dock D1") }),
        mk("staging", 10, 10, 8, 4, { label: t("Inbound Staging") }),
        mk("bench", 40, 10, 6, 3, { label: t("QC Bench") }),
        mk("zone", 13, 3, 33, 6, { label: t("DRY STORAGE"), color: "rgba(90,160,255,.06)" }),
        mk("rack", 14, 4, 10, 4, { aisle: "A01", bays: 5, levels: 3, lot: "LOT-A", name: t("Dry Goods") }),
        mk("rack", 26, 4, 10, 4, { aisle: "A02", bays: 5, levels: 3, lot: "LOT-A" }),
        mk("rack", 14, 21, 10, 4, { aisle: "A03", bays: 5, levels: 4, lot: "LOT-B", name: t("Beverages") }),
        mk("subzone", 26, 20, 14, 7, { label: t("RETURNS HOLD"), color: "rgba(255,180,80,.07)" }),
        mk("label", 20, 12, 8, 2, { label: t("Receiving") }),
      ];
      S2.doc.elements.push(...ex);
      markDirty(); drawEls(); drawProps();
      setTimeout(() => $("#im-zfit")?.click(), 50);
    }
    render();
  }

  function closeCtx() { const m = $("#im-ctx"); if (m) m.remove(); }
  function openCtx(evt, items) {
    closeCtx();
    const m = document.createElement("div");
    m.id = "im-ctx"; m.className = "im-ctx";
    m.innerHTML = items.map((it, i) => it === "-" ? `<div class="im-ctx-sep"></div>`
      : `<button class="im-ctx-it" data-i="${i}">${it.ico || ""} ${esc(it.label)}</button>`).join("");
    document.body.appendChild(m);
    const mw = 260;
    m.style.left = Math.min(evt.clientX, innerWidth - mw - 8) + "px";
    m.style.top = Math.min(evt.clientY, innerHeight - m.offsetHeight - 8) + "px";
    m.querySelectorAll(".im-ctx-it").forEach(b => b.onclick = () => { closeCtx(); const it = items[+b.dataset.i]; if (it.fn) it.fn(); });
    setTimeout(() => document.addEventListener("pointerdown", function h(e) {
      if (!m.contains(e.target)) { closeCtx(); document.removeEventListener("pointerdown", h); }
    }), 0);
  }

  const cellOf = key => {
    const [rid, b, l] = key.split("|");
    const rack = S.doc.elements.find(e => e.id === rid);
    if (!rack) return null;
    const p = rack.props = rack.props || {};
    p.cells = p.cells || {};
    return { rack, p, k: cellKey(b, l), cell: p.cells[cellKey(b, l)] = p.cells[cellKey(b, l)] || {}, b: +b, l: +l };
  };
  const baseCode = c => `${c.p.aisle || "A01"}-${String(c.b).padStart(2, "0")}-L${c.l}`;

  function ctxForCells(evt) {
    const multi = S.selCells.length > 1;
    if (multi) {
      openCtx(evt, [
        { ico: "⧉", label: t("Merge") + ` (${S.selCells.length} ${t("slots")})`, fn: () => {
          const name = prompt(t("Merged location name (one location code for all selected slots):"),
            baseCode(cellOf(S.selCells[0])) + "-MRG");
          if (name === null) return;
          const gid = "m" + Date.now();
          const perRack = {};
          for (const key of S.selCells) (perRack[key.split("|")[0]] = perRack[key.split("|")[0]] || []).push(key);
          for (const [rid, keys] of Object.entries(perRack)) {
            const rack = S.doc.elements.find(e => e.id === rid);
            const p = rack.props = rack.props || {};
            p.merges = p.merges || {};
            p.merges[gid] = { name: name.trim(), cells: keys.map(k => k.split("|").slice(1).join("|")) };
            for (const key of keys) {
              const c = cellOf(key);
              delete c.cell.virt;
              c.cell.merge = gid;
            }
          }
          S.selCells = [];
          markDirty(); drawEls(); drawProps();
          toast("⧉ " + t("Slots merged into one location"));
        } },
        "-",
        { ico: "✖", label: t("Clear selection"), fn: () => { S.selCells = []; drawEls(); drawProps(); } },
      ]);
      return;
    }
    const c = cellOf(S.selCells[0]);
    if (!c) return;
    const code = c.cell.name || baseCode(c);
    openCtx(evt, [
      { ico: "🏷️", label: t("Name this location"), fn: () => {
        const v = prompt(t("Location name / code:"), c.cell.name || baseCode(c));
        if (v === null) return;
        c.cell.name = v.trim();
        if (!c.cell.name) delete c.cell.name;
        markDirty(); drawEls(); drawProps();
      } },
      { ico: "⧈", label: t("Split into more Virtual Locations"), fn: () => {
        const v = prompt(t("Number of virtual locations for") + ` ${code} (2–50):`, String(c.cell.virt || 2));
        if (v === null) return;
        const n = Math.max(1, Math.min(50, +v || 1));
        if (n > 1) c.cell.virt = n; else delete c.cell.virt;
        delete c.cell.merge;
        markDirty(); drawEls(); drawProps();
        toast("⧈ " + code + " → " + n + " " + t("virtual location(s)"));
      } },
      { ico: "⚙", label: t("For other operation Purpose"), fn: () => {
        const v = prompt(t("Operational purpose (e.g. QC hold, staging, returns, damaged, empty-pallet):"), c.cell.purpose || "");
        if (v === null) return;
        c.cell.purpose = v.trim();
        if (!c.cell.purpose) delete c.cell.purpose;
        markDirty(); drawEls(); drawProps();
      } },
      "-",
      ...(c.cell.merge ? [{ ico: "✂", label: t("Unmerge"), fn: () => {
        const gid = c.cell.merge, merges = c.p.merges || {};
        for (const k of Object.keys(c.p.cells)) if (c.p.cells[k].merge === gid) delete c.p.cells[k].merge;
        delete merges[gid];
        markDirty(); drawEls(); drawProps();
      } }] : []),
      { ico: "♻", label: t("Reset slot"), fn: () => {
        delete c.p.cells[c.k];
        markDirty(); drawEls(); drawProps();
      } },
    ]);
  }

  function dupEl(el) {
    const c = JSON.parse(JSON.stringify(el));
    c.id = "e" + Date.now();
    c.x += INVMAP_GRID * 2; c.y += INVMAP_GRID * 2;
    if (c.type === "rack" && c.props && c.props.aisle) {
      const mm = /^([A-Za-z]+)(\d+)$/.exec(c.props.aisle);
      if (mm) c.props.aisle = mm[1] + String(+mm[2] + 1).padStart(mm[2].length, "0");
    }
    S.doc.elements.push(c);
    S.sel = c.id; S.selCells = [];
    markDirty(); drawEls(); drawProps();
    toast("⧉ " + t("Duplicated"));
  }

  function ctxForRack(evt, el) {
    const p = el.props = el.props || {};
    openCtx(evt, [
      { ico: "🏷️", label: t("Name this location"), fn: () => {
        const v = prompt(t("Rack name:"), p.name || p.aisle || "A01");
        if (v === null) return;
        p.name = v.trim(); if (!p.name) delete p.name;
        markDirty(); drawEls(); drawProps();
      } },
      { ico: "⧈", label: t("Split into more Virtual Locations"), fn: () => {
        const b = prompt(t("Bays:"), String(p.bays || 4)); if (b === null) return;
        const l = prompt(t("Levels:"), String(p.levels || 3)); if (l === null) return;
        p.bays = Math.max(1, Math.min(60, +b || 1)); p.levels = Math.max(1, Math.min(15, +l || 1));
        markDirty(); drawEls(); drawProps();
      } },
      { ico: "⚙", label: t("For other operation Purpose"), fn: () => {
        const v = prompt(t("Operational purpose for the whole rack:"), p.purpose || "");
        if (v === null) return;
        p.purpose = v.trim(); if (!p.purpose) delete p.purpose;
        markDirty(); drawEls(); drawProps();
      } },
      "-",
      { ico: "⧉", label: t("Duplicate"), fn: () => dupEl(el) },
      { ico: "🗑", label: t("Remove"), fn: () => {
        S.doc.elements = S.doc.elements.filter(e => e.id !== el.id); S.sel = null; S.selCells = [];
        markDirty(); drawEls(); drawProps();
      } },
    ]);
  }

  function groupSelection() {
    if (S.selMulti.length < 2) return;
    const gid = "g" + Date.now();
    for (const el of membersOf(S.selMulti)) el.grp = gid;
    markDirty(); drawEls(); drawProps();
    toast("⧉ " + t("Grouped") + ` (${S.selMulti.length})`);
  }
  function ungroupSelection() {
    for (const el of membersOf(S.selMulti)) delete el.grp;
    markDirty(); drawEls(); drawProps();
    toast("⧉ " + t("Ungrouped"));
  }
  function ctxForMulti(evt) {
    const grps = new Set(membersOf(S.selMulti).map(e => e.grp || ""));
    const isGroup = grps.size === 1 && [...grps][0];
    openCtx(evt, [
      isGroup
        ? { ico: "⧉", label: t("Ungroup"), fn: ungroupSelection }
        : { ico: "⧉", label: t("Group Together") + ` (${S.selMulti.length})`, fn: groupSelection },
      "-",
      { ico: "🗑", label: t("Remove"), fn: () => {
        S.doc.elements = S.doc.elements.filter(e => !S.selMulti.includes(e.id));
        S.selMulti = []; S.sel = null;
        markDirty(); drawEls(); drawProps();
      } },
    ]);
  }

  function ctxForObject(evt, el) {
    const p = el.props = el.props || {};
    const canLabel = !(["wall", "door"].includes(el.type));
    openCtx(evt, [
      ...(canLabel ? [{ ico: "🏷️", label: t("Name this location"), fn: () => {
        const v = prompt(t("Label:"), p.label || "");
        if (v === null) return;
        p.label = v.trim(); if (!p.label) delete p.label;
        markDirty(); drawEls(); drawProps();
      } }] : []),
      { ico: "⧉", label: t("Duplicate"), fn: () => dupEl(el) },
      { ico: "⟳", label: t("Rotate 90°"), fn: () => { el.rot = ((el.rot || 0) + 90) % 360; markDirty(); drawEls(); drawProps(); } },
      "-",
      { ico: "🗑", label: t("Remove"), fn: () => {
        S.doc.elements = S.doc.elements.filter(e => e.id !== el.id); S.sel = null; S.selCells = [];
        markDirty(); drawEls(); drawProps();
      } },
    ]);
  }

  /* ---- canvas interaction: draw, move, resize, rotate-by-drag, pan, zoom ---- */
  function bindCanvas() {
    const svg = $("#im-svg"), wrap = $("#im-wrap");
    if (!svg) return;
    const toSvg = evt => {
      const r = svg.getBoundingClientRect();
      return { x: S.vb.x + (evt.clientX - r.left) * S.vb.w / r.width,
               y: S.vb.y + (evt.clientY - r.top) * S.vb.h / r.height };
    };
    let drag = null;
    svg.addEventListener("wheel", evt => {
      evt.preventDefault();
      const f = evt.deltaY < 0 ? 0.85 : 1.18;
      const pos = toSvg(evt);
      const nw = Math.min(40000, Math.max(200, S.vb.w * f));
      const k = nw / S.vb.w;
      S.vb.x = pos.x - (pos.x - S.vb.x) * k;
      S.vb.y = pos.y - (pos.y - S.vb.y) * k;
      S.vb.w = nw; S.vb.h = S.vb.h * k;
      applyVb();
    }, { passive: false });
    svg.oncontextmenu = evt => {
      evt.preventDefault();
      const cellEl = evt.target.closest(".im-cell");
      const g = evt.target.closest(".im-el");
      // multi-selection (marquee) or grouped object → group menu
      if (S.selMulti.length > 1 && (!g || S.selMulti.includes(g.dataset.id))) { ctxForMulti(evt); return; }
      if (g) {
        const hit = S.doc.elements.find(e => e.id === g.dataset.id);
        if (hit && hit.grp) {
          S.selMulti = groupOf(hit.grp); S.sel = null; S.selCells = [];
          drawEls(); drawProps(); ctxForMulti(evt); return;
        }
      }
      if (cellEl) {
        const key = cellEl.dataset.rack + "|" + cellEl.dataset.bay + "|" + cellEl.dataset.level;
        if (!S.selCells.includes(key)) { S.selCells = evt.ctrlKey ? [...S.selCells, key] : [key]; drawEls(); drawProps(); }
        ctxForCells(evt);
        return;
      }
      if (g) {
        const el = S.doc.elements.find(e => e.id === g.dataset.id);
        if (el && el.type === "rack") { S.sel = el.id; drawEls(); ctxForRack(evt, el); return; }
        if (el) { S.sel = el.id; S.selCells = []; drawEls(); drawProps(); ctxForObject(evt, el); }
      }
    };
    svg.onpointerdown = evt => {
      if (evt.button === 2) return;
      closeCtx();
      const pos = toSvg(evt);
      // pan: space held or middle button
      if (S.space || evt.button === 1) {
        drag = { mode: "pan", cx: evt.clientX, cy: evt.clientY, vx: S.vb.x, vy: S.vb.y };
        svg.setPointerCapture(evt.pointerId);
        wrap.classList.add("im-panning");
        evt.preventDefault();
        return;
      }
      const h = evt.target.closest(".im-handle");
      const gh = evt.target.closest(".im-ghandle");
      const rot = evt.target.closest(".im-rot");
      const gear = evt.target.closest(".im-gear");
      const doorEl = evt.target.closest(".im-roomdoor");
      const cellEl = evt.target.closest(".im-cell");
      const g = evt.target.closest(".im-el");
      // group bounding-box resize handle
      if (gh && S.selMulti.length > 1) {
        const b = bboxOf(S.selMulti);
        drag = { mode: "gresize", dir: gh.dataset.dir || "se", sx: pos.x, sy: pos.y, b0: b,
                 rel: membersOf(S.selMulti).map(el => ({ el,
                   fx: (el.x - b.x) / Math.max(1, b.w), fy: (el.y - b.y) / Math.max(1, b.h),
                   fw: el.w / Math.max(1, b.w), fh: el.h / Math.max(1, b.h) })) };
        svg.setPointerCapture(evt.pointerId);
        return;
      }
      if (gear) {
        S.sel = gear.dataset.id; S.selCells = [];
        drawEls(); drawProps();
        const pane = $("#im-props");
        if (pane) { pane.classList.add("im-flash"); setTimeout(() => pane.classList.remove("im-flash"), 900); }
        return;
      }
      if (rot) {
        const el = S.doc.elements.find(e => e.id === rot.dataset.id);
        drag = { mode: "rotate", el };
        svg.setPointerCapture(evt.pointerId);
        return;
      }
      if (h) {
        const el = S.doc.elements.find(e => e.id === h.dataset.id);
        drag = { mode: "resize", el, dir: h.dataset.dir || "se", sx: pos.x, sy: pos.y,
                 x0: el.x, y0: el.y, w0: el.w, h0: el.h };
        svg.setPointerCapture(evt.pointerId);
        return;
      }
      if (doorEl) {
        const el = S.doc.elements.find(e => e.id === doorEl.dataset.el);
        drag = { mode: "door", el, i: +doorEl.dataset.i };
        svg.setPointerCapture(evt.pointerId);
        return;
      }
      if (S.tool === "select") {
        if (cellEl) {
          const rackEl = S.doc.elements.find(e => e.id === cellEl.dataset.rack);
          // rack inside a group → move the whole group instead of slot-select
          if (rackEl && rackEl.grp && !evt.ctrlKey && !evt.metaKey) {
            S.selMulti = groupOf(rackEl.grp); S.sel = null; S.selCells = [];
            drag = { mode: "gmove", sx: pos.x, sy: pos.y,
                     orig: membersOf(S.selMulti).map(m => ({ el: m, x0: m.x, y0: m.y })) };
            svg.setPointerCapture(evt.pointerId);
            drawEls(); drawProps();
            return;
          }
          const key = cellEl.dataset.rack + "|" + cellEl.dataset.bay + "|" + cellEl.dataset.level;
          if (evt.ctrlKey || evt.metaKey) {
            S.selCells = S.selCells.includes(key) ? S.selCells.filter(k => k !== key) : [...S.selCells, key];
          } else {
            S.selCells = [key];
          }
          S.sel = cellEl.dataset.rack;
          // still allow moving the rack by dragging a cell (without ctrl)
          if (!evt.ctrlKey && !evt.metaKey) {
            const el = S.doc.elements.find(e => e.id === cellEl.dataset.rack);
            drag = { mode: "move", el, sx: pos.x, sy: pos.y, x0: el.x, y0: el.y, moved: false };
            svg.setPointerCapture(evt.pointerId);
          }
          drawEls(); drawProps();
          return;
        }
        if (g) {
          const el = S.doc.elements.find(e => e.id === g.dataset.id);
          // clicking a member of the current multi-selection, or any grouped
          // element, moves the whole set together
          if (el.grp && !S.selMulti.includes(el.id)) { S.selMulti = groupOf(el.grp); S.sel = null; S.selCells = []; }
          if (S.selMulti.length > 1 && S.selMulti.includes(el.id)) {
            drag = { mode: "gmove", sx: pos.x, sy: pos.y,
                     orig: membersOf(S.selMulti).map(m => ({ el: m, x0: m.x, y0: m.y })) };
            svg.setPointerCapture(evt.pointerId);
            drawEls(); drawProps();
            return;
          }
          S.sel = el.id; S.selCells = []; S.selMulti = [];
          drag = { mode: "move", el, sx: pos.x, sy: pos.y, x0: el.x, y0: el.y };
          svg.setPointerCapture(evt.pointerId);
        } else {
          // empty canvas → start a marquee (rubber-band) selection
          S.sel = null; S.selCells = []; S.selMulti = [];
          drag = { mode: "marquee", sx: pos.x, sy: pos.y };
          svg.setPointerCapture(evt.pointerId);
        }
        drawEls(); drawProps();
        return;
      }
      // draw tool → place a new element
      const d = INVMAP_TYPES[S.tool];
      if (!d) return;
      const el = { id: "e" + Date.now(), type: S.tool, x: snap(pos.x - d.w / 2), y: snap(pos.y - d.h / 2), w: d.w, h: d.h, rot: 0, props: {} };
      if (S.tool === "rack") {
        const n = S.doc.elements.filter(e => e.type === "rack").length + 1;
        el.props = { aisle: "A" + String(n).padStart(2, "0"), bays: 4, levels: 3, lot: "" };
      }
      if (S.tool === "room") el.props = { label: "ROOM", doors: [{ side: "s", off: Math.max(0, d.w / 2 - 21) }] };
      S.doc.elements.push(el);
      S.sel = el.id; S.selCells = []; S.tool = "select";
      markDirty(); draw();
    };
    svg.onpointermove = evt => {
      if (!drag) return;
      const pos = toSvg(evt);
      if (drag.mode === "pan") {
        const r = svg.getBoundingClientRect();
        S.vb.x = drag.vx - (evt.clientX - drag.cx) * S.vb.w / r.width;
        S.vb.y = drag.vy - (evt.clientY - drag.cy) * S.vb.h / r.height;
        applyVb();
        return;
      }
      if (drag.mode === "rotate") {
        const cx = drag.el.x + drag.el.w / 2, cy = drag.el.y + drag.el.h / 2;
        let a = Math.atan2(pos.y - cy, pos.x - cx) * 180 / Math.PI + 90;
        a = Math.round(a / 15) * 15;
        drag.el.rot = ((a % 360) + 360) % 360;
        drawEls();
        return;
      }
      if (drag.mode === "door") {
        const el = drag.el, p = el.props || {}, d = (p.doors || [])[drag.i];
        if (!d) return;
        // local coords (ignore rotation for door placement)
        const lx = pos.x - el.x, ly = pos.y - el.y;
        const dists = { n: Math.abs(ly), s: Math.abs(ly - el.h), w: Math.abs(lx), e: Math.abs(lx - el.w) };
        d.side = Object.keys(dists).reduce((a, b) => dists[a] < dists[b] ? a : b);
        const L = 42;
        if (d.side === "n" || d.side === "s") d.off = Math.max(0, Math.min(el.w - L, lx - L / 2));
        else d.off = Math.max(0, Math.min(el.h - L, ly - L / 2));
        drawEls();
        return;
      }
      if (drag.mode === "marquee") {
        const x = Math.min(drag.sx, pos.x), y = Math.min(drag.sy, pos.y);
        const w = Math.abs(pos.x - drag.sx), hgt = Math.abs(pos.y - drag.sy);
        drag.rect = { x, y, w, h: hgt };
        let mq = svg.querySelector("#im-marquee");
        if (!mq) {
          mq = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          mq.id = "im-marquee";
          mq.setAttribute("fill", "rgba(77,163,255,.10)");
          mq.setAttribute("stroke", "var(--accent,#4da3ff)");
          mq.setAttribute("stroke-width", "1.2");
          mq.setAttribute("stroke-dasharray", "5 3");
          svg.appendChild(mq);
        }
        mq.setAttribute("x", x); mq.setAttribute("y", y);
        mq.setAttribute("width", w); mq.setAttribute("height", hgt);
        return;
      }
      if (drag.mode === "gmove") {
        const dx = snap(pos.x - drag.sx), dy = snap(pos.y - drag.sy);
        for (const o of drag.orig) { o.el.x = o.x0 + dx; o.el.y = o.y0 + dy; }
        drawEls();
        return;
      }
      if (drag.mode === "gresize") {
        const dir = drag.dir, b0 = drag.b0;
        const dx = pos.x - drag.sx, dy = pos.y - drag.sy;
        let nx = b0.x, ny = b0.y, nw = b0.w, nh = b0.h;
        const minB = 40;
        if (dir.includes("e")) nw = Math.max(minB, b0.w + dx);
        if (dir.includes("s")) nh = Math.max(minB, b0.h + dy);
        if (dir.includes("w")) { nw = Math.max(minB, b0.w - dx); nx = b0.x + (b0.w - nw); }
        if (dir.includes("n")) { nh = Math.max(minB, b0.h - dy); ny = b0.y + (b0.h - nh); }
        if (evt.shiftKey && dir.length === 2) {
          const ar = b0.w / Math.max(1, b0.h);
          if (Math.abs(nw - b0.w) >= Math.abs(nh - b0.h) * ar) nh = Math.max(minB, Math.round(nw / ar));
          else nw = Math.max(minB, Math.round(nh * ar));
          if (dir.includes("w")) nx = b0.x + (b0.w - nw);
          if (dir.includes("n")) ny = b0.y + (b0.h - nh);
        }
        for (const r of drag.rel) {
          r.el.x = Math.round(nx + r.fx * nw); r.el.y = Math.round(ny + r.fy * nh);
          r.el.w = Math.max(10, Math.round(r.fw * nw)); r.el.h = Math.max(10, Math.round(r.fh * nh));
        }
        drawEls();
        return;
      }
      if (drag.mode === "move") {
        const nx = snap(drag.x0 + pos.x - drag.sx), ny = snap(drag.y0 + pos.y - drag.sy);
        if (nx !== drag.el.x || ny !== drag.el.y) drag.moved = true;
        drag.el.x = nx; drag.el.y = ny;
      } else if (drag.mode === "resize") {
        const d = INVMAP_TYPES[drag.el.type];
        const dir = drag.dir, el = drag.el;
        // rotate the pointer delta into the element's local frame so the
        // horizontal / vertical (E·W·N·S) handles work at any rotation angle
        const th = (el.rot || 0) * Math.PI / 180;
        const cos = Math.cos(th), sin = Math.sin(th);
        const gdx = pos.x - drag.sx, gdy = pos.y - drag.sy;
        const dx = gdx * cos + gdy * sin;
        const dy = -gdx * sin + gdy * cos;
        const minW = d.min || 20, minH = 10;
        let nw2 = drag.w0, nh2 = drag.h0;
        if (dir.includes("e")) nw2 = Math.max(minW, snap(drag.w0 + dx));
        if (dir.includes("s")) nh2 = Math.max(minH, snap(drag.h0 + dy));
        if (dir.includes("w")) nw2 = Math.max(minW, snap(drag.w0 - dx));
        if (dir.includes("n")) nh2 = Math.max(minH, snap(drag.h0 - dy));
        // Shift — constrain to the original aspect ratio (corner handles)
        if (evt.shiftKey && dir.length === 2) {
          const ar = drag.w0 / Math.max(1, drag.h0);
          if (Math.abs(nw2 - drag.w0) >= Math.abs(nh2 - drag.h0) * ar) nh2 = Math.max(minH, Math.round(nw2 / ar));
          else nw2 = Math.max(minW, Math.round(nh2 * ar));
        }
        // anchor = point that must stay pinned in world space:
        // the opposite side / corner, or the center when Alt is held
        const alt = !!evt.altKey;
        if (drag.anchor === undefined || drag.anchorAlt !== alt) {
          const ax0 = alt ? drag.w0 / 2 : dir.includes("e") ? 0 : dir.includes("w") ? drag.w0 : drag.w0 / 2;
          const ay0 = alt ? drag.h0 / 2 : dir.includes("s") ? 0 : dir.includes("n") ? drag.h0 : drag.h0 / 2;
          const cx0 = drag.x0 + drag.w0 / 2, cy0 = drag.y0 + drag.h0 / 2;
          drag.anchor = {
            x: cx0 + (ax0 - drag.w0 / 2) * cos - (ay0 - drag.h0 / 2) * sin,
            y: cy0 + (ax0 - drag.w0 / 2) * sin + (ay0 - drag.h0 / 2) * cos,
          };
          drag.anchorAlt = alt;
        }
        if (alt) {
          // symmetric growth from the center
          nw2 = Math.max(minW, snap(drag.w0 + (nw2 - drag.w0) * 2));
          nh2 = Math.max(minH, snap(drag.h0 + (nh2 - drag.h0) * 2));
        }
        const ax = alt ? nw2 / 2 : dir.includes("e") ? 0 : dir.includes("w") ? nw2 : nw2 / 2;
        const ay = alt ? nh2 / 2 : dir.includes("s") ? 0 : dir.includes("n") ? nh2 : nh2 / 2;
        const cx = drag.anchor.x - ((ax - nw2 / 2) * cos - (ay - nh2 / 2) * sin);
        const cy = drag.anchor.y - ((ax - nw2 / 2) * sin + (ay - nh2 / 2) * cos);
        el.w = nw2; el.h = nh2;
        el.x = Math.round(cx - nw2 / 2); el.y = Math.round(cy - nh2 / 2);
        // live dimension badge next to the cursor (Photoshop-style)
        let badge = $("#im-size-badge");
        if (!badge) {
          badge = document.createElement("div");
          badge.id = "im-size-badge"; badge.className = "im-size-badge";
          wrap.appendChild(badge);
        }
        const cells = INVMAP_GRID;
        badge.innerHTML = `W <b>${el.w}</b> × H <b>${el.h}</b> px &nbsp;·&nbsp; ${(el.w / cells / 2).toFixed(1)} × ${(el.h / cells / 2).toFixed(1)} m` +
          (evt.shiftKey ? " · ⧉ aspect" : "") + (evt.altKey ? " · ⊕ center" : "");
        badge.style.left = (evt.clientX - wrap.getBoundingClientRect().left + 16) + "px";
        badge.style.top = (evt.clientY - wrap.getBoundingClientRect().top + 14) + "px";
      }
      drawEls();
    };
    svg.onpointerup = () => {
      wrap.classList.remove("im-panning");
      const badge = $("#im-size-badge");
      if (badge) badge.remove();
      const mq = svg.querySelector("#im-marquee");
      if (mq) mq.remove();
      if (drag && drag.mode === "marquee") {
        const r = drag.rect;
        if (r && r.w > 6 && r.h > 6) {
          const ids = S.doc.elements.filter(el => {
            const b = bboxOf([el.id]);
            return b.x < r.x + r.w && b.x + b.w > r.x && b.y < r.y + r.h && b.y + b.h > r.y;
          }).map(el => el.id);
          // pull in whole groups when any member is caught by the marquee
          const withGroups = new Set(ids);
          for (const el of membersOf(ids)) if (el.grp) for (const gid2 of groupOf(el.grp)) withGroups.add(gid2);
          S.selMulti = [...withGroups];
          if (S.selMulti.length === 1) { S.sel = S.selMulti[0]; S.selMulti = []; }
        }
        drawEls(); drawProps();
        drag = null;
        return;
      }
      if (drag && drag.mode !== "pan") { markDirty(); drawProps(); }
      drag = null;
    };
    document.onkeydown = evt => {
      if (state.bizModule !== "__invmap") return;
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
      if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "z") {
        evt.shiftKey ? redo() : undo(); evt.preventDefault(); return;
      }
      if ((evt.ctrlKey || evt.metaKey) && evt.key.toLowerCase() === "y") {
        redo(); evt.preventDefault(); return;
      }
      if (evt.code === "Space") { S.space = true; wrap.classList.add("im-pan-ready"); evt.preventDefault(); return; }
      if (S.selMulti.length > 1 && (evt.key === "Delete" || evt.key === "Backspace")) {
        S.doc.elements = S.doc.elements.filter(e => !S.selMulti.includes(e.id));
        S.selMulti = []; S.sel = null; S.selCells = [];
        markDirty(); drawEls(); drawProps(); evt.preventDefault(); return;
      }
      if (!S.sel) return;
      const el = S.doc.elements.find(e => e.id === S.sel);
      if (!el) return;
      if (evt.key === "Delete" || evt.key === "Backspace") {
        S.doc.elements = S.doc.elements.filter(e => e.id !== S.sel); S.sel = null; S.selCells = [];
        markDirty(); drawEls(); drawProps(); evt.preventDefault();
      } else if (evt.key.toLowerCase() === "r") {
        el.rot = ((el.rot || 0) + 90) % 360; markDirty(); drawEls(); drawProps();
      } else if (/^Arrow/.test(evt.key)) {
        const d = evt.shiftKey ? INVMAP_GRID * 5 : INVMAP_GRID;
        if (evt.key === "ArrowLeft") el.x -= d;
        if (evt.key === "ArrowRight") el.x += d;
        if (evt.key === "ArrowUp") el.y -= d;
        if (evt.key === "ArrowDown") el.y += d;
        markDirty(); drawEls(); drawProps(); evt.preventDefault();
      }
    };
    document.onkeyup = evt => {
      if (evt.code === "Space") { S.space = false; wrap.classList.remove("im-pan-ready"); }
    };
  }

  boot();
}

/* ---------- Operations Log — tamper-evident audit trail with operator
   face attribution. Enterprise NOC style; double-click a row for a full
   dossier of every action taken on that register. ---------- */
const OPLOG_ACTION = {
  "business.record.create": ["➕", "CREATE", "ok"],
  "business.record.update": ["✏️", "AMEND", "warn"],
  "business.record.delete": ["🗑", "DELETE", "err"],
  "business.face.capture": ["🦅", "FACE ID", "ok"],
  "business.face.rejected": ["🚫", "FACE REJECTED", "err"],
  "business.ocr.serial": ["📷", "OCR SERIAL", ""],
};
/* chat-driven register actions: business.<module>.<op> → same badge set */
function oplogActionBadge(action) {
  if (OPLOG_ACTION[action]) return OPLOG_ACTION[action];
  const m = /^business\.[a-z_]+\.(create|update|delete|status)$/.exec(action);
  if (m) return { create: ["➕", "CREATE (CHAT)", "ok"], update: ["✏️", "AMEND (CHAT)", "warn"],
                  delete: ["🗑", "DELETE (CHAT)", "err"], status: ["✔", "STATUS (CHAT)", "ok"] }[m[1]];
  return ["•", action.replace("business.", "").toUpperCase(), ""];
}
function oplogModLabel(ws, moduleKeyOrName) {
  const key = String(moduleKeyOrName).split(" ")[0];
  const m = ws.modules.find(x => x.key === key);
  if (!m) return { icon: "📄", label: moduleKeyOrName || "—" };
  const mm = /^(.*?)\s*\((FRM[^)]*|OP-[^)]*)\)\s*$/.exec(m.name);
  return { icon: m.icon || "📄", label: t(mm ? mm[1] : m.name), code: mm ? mm[2] : "" };
}
/* Parse the recorded value payload (values={...} | changes=[k: 'a' → 'b'] |
   deleted_values={...}) into structured {kind, rows:[{f, oldV, newV}]}. */
function oplogParseValues(raw) {
  if (!raw) return null;
  let kind = "", body = raw, diff = false;
  if (raw.startsWith("changes=[")) { kind = "amend"; body = raw.slice(9).replace(/\]$/, ""); diff = true; }
  else if (raw.startsWith("deleted_values=")) { kind = "delete"; body = raw.slice(15); }
  else if (raw.startsWith("values=")) { kind = "create"; body = raw.slice(7); }
  // strip a trailing "| prompt: ..." segment into its own field
  let prompt = "";
  const pm = body.match(/\s*\|\s*prompt:\s*([\s\S]*)$/);
  if (pm) { prompt = pm[1].trim(); body = body.slice(0, pm.index); }
  const rows = [];
  if (body.trim().startsWith("{")) {
    try {
      const o = JSON.parse(body);
      for (const [k, v] of Object.entries(o)) {
        if (String(v ?? "").trim() === "") continue;
        rows.push({ f: k, oldV: null, newV: String(v) });
      }
    } catch { rows.push({ f: "—", oldV: null, newV: body }); }
  } else if (diff) {
    for (const seg of body.split("; ")) {
      const m = /^\s*([^:]+):\s*'([\s\S]*?)'\s*→\s*'([\s\S]*?)'\s*$/.exec(seg);
      if (m) rows.push({ f: m[1].trim(), oldV: m[2], newV: m[3] });
      else if (seg.trim()) rows.push({ f: "—", oldV: null, newV: seg.trim() });
    }
  } else if (body.trim()) {
    rows.push({ f: "—", oldV: null, newV: body.trim() });
  }
  return rows.length || prompt ? { kind, rows, prompt } : null;
}
const OPLOG_KIND_META = {
  amend: { lbl: "CHANGE MANIFEST — AMENDMENT", cls: "warn" },
  create: { lbl: "CHANGE MANIFEST — INITIAL ENTRY", cls: "ok" },
  delete: { lbl: "CHANGE MANIFEST — RECORD REMOVAL (values preserved)", cls: "err" },
  "": { lbl: "CHANGE MANIFEST", cls: "" },
};
/* Full structured diff table — data-center change-record style. */
function oplogValuesHtml(raw) {
  const p = oplogParseValues(raw);
  if (!p) return "";
  const meta = OPLOG_KIND_META[p.kind] || OPLOG_KIND_META[""];
  const hasOld = p.rows.some(r => r.oldV !== null);
  return `<div class="biz-manifest biz-manifest-${meta.cls}">
    <div class="biz-manifest-head"><span>${t(meta.lbl)}</span><span class="biz-manifest-n">${p.rows.length} ${t("field(s)")}</span></div>
    <table class="biz-manifest-tbl"><thead><tr>
      <th>${t("FIELD")}</th>${hasOld ? `<th>${t("PREVIOUS VALUE")}</th><th class="biz-manifest-arr"></th>` : ""}<th>${t(hasOld ? "NEW VALUE" : "RECORDED VALUE")}</th></tr></thead><tbody>
      ${p.rows.map(r => `<tr>
        <td class="biz-manifest-f">${esc(r.f)}</td>
        ${hasOld ? `<td class="biz-manifest-old mono">${r.oldV ? esc(r.oldV) : `<span class="biz-manifest-nil">${t("(empty)")}</span>`}</td><td class="biz-manifest-arr">→</td>` : ""}
        <td class="biz-manifest-new mono">${esc(r.newV)}</td></tr>`).join("")}
    </tbody></table>
    ${p.prompt ? `<div class="biz-manifest-src"><span class="noc-lbl">${t("SOURCE INSTRUCTION")}</span><span class="mono">${esc(p.prompt)}</span></div>` : ""}
  </div>`;
}
/* One-line professional summary for table cells / timeline rows. */
function oplogValuesSummary(raw, max = 3) {
  const p = oplogParseValues(raw);
  if (!p || !p.rows.length) return "";
  const parts = p.rows.slice(0, max).map(r =>
    r.oldV !== null
      ? `<span class="biz-oplog-kv"><b>${esc(r.f)}</b> <s>${esc(r.oldV || "∅")}</s> → ${esc(r.newV)}</span>`
      : `<span class="biz-oplog-kv"><b>${esc(r.f)}</b> ${esc(r.newV)}</span>`);
  const more = p.rows.length > max ? `<span class="biz-oplog-kv biz-oplog-kv-more">+${p.rows.length - max}</span>` : "";
  return parts.join("") + more;
}
async function loadBusinessOplog(root, ws) {
  let rows;
  try { rows = await api("/business/oplog"); }   // limit=0 → complete log
  catch (e) {
    const box0 = $("#biz-rows");
    if (box0) box0.innerHTML = `<div class="empty">⚠ ${esc(e.message || e)}</div>`;
    return;
  }
  const box = $("#biz-rows");
  if (!box) return;
  // filter state (persisted across refreshes within the session)
  const F = state.oplogF = state.oplogF || { act: "", mod: "", usr: "", from: "", to: "", fromT: "", toT: "", page: 1, size: 100 };
  const actOf = r => oplogActionBadge(r.action)[1];
  const acts = [...new Set(rows.map(actOf))].sort();
  const mods = [...new Set(rows.map(r => String(r.module).split(" ")[0]))].sort();
  const usrs = [...new Set(rows.map(r => r.user))].sort();
  const modLbl = k => { const ml = oplogModLabel(ws, k); return ml.label + (ml.code ? ` (${ml.code})` : ""); };
  box.innerHTML = `
    <div class="biz-oplog-filters">
      <select id="olf-act"><option value="">${t("All actions")}</option>${acts.map(a => `<option ${F.act === a ? "selected" : ""} value="${esc(a)}">${esc(t(a))}</option>`).join("")}</select>
      <select id="olf-mod"><option value="">${t("All registers")}</option>${mods.map(m => `<option ${F.mod === m ? "selected" : ""} value="${esc(m)}">${esc(modLbl(m))}</option>`).join("")}</select>
      <select id="olf-usr"><option value="">${t("All operators")}</option>${usrs.map(u => `<option ${F.usr === u ? "selected" : ""} value="${esc(u)}">${esc(u)}</option>`).join("")}</select>
      <label class="olf-date">${t("From")} <input type="date" id="olf-from" value="${esc(F.from)}"><input type="time" id="olf-from-t" step="1" value="${esc(F.fromT)}" title="${t('Time')}"></label>
      <label class="olf-date">${t("To")} <input type="date" id="olf-to" value="${esc(F.to)}"><input type="time" id="olf-to-t" step="1" value="${esc(F.toT)}" title="${t('Time')}"></label>
      <button class="btn small" id="olf-clear">✕ ${t("Clear filters")}</button>
    </div>
    <div id="olf-body"></div>`;
  const body = $("#olf-body");
  const draw = () => {
    const q = ($("#biz-search")?.value || "").trim().toLowerCase();
    const vis = rows.filter(r => {
      if (q && !`${r.action} ${r.module} ${r.user} ${r.detail}`.toLowerCase().includes(q)) return false;
      if (F.act && actOf(r) !== F.act) return false;
      if (F.mod && String(r.module).split(" ")[0] !== F.mod) return false;
      if (F.usr && r.user !== F.usr) return false;
      // timestamp bounds — date is required for a bound; time-of-day optional
      // (defaults: 00:00:00 for From, 23:59:59 for To). Seconds precision.
      const ts = r.created_at.slice(0, 19).replace("T", " ");
      if (F.from && ts < F.from + " " + (F.fromT || "00:00:00").padEnd(8, ":00").slice(0, 8)) return false;
      if (F.to && ts > F.to + " " + (F.toT || "23:59:59").padEnd(8, ":59").slice(0, 8)) return false;
      return true;
    });
    if (!vis.length) { body.innerHTML = `<div class="empty">${t("No log entries.")}</div>`; return; }
    const pages = Math.max(1, Math.ceil(vis.length / F.size));
    if (F.page > pages) F.page = pages;
    const start = (F.page - 1) * F.size;
    const pageRows = vis.slice(start, start + F.size);
    const pager = `<div class="biz-oplog-pager">
      <button class="btn small" data-pg="first" ${F.page <= 1 ? "disabled" : ""}>⏮</button>
      <button class="btn small" data-pg="prev" ${F.page <= 1 ? "disabled" : ""}>‹ ${t("Prev")}</button>
      <span class="mono">${F.page} / ${pages}</span>
      <button class="btn small" data-pg="next" ${F.page >= pages ? "disabled" : ""}>${t("Next")} ›</button>
      <button class="btn small" data-pg="last" ${F.page >= pages ? "disabled" : ""}>⏭</button>
      <select id="olf-size">${[50, 100, 300, 1000].map(n => `<option ${F.size === n ? "selected" : ""} value="${n}">${n} / ${t("page")}</option>`).join("")}</select>
    </div>`;
    body.innerHTML = `<div class="biz-table-wrap"><table class="noc-table biz-table biz-oplog"><thead><tr>
      <th>${t("TIME")}</th><th>${t("ACTION")}</th><th>${t("REGISTER")}</th><th>${t("OPERATOR")}</th><th>${t("OPERATED VALUES")}</th><th>${t("FACE CAPTURE")}</th><th>${t("INTEGRITY")}</th></tr></thead><tbody>
      ${pageRows.map((r, i) => {
        const [ic, lbl, cls] = oplogActionBadge(r.action);
        const ml = oplogModLabel(ws, r.module);
        return `<tr class="biz-oplog-row" data-i="${i}" title="${t('Double-click for the full action dossier')}">
        <td class="mono">${esc(r.created_at.slice(0, 19).replace("T", " "))}</td>
        <td><span class="biz-oplog-act biz-oplog-${cls}">${ic} ${esc(t(lbl))}</span></td>
        <td>${ml.icon} ${esc(ml.label)}${ml.code ? ` <span class="biz-nav-code">${esc(ml.code)}</span>` : ""}</td>
        <td>${esc(r.user)}</td>
        <td class="biz-oplog-vals">${oplogValuesSummary(r.values) || `<span class="biz-oplog-noface">—</span>`}</td>
        <td>${r.face ? `<img class="biz-oplog-face" loading="lazy" src="/api/business/face-image/${encodeURIComponent(r.face)}" alt="face">` : `<span class="biz-oplog-noface">${t("none")}</span>`}</td>
        <td class="mono" title="${t('Tamper-evident hash chain (SHA-256)')}">⚓ ${esc(r.entry_hash)}</td></tr>`;
      }).join("")}</tbody></table></div>
      <div class="biz-table-foot">${t("Showing")} ${start + 1}–${start + pageRows.length} / ${vis.length}${vis.length !== rows.length ? ` (${t("filtered from")} ${rows.length})` : ""} · ${t("Double-click a row for the full action dossier")}</div>
      ${pager}`;
    $$(".biz-oplog-row").forEach(tr => tr.ondblclick = () => oplogDetailModal(ws, rows, pageRows[+tr.dataset.i]));
    body.querySelectorAll("[data-pg]").forEach(b => b.onclick = () => {
      const k = b.dataset.pg;
      F.page = k === "first" ? 1 : k === "prev" ? F.page - 1 : k === "next" ? F.page + 1 : pages;
      draw();
    });
    const sz = $("#olf-size");
    if (sz) sz.onchange = () => { F.size = +sz.value; F.page = 1; draw(); };
  };
  const bind = (id, key) => { const el = $(id); if (el) el.onchange = () => { F[key] = el.value; F.page = 1; draw(); }; };
  bind("#olf-act", "act"); bind("#olf-mod", "mod"); bind("#olf-usr", "usr");
  bind("#olf-from", "from"); bind("#olf-to", "to");
  bind("#olf-from-t", "fromT"); bind("#olf-to-t", "toT");
  $("#olf-clear").onclick = () => { state.oplogF = null; const s0 = $("#biz-search"); if (s0) s0.value = ""; loadBusinessOplog(root, ws); };
  const s = $("#biz-search");
  if (s) s.oninput = () => { F.page = 1; draw(); };
  const rf = $("#biz-log-refresh");
  if (rf) rf.onclick = () => loadBusinessOplog(root, ws);
  draw();
}

/* ── Image lightbox — click any face capture / evidence photo to magnify.
   Delegated globally so it works in tables, modals and timelines alike. ── */
document.addEventListener("click", (e) => {
  const img = e.target.closest(".biz-oplog-face, .biz-oplog-hero img");
  if (!img || !img.src) return;
  e.stopPropagation();
  let lb = document.getElementById("img-lightbox");
  if (!lb) {
    lb = document.createElement("div");
    lb.id = "img-lightbox";
    lb.innerHTML = `<img alt=""><span class="img-lb-cap"></span><span class="img-lb-x">✕</span>`;
    lb.onclick = () => { lb.classList.remove("open"); };
    document.body.appendChild(lb);
    document.addEventListener("keydown", ev => { if (ev.key === "Escape") lb.classList.remove("open"); });
  }
  lb.querySelector("img").src = img.src;
  lb.querySelector(".img-lb-cap").textContent = decodeURIComponent(img.src.split("/").pop());
  lb.classList.add("open");
}, true);

/* ---- image lightbox: click any evidence photo (face capture etc.) to
   magnify. Wheel zooms 25%–800%, drag pans, Esc / click backdrop closes. ---- */
function imgLightbox(src, caption) {
  document.querySelectorAll(".img-lightbox").forEach(n => n.remove());
  const ov = document.createElement("div");
  ov.className = "img-lightbox";
  ov.innerHTML = `<div class="img-lb-tools">
      <span class="img-lb-cap mono">${esc(caption || "")}</span>
      <span class="img-lb-pct mono">100%</span>
      <button class="btn small" data-z="-">−</button>
      <button class="btn small" data-z="+">＋</button>
      <button class="btn small" data-z="1">1:1</button>
      <button class="btn small" data-z="x">✕ ${t("Close")}</button>
    </div><img src="${src}" alt="">`;
  document.body.appendChild(ov);
  const img = ov.querySelector("img"), pct = ov.querySelector(".img-lb-pct");
  let z = 1, px = 0, py = 0;
  const apply = () => { img.style.transform = `translate(${px}px,${py}px) scale(${z})`; pct.textContent = Math.round(z * 100) + "%"; };
  const setZ = nz => { z = Math.min(8, Math.max(0.25, nz)); apply(); };
  ov.addEventListener("wheel", e => { e.preventDefault(); setZ(z * (e.deltaY < 0 ? 1.2 : 1 / 1.2)); }, { passive: false });
  ov.querySelectorAll("[data-z]").forEach(b => b.onclick = e => {
    e.stopPropagation();
    const k = b.dataset.z;
    if (k === "x") ov.remove();
    else if (k === "1") { z = 1; px = py = 0; apply(); }
    else setZ(z * (k === "+" ? 1.25 : 0.8));
  });
  let drag = null;
  img.onpointerdown = e => { e.preventDefault(); drag = { x: e.clientX - px, y: e.clientY - py }; img.setPointerCapture(e.pointerId); };
  img.onpointermove = e => { if (drag) { px = e.clientX - drag.x; py = e.clientY - drag.y; apply(); } };
  img.onpointerup = () => drag = null;
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  const esc2 = e => { if (e.key === "Escape") { ov.remove(); document.removeEventListener("keydown", esc2); } };
  document.addEventListener("keydown", esc2);
}
/* delegated: every face-capture / evidence image is magnifiable */
document.addEventListener("click", e => {
  const im = e.target.closest(".biz-oplog-hero img, img.biz-oplog-face, img.biz-row-face");
  if (!im) return;
  e.stopPropagation(); e.preventDefault();
  imgLightbox(im.src, im.getAttribute("alt") === "face" || im.alt === "operator face" ? t("OPERATOR FACE CAPTURE") : "");
}, true);

function oplogDetailModal(ws, allRows, row) {  const key = String(row.module).split(" ")[0];
  const ml = oplogModLabel(ws, row.module);
  const related = allRows.filter(r => String(r.module).split(" ")[0] === key);
  const [ic0, lbl0, cls0] = oplogActionBadge(row.action);
  modal("", `
  <div class="biz-mast">
    <div class="biz-mast-brand">
      <span class="biz-mast-org">${esc((state.bizWs && state.bizWs.company_name) || "")}</span>
      <span class="biz-mast-sys">${t("Integrated Management System")} — ${t("Operations Log")} · ISO 9001 §7.5.3 / §9.2</span>
    </div>
    <div class="biz-mast-doc">
      <span class="biz-mast-code">AUDIT-TRAIL</span>
      <span class="biz-mast-class">${t("Internal — Controlled")}</span>
    </div>
  </div>
  <div class="biz-mast-title">
    <h3>📜 ${t("Action dossier")} — ${ml.icon} ${esc(ml.label)}</h3>
    <span class="biz-mast-sub">${ml.code ? esc(ml.code) + " · " : ""}${t("All recorded actions for this register, newest first")}</span>
  </div>
  <div class="biz-doccontrol">
    <div><span class="noc-lbl">${t("Selected event")}</span><b>${ic0} ${esc(t(lbl0))}</b></div>
    <div><span class="noc-lbl">${t("TIME")}</span><b class="mono">${esc(row.created_at.slice(0, 19).replace("T", " "))}</b></div>
    <div><span class="noc-lbl">${t("OPERATOR")}</span><b>${esc(row.user)}</b></div>
  </div>
  ${oplogValuesHtml(row.values)}
  ${row.face ? `<div class="biz-oplog-hero">
    <img src="/api/business/face-image/${encodeURIComponent(row.face)}" alt="operator face">
    <div><span class="noc-lbl">${t("OPERATOR FACE CAPTURE")}</span>
      <b class="mono">${esc(row.face)}</b>
      <span class="biz-oplog-note">${t("Captured at action start — verifies the person physically present at the workstation.")}</span></div>
  </div>` : ""}
  <div class="biz-sect"><span>${t("Action history")} (${related.length})</span><span class="biz-sect-req">⚓ ${t("hash-chained")}</span></div>
  <div class="biz-oplog-timeline">
    ${related.map(r => {
      const [ic, lbl, cls] = oplogActionBadge(r.action);
      const rml = oplogModLabel(ws, r.module);
      return `<div class="biz-oplog-ev ${r.id === row.id ? "sel" : ""}">
        <span class="biz-oplog-ev-t mono">${esc(r.created_at.slice(0, 19).replace("T", " "))}</span>
        <span class="biz-oplog-act biz-oplog-${cls}">${ic} ${esc(t(lbl))}</span>
        <span class="biz-oplog-ev-u">${esc(r.user)}<span class="biz-oplog-ev-reg">${rml.icon} ${esc(rml.label)}${rml.code ? ` · ${esc(rml.code)}` : ""}</span></span>
        ${r.face ? `<img class="biz-oplog-face" loading="lazy" src="/api/business/face-image/${encodeURIComponent(r.face)}" alt="face">` : `<span class="biz-oplog-noface">${t("none")}</span>`}
        <span class="mono biz-oplog-ev-h" title="${t('Tamper-evident hash chain (SHA-256)')}">⚓ ${esc(r.entry_hash)}</span>
        ${r.values ? `<div class="biz-oplog-ev-vals">${oplogValuesSummary(r.values, 6)}</div>` : ""}
      </div>`;
    }).join("")}
  </div>
  <div class="biz-compliance">
    <span class="biz-comp-title">${t("Documented Information Notice")}</span>
    ${t("Log entries are hash-chained (SHA-256) — any retroactive modification breaks the chain and is detectable at internal audit (§9.2). Face captures attribute each action to the person physically present, preventing account misuse.")}
  </div>`, null);
  const mEl = document.querySelector("#modal-root .modal");
  if (mEl) { mEl.classList.add("biz-modal"); const h = mEl.querySelector("h3"); if (h && !h.textContent.trim()) h.remove(); }
}

/* ── Technician Performance KPI (FRM-CHR-TEST-001) — ISO 9001 §9.1 ────────
   Derived entirely from existing test records: throughput, first-pass
   yield, repair rate, reject rate and pre-test safety compliance per
   technician. Paired quality + volume metrics per industry practice. */
async function bizTechKpi(mod) {
  const rows = await api("/business/records?module=" + encodeURIComponent(mod.key));
  const parseDay = r => String(r.data.at || (r.created_at || "").slice(0, 10) || "").slice(0, 10);
  const build = (days) => {
    const cutoff = days ? new Date(Date.now() - days * 86400000).toISOString().slice(0, 10) : "";
    const inRange = rows.filter(r => !cutoff || parseDay(r) >= cutoff);
    const byTech = {};
    for (const r of inRange) {
      const tech = String(r.data.tech || "— " + t("unassigned")).trim() || "—";
      const o = byTech[tech] = byTech[tech] || { n: 0, pass: 0, repair: 0, fail: 0, safety: 0, safetyN: 0, days: new Set() };
      o.n++;
      const res = String(r.data.result || "").toLowerCase();
      if (res.startsWith("pass")) o.pass++;
      else if (res.includes("repair")) o.repair++;
      else if (res) o.fail++;
      const sf = String(r.data.safety || "").toLowerCase();
      if (sf) { o.safetyN++; if (sf.startsWith("pass")) o.safety++; }
      const dday = parseDay(r);
      if (dday) o.days.add(dday);
    }
    const pct = (a, b) => b ? Math.round(a / b * 100) : null;
    const fmtPct = (v, goodHi, warnLo) => v === null ? "—"
      : `<b style="color:${goodHi ? (v >= warnLo ? "#7fd7a8" : v >= warnLo - 10 ? "#ffd98a" : "#ff8f8f")
                             : (v <= warnLo ? "#7fd7a8" : v <= warnLo + 10 ? "#ffd98a" : "#ff8f8f")}">${v}%</b>`;
    const techs = Object.entries(byTech).sort((a, b) => b[1].n - a[1].n);
    const tot = inRange.length;
    const totPass = techs.reduce((s, [, o]) => s + o.pass, 0);
    if (!tot) return `<div class="empty">${t("No test records in this period.")}</div>`;
    return `
      <div class="kpi-cards">
        <div class="kpi-card"><span>${t("Units tested")}</span><b>${tot}</b></div>
        <div class="kpi-card"><span>${t("First-pass yield")}</span><b>${pct(totPass, tot) ?? 0}%</b><small>${t("target")} ≥ 85%</small></div>
        <div class="kpi-card"><span>${t("Technicians")}</span><b>${techs.length}</b></div>
      </div>
      <table class="noc-table kpi-tbl"><thead><tr>
        <th>${t("TECHNICIAN")}</th><th>${t("UNITS")}</th><th>${t("UNITS / DAY")}</th>
        <th>${t("FIRST-PASS YIELD")}<br><small>≥ 85%</small></th>
        <th>${t("REPAIR RATE")}<br><small>≤ 10%</small></th>
        <th>${t("REJECT RATE")}<br><small>≤ 5%</small></th>
        <th>${t("SAFETY COMPLIANCE")}<br><small>= 100%</small></th></tr></thead><tbody>
      ${techs.map(([tech, o]) => `<tr>
        <td><b>${esc(tech)}</b></td>
        <td>${o.n}</td>
        <td>${o.days.size ? (o.n / o.days.size).toFixed(1) : "—"}</td>
        <td>${fmtPct(pct(o.pass, o.n), true, 85)}</td>
        <td>${fmtPct(pct(o.repair, o.n), false, 10)}</td>
        <td>${fmtPct(pct(o.fail, o.n), false, 5)}</td>
        <td>${fmtPct(pct(o.safety, o.safetyN), true, 100)}</td></tr>`).join("")}
      </tbody></table>
      <p class="im-pal-note" style="margin-top:10px">⚠ ${t("Governance note: throughput must always be read together with first-pass yield and reject rate — volume-only targets drive quality escapes. Use these figures for coaching and capacity planning (ISO 9001 §9.1.3).")}</p>`;
  };
  modal("📊 " + t("Technician Performance KPI") + " — FRM-CHR-TEST-001", `
    <div class="kpi-range">
      <button type="button" class="btn small kpi-r active" data-d="7">7 ${t("days")}</button>
      <button type="button" class="btn small kpi-r" data-d="30">30 ${t("days")}</button>
      <button type="button" class="btn small kpi-r" data-d="90">90 ${t("days")}</button>
      <button type="button" class="btn small kpi-r" data-d="">${t("All time")}</button>
    </div>
    <div id="kpi-body">${build(7)}</div>`, null);
  $$(".kpi-r").forEach(b => b.onclick = () => {
    $$(".kpi-r").forEach(x => x.classList.toggle("active", x === b));
    $("#kpi-body").innerHTML = build(b.dataset.d ? +b.dataset.d : 0);
  });
}

async function loadBusinessRows(mod, root, ws) {
  const rows = await api("/business/records?module=" + encodeURIComponent(mod.key));
  const box = $("#biz-rows");
  if (!box) return;
  const dataFields = mod.fields.filter(f => f[2] !== "section");
  const cols = dataFields.map(f => f[0]);
  const STATUS = { open: "Open", done: "Closed", archived: "Archived" };
  // per-column filters (🔎 Filter) — survive redraws within this register view
  const colF = {};
  let showFilters = false, focusCol = null;
  const draw = () => {
    const q = ($("#biz-search")?.value || "").trim().toLowerCase();
    const st = $("#biz-status")?.value || "";
    const active = Object.entries(colF).filter(([, v]) => v.trim() !== "");
    const vis = rows.filter(r => (!st || r.status === st) &&
      (!q || cols.some(c => String(r.data[c] ?? "").toLowerCase().includes(q))) &&
      active.every(([c, v]) => String(r.data[c] ?? "").toLowerCase().includes(v.trim().toLowerCase())));
    if (!rows.length) {
      box.innerHTML = `<div class="biz-empty">
        <div class="biz-empty-title">${t("This register is empty")}</div>
        <p>${t("Create the first controlled entry — it will be time-stamped, attributed to you and retained per ISO 9001/14001/45001 §7.5.")}</p>
        <button class="btn primary" id="biz-empty-add">+ ${t("New record")}</button></div>`;
      $("#biz-empty-add").onclick = () => $("#biz-add").click();
      return;
    }
    if (!vis.length) { box.innerHTML = `<div class="empty">${t("No records match the current search / filter.")}</div>${showFilters ? `<div style="text-align:center;margin-top:8px"><button class="btn small" id="biz-colf-clear">✕ ${t("Clear filters")}</button></div>` : ""}`;
      const cc = $("#biz-colf-clear"); if (cc) cc.onclick = () => { for (const k of Object.keys(colF)) delete colF[k]; draw(); };
      return; }
    const filterRow = showFilters ? `<tr class="biz-colf-row">${dataFields.map(f => {
      const sel = String(f[2]).startsWith("select:");
      if (sel) {
        const opts = f[2].slice(7).split(",").map(o => o.trim()).filter(Boolean);
        return `<th><select class="biz-colf" data-c="${esc(f[0])}" style="width:100%;box-sizing:border-box;padding:4px 6px;font-size:11px;border-radius:5px;border:1px solid var(--border);background:var(--panel2);color:var(--text)">
          <option value="">${t("All")}</option>${opts.map(o => `<option value="${esc(o)}" ${colF[f[0]] === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></th>`;
      }
      return `<th><input class="biz-colf" data-c="${esc(f[0])}" type="search" value="${esc(colF[f[0]] || "")}" placeholder="🔎" style="width:100%;box-sizing:border-box;padding:4px 6px;font-size:11px;border-radius:5px;border:1px solid var(--border);background:var(--panel2);color:var(--text)"></th>`;
    }).join("")}<th></th><th style="white-space:nowrap"><button class="btn small" id="biz-colf-clear" title="${t('Clear filters')}">✕</button></th></tr>` : "";
    box.innerHTML = `<div class="biz-table-wrap"><table class="noc-table biz-table"><thead><tr>${dataFields.map(f => `<th>${esc(t(f[1]).toUpperCase())}</th>`).join("")}<th>${t("STATUS")}</th><th>${t("ACTIONS")}</th></tr>${filterRow}</thead><tbody>
      ${vis.map(r => `<tr>${cols.map(c => {
        const v = String(r.data[c] ?? "");
        const fdef = dataFields.find(f => f[0] === c) || [];
        const isLoc = v && (c === "location" || c === "spare_loc" || /storage location|map code/i.test(fdef[1] || ""));
        if (isLoc) return `<td title="${esc(v)}"><a class="biz-loc-link" data-loc="${esc(v)}" href="javascript:void 0" title="${esc(t('Show this location blinking on the Inventory Map'))}">📍 ${esc(v)}</a></td>`;
        return `<td title="${esc(v)}">${esc(v)}</td>`;
      }).join("")}
        <td><span class="biz-status biz-status-${r.status}">${t(STATUS[r.status] || r.status)}</span></td>
        <td class="biz-row-actions">
          <button class="btn small biz-edit" data-id="${r.id}">${t("Amend")}</button>
          ${mod.key === "workers" ? `<button class="btn small biz-badge" data-id="${r.id}" title="${esc(t('Generate the printable worker ID badge with check-in QR code'))}">🪪 ${t("Badge")}</button>` : ""}
          ${r.status === "open" ? `<button class="btn small biz-done" data-id="${r.id}">${t("Close")}</button>` : ""}
          <button class="btn small danger biz-del" data-id="${r.id}">${t("Delete")}</button></td></tr>`).join("")}</tbody></table></div>
      <div class="biz-table-foot">${t("Showing")} ${vis.length} / ${rows.length}${active.length ? ` · 🔎 ${active.length} ${t("column filter(s) active")}` : ""}</div>`;
    // wire the per-column filter row (debounced live filtering, focus kept)
    $$(".biz-colf").forEach(el => {
      const apply = () => { colF[el.dataset.c] = el.value; focusCol = el.dataset.c; draw();
        const nf = box.querySelector(`.biz-colf[data-c="${CSS.escape(focusCol)}"]`);
        if (nf && nf.tagName === "INPUT") { nf.focus(); nf.setSelectionRange(nf.value.length, nf.value.length); } };
      if (el.tagName === "SELECT") el.onchange = apply;
      else el.oninput = apply;
    });
    const cc = $("#biz-colf-clear");
    if (cc) cc.onclick = () => { for (const k of Object.keys(colF)) delete colF[k]; draw(); };
    const refresh = () => renderBusinessWorkspace(root, ws);
    $$(".biz-loc-link").forEach(a => a.onclick = () => invMapLocate(a.dataset.loc, root, ws));
    $$(".biz-edit").forEach(b => b.onclick = () => businessRecordModal(mod, rows.find(r => r.id === b.dataset.id), refresh));
    $$(".biz-badge").forEach(b => b.onclick = async () => {
      b.disabled = true;
      try {
        const res = await api("/business/workers/" + b.dataset.id + "/badge", { method: "POST", body: {} });
        showWorkerBadgeModal(res);
      } catch (e) { toast("⚠ " + (e.message || e), "err"); }
      b.disabled = false;
    });
    $$(".biz-done").forEach(b => b.onclick = async () => {
      let fid; try { fid = await captureWorkerFace(t("Close")); } catch (e) { toast("⚠ " + (e.message || e), "err"); return; }
      await api("/business/records/" + b.dataset.id, { method: "PUT", body: { status: "done", face: fid } });
      toast(t("Record closed")); refresh();
    });
    $$(".biz-del").forEach(b => b.onclick = async () => {
      if (!confirm(t("Permanently delete this controlled record? This action is recorded in the audit trail."))) return;
      let fid; try { fid = await captureWorkerFace(t("Delete")); } catch (e) { toast("⚠ " + (e.message || e), "err"); return; }
      await api("/business/records/" + b.dataset.id + "?face=" + encodeURIComponent(fid), { method: "DELETE" });
      toast(t("Record deleted")); refresh();
    });
  };
  const s = $("#biz-search"), f = $("#biz-status"), fb = $("#biz-filter");
  if (s) s.oninput = draw;
  if (f) f.onchange = draw;
  if (fb) fb.onclick = () => { showFilters = !showFilters;
    if (!showFilters) for (const k of Object.keys(colF)) delete colF[k];
    fb.classList.toggle("primary", showFilters); draw(); };
  draw();
}

function businessRecordModal(mod, rec, done) {
  const d = rec ? rec.data : {};
  // Fields considered mandatory for record integrity (ISO 9001 §7.5.2 —
  // identification & description of documented information).
  const REQUIRED = new Set(mod.fields.filter(f => f[2] !== "section").slice(0, 2).map(f => f[0]));
  const HINTS = { number: t("Numeric value"), date: "YYYY-MM-DD", text: "", textarea: "" };
  // Enterprise layout: every register form is organised into titled, emoji-
  // coded sections. Registers may declare sections explicitly (type
  // "section"); all others are auto-grouped by field semantics so EVERY form
  // gets the same professional documented-information structure.
  const displayFields = mod.fields.some(f => f[2] === "section") ? mod.fields : (() => {
    const S = { id: [], date: [], qty: [], proc: [], notes: [], status: [] };
    const keys = mod.fields.map(f => f[0]);
    mod.fields.forEach((f, i) => {
      const [k, , ty] = f;
      if (/^(status|disposition|result|decision)$/.test(k)) S.status.push(f);
      else if (ty === "textarea") S.notes.push(f);
      else if (ty === "date") S.date.push(f);
      else if (ty === "number") S.qty.push(f);
      else if (i < 2 || /serial|asset|^id$|_id$|^po$|^ref|name|worker|tech|supplier|customer|vendor|employee|carrier|batch|lot/.test(k)) S.id.push(f);
      else S.proc.push(f);
    });
    const out = [];
    const sec = (label, arr) => { if (arr.length) { out.push(["_as_" + out.length, label, "section"]); out.push(...arr); } };
    sec("🪪 " + t("Identification & Reference"), S.id);
    sec("⚙️ " + t("Process Details"), S.proc);
    sec("📅 " + t("Dates & Scheduling"), S.date);
    sec("🔢 " + t("Quantities & Financials"), S.qty);
    sec("📝 " + t("Notes & Description"), S.notes);
    sec("🚦 " + t("Status & Disposition"), S.status);
    return out.length > 2 ? out : mod.fields;  // degenerate — keep original
  })();
  const fieldHtml = displayFields.map(([k, label, type]) => {
    if (type === "section")
      return `<div class="bizf bizf-wide" style="margin:6px 0 -2px;padding:7px 0 5px;border-bottom:1px solid rgba(120,150,200,.22);display:flex;align-items:center;gap:8px">
        <span style="width:3px;height:13px;border-radius:2px;background:linear-gradient(180deg,#c9a227,#1a4fa0)"></span>
        <span style="font-size:11px;font-weight:800;letter-spacing:2.2px;text-transform:uppercase;color:#9db4d8">${esc(t(label))}</span></div>`;
    const val = d[k] ?? "";
    const req = REQUIRED.has(k);
    const tl = t(label);
    const fe = bizFieldEmoji(k, type);
    const lbl = `<span class="bizf-lbl">${fe ? fe + " " : ""}${esc(tl)}${req ? ' <em class="bizf-req" title="Required field">*</em>' : ""}</span>`;
    if (type === "textarea")
      return `<label class="bizf bizf-wide">${lbl}<textarea data-f="${k}" rows="3" ${req ? "required" : ""} placeholder="${esc(tl)}…">${esc(String(val))}</textarea></label>`;
    if (type.startsWith("checks:")) {
      // Certified test matrix — each procedure gets PASS / FAIL / N/A.
      // Stored canonically as "item:pass;item:fail;…" (English tokens).
      const items = type.slice(7).split(",");
      const prev = {};
      String(val).split(";").forEach(p => { const mm = /^(.*?):(pass|fail|na)$/.exec(p.trim()); if (mm) prev[mm[1]] = mm[2]; });
      const RES = [["pass", t("PASS")], ["fail", t("FAIL")], ["na", t("N/A")]];
      return `<div class="bizf bizf-wide"><span class="bizf-lbl">${esc(tl)}${req ? ' <em class="bizf-req" title="Required field">*</em>' : ""}</span>
        <div class="biz-checks" data-f="${k}" data-checks="1">
          <div class="biz-checks-head"><span>${t("Test procedure")}</span><span>${t("PASS")}</span><span>${t("FAIL")}</span><span>${t("N/A")}</span></div>
          ${items.map((it, i) => `<div class="biz-checks-row">
            <span class="biz-checks-name"><span class="biz-checks-no">${String(i + 1).padStart(2, "0")}</span> ${esc(t(it))}</span>
            ${RES.map(([rv]) => `<label class="biz-checks-opt biz-checks-${rv}"><input type="radio" name="chk-${k}-${i}" data-item="${esc(it)}" value="${rv}" ${prev[it] === rv ? "checked" : ""}><span></span></label>`).join("")}</div>`).join("")}
        </div></div>`;
    }
    if (type.startsWith("select:")) {
      const opts = type.slice(7).split(",");
      return `<label class="bizf">${lbl}<select data-f="${k}" ${req ? "required" : ""}>${opts.map(o => `<option value="${esc(o)}" ${String(val) === o ? "selected" : ""}>${esc(t(o))}</option>`).join("")}</select></label>`;
    }
    const it = type === "number" ? 'type="number" step="any" min="0"' : type === "date" ? 'type="date"' : type === "password" ? 'type="password" autocomplete="new-password" minlength="8"' : 'type="text"';
    if (type === "password")
      return `<label class="bizf">${lbl}<input ${it} data-f="${k}" value="" ${rec ? "" : "required"} placeholder="${esc(rec ? t('Leave blank to keep current password') : tl)}"></label>`;
    if (type === "text" && (k === "location" || k === "spare_loc" || /storage location|map code/i.test(label)))
      return `<label class="bizf">${lbl}<span class="bizf-scan-wrap"><input ${it} data-f="${k}" list="im-loc-dl" value="${esc(String(val))}" ${req ? "required" : ""} placeholder="${esc(t('Pick a map location (aisle-bay-level)…'))}" autocomplete="off"><button type="button" class="btn small bizf-locpick" data-locpick="${k}" title="${esc(t('Choose from the Inventory Map location schedule'))}">🗺️ ${t("Map")}</button></span><datalist id="im-loc-dl"></datalist></label>`;
    if (type === "text" && /serial/i.test(k + " " + label))
      return `<label class="bizf">${lbl}<span class="bizf-scan-wrap"><input ${it} data-f="${k}" value="${esc(String(val))}" ${req ? "required" : ""} placeholder="${esc(HINTS[type] || tl)}" autocomplete="off"><button type="button" class="btn small bizf-scan" data-scan="${k}" title="${esc(t('Scan serial number with camera (ALT+V screen)'))}">📷 ${t("Scan")}</button></span></label>`;
    return `<label class="bizf">${lbl}<input ${it} data-f="${k}" value="${esc(String(val))}" ${req ? "required" : ""} placeholder="${esc(HINTS[type] || tl)}" autocomplete="off"></label>`;
  }).join("");

  const now = new Date();
  const recId = rec ? rec.id : "— assigned on save —";
  const created = rec && rec.created_at ? String(rec.created_at).slice(0, 16).replace("T", " ") : now.toISOString().slice(0, 16).replace("T", " ");
  const isoRefs = String(mod.iso).split("·").map(s => "ISO " + s.trim()).join(" · ");
  const user = (state.user && (state.user.display_name || state.user.username)) || "—";

  const modCode = (() => { const mm = /\((FRM[^)]*|OP-[^)]*)\)\s*$/.exec(mod.name); return mm ? mm[1] : ""; })();
  const modNameT = (() => { const mm = /^(.*?)\s*\((FRM[^)]*|OP-[^)]*)\)\s*$/.exec(mod.name); return t(mm ? mm[1] : mod.name); })();
  modal("", `
  <div class="biz-mast">
    <div class="biz-mast-brand">
      <span class="biz-mast-org">${esc((state.bizWs && state.bizWs.company_name) || "")}</span>
      <span class="biz-mast-sys">${t("Integrated Management System")} — ISO 9001 · 14001 · 45001 · R2v3</span>
    </div>
    <div class="biz-mast-doc">
      ${modCode ? `<span class="biz-mast-code">${esc(modCode)}</span>` : ""}
      <span class="biz-mast-class">${t("Internal — Controlled")}</span>
    </div>
  </div>
  <div class="biz-mast-title">
    <h3>${mod.icon || ""} ${esc(modNameT)}</h3>
    <span class="biz-mast-sub">${rec ? t("Amend Controlled Record") : t("New Controlled Record")} · ${esc(isoRefs)}</span>
  </div>
  <div class="biz-doccontrol">
    <div><span class="noc-lbl">${t("Record ID")}</span><b class="mono">${esc(String(recId))}</b></div>
    <div><span class="noc-lbl">${rec ? t("Created") : t("Entry date")}</span><b class="mono">${esc(created)}</b></div>
    <div><span class="noc-lbl">${t("Recorded by")}</span><b>${esc(user)}</b></div>
  </div>
  <div class="biz-sect"><span>${t("Record details")}</span><span class="biz-sect-req">${t("* mandatory")}</span></div>
  <div id="biz-company-pick"></div>
  <div class="biz-form-grid">${fieldHtml}</div>
  <div class="biz-compliance">
    <span class="biz-comp-title">${t("Documented Information Notice")}</span>
    ${t("This entry is retained as a controlled record of the integrated management system in accordance with ISO 9001:2015 §7.5 (Quality), ISO 14001:2015 §7.5 (Environmental) and ISO 45001:2018 §7.5 (OH&S). All entries are attributable, time-stamped and subject to internal audit (§9.2) and management review (§9.3). Fields marked * are mandatory for record integrity.")}
  </div>`,
    async () => {
      const data = {};
      let firstInvalid = null;
      $$("#modal-root [data-f]").forEach(el => {
        if (el.dataset.checks) {
          // test matrix → canonical "item:result" list (only rows answered)
          const parts = [];
          el.querySelectorAll("input[type=radio]:checked").forEach(r => parts.push(`${r.dataset.item}:${r.value}`));
          data[el.dataset.f] = parts.join("; ");
          return;
        }
        const v = el.value.trim();
        if (REQUIRED.has(el.dataset.f) && !v && !firstInvalid) firstInvalid = el;
        data[el.dataset.f] = el.value;
      });
      if (firstInvalid) { firstInvalid.focus(); throw new Error(t("Please complete all mandatory (*) fields before submitting the record.")); }
      let face = state._opFace || "";
      if (!face) {
        // capture didn't succeed at open time (camera busy / permission just
        // granted) — try once more now, blocking. Form data stays intact.
        try { face = await captureWorkerFace(rec ? t("Amend Controlled Record") : t("New Controlled Record")); state._opFace = face; }
        catch (e) { throw new Error(t("Operator face not verified — the action cannot proceed without identity capture.") + " (" + (e.message || e) + ")"); }
      }
      if (rec) await api("/business/records/" + rec.id, { method: "PUT", body: { data, face } });
      else {
        const r = await api("/business/records", { method: "POST", body: { module: mod.key, data, face } });
        // cross-form cascades — related registers auto-populated server-side
        (r.cascades || []).forEach(c => toast("🔗 " + t("Linked record created") + ": " + c.reason, "ok"));
        if (r.user_created) toast("👤 " + t("User account created") + ": " + r.user_created, "ok");
      }
      toast(rec ? t("Record amended and retained in the register") : t("Record committed to the controlled register")); done();
    }, rec ? t("Amend record") : t("Commit record"));
  const mEl = document.querySelector("#modal-root .modal");
  if (mEl) { mEl.classList.add("biz-modal"); const h = mEl.querySelector("h3"); if (h && !h.textContent.trim()) h.remove(); }
  $$("#modal-root .bizf-scan").forEach(b => b.onclick = () =>
    serialScanOverlay(document.querySelector(`#modal-root [data-f="${b.dataset.scan}"]`)));
  // HR Employee Enrollment on a multi-company server: ask WHICH company the
  // employee belongs to. Backend binds users.company_owner_id accordingly so
  // the worker's login only shows that company's operations and data.
  if (mod.key === "workers" && !rec && state.user && state.user.is_admin) {
    api("/business/companies").then(r => {
      const cos = Array.isArray(r) ? r : (r && r.companies) || [];
      const box = $("#modal-root #biz-company-pick");
      if (!box || cos.length < 2) return;
      box.innerHTML = `<label class="bizf bizf-wide" style="margin-bottom:8px">
        <span class="bizf-lbl">🏢 ${t("Company (multi-company server)")} <em class="bizf-req" title="Required field">*</em></span>
        <select data-f="company_owner">${cos.map(c =>
        `<option value="${esc(c.owner_id)}" ${c.mine ? "selected" : ""}>${esc(c.company_name)}${c.licensed ? "" : " — ⚠ " + t("unlicensed")}</option>`).join("")}</select></label>`;
    }).catch(() => { /* companies list is admin-only; non-fatal */ });
  }
  // Storage-location picker — populate the datalist from the facility maps
  // and offer a structured chooser grouped by warehouse / zone.
  if ($("#modal-root #im-loc-dl")) invMapLocationIndex().then(idx => {
    const dl = $("#modal-root #im-loc-dl");
    if (dl) dl.innerHTML = idx.slice(0, 800).map(o => `<option value="${esc(o.code)}">🏭 ${esc(o.warehouse)} / ${esc(o.zone)}</option>`).join("");
  });
  $$("#modal-root .bizf-locpick").forEach(b => b.onclick = async () => {
    const inp = document.querySelector(`#modal-root [data-f="${b.dataset.locpick}"]`);
    const idx = await invMapLocationIndex();
    if (!idx.length) { toast("⚠ " + t("No facility maps with racks yet — draw the Inventory Map first."), "err"); return; }
    const byWz = {};
    for (const o of idx) (byWz[o.warehouse + " / " + o.zone] = byWz[o.warehouse + " / " + o.zone] || []).push(o);
    const pop = document.createElement("div");
    pop.className = "im-ctx im-locpick";
    pop.innerHTML = Object.entries(byWz).map(([wz, os]) => `<div class="im-ctx-sep-lbl">🏭 ${esc(wz)}</div>` +
      os.slice(0, 200).map(o => `<button class="im-ctx-it" data-code="${esc(o.code)}">📍 ${esc(o.code)}</button>`).join("")).join("");
    document.body.appendChild(pop);
    const r = b.getBoundingClientRect();
    pop.style.left = Math.min(r.left, innerWidth - 300) + "px";
    pop.style.top = Math.min(r.bottom + 4, innerHeight - Math.min(pop.offsetHeight, 340) - 8) + "px";
    pop.querySelectorAll(".im-ctx-it").forEach(x => x.onclick = () => { inp.value = x.dataset.code; pop.remove(); });
    setTimeout(() => document.addEventListener("pointerdown", function h(e) {
      if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener("pointerdown", h); }
    }), 0);
  });
  // operator identity: capture the worker's face silently when the operation
  // starts. NON-FATAL here — if the camera is busy/denied we retry at submit
  // time instead of destroying the form the user is typing into.
  state._opFace = "";
  captureWorkerFace(rec ? t("Amend Controlled Record") : t("New Controlled Record"))
    .then(fid => { state._opFace = fid; })
    .catch(() => { /* retried on submit */ });
  // operator-identity fields: prefill with the signed-in worker's name so
  // the record is attributed to the person operating the form
  if (!rec && state.user) {
    const opName = state.user.display_name || state.user.username || "";
    const OP_KEYS = /^(by|operator|recorded_by|prepared_by|checked_by|handled_by|entered_by|inspector|tech|clerk|staff|verified_by|received_by|counted_by|issued_by)$/;
    $$("#modal-root [data-f]").forEach(el => {
      if (el.tagName === "INPUT" && el.type === "text" && !el.value && OP_KEYS.test(el.dataset.f)) el.value = opName;
    });
  }
  // HR enrollment: auto-capture the ENROLLED WORKER's face with the external
  // (serial-number) camera and store it on the record — used on the ID badge.
  if (mod.key === "workers") workerPhotoPanel(rec);
}

/* ---------- HR enrollment: worker face auto-capture (external camera) ----
   The enrolled worker stands in front of the EXTERNAL camera (the one
   assigned to serial-number capture). Frames are auto-submitted until the
   server confirms a real human face; the verified image id is stored in the
   record's face_photo field and printed on the worker's ID badge. */
function workerPhotoPanel(rec) {
  const grid = document.querySelector("#modal-root .biz-form-grid");
  if (!grid) return;
  const existing = (rec && rec.data && rec.data.face_photo) || "";
  const wrap = document.createElement("div");
  wrap.className = "bizf bizf-wide";
  wrap.innerHTML = `
    <span class="bizf-lbl">📷 ${t("Worker face photo")} <em class="bizf-req" title="Required field">*</em></span>
    <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <video id="wfp-live" autoplay playsinline muted style="width:170px;height:128px;background:#0b1220;border-radius:8px;object-fit:cover;display:none"></video>
      <img id="wfp-img" alt="" style="width:128px;height:128px;border-radius:8px;object-fit:cover;border:2px solid #2f8f5b;display:${existing ? "" : "none"}" ${existing ? `src="/api/business/face-image/${encodeURIComponent(existing)}"` : ""}>
      <div style="flex:1;min-width:200px">
        <div id="wfp-status" class="muted" style="font-size:12.5px">${existing ? "✔ " + t("Photo on file — press Capture again to replace it") : t("Point the worker at the external (serial-number) camera — the photo is captured automatically once a face is detected.")}</div>
        <button type="button" class="btn small" id="wfp-retake" style="margin-top:8px">🔄 ${t("Capture again")}</button>
      </div>
      <input type="hidden" data-f="face_photo" value="${esc(existing)}">
    </div>`;
  grid.appendChild(wrap);
  const video = wrap.querySelector("#wfp-live"), img = wrap.querySelector("#wfp-img"),
    status = wrap.querySelector("#wfp-status"), hidden = wrap.querySelector('[data-f="face_photo"]');
  let stream = null, timer = null, busy = false;
  const stop = () => {
    clearInterval(timer); timer = null;
    if (stream) { stream.getTracks().forEach(tr => tr.stop()); stream = null; }
    video.style.display = "none";
  };
  const start = async () => {
    stop();
    status.textContent = t("Starting the external camera…");
    try {
      const vc = await cameraConstraints("external", { width: { ideal: 1280 } });
      stream = await navigator.mediaDevices.getUserMedia({ video: vc, audio: false });
      video.srcObject = stream; video.style.display = "";
      status.textContent = t("Auto-capturing — the worker should look straight at the camera…");
    } catch {
      status.textContent = "⚠ " + t("External camera unavailable — check permission / device, then press Capture again.");
      return;
    }
    timer = setInterval(async () => {
      // self-clean when the form is closed mid-capture
      if (!document.body.contains(video)) { stop(); return; }
      if (busy || !video.videoWidth) return;
      busy = true;
      try {
        const c = document.createElement("canvas");
        c.width = video.videoWidth; c.height = video.videoHeight;
        c.getContext("2d").drawImage(video, 0, 0);
        const uri = c.toDataURL("image/jpeg", 0.85);
        const res = await api("/business/face-capture", { method: "POST", body: { image: uri } });
        if (res.ok) {
          hidden.value = res.face_id;
          img.src = uri; img.style.display = "";
          status.textContent = "✔ " + t("Face verified and stored — it will appear on the worker's ID badge.");
          stop();
        }
      } catch { /* keep trying — next frame */ }
      busy = false;
    }, 1600);
  };
  wrap.querySelector("#wfp-retake").onclick = start;
  if (!existing) start();
}

/* ---------- Operator face capture: silent action attribution ----------
   Every operations action (new / amend / close / delete record) silently
   captures the worker's face from the webcam the moment the action starts —
   no visible camera window, no prompt. The server verifies a real human face
   is present; ONLY if verification fails is the worker alerted to show their
   face. The stored face id is chained into the audit log for that action so
   operations are traceable to the person physically present, not just the
   logged-in account. */
function captureWorkerFace(actionLabel) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(".biz-face-alert")) { reject(new Error("busy")); return; }
    // hidden off-screen video — worker does not see any camera UI
    const video = document.createElement("video");
    video.autoplay = true; video.playsInline = true; video.muted = true;
    video.style.cssText = "position:fixed;left:-9999px;top:-9999px;width:2px;height:2px;opacity:0;pointer-events:none";
    document.body.appendChild(video);
    let stream = null, closed = false, timer = null, busy = false, tries = 0, alertBox = null;
    const cleanup = () => {
      closed = true; clearInterval(timer);
      if (stream) stream.getTracks().forEach(tr => tr.stop());
      video.remove();
      if (alertBox) alertBox.remove();
    };
    // Alert shown ONLY when no human face was found — worker must comply.
    const showAlert = () => {
      if (alertBox) return;
      alertBox = document.createElement("div");
      alertBox.className = "biz-ocr-overlay biz-face-alert";
      alertBox.innerHTML = `
        <div class="biz-ocr-card" style="width:min(460px,94vw)">
          <div class="biz-ocr-head"><span>⚠ ${t("Identity verification")}</span></div>
          <div class="biz-ocr-hint" style="font-size:14px;padding:18px 16px">
            ${t("No human face detected — you MUST show your face to the camera to continue.")}
          </div>
          <div class="biz-ocr-bar">
            <span class="biz-ocr-status" id="face-alert-status">${esc(actionLabel || "")}</span>
            <button type="button" class="btn small" id="face-alert-cancel">✕ ${t("Cancel")}</button>
          </div>
        </div>`;
      document.body.appendChild(alertBox);
      alertBox.querySelector("#face-alert-cancel").onclick = () => {
        cleanup(); reject(new Error(t("Face capture is required for this action.")));
      };
    };
    (async () => {
      try {
        const vc = await cameraConstraints("internal", { width: { ideal: 1280 } });
        stream = await navigator.mediaDevices.getUserMedia({ video: vc, audio: false });
        video.srcObject = stream;
      } catch {
        cleanup(); reject(new Error(t("Camera unavailable — check permission / device."))); return;
      }
      const attempt = async () => {
        if (busy || closed || !video.videoWidth) return;
        busy = true;
        try {
          const c = document.createElement("canvas");
          c.width = video.videoWidth; c.height = video.videoHeight;
          c.getContext("2d").drawImage(video, 0, 0);
          const res = await api("/business/face-capture", { method: "POST", body: { image: c.toDataURL("image/jpeg", 0.85) } });
          if (res.ok) { cleanup(); resolve(res.face_id); return; }   // silent success
          tries++;
          if (tries >= 2) showAlert();   // give the camera a warm-up frame first
        } catch (e) {
          tries++;
          if (tries >= 2) { showAlert(); const s = alertBox && alertBox.querySelector("#face-alert-status"); if (s) s.textContent = "⚠ " + (e.message || e); }
        }
        busy = false;
      };
      timer = setInterval(attempt, 1500);
      setTimeout(attempt, 800);
    })();
  });
}

/* ---------- Worker ID badge: printable card with check-in QR ----------
   Enterprise / data-center grade credential card — EXACTLY 4in × 3in
   (384 × 288 CSS px @96dpi; @page 4in 3in for pixel-perfect print).
   Dark navy identity band, photo panel, kiosk QR, ISO-style footer. */
function showWorkerBadgeModal(r) {
  const co = ((state.bizWs && state.bizWs.company_name) || "COMPANY").toUpperCase();
  const fullName = (r.first_name + " " + r.last_name).trim();
  const issued = new Date().toISOString().slice(0, 10);
  const NAVY = "#0c2340", BLUE = "#1a4fa0", GOLD = "#c9a227";
  const mgmt = !!r.management;
  // adaptive typography — long names / titles shrink instead of truncating;
  // a credential card must NEVER cut off the position ("Technical Dir…")
  const nameFs = fullName.length > 26 ? 10.5 : fullName.length > 18 ? 12.5 : 15.5;
  const role = (r.role || "").trim();
  const roleFs = role.length > 44 ? 7.6 : role.length > 30 ? 8.4 : 9.4;
  const dept = (r.department || "").trim();
  const card = `
  <div id="wb-card" style="width:4in;height:3in;background:#fff;color:#111;font-family:'Segoe UI',Arial,Helvetica,sans-serif;position:relative;overflow:hidden;box-sizing:border-box;box-shadow:0 6px 24px rgba(0,0,0,.45);border-radius:10px${mgmt ? `;outline:3px solid ${GOLD};outline-offset:-3px` : ""}">
    <!-- header band -->
    <div style="background:${NAVY};color:#fff;height:0.62in;box-sizing:border-box;padding:0.08in 0.14in 0 0.14in;position:relative">
      <div style="font-size:15px;font-weight:800;letter-spacing:1.6px;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(co)}</div>
      <div style="font-size:6.4px;font-weight:700;letter-spacing:2.6px;color:#9fb6d6;text-transform:uppercase">${t("Employee Identification")} · ${t("Access Credential")}</div>
      <div style="position:absolute;right:0.14in;top:0.10in;text-align:right">
        ${mgmt ? `<div style="display:inline-block;background:linear-gradient(90deg,${GOLD},#e6c458);color:${NAVY};font-size:7px;font-weight:900;letter-spacing:2.2px;padding:2px 8px;border-radius:3px;margin-bottom:2px;text-transform:uppercase">★ ${t("Management")}</div>` : ""}
        <div style="font-size:6px;letter-spacing:1.6px;color:#9fb6d6;font-weight:700">${t("BADGE NO.")}</div>
        <div style="font-size:9.5px;font-weight:800;letter-spacing:.8px;font-family:Consolas,monospace;color:#fff">${esc(r.badge_no)}</div>
      </div>
      <div style="position:absolute;left:0;right:0;bottom:0;height:0.035in;background:${mgmt ? GOLD : `linear-gradient(90deg,${GOLD},${BLUE})`}"></div>
    </div>
    <!-- body -->
    <div style="display:flex;height:1.98in;box-sizing:border-box;padding:0.10in 0.14in 0.06in 0.14in;gap:0.12in;align-items:stretch">
      <!-- photo -->
      <div style="width:1.10in;display:flex;flex-direction:column">
        <div style="width:1.10in;height:1.38in;border:2px solid ${NAVY};border-radius:6px;overflow:hidden;background:#e9edf3;box-sizing:border-box">
          ${r.photo ? `<img src="${r.photo}" style="width:100%;height:100%;object-fit:cover;display:block">` : ""}
        </div>
        <div style="margin-top:0.05in;text-align:center;font-size:5.6px;font-weight:800;letter-spacing:1.4px;color:${NAVY};text-transform:uppercase">${t("Employee Photo")}</div>
      </div>
      <!-- identity -->
      <div style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:flex-start;padding-top:0.02in">
        <div style="font-size:6.2px;font-weight:700;letter-spacing:1.8px;color:#6a7688;text-transform:uppercase">${t("Employee Name")}</div>
        <div style="font-size:${nameFs}px;font-weight:800;color:${NAVY};line-height:1.12;margin:1px 0 6px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${mgmt ? `<span style="color:${GOLD}">★</span> ` : ""}${esc(fullName)}</div>
        <div style="font-size:6.2px;font-weight:700;letter-spacing:1.8px;color:#6a7688;text-transform:uppercase">${t("Position")}</div>
        <div style="font-size:${roleFs}px;font-weight:600;color:#1c2733;line-height:1.25;margin:1px 0 6px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical">${esc(role || "—")}</div>
        <div style="display:flex;gap:0.14in">
          ${dept ? `<div style="min-width:0">
            <div style="font-size:6.2px;font-weight:700;letter-spacing:1.8px;color:#6a7688;text-transform:uppercase">${t("Department")}</div>
            <div style="font-size:8.6px;font-weight:600;color:#1c2733;margin-top:1px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical">${esc(dept)}</div>
          </div>` : ""}
          <div>
            <div style="font-size:6.2px;font-weight:700;letter-spacing:1.8px;color:#6a7688;text-transform:uppercase">${t("Issued")}</div>
            <div style="font-size:9px;font-weight:600;color:#1c2733;margin-top:1px;font-family:Consolas,monospace">${issued}</div>
          </div>
        </div>
      </div>
      <!-- QR -->
      <div style="width:0.98in;display:flex;flex-direction:column;align-items:center;justify-content:flex-start">
        ${r.qr_png ? `<img src="${r.qr_png}" style="width:0.95in;height:0.95in;display:block;border:1.5px solid ${NAVY};border-radius:5px;background:#fff;box-sizing:border-box">` : ""}
        <div style="margin-top:0.04in;text-align:center;font-size:5.6px;font-weight:800;letter-spacing:1.2px;color:${NAVY};text-transform:uppercase">${t("Check-in Kiosk")}</div>
        <div style="text-align:center;font-size:5.2px;color:#6a7688;letter-spacing:.6px;margin-top:1px">${t("Scan to clock in / out")}</div>
      </div>
    </div>
    <!-- footer band -->
    <div style="position:absolute;left:0;right:0;bottom:0;height:0.34in;background:${NAVY};color:#8fa7c6;box-sizing:border-box;padding:0.035in 0.14in;display:flex;align-items:center;justify-content:space-between${mgmt ? `;border-top:2px solid ${GOLD}` : ""}">
      <div style="font-size:5.4px;letter-spacing:.5px;line-height:1.35;max-width:2.7in">${mgmt ? `<b style="color:${GOLD};letter-spacing:1.2px">${t("MANAGEMENT AUTHORITY")}</b> · ` : ""}${t("Property of the company. If found, return to security. Loss must be reported immediately — the credential is revoked on report.")}</div>
      <div style="font-size:6px;font-weight:700;letter-spacing:1.4px;font-family:Consolas,monospace;color:#c9d6e8">${esc(r.badge_no)}</div>
    </div>
  </div>`;
  modal("🪪 " + t("Worker Badge") + " — " + r.badge_no, `
    <p class="muted" style="margin-top:0;font-size:12.5px">⚠ ${t("Print or save this badge NOW — the QR code is shown only once. Generating a new badge revokes this one.")}
    <br><span style="opacity:.8">${t("Card size")}: 4.0 in × 3.0 in</span></p>
    <div style="display:flex;justify-content:center;padding:6px 0">${card}</div>
    <div style="text-align:center;margin-top:12px">
      <button type="button" class="btn primary" id="wb-print">🖨 ${t("Print badge")}</button>
    </div>`, null);
  $("#wb-print").onclick = () => {
    const w = window.open("", "_blank", "width=760,height=560");
    if (!w) { toast("⚠ " + t("Pop-up blocked — allow pop-ups to print the badge."), "err"); return; }
    w.document.write(`<!doctype html><html><head><title>${esc(r.badge_no)}</title>
      <style>
        @page{size:4in 3in;margin:0}
        html,body{margin:0;padding:0;background:#fff}
        body{display:flex;justify-content:center;align-items:flex-start}
        #wb-card{box-shadow:none!important;border-radius:0!important}
        *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
      </style>
      </head><body>${$("#wb-card").outerHTML}</body></html>`);
    w.document.close();
    w.onload = () => { w.focus(); w.print(); };
    setTimeout(() => { try { w.focus(); w.print(); } catch { } }, 600);
  };
}

/* ---------- Serial-number capture: webcam → OCR → form field ----------
   Workers press ALT+V on the Chromebook so the serial number is shown on
   its screen, then point the workstation webcam at it. Frames are OCR'd
   with Tesseract.js and the serial is auto-filled into the open form. */
let _tessLoad = null;
function loadTesseract(onProgress) {
  if (window.Tesseract) return Promise.resolve();
  if (_tessLoad) return _tessLoad;
  // Prefer the engine hosted by OUR server (installed with the program and
  // shipped in every update) — loads from the LAN in milliseconds and works
  // without internet. CDN is only the last-resort fallback.
  const load = (src) => new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = res;
    s.onerror = () => rej(new Error("load failed: " + src));
    document.head.appendChild(s);
  });
  _tessLoad = (async () => {
    if (onProgress) onProgress(2, t("Loading OCR engine…"));
    try { await load("/static/vendor/tesseract/tesseract.min.js"); window._tessLocal = true; }
    catch {
      try { await load("https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"); window._tessLocal = false; }
      catch { _tessLoad = null; throw new Error(t("OCR engine could not be loaded — check the internet connection.")); }
    }
  })();
  return _tessLoad;
}

// ---- shared OCR worker: initialized ONCE per client, then reused by every
// scan window (no reload between captures). Progress is reported so workers
// see that the engine is being prepared.
let _ocrWorker = null, _ocrWorkerReady = null;
function getOcrWorker(onProgress) {
  if (_ocrWorker) { if (onProgress) onProgress(100, t("OCR engine ready ✓")); return Promise.resolve(_ocrWorker); }
  if (_ocrWorkerReady) return _ocrWorkerReady;
  _ocrWorkerReady = (async () => {
    await loadTesseract(onProgress);
    const mkOpts = () => ({
      errorHandler: () => { },   // worker-side errors must not go unhandled
      logger: (m) => {
        if (!onProgress) return;
        // map engine stages onto a single 0–100 bar
        const stage = { "loading tesseract core": [5, 35], "initializing tesseract": [35, 45],
          "loading language traineddata": [45, 90], "initializing api": [90, 99] }[m.status];
        if (stage) onProgress(stage[0] + (m.progress || 0) * (stage[1] - stage[0]),
          t("Preparing OCR engine…") + " " + (m.status || ""));
      }
    });
    const withTimeout = (p, ms) => Promise.race([p,
      new Promise((_, rej) => setTimeout(() => rej(new Error("OCR engine load timed out")), ms))]);
    const create = async (useLocal) => {
      const opts = mkOpts();
      if (useLocal) {
        opts.workerPath = "/static/vendor/tesseract/worker.min.js";
        opts.corePath = "/static/vendor/tesseract";
        opts.langPath = "/static/vendor/tesseract";
      }
      return withTimeout(Tesseract.createWorker("eng", 1, opts), 45000);
    };
    let useLocal = false;
    if (window._tessLocal) {   // use our self-hosted files only if ALL exist
      try {
        const st = await fetch("/api/ocr-assets-status").then(r => r.json());
        useLocal = Object.values(st).every(Boolean);
      } catch { }
    }
    let w;
    try {
      w = await create(useLocal);
    } catch (e) {
      if (!useLocal) throw e;
      // local files broken/incomplete → automatic internet CDN fallback
      if (onProgress) onProgress(5, t("Preparing OCR engine…") + " (fallback)");
      w = await create(false);
    }
    await w.setParameters({
      tessedit_char_whitelist: "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:#-.() ",
      tessedit_pageseg_mode: "6"
    });
    _ocrWorker = w;
    if (onProgress) onProgress(100, t("OCR engine ready ✓"));
    return w;
  })();
  _ocrWorkerReady.catch(() => { _ocrWorkerReady = null; });
  return _ocrWorkerReady;
}

// A plausible device serial: 8–22 chars, contains BOTH letters and at least
// 2 digits, and is not a dictionary-ish all-repeat string. Rejects garbage
// reads like "EECSEBEE".
function plausibleSerial(sn) {
  if (!sn || sn.length < 8 || sn.length > 22) return false;
  if (!/[A-Z]/.test(sn)) return false;
  if ((sn.match(/\d/g) || []).length < 2) return false;
  if (/^(.)\1+$/.test(sn)) return false;
  return true;
}

function extractSerial(text) {
  const raw = String(text).replace(/[|]/g, "I");
  // 1) HIGHEST priority: the ALT+V line "SN:XXXXX" (e.g. "SN:LI9BTFQI2018880D").
  //    Require a real "SN" marker followed by a separator — the fuzzy 5N/8N
  //    forms caused false matches on garbage, so only S/5 + N with an explicit
  //    : . · ; , - separator is accepted.
  const m = /\b[S5]N\s*[:.\u00b7;,\-]\s*([A-Z0-9][A-Z0-9\-. ]{5,32})/i.exec(raw);
  if (m) {
    // OCR may split the serial with stray spaces OR append following words —
    // test the joined form first, then progressively fewer space-separated
    // chunks, then the first chunk alone.
    const chunks = m[1].trim().split(/\s+/);
    for (let n = 1; n <= chunks.length; n++) {   // shortest plausible prefix wins
      const sn = chunks.slice(0, n).join("").replace(/[\-.]+/g, "").toUpperCase();
      if (plausibleSerial(sn)) return sn;
    }
  }
  const lines = raw.split(/\n+/).map(l => l.trim()).filter(Boolean);
  // 2) explicit "Serial number: XXXX" pattern
  for (const l of lines) {
    const mm = /serial\s*(?:number|no\.?|#)?\s*[:\-#]?\s*([A-Z0-9][A-Z0-9\-]{5,24})/i.exec(l);
    if (mm && plausibleSerial(mm[1].toUpperCase())) return mm[1].toUpperCase();
  }
  // 3) fallback: best standalone token that looks like a serial (letters+digits)
  const cand = (raw.toUpperCase().match(/\b[A-Z0-9][A-Z0-9\-]{7,22}\b/g) || [])
    .map(tk => tk.replace(/-/g, ""))
    .filter(tk => plausibleSerial(tk) && !/^(CHROMEBOOK|VERSION|GOOGLE|CHROME|SERIAL|PLATFORM)/.test(tk));
  cand.sort((a, b) => b.length - a.length);
  return cand[0] || "";
}

// strict test: does the OCR text contain a genuine "SN:" marker?
const hasSNMarker = (txt) => /\b[S5]N\s*[:.\u00b7;,\-]\s*[A-Z0-9]/i.test(String(txt).replace(/[|]/g, "I"));

async function serialScanOverlay(input) {
  if (!input) return;
  if (document.querySelector(".biz-ocr-overlay")) return;
  const ov = document.createElement("div");
  ov.className = "biz-ocr-overlay";
  ov.innerHTML = `
    <div class="biz-ocr-card">
      <div class="biz-ocr-head">
        <span>📷 ${t("Serial number capture")}</span>
        <button type="button" class="btn small" id="ocr-close">✕ ${t("Close window")}</button>
      </div>
      <div class="biz-ocr-hint">${t("On the Chromebook press ALT+V at the sign-in screen, then point this camera at its screen. The serial number is detected automatically.")}</div>
      <div class="biz-ocr-stage">
        <video id="ocr-video" autoplay playsinline muted></video>
        <div class="biz-ocr-frame"></div>
      </div>
      <div class="biz-ocr-focus hidden" id="ocr-focusrow">
        <span title="${t('Manual focus — slide until the text is sharp')}">🔍 ${t("Focus")}</span>
        <input type="range" id="ocr-focus" min="0" max="100" step="1">
        <button type="button" class="btn small" id="ocr-af">AF</button>
      </div>
      <div class="biz-ocr-bar">
        <span id="ocr-status" class="biz-ocr-status">${t("Starting camera…")}</span>
        <button type="button" class="btn small primary" id="ocr-shot">📸 ${t("Capture now")}</button>
      </div>
      <div class="biz-ocr-progress hidden" id="ocr-progress">
        <div class="biz-ocr-progress-fill" id="ocr-progress-fill"></div>
        <span class="biz-ocr-progress-txt" id="ocr-progress-txt"></span>
      </div>
    </div>`;
  document.body.appendChild(ov);
  const video = ov.querySelector("#ocr-video"), status = ov.querySelector("#ocr-status");
  let stream = null, worker = null, busy = false, closed = false, timer = null;
  const close = async () => {
    closed = true;
    clearInterval(timer);
    if (stream) stream.getTracks().forEach(tr => tr.stop());
    // NOTE: the OCR worker is shared and stays alive — the next scan window
    // on this client opens instantly without reloading the engine.
    ov.remove();
  };
  ov.querySelector("#ocr-close").onclick = close;
  ov.addEventListener("click", e => { if (e.target === ov) close(); });

  try {
    // ask for the highest resolution the camera offers — more pixels on the
    // SN line means sharper glyphs for OCR even before focus kicks in
    const vc = await cameraConstraints("external", {
      width: { ideal: 3840 }, height: { ideal: 2160 },
      // hint continuous autofocus from the start (supported browsers apply
      // it at open time; others ignore unknown constraints silently)
      focusMode: "continuous"
    });
    stream = await navigator.mediaDevices.getUserMedia({ video: vc, audio: false });
    video.srcObject = stream;
  } catch (e) {
    status.textContent = "⚠ " + t("Camera unavailable — check permission / device.");
    return;
  }

  // ---- close-up sharpness: force continuous autofocus / macro behaviour ----
  // Webcams like the C920 default to a far focus plane; for a screen 10–20 cm
  // away we (1) enable continuous AF when the driver exposes it, (2) offer a
  // manual focus slider + AF toggle when focusDistance is controllable.
  const track = stream.getVideoTracks()[0];
  const caps = (track.getCapabilities && track.getCapabilities()) || {};
  const adv = [];
  if (Array.isArray(caps.focusMode) && caps.focusMode.includes("continuous"))
    adv.push({ focusMode: "continuous" });
  if (Array.isArray(caps.exposureMode) && caps.exposureMode.includes("continuous"))
    adv.push({ exposureMode: "continuous" });
  if (Array.isArray(caps.whiteBalanceMode) && caps.whiteBalanceMode.includes("continuous"))
    adv.push({ whiteBalanceMode: "continuous" });
  if (caps.sharpness && typeof caps.sharpness.max === "number")
    adv.push({ sharpness: caps.sharpness.max });
  if (adv.length) { try { await track.applyConstraints({ advanced: adv }); } catch { } }

  const focusRow = ov.querySelector("#ocr-focusrow");
  const focusSlider = ov.querySelector("#ocr-focus");
  const afBtn = ov.querySelector("#ocr-af");
  if (caps.focusDistance && typeof caps.focusDistance.min === "number") {
    // manual focus is available — show the slider (near = left)
    focusRow.classList.remove("hidden");
    const fd = caps.focusDistance;
    const toDist = v => fd.min + (v / 100) * (fd.max - fd.min);
    let manual = false;
    focusSlider.oninput = async () => {
      manual = true;
      afBtn.classList.remove("primary");
      try {
        await track.applyConstraints({ advanced: [
          { focusMode: "manual", focusDistance: toDist(Number(focusSlider.value)) }] });
      } catch { }
    };
    afBtn.onclick = async () => {
      manual = false;
      afBtn.classList.add("primary");
      try { await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); } catch { }
    };
    if (Array.isArray(caps.focusMode) && caps.focusMode.includes("continuous")) {
      afBtn.classList.add("primary");           // start in continuous AF
    } else {
      // no AF at all — start manual, pre-focused NEAR for close-up scanning
      focusSlider.value = "12";
      focusSlider.oninput();
    }
    // tapping the video nudges a refocus cycle (helps stubborn drivers)
    video.onclick = async () => {
      if (manual) return;
      try {
        await track.applyConstraints({ advanced: [{ focusMode: "manual", focusDistance: toDist(12) }] });
        setTimeout(() => track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }).catch(() => { }), 250);
      } catch { }
    };
  }
  const progRow = ov.querySelector("#ocr-progress");
  const progFill = ov.querySelector("#ocr-progress-fill");
  const progTxt = ov.querySelector("#ocr-progress-txt");
  const onProg = (pct, msg) => {
    if (closed) return;
    if (pct >= 100) {   // ready (instant when the shared engine is cached)
      progRow.classList.add("hidden");
      return;
    }
    progRow.classList.remove("hidden");
    progFill.style.width = Math.min(100, pct).toFixed(0) + "%";
    progTxt.textContent = `${msg || t("Preparing OCR engine…")} · ${Math.min(100, pct).toFixed(0)} %`;
    status.textContent = t("Loading OCR engine…");
  };
  try {
    // shared engine — loads ONCE per client (from this server's own files),
    // every later scan window reuses it instantly
    worker = await getOcrWorker(onProg);
    // shared worker may carry state from a previous scan window — reset psm
    await worker.setParameters({ tessedit_pageseg_mode: "6" });
    progRow.classList.add("hidden");
    status.textContent = t("Waiting for the “SN:” line — point the camera at the ALT+V screen.");
  } catch (e) {
    status.textContent = "⚠ " + (e.message || e);
    return;
  }
  if (closed) return;
  const canvas = document.createElement("canvas");
  // Build a processed frame.
  //   variant: 0 = contrast-stretched grayscale, 1 = adaptive local threshold
  //            (best under uneven glare), 2 = Otsu B/W, 3 = inverted Otsu.
  //   band:    0 = whole guide region; 1/2/3 = overlapping horizontal strips
  //            (top/middle/bottom) upscaled much larger — the SN line is a
  //            single text strip, so strips give OCR far bigger glyphs.
  const grabFrame = (variant, band = 0) => {
    const vw = video.videoWidth, vh = video.videoHeight;
    // FULL frame — the SN line may sit outside the dashed guide box
    let sx = 0, sy = 0, sw = vw, sh = vh;
    if (band) { sh = sh / 2; sy = sy + (band - 1) * sh * .5; }
    // normalize to a fixed OCR width — UPSCALE small frames, DOWNSCALE 4K
    // frames (a full-resolution frame is 30× too many pixels for JS
    // preprocessing and would take many seconds per pass)
    const scale = Math.min(4, Math.max(0.3, (band ? 2200 : 1700) / sw));
    canvas.width = Math.round(sw * scale); canvas.height = Math.round(sh * scale);
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    const W = canvas.width, H = canvas.height;
    const img = ctx.getImageData(0, 0, W, H);
    const px = img.data;
    const n = W * H, gray = new Uint8ClampedArray(n);
    let lo = 255, hi = 0;
    for (let i = 0, j = 0; i < px.length; i += 4, j++) {
      const g = px[i] * .3 + px[i + 1] * .59 + px[i + 2] * .11;
      gray[j] = g;
      if (g < lo) lo = g; if (g > hi) hi = g;
    }
    const range = Math.max(1, hi - lo);
    if (variant === 1) {
      // adaptive mean threshold via integral image — window ~ 1/8 width
      const ii = new Float64Array((W + 1) * (H + 1));
      for (let y = 0; y < H; y++) {
        let rowsum = 0;
        for (let x = 0; x < W; x++) {
          rowsum += gray[y * W + x];
          ii[(y + 1) * (W + 1) + (x + 1)] = ii[y * (W + 1) + (x + 1)] + rowsum;
        }
      }
      const r = Math.max(8, W >> 4);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const x1 = Math.max(0, x - r), x2 = Math.min(W - 1, x + r);
        const y1 = Math.max(0, y - r), y2 = Math.min(H - 1, y + r);
        const area = (x2 - x1 + 1) * (y2 - y1 + 1);
        const s = ii[(y2 + 1) * (W + 1) + (x2 + 1)] - ii[y1 * (W + 1) + (x2 + 1)]
                - ii[(y2 + 1) * (W + 1) + x1] + ii[y1 * (W + 1) + x1];
        const j = y * W + x, i = j * 4;
        const v = gray[j] * area > s * 0.90 ? 255 : 0;   // darker than 90% of local mean → ink
        px[i] = px[i + 1] = px[i + 2] = v;
      }
    } else {
      let thr = 0;
      if (variant >= 2) {   // Otsu threshold
        const hist = new Array(256).fill(0);
        for (let j = 0; j < n; j++) hist[gray[j] | 0]++;
        let sum = 0; for (let k = 0; k < 256; k++) sum += k * hist[k];
        let sumB = 0, wB = 0, maxVar = 0;
        for (let k = 0; k < 256; k++) {
          wB += hist[k]; if (!wB) continue;
          const wF = n - wB; if (!wF) break;
          sumB += k * hist[k];
          const mB = sumB / wB, mF = (sum - sumB) / wF, v = wB * wF * (mB - mF) * (mB - mF);
          if (v > maxVar) { maxVar = v; thr = k; }
        }
      }
      for (let i = 0, j = 0; i < px.length; i += 4, j++) {
        let v;
        if (variant === 0) v = (gray[j] - lo) * 255 / range;              // contrast stretch
        else if (variant === 2) v = gray[j] > thr ? 255 : 0;              // Otsu
        else v = gray[j] > thr ? 0 : 255;                                 // inverted Otsu
        px[i] = px[i + 1] = px[i + 2] = v;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas;
  };
  const frame = ov.querySelector(".biz-ocr-frame");
  // ---- capture flow ----
  // Phase 1 (detect): local Tesseract watches for the "SN:" marker inside the
  //   dashed guide. When seen, the frame turns GREEN and a 2-second hold
  //   countdown starts.
  // Phase 2 (capture): after 2 s of continuous detection, a full-quality frame
  //   is sent to the server, which runs Python OCR (RapidOCR) and returns the
  //   value after "SN:". That value is filled into the serial field.
  let greenSince = 0, sending = false;
  const setGreen = (on) => { frame.classList.toggle("ok", on); if (!on) greenSince = 0; };
  const accept = async (sn) => {
    input.value = sn;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    toast(`✅ ${t("Serial number captured")}: ${sn}`);
    await close();
    input.classList.add("bizf-flash");
    setTimeout(() => input.classList.remove("bizf-flash"), 1600);
  };
  const sendToServer = async (quiet = false) => {
    if (sending || closed) return;
    sending = true;
    if (!quiet) status.textContent = "📡 " + t("Capturing — sending image to server for OCR…");
    try {
      // full-quality raw frame (no preprocessing — the server pipeline is better)
      const c = document.createElement("canvas");
      c.width = video.videoWidth; c.height = video.videoHeight;
      c.getContext("2d").drawImage(video, 0, 0);
      const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.92));
      const fd = new FormData();
      fd.append("file", blob, "serial.jpg");
      const res = await fetch("/api/business/ocr-serial", { method: "POST", body: fd, credentials: "same-origin" });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
      const out = await res.json();
      if (out.serial && plausibleSerial(out.serial)) { await accept(out.serial); return; }
      if (!quiet) {
        status.textContent = t("Server OCR could not read the serial — hold steady, retrying…");
        setGreen(false);
      }
    } catch (e) {
      if (!quiet) { status.textContent = "⚠ OCR: " + (e && e.message || e); setGreen(false); }
    }
    sending = false;
  };
  // parallel path: even when the local OCR reads nothing (dark / moiré / angled
  // screen), the much stronger server OCR gets a full frame every 2.5 s and
  // auto-captures the moment IT can read "SN:".
  const scan = async (manual = false) => {
    if (busy || closed || !video.videoWidth || sending) return;
    busy = true;
    let sawMarker = false, bestRead = "";
    try {
      if (manual) { busy = false; await sendToServer(); return; }
      // local detection passes — read the SN: line inside the guide.
      // As soon as the CLIENT OCR itself reads "SN:<serial>", the value after
      // "SN:" is accepted IMMEDIATELY (no server round-trip, no hold time).
      const combos = [[0, 0, "6"], [1, 0, "6"], [0, 1, "6"], [1, 1, "6"], [0, 2, "7"]];
      let curPsm = "6";
      const reads = [];
      for (const [variant, band, psm] of combos) {
        if (closed || sending) { busy = false; return; }
        if (psm !== curPsm) { await worker.setParameters({ tessedit_pageseg_mode: psm }); curPsm = psm; }
        const { data } = await worker.recognize(grabFrame(variant, band));
        const txt = (data.text || "").trim();
        reads.push(txt);
        if (txt.length > bestRead.length) bestRead = txt;
        if (hasSNMarker(txt)) {
          sawMarker = true;
          // AUTO-CAPTURE: extract the letters behind "SN:" right here
          const sn = extractSerial(txt);
          if (sn) { busy = false; await accept(sn); return; }
          // marker seen but serial unreadable in this pass — try remaining
          // variants before falling back to the server pipeline
          continue;
        }
      }
      // sometimes the marker and the serial OCR best in different passes —
      // try the combined text too
      if (!closed && !sending) {
        const all = reads.join("\n");
        if (hasSNMarker(all)) {
          sawMarker = true;
          const sn = extractSerial(all);
          if (sn) { busy = false; await accept(sn); return; }
        }
      }
      if (closed || sending) { busy = false; return; }
      if (sawMarker) {
        // SN: visible but the client OCR can't read the value cleanly —
        // brief hold, then let the stronger server OCR take over
        setGreen(true);
        if (!greenSince) greenSince = Date.now();
        const held = Date.now() - greenSince;
        const left = Math.max(0, 1000 - held);
        if (left <= 0) { busy = false; await sendToServer(); return; }
        status.textContent = "🟢 " + t("SN: detected — hold steady for {s} more second(s)…").replace("{s}", (left / 1000).toFixed(1));
      } else {
        setGreen(false);
        const peek = bestRead.replace(/\s+/g, " ").slice(0, 50);
        status.textContent = t("Waiting for the “SN:” line — point the camera at the ALT+V screen.")
          + (peek ? `  【OCR: ${peek}】` : "");
      }
    } catch (e) {
      if (!closed) status.textContent = "⚠ OCR: " + (e && e.message || e);
    }
    busy = false;
  };
  ov.querySelector("#ocr-shot").onclick = () => scan(true);
  timer = setInterval(() => scan(false), 500);   // continuous detection
  setTimeout(() => scan(false), 400);
  // independent server pipeline: a full frame goes to the strong Python OCR
  // every 2.5 s no matter what the local engine is doing — auto-capture
  // happens through whichever engine reads the serial first
  const probeTimer = setInterval(() => {
    if (closed) { clearInterval(probeTimer); return; }
    if (!video.videoWidth || sending) return;
    sendToServer(true);
  }, 2500);
}

/* ---------------- POS Server (restaurant / supermarket) ---------------- */
views.pos = async (v) => {
  const pn = state.posNav && state.posNav.pos ? state.posNav : await api("/pos/nav");
  state.posNav = pn;
  if (!pn.pos) { v.innerHTML = `<div class="empty"><div class="big">🚫</div>POS Server is available only for Restaurant or Supermarket businesses — configure the type in 🏢 Business.</div>`; return; }
  const allKinds = pn.sections.flatMap(s => s.items);
  const kind = allKinds.find(k => k.kind === state.posKind) ? state.posKind : allKinds[0].kind;
  state.posKind = kind;
  const [schema, rows] = await Promise.all([api("/pos/schema/" + kind), api("/pos/objects/" + kind)]);
  const cur = allKinds.find(k => k.kind === kind);
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="noc-lbl">BUSINESS TYPE</span><b>${pn.type === "restaurant" ? "🍽️ RESTAURANT" : "🛍️ SUPERMARKET"}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">MODULE</span><b>${cur.icon} ${esc(cur.label.toUpperCase())}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">OBJECTS</span><b>${rows.length} · ${rows.filter(r => r.active).length} active</b></div>
    <div class="noc-kpi"><span class="noc-lbl">CHAT CONTROL</span><b>💬 ANY LANGUAGE</b></div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">${cur.icon} ${esc(cur.label.toUpperCase())} — POS SERVER CONFIGURATION</span>
      <button class="btn small primary" id="pos-add">➕ New ${esc(cur.label.replace(/s$/, ""))}</button></div>
    ${(kind === "zone" || kind === "table" || kind === "structure") ? `<div style="margin:10px 14px 0;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <span style="font-size:10.5px;letter-spacing:.08em;opacity:.65">🖱 DRAG BODY = MOVE · DRAG ◢ CORNER = RESIZE · DOUBLE-CLICK = EDIT — layout saves automatically</span>
      ${(kind === "table" || kind === "zone" || kind === "structure") ? `<label style="display:flex;gap:6px;align-items:center;font-size:10.5px;letter-spacing:.08em"><span class="noc-lbl">ZONE MAP</span><select id="pos-zone-filter" style="min-width:160px"></select></label>` : ""}
    </div>
    <div id="pos-designer" style="margin:8px 14px;position:relative;height:560px;background:repeating-linear-gradient(0deg,#0b1220,#0b1220 24px,#0d1526 24px,#0d1526 25px),repeating-linear-gradient(90deg,#0b1220,#0b1220 24px,#0d1526 24px,#0d1526 25px);border:1px solid #24304a;border-radius:8px;overflow:hidden;touch-action:none"></div>` : ""}
    ${kind === "kiosk" ? `<div id="kiosk-noc" style="margin:10px 14px 0"></div>` : ""}
    <div id="pos-rows" style="padding:0 14px 14px"></div>
  </div>`;

  // ---- kiosk client connection status board (data-center NOC style) ----
  if (kind === "kiosk") {
    const noc = $("#kiosk-noc");
    const AGE = (s) => s == null ? "never" : s < 90 ? s + "s ago" : s < 5400 ? Math.round(s / 60) + "m ago" : Math.round(s / 3600) + "h ago";
    const drawNoc = (st) => {
      if (!noc.isConnected) return false;
      const C = { online: ["ok", "#22c55e"], degraded: ["warn", "#eab308"], offline: ["err", "#ef4444"], never: ["", "#64748b"], disabled: ["", "#64748b"] };
      noc.innerHTML = `
      <div style="border:1px solid #24304a;border-radius:8px;overflow:hidden">
        <div style="display:flex;gap:22px;align-items:center;padding:8px 14px;background:#0d1526;border-bottom:1px solid #24304a">
          <span class="noc-lbl">📡 KIOSK CLIENT CONNECTIONS — LIVE</span>
          <span style="font-size:11px"><span class="noc-led ok"></span> ${st.online}/${st.total} ONLINE</span>
          <span class="noc-lbl" style="margin-left:auto">CLIENT URL: <b style="user-select:all">${secureOrigin()}/kiosk</b> · AUTO-REFRESH 10s · ${new Date(st.server_time).toLocaleTimeString()}</span>
        </div>
        ${st.kiosks.length ? `<table class="noc-table" style="margin:0"><tr>
          <th>KIOSK</th><th>LOCATION</th><th>CONNECTION</th><th>LAST HEARTBEAT</th><th>CLIENT</th><th>IP</th><th>ORDERS TODAY</th></tr>
          ${st.kiosks.map(k => { const [led, col] = C[k.status] || C.never; return `<tr>
            <td><b>${esc(k.name)}</b></td><td>${esc(k.location || "—")}</td>
            <td><span class="noc-led ${led}"></span> <b style="color:${col}">${k.status.toUpperCase()}</b></td>
            <td style="font-family:Consolas,monospace;font-size:11.5px">${AGE(k.age_seconds)}</td>
            <td style="font-size:11px">${esc(k.client_version || "—")}</td>
            <td style="font-family:Consolas,monospace;font-size:11px">${esc(k.client_ip || "—")}</td>
            <td style="text-align:center">${k.orders_today}</td></tr>`; }).join("")}</table>`
          : `<div class="empty" style="padding:18px">No kiosks yet — create one below; its device token connects the client at <b>${secureOrigin()}/kiosk</b>.</div>`}
      </div>`;
      return true;
    };
    try { drawNoc(await api("/pos/kiosks/status")); } catch (e) { noc.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
    const tick = async () => {
      if (!noc.isConnected) return;             // view changed — stop polling
      try { if (!drawNoc(await api("/pos/kiosks/status"))) return; } catch { }
      setTimeout(tick, 10000);
    };
    setTimeout(tick, 10000);
  }

  // floor designer — zones, building structures and tables; drag = move,
  // ◢ = resize; coordinates persist to the POS Server (spec §4.4/§4.5).
  // In Tables, pick a Dining Zone to use it as the map for placing tables.
  let effZoneOf = (d) => String(d.zone || "").trim(); // refined below when designer is active
  let zoneNames = [];                                  // for the editor's ZONE dropdown
  const des = $("#pos-designer");
  if (des) {
    const [zones, structs, tables] = await Promise.all([
      kind === "zone" ? Promise.resolve(rows) : api("/pos/objects/zone"),
      kind === "structure" ? Promise.resolve(rows) : api("/pos/objects/structure").catch(() => []),
      kind === "table" ? Promise.resolve(rows) : api("/pos/objects/table").catch(() => [])]);
    const STATC = { available: "#22c55e", occupied: "#ef4444", reserved: "#eab308", "awaiting payment": "#f97316", cleaning: "#38bdf8", disabled: "#64748b" };
    const STRUCT_STYLE = {
      wall: ["#94a3b8", "⬛"], door: ["#f59e0b", "🚪"], window: ["#38bdf8", "🪟"],
      entrance: ["#22c55e", "➡"], kitchen: ["#f97316", "🍳"], bar: ["#a78bfa", "🍸"],
      counter: ["#eab308", "🧾"], restroom: ["#60a5fa", "🚻"], stairs: ["#94a3b8", "🪜"],
      pillar: ["#64748b", "■"], divider: ["#64748b", "┄"], plant: ["#4ade80", "🪴"],
      other: ["#94a3b8", "□"] };
    const SNAP = 8, snap = (n) => Math.round(n / SNAP) * SNAP;
    const editable = (obj) => obj.kind === kind;

    // zone filter for the Table Layout module
    const zsel = $("#pos-zone-filter");
    if (zsel && zones.length) {
      // no "whole floor" option — always work on one zone map at a time
      if (!state.posZoneMap || !zones.some(z => z.name === state.posZoneMap))
        state.posZoneMap = zones[0].name;
      zsel.innerHTML =
        zones.map(z => `<option value="${esc(z.name)}" ${state.posZoneMap === z.name ? "selected" : ""}>${esc(z.name)}</option>`).join("");
      zsel.onchange = () => { state.posZoneMap = zsel.value; render(); };
    }
    const zoneFilter = state.posZoneMap || "";
    // effective zone: explicit value, otherwise the zone whose rectangle
    // contains the object's center on the floor plan (spatial inference)
    const effZone = (d, w0, h0) => {
      const z = String(d.zone || "").trim();
      if (z) return z;
      const cx = (+d.x || 0) + (+d.w || w0) / 2, cy = (+d.y || 0) + (+d.h || h0) / 2;
      const hit = zones.find(zn => { const zd = zn.data;
        return cx >= (+zd.x || 0) && cx <= (+zd.x || 0) + (+zd.w || 200) &&
               cy >= (+zd.y || 0) && cy <= (+zd.y || 0) + (+zd.h || 140); });
      return hit ? hit.name : "";
    };
    effZoneOf = (d) => effZone(d, 52, 52);
    zoneNames = zones.map(z => z.name);
    const inZone = (d, w0 = 52, h0 = 52) => {
      if (!zoneFilter) return true;
      const z = effZone(d, w0, h0);
      return !z || z.toLowerCase() === zoneFilter.trim().toLowerCase(); // orphans stay visible everywhere
    };

    const mkEl = (obj, role) => { // role: zone | structure | table
      const d = obj.data, el = document.createElement("div");
      const isZone = role === "zone", isStruct = role === "structure";
      const ss = isStruct ? (STRUCT_STYLE[d.type] || STRUCT_STYLE.other) : null;
      const col = isZone ? (d.color || "#4f6ba8") : isStruct ? ss[0] : (STATC[d.status] || "#22c55e");
      const w = +d.w || (isZone ? 200 : isStruct ? 90 : 52), h = +d.h || (isZone ? 140 : isStruct ? (d.type === "wall" || d.type === "divider" ? 12 : 60) : 52);
      el.className = "pos-des-obj";
      el.style.cssText = `position:absolute;left:${+d.x || 12}px;top:${+d.y || 12}px;width:${w}px;height:${h}px;` +
        (isZone
          ? `border:1.5px dashed ${col};border-radius:8px;padding:3px 6px;font-size:10px;letter-spacing:.1em;color:${col};`
          : isStruct
            ? `transform:rotate(${d.rot || 0}deg);background:${col}33;border:1.5px solid ${col};border-radius:${d.type === "pillar" ? "50%" : "4px"};display:flex;align-items:center;justify-content:center;gap:4px;font-size:10px;color:${col};overflow:hidden;white-space:nowrap;`
            : `transform:rotate(${d.rot || 0}deg);border-radius:${d.shape === "round" ? "50%" : "8px"};background:${col}22;border:2px solid ${col};display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:bold;color:${col};`) +
        (editable(obj) ? "cursor:grab;" : "opacity:.45;pointer-events:none;");
      el.textContent = isZone ? obj.name.toUpperCase()
        : isStruct ? `${ss[1]} ${obj.name || d.type || ""}`.trim() : obj.name;
      if (role === "table") el.title = `${obj.name} · ${d.seats || "?"} seats · ${d.status || "available"}`;
      if (isStruct) el.title = `${d.type || "structure"}${d.zone ? " · " + d.zone : ""}`;
      if (editable(obj)) {
        const hd = document.createElement("div");
        hd.className = "pos-des-handle";
        hd.style.cssText = `position:absolute;right:-1px;bottom:-1px;width:14px;height:14px;cursor:nwse-resize;` +
          `border-right:3px solid ${col};border-bottom:3px solid ${col};border-radius:0 0 6px 0;`;
        el.appendChild(hd);
        el.ondblclick = () => openModal(rows.find(r => r.id === obj.id));
        el.oncontextmenu = (e) => {
          e.preventDefault();
          $$(".pos-des-menu").forEach(m => m.remove());
          const menu = document.createElement("div");
          menu.className = "pos-des-menu";
          menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:100;` +
            `background:#16213b;border:1px solid #2d3d60;border-radius:10px;padding:5px;min-width:170px;` +
            `box-shadow:0 8px 32px rgba(0,0,0,.5);font-size:12.5px`;
          const mi = (label, fn, danger) => {
            const b = document.createElement("div");
            b.textContent = label;
            b.style.cssText = `padding:8px 14px;border-radius:7px;cursor:pointer;${danger ? "color:#f87171;" : ""}`;
            b.onmouseenter = () => b.style.background = "#22304e";
            b.onmouseleave = () => b.style.background = "";
            b.onclick = () => { menu.remove(); fn(); };
            menu.appendChild(b);
          };
          mi("⧉ Duplicate", async () => {
            // auto-increment name: "11" → "12", "Table 3" → "Table 4", else append " copy"
            const m = String(obj.name).match(/^(.*?)(\d+)\s*$/);
            const newName = m ? m[1] + (parseInt(m[2], 10) + 1) : obj.name + " copy";
            const nd = { ...obj.data, x: (+obj.data.x || 12) + 24, y: (+obj.data.y || 12) + 24,
                         name: newName, status: kind === "table" ? "available" : obj.data.status };
            if (kind === "table" && zoneFilter && !nd.zone) nd.zone = zoneFilter;
            try {
              await api("/pos/objects/" + kind, { method: "POST", body: { data: nd, name: newName } });
              toast(`⧉ Duplicated as “${newName}”`); render();
            } catch (err) { toast("❌ " + err.message, "err"); }
          });
          mi("✏️ Edit", () => openModal(rows.find(r => r.id === obj.id)));
          mi("🗑 Delete", async () => {
            if (!confirm(`Delete “${obj.name}”?`)) return;
            await api("/pos/objects/" + obj.id, { method: "DELETE" });
            toast("🗑 Deleted"); render();
          }, true);
          document.body.appendChild(menu);
          setTimeout(() => addEventListener("pointerdown", (ev) => {
            if (!menu.contains(ev.target)) menu.remove();
          }, { once: true }), 0);
        };
        el.onpointerdown = (e) => {
          e.preventDefault();
          el.setPointerCapture(e.pointerId);
          const resizing = e.target === hd;
          const r0 = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight, cx: e.clientX, cy: e.clientY };
          el.style.cursor = resizing ? "nwse-resize" : "grabbing";
          el.style.zIndex = 10;
          const move = (ev) => {
            const dx = ev.clientX - r0.cx, dy = ev.clientY - r0.cy;
            if (resizing) {
              el.style.width = Math.max(10, snap(r0.w + dx)) + "px";
              el.style.height = Math.max(10, snap(r0.h + dy)) + "px";
            } else {
              el.style.left = Math.max(0, Math.min(des.clientWidth - r0.w, snap(r0.x + dx))) + "px";
              el.style.top = Math.max(0, Math.min(des.clientHeight - r0.h, snap(r0.y + dy))) + "px";
            }
          };
          const up = async (ev) => {
            el.releasePointerCapture(e.pointerId);
            el.removeEventListener("pointermove", move);
            el.removeEventListener("pointerup", up);
            el.style.cursor = "grab";
            el.style.zIndex = "";
            const changed = el.offsetLeft !== r0.x || el.offsetTop !== r0.y ||
              el.offsetWidth !== r0.w || el.offsetHeight !== r0.h;
            if (!changed) return;
            const nd = { ...obj.data, x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
            if (kind === "table" && zoneFilter && !nd.zone) nd.zone = zoneFilter; // placing on a zone map assigns the zone
            obj.data = nd;
            try {
              await api("/pos/objects/" + obj.id, { method: "PUT", body: { data: nd, name: obj.name } });
              toast(`📍 ${obj.name}: ${resizing ? "resized" : "moved"} — layout saved`);
            } catch (err) { toast("❌ " + err.message, "err"); }
          };
          el.addEventListener("pointermove", move);
          el.addEventListener("pointerup", up);
        };
      }
      return el;
    };
    const showZones = zoneFilter ? zones.filter(z => z.name.trim().toLowerCase() === zoneFilter.trim().toLowerCase()) : zones;
    des.replaceChildren(
      ...showZones.map(z => mkEl(z, "zone")),
      ...structs.filter(s => inZone(s.data, 90, 40)).map(s => mkEl(s, "structure")),
      ...tables.filter(t => inZone(t.data)).map(t => mkEl(t, "table")));
  }

  const fields = schema.fields;
  const label_of = Object.fromEntries(fields.map(f => [f[0], f[1]]));
  const showCols = fields.slice(0, 6).map(f => f[0]);
  const box = $("#pos-rows");
  if (!rows.length) box.innerHTML = `<div class="empty">No ${esc(cur.label.toLowerCase())} yet — create one here or in chat: <b>add ${esc(kind.replace(/_/g, " "))}: name=…</b></div>`;
  else box.innerHTML = `<table class="noc-table"><tr>${showCols.map(c => `<th>${esc(label_of[c].toUpperCase())}</th>`).join("")}${kind === "kiosk" ? `<th>DEVICE TOKEN</th>` : ""}<th>STATE</th><th></th></tr>
    ${rows.map(r => `<tr>${showCols.map(c => `<td>${esc(String((c === "name" ? r.name : c === "zone" ? (String(r.data.zone || "").trim() || (effZoneOf(r.data) && effZoneOf(r.data) + " (auto)") || "") : r.data[c]) ?? ""))}</td>`).join("")}
      ${kind === "kiosk" ? `<td style="white-space:nowrap"><code style="font-size:10.5px;user-select:all;background:#0b1220;padding:2px 6px;border-radius:4px">${esc(r.device_token || "—")}</code>
        <button class="btn small tok-copy" data-tok="${esc(r.device_token || "")}" title="Copy token">📋</button></td>` : ""}
      <td><span class="noc-led ${r.active ? "ok" : ""}"></span> ${r.active ? "ACTIVE" : "INACTIVE"}${r.has_secret ? " 🔐" : ""}</td>
      <td style="white-space:nowrap">
        <button class="btn small pos-edit" data-id="${r.id}">✏️</button>
        <button class="btn small pos-tog" data-id="${r.id}" data-a="${r.active ? 0 : 1}">${r.active ? "⏸" : "▶"}</button>
        ${kind === "kiosk" ? `<button class="btn small pos-revoke" data-id="${r.id}" title="Revoke & regenerate device token">🔑</button>` : ""}
        <button class="btn small danger pos-del" data-id="${r.id}">✕</button></td></tr>`).join("")}</table>`;
  $$(".tok-copy").forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.tok); toast("📋 Device token copied"); }
    catch { toast("❌ Clipboard blocked — select the token text manually", "err"); }
  });
  // double-click a list row → focus the designer on that record's zone
  // (zones: the zone itself; tables/structures: their assigned zone)
  if (kind === "zone" || kind === "table" || kind === "structure") {
    $$("#pos-rows tr").forEach((tr, i) => {
      if (i === 0) return; // header
      const r = rows[i - 1];
      if (!r) return;
      tr.style.cursor = "pointer";
      tr.title = "Double-click to open this record's zone in the designer";
      tr.ondblclick = () => {
        state.posZoneMap = kind === "zone" ? r.name : effZoneOf(r.data);
        render();
      };
    });
  }

  const openModal = (rec) => {
    const d = rec ? { name: rec.name, ...rec.data } : {};
    if (!rec && kind === "table" && state.posZoneMap && !d.zone) d.zone = state.posZoneMap;
    const GEO = new Set(["x", "y", "w", "h", "rot", "width", "height", "rotation"]);
    const HINT = {
      name: "Unique identifier shown to staff and on receipts",
      zone: "Dining zone this record belongs to",
      seats: "Guest capacity — shown to staff on the kiosk floor map",
      status: "Live service state — controls availability on the kiosk",
      shape: "Rendered shape on the floor plan",
      price: "Unit price before tax", tax_rate: "Percent, e.g. 8.25",
      category: "Menu category for the kiosk product grid",
      order_types: "Comma-separated, e.g. dine-in, pickup, delivery",
      username: "Sign-in ID typed on the kiosk — must be unique",
      worker: "Linked HR employee — start typing to search the directory",
      pos_scope: "Which POS systems this account may sign into",
      role: "Determines permitted actions — enforced at sign-in",
      schedule: "Optional, e.g. Mon–Fri 08:00–18:00",
    };
    const field = ([k, label, type]) => {
      const val = d[k] ?? "";
      const hint = HINT[k] ? `<span style="font-size:10px;opacity:.55;letter-spacing:.02em">${esc(HINT[k])}</span>` : "";
      if (kind === "pos_account" && k === "worker")
        return `<label style="position:relative"><span class="noc-lbl">HR WORKER NAME</span>
          <input data-f="worker" value="${esc(String(val))}" autocomplete="off" placeholder="Start typing to search HR directory…">
          <div id="wk-suggest" style="display:none;position:absolute;left:0;right:0;top:100%;z-index:50;max-height:180px;overflow:auto;background:#0e1730;border:1px solid #2c3c63;border-radius:8px;box-shadow:0 12px 30px rgba(0,0,0,.5)"></div>${hint}</label>`;
      if (kind === "pos_account" && k === "pos_scope") {
        const cur2 = String(val || "both");
        const OPT = [["both", "🏬 Both systems"], ["restaurant", "🍽 Restaurant POS"], ["supermarket", "🛒 Supermarket POS"]];
        return `<label><span class="noc-lbl">POS SYSTEMS ALLOWED</span><select data-f="pos_scope">
          ${OPT.map(([v2, l2]) => `<option value="${v2}" ${cur2 === v2 ? "selected" : ""}>${l2}</option>`).join("")}</select>${hint}</label>`;
      }
      if (k === "zone" && zoneNames.length)
        return `<label><span class="noc-lbl">ZONE</span><select data-f="zone">
          <option value="">— unassigned —</option>
          ${zoneNames.map(z => `<option ${String(val) === z ? "selected" : ""}>${esc(z)}</option>`).join("")}</select>${hint}</label>`;
      if (type === "textarea") return `<label><span class="noc-lbl">${esc(label.toUpperCase())}</span><textarea data-f="${k}" rows="2">${esc(String(val))}</textarea>${hint}</label>`;
      if (type.startsWith("select:")) return `<label><span class="noc-lbl">${esc(label.toUpperCase())}</span><select data-f="${k}">${type.slice(7).split(",").map(o => `<option ${String(val) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>${hint}</label>`;
      return `<label><span class="noc-lbl">${esc(label.toUpperCase())}</span><input type="${type === "number" ? "number" : "text"}" step="any" data-f="${k}" value="${esc(String(val))}" ${k === "name" ? "required placeholder='Required'" : ""}>${hint}</label>`;
    };
    const geoF = fields.filter(f => GEO.has(f[0])), mainF = fields.filter(f => !GEO.has(f[0]));
    const sec = (title, inner, note) => inner ? `<div style="grid-column:1/-1;margin-top:6px;padding-top:10px;border-top:1px solid #22304e">
        <div style="font-size:10px;letter-spacing:.14em;opacity:.6;margin-bottom:2px">${title}${note ? ` <span style="letter-spacing:.02em;text-transform:none;opacity:.75">— ${note}</span>` : ""}</div></div>` + inner : "";
    const fh = mainF.map(field).join("") +
      sec("PLACEMENT &amp; GEOMETRY", geoF.map(field).join(""),
          "set automatically when you drag / resize on the floor designer");
    const sh = (schema.secret_fields || []).length
      ? sec("🔐 CREDENTIALS", (schema.secret_fields || []).map(([k, label]) => `<label><span class="noc-lbl">${esc(label.toUpperCase())}</span><input type="password" data-s="${k}" placeholder="${rec && rec.has_secret ? "•••••• (unchanged)" : ""}"></label>`).join(""),
            "encrypted at rest — never displayed again")
      : "";
    const meta = rec ? `<div style="grid-column:1/-1;display:flex;gap:18px;font-size:10px;opacity:.5;letter-spacing:.06em">
        <span>RECORD ID&nbsp;<code>${esc(rec.id.slice(0, 8))}</code></span><span>STATE&nbsp;${rec.active ? "ACTIVE" : "INACTIVE"}</span></div>` : "";
    modal(`${cur.icon} ${rec ? "Edit" : "New"} ${cur.label.replace(/s$/, "")} — POS Server`,
      `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px 14px">${meta}${fh}${sh}</div>`,
      async () => {
        const data = {}; $$("#modal-root [data-f]").forEach(el => { data[el.dataset.f] = el.value; });
        // records without a "name" field identify by their first field (e.g.
        // POS accounts → username)
        const recName = data.name || data.username || data.worker || "";
        if (!String(recName).trim()) throw new Error(`${esc(label_of[fields[0][0]] || "Name")} is required`);
        // Enterprise identity check: the HR worker name must match a real
        // record in Worker Information (HR) — not the virtual AI employees.
        if (kind === "pos_account" && String(data.worker || "").trim()) {
          const hr = await api("/business/records?module=workers").catch(() => []);
          const names = hr.map(r => String(r.data.name || "").trim().toLowerCase()).filter(Boolean);
          if (!names.includes(data.worker.trim().toLowerCase()))
            throw new Error(`"${data.worker}" is not in Worker Information (HR) — pick a name from the suggestions`);
        }
        const secrets = {}; $$("#modal-root [data-s]").forEach(el => { if (el.value) secrets[el.dataset.s] = el.value; });
        const body = { data, name: recName };
        if (Object.keys(secrets).length) body.secrets = secrets;
        let out;
        if (rec) out = await api("/pos/objects/" + rec.id, { method: "PUT", body });
        else out = await api("/pos/objects/" + kind, { method: "POST", body });
        if (out.device_token) modal("🔑 Kiosk Device Token — shown only once",
          `<p>Store this token on the kiosk device. It authenticates the kiosk to the POS Server and can be revoked anytime.</p><pre style="user-select:all;background:#0b1220;padding:10px;border-radius:6px">${esc(out.device_token)}</pre>`, null);
        toast("✅ Saved"); render();
      }, rec ? "Update" : "Create");
    // HR worker directory autocomplete — suggestions appear in a box under the
    // input; clicking one fills the field (and derives a username if empty).
    if (kind === "pos_account") {
      const inp = $("#modal-root [data-f=worker]"), sug = $("#wk-suggest");
      if (inp && sug) {
        // Directory = Worker Information (HR) business records (real staff),
        // NOT the virtual AI employees.
        let people = [];
        api("/business/records?module=workers").then(rows => {
          people = rows
            .filter(r => String(r.data.status || "active") !== "terminated")
            .map(r => ({ name: String(r.data.name || ""), title: String(r.data.role || "") }))
            .filter(p => p.name);
        }).catch(() => {});
        const show = () => {
          const q = inp.value.trim().toLowerCase();
          const hits = people.filter(p => !q || p.name.toLowerCase().includes(q)).slice(0, 8);
          if (!hits.length) {
            sug.innerHTML = `<div style="padding:8px 12px;opacity:.55;font-size:11.5px">No matching worker in Worker Information (HR)</div>`;
            sug.style.display = people.length || q ? "" : "none";
            return;
          }
          sug.innerHTML = hits.map(p => `<div class="wk-opt" data-n="${esc(p.name)}" style="padding:8px 12px;cursor:pointer;display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #1b2745">
            <span>👤 ${esc(p.name)}</span><span style="opacity:.5;font-size:11px">${esc(p.title)}</span></div>`).join("");
          sug.style.display = "";
          sug.querySelectorAll(".wk-opt").forEach(o => {
            o.onmouseenter = () => o.style.background = "#1b2745";
            o.onmouseleave = () => o.style.background = "";
            o.onpointerdown = (ev) => {
              ev.preventDefault();
              inp.value = o.dataset.n;
              const u = $("#modal-root [data-f=username]");
              if (u && !u.value.trim()) u.value = o.dataset.n.toLowerCase().replace(/[^a-z0-9]+/g, ".").replace(/^\.|\.$/g, "");
              sug.style.display = "none";
            };
          });
        };
        inp.oninput = show;
        inp.onfocus = show;
        inp.onblur = () => setTimeout(() => { sug.style.display = "none"; }, 150);
      }
    }
  };
  $("#pos-add").onclick = () => openModal(null);
  $$(".pos-edit").forEach(b => b.onclick = () => openModal(rows.find(r => r.id === b.dataset.id)));
  $$(".pos-tog").forEach(b => b.onclick = async () => { await api("/pos/objects/" + b.dataset.id, { method: "PUT", body: { active: b.dataset.a === "1" } }); render(); });
  $$(".pos-revoke").forEach(b => b.onclick = async () => {
    if (!confirm("Revoke this kiosk's device token? The kiosk will lose access until the new token is installed.")) return;
    await api("/pos/objects/" + b.dataset.id, { method: "PUT", body: { revoke_token: true } });
    toast("🔑 Token revoked & regenerated"); render();
  });
  $$(".pos-del").forEach(b => b.onclick = async () => { if (!confirm("Delete this object?")) return; await api("/pos/objects/" + b.dataset.id, { method: "DELETE" }); toast("🗑 Deleted"); render(); });
};

/* ---------------- Purchasing: vendors, POs, AI invoice verification ---------------- */
views.purchasing = async (v) => {
  let vendors, pos, invs;
  try { [vendors, pos, invs] = await Promise.all([api("/purchasing/vendors"), api("/purchasing/pos"), api("/purchasing/invoices")]); }
  catch (e) { v.innerHTML = `<div class="empty"><div class="big">🚫</div>${esc(e.message)}</div>`; return; }
  const pend = invs.filter(i => !["posted", "rejected"].includes(i.status)).length;
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="noc-lbl">VENDORS</span><b>${vendors.length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">PURCHASE ORDERS</span><b>${pos.length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">INVOICES PENDING REVIEW</span><b><span class="noc-led ${pend ? "warn" : "ok"}"></span> ${pend}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">VERIFICATION</span><b>👁 HUMAN MANDATORY</b></div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🏭 VENDORS</span><button class="btn small" id="ven-add">➕ Vendor</button></div>
    <div style="padding:0 14px 12px">${vendors.length ? `<table class="noc-table"><tr><th>VENDOR</th><th>CONTACT</th><th>TERMS</th><th>STATUS</th></tr>
      ${vendors.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.contact || x.email || x.phone || "")}</td><td>${esc(x.terms)}</td><td>${esc(x.status)}</td></tr>`).join("")}</table>` : `<div class="empty">No vendors yet.</div>`}</div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">📑 PURCHASE ORDERS</span><button class="btn small" id="po-add">➕ Purchase order</button></div>
    <div style="padding:0 14px 12px">${pos.length ? `<table class="noc-table"><tr><th>PO #</th><th>TOTAL</th><th>EXPECTED</th><th>STATUS</th><th></th></tr>
      ${pos.map(p => `<tr><td>${esc(p.po_number)}</td><td>$${(p.total || 0).toFixed(2)}</td><td>${esc(p.expected || "—")}</td><td>${esc(p.status.toUpperCase())}</td>
        <td>${["approved", "sent", "partially received"].includes(p.status) ? `<button class="btn small po-recv" data-id="${p.id}">📦 Receive</button>` : ""}
        ${p.status === "draft" ? `<button class="btn small po-appr" data-id="${p.id}">✅ Approve</button>` : ""}</td></tr>`).join("")}</table>` : `<div class="empty">No purchase orders yet.</div>`}</div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🧾 AI INVOICE VERIFICATION — human confirmation is mandatory for every invoice</span>
      <button class="btn small primary" id="inv-up">📤 Upload invoice</button></div>
    <div style="padding:0 14px 12px">${invs.length ? `<table class="noc-table"><tr><th>DOCUMENT</th><th>TYPE</th><th>STATUS</th><th>CONFIRMED BY</th><th></th></tr>
      ${invs.map(i => `<tr><td>📄 ${esc(i.file_name)}</td><td>${esc(i.doc_type)}</td>
        <td><span class="noc-led ${i.status === "posted" ? "ok" : i.status === "exception" ? "err" : "warn"}"></span> ${esc(i.status.toUpperCase())}</td>
        <td>${esc(i.confirmed_by || "—")}</td>
        <td>${i.status !== "posted" ? `<button class="btn small inv-match" data-id="${i.id}" title="Three-way match: PO ↔ receiving ↔ invoice">🔀 Match</button> <button class="btn small inv-rev" data-id="${i.id}">👁 Review</button>` : `JE linked`}</td></tr>`).join("")}</table>` : `<div class="empty">Upload PDF / JPG / PNG / TIFF invoices — AI extracts fields with confidence levels; you review & confirm each field before posting.</div>`}</div>
  </div>`;

  $("#ven-add").onclick = () => modal("➕ New Vendor",
    `<label><span class="noc-lbl">NAME</span><input id="vn-name"></label>
     <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
     <label><span class="noc-lbl">CONTACT</span><input id="vn-contact"></label>
     <label><span class="noc-lbl">PHONE</span><input id="vn-phone"></label>
     <label><span class="noc-lbl">EMAIL</span><input id="vn-email"></label>
     <label><span class="noc-lbl">TERMS</span><select id="vn-terms"><option>Net 30</option><option>Net 15</option><option>Net 60</option><option>Due on receipt</option><option>COD</option></select></label></div>`,
    async () => { await api("/purchasing/vendors", { method: "POST", body: { name: $("#vn-name").value, contact: $("#vn-contact").value, phone: $("#vn-phone").value, email: $("#vn-email").value, terms: $("#vn-terms").value } }); toast("✅ Vendor created"); render(); }, "Create vendor");

  $("#po-add").onclick = () => modal("➕ New Purchase Order",
    `<label><span class="noc-lbl">VENDOR</span><select id="po-ven"><option value="">—</option>${vendors.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
     <label><span class="noc-lbl">LINES (one per line: SKU | description | qty | unit cost)</span><textarea id="po-lines" rows="5" placeholder="RICE01 | Jasmine rice 25lb | 10 | 22.50"></textarea></label>
     <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
     <label><span class="noc-lbl">TAX $</span><input id="po-tax" type="number" step="any" value="0"></label>
     <label><span class="noc-lbl">SHIPPING $</span><input id="po-ship" type="number" step="any" value="0"></label>
     <label><span class="noc-lbl">DISCOUNT $</span><input id="po-disc" type="number" step="any" value="0"></label></div>`,
    async () => {
      const lines = $("#po-lines").value.split("\n").map(l => l.split("|").map(s => s.trim())).filter(a => a.length >= 4)
        .map(a => ({ sku: a[0], desc: a[1], qty: parseFloat(a[2]) || 0, unit_cost: parseFloat(a[3]) || 0, received: 0 }));
      if (!lines.length) throw new Error("Add at least one line: SKU | description | qty | unit cost");
      await api("/purchasing/pos", { method: "POST", body: { vendor_id: $("#po-ven").value, lines, tax: +$("#po-tax").value, shipping: +$("#po-ship").value, discount: +$("#po-disc").value } });
      toast("✅ PO created (draft)"); render();
    }, "Create PO");

  $$(".po-appr").forEach(b => b.onclick = async () => { await api("/purchasing/pos/" + b.dataset.id, { method: "PUT", body: { status: "approved" } }); toast("✅ PO approved"); render(); });
  $$(".po-recv").forEach(b => b.onclick = () => {
    const p = pos.find(x => x.id === b.dataset.id);
    modal(`📦 Receive — ${p.po_number}`,
      p.lines.map((l, i) => `<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:8px;align-items:end">
        <span class="noc-lbl">${esc(l.desc || l.sku)} (ordered ${l.qty}, received ${l.received || 0})</span>
        <label><span class="noc-lbl">RECEIVED</span><input type="number" step="any" data-ri="${i}" value="${Math.max(0, l.qty - (l.received || 0))}"></label>
        <label><span class="noc-lbl">DAMAGED</span><input type="number" step="any" data-di="${i}" value="0"></label>
        <label><span class="noc-lbl">LOT/EXP</span><input data-li="${i}" placeholder="lot / expiry"></label></div>`).join(""),
      async () => {
        const receipts = p.lines.map((l, i) => ({ idx: i, received: +($(`#modal-root [data-ri="${i}"]`).value || 0), damaged: +($(`#modal-root [data-di="${i}"]`).value || 0), lot: $(`#modal-root [data-li="${i}"]`).value }));
        await api(`/purchasing/pos/${p.id}/receive`, { method: "POST", body: { receipts } });
        toast("📦 Receiving recorded — inventory updated"); render();
      }, "Record receiving");
  });

  $("#inv-up").onclick = () => {
    const inp = document.createElement("input"); inp.type = "file"; inp.accept = ".pdf,.jpg,.jpeg,.png,.tiff,.txt,.csv";
    inp.onchange = async () => {
      if (!inp.files[0]) return;
      const fd = new FormData(); fd.append("file", inp.files[0]);
      toast("⏳ Uploading — AI extraction with field-level confidence…");
      const r = await fetch("/api/purchasing/invoices", { method: "POST", body: fd, credentials: "same-origin" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { toast("❌ " + (d.detail || "Upload failed"), "err"); return; }
      toast("✅ Invoice analyzed — status: " + d.status); render();
    };
    inp.click();
  };
  $$(".inv-rev").forEach(b => b.onclick = () => invoiceReviewModal(invs.find(x => x.id === b.dataset.id), vendors));
  $$(".inv-match").forEach(b => b.onclick = async () => {
    const inv = invs.find(x => x.id === b.dataset.id);
    let poId = inv.po_id;
    if (!poId && pos.length) {
      // let the reviewer link a PO first
      modal(`🔀 Three-way match — ${esc(inv.file_name)}`,
        `<p>Link the purchase order this invoice bills against. The match compares PO ↔ receiving ↔ invoice quantities and costs (never auto-posts).</p>
         <label><span class="noc-lbl">PURCHASE ORDER</span><select id="tm-po"><option value="">— none / invoice-only expense —</option>${pos.map(p => `<option value="${p.id}">${esc(p.po_number)} · $${(p.total || 0).toFixed(2)} · ${esc(p.status)}</option>`).join("")}</select></label>`,
        async () => {
          const pid = $("#tm-po").value;
          if (pid) await api("/purchasing/invoices/" + inv.id, { method: "PUT", body: { po_id: pid } });
          const r = await api(`/purchasing/invoices/${inv.id}/match`);
          modal(`🔀 Match result — ${esc(inv.file_name)}`, matchResultHtml(r), null);
        }, "Run match");
      return;
    }
    const r = await api(`/purchasing/invoices/${inv.id}/match`);
    modal(`🔀 Match result — ${esc(inv.file_name)}`, matchResultHtml(r), null);
  });
};

function matchResultHtml(r) {
  return `<div style="border:1px solid ${r.matched ? "#22c55e" : "#eab308"};border-radius:6px;padding:10px;margin-bottom:8px">
      ${r.matched ? "✅ <b>MATCHED</b> — PO, receiving and invoice agree within tolerance." : "⚠ <b>EXCEPTIONS</b> — resolve before approval:"}</div>
    ${r.po_number ? `<p class="noc-lbl">PO ${esc(r.po_number)} · ${esc(r.po_status || "")}</p>` : ""}
    ${r.issues.length ? `<ul>${r.issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
    ${(r.lines || []).length ? `<table class="noc-table"><tr><th>LINE</th><th>STATUS</th><th>PROBLEMS</th></tr>
      ${r.lines.map(l => `<tr><td>${esc(l.line)}</td><td>${l.status === "matched" ? "🟢" : "🔴"} ${esc(l.status)}</td><td>${(l.problems || []).map(esc).join("; ")}</td></tr>`).join("")}</table>` : ""}`;
}

function invoiceReviewModal(inv, vendors) {
  const CONF_ICON = { high: "🟢", medium: "🟡", low: "🟠", unreadable: "🔴", missing: "⚫", conflicting: "🟣" };
  const flds = inv.extracted.fields || {};
  const warnings = inv.extracted.warnings || [];
  const req = inv.required_fields;
  const rows = req.filter(f => f !== "lines" && f !== "account").map(f => {
    const e = flds[f] || { value: "", confidence: "missing" };
    const cor = inv.corrected[f] !== undefined ? inv.corrected[f] : (e.value ?? "");
    const chk = inv.fields_confirmed.includes(f);
    return `<tr><td><b>${esc(f.replace(/_/g, " ").toUpperCase())}</b></td>
      <td>${CONF_ICON[e.confidence] || "⚫"} ${esc(e.confidence || "missing")}</td>
      <td style="opacity:.7">${esc(String(e.value ?? ""))}</td>
      <td><input data-cf="${f}" value="${esc(String(cor))}" style="width:100%"></td>
      <td style="text-align:center"><input type="checkbox" data-ck="${f}" ${chk ? "checked" : ""}></td></tr>`;
  }).join("");
  const linesE = flds.lines || { value: [], confidence: "missing" };
  modal(`👁 Invoice Review — ${inv.file_name}`,
    `${warnings.length ? `<div style="border:1px solid #eab308;border-radius:6px;padding:8px;margin-bottom:8px">⚠ AI warnings: ${warnings.map(esc).join(" · ")}</div>` : ""}
     ${inv.status === "exception" ? `<div style="border:1px solid #ef4444;border-radius:6px;padding:8px;margin-bottom:8px">🛑 Validation exceptions detected — review carefully before confirming.</div>` : ""}
     <table class="noc-table"><tr><th>FIELD</th><th>AI CONFIDENCE</th><th>AI VALUE</th><th>CORRECTED VALUE</th><th>CONFIRMED</th></tr>${rows}</table>
     <div style="margin:8px 0"><span class="noc-lbl">LINE ITEMS (${CONF_ICON[linesE.confidence] || "⚫"} ${esc(linesE.confidence)})</span>
       <pre style="max-height:120px;overflow:auto;background:#0b1220;padding:8px;border-radius:6px;font-size:11px">${esc(JSON.stringify(linesE.value || [], null, 1))}</pre>
       <label>Line items reviewed & receiving confirmed <input type="checkbox" data-ck="lines" ${inv.fields_confirmed.includes("lines") ? "checked" : ""}></label></div>
     <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
       <label><span class="noc-lbl">VENDOR RECORD</span><select id="ir-ven"><option value="">— unmatched —</option>${vendors.map(x => `<option value="${x.id}" ${inv.vendor_id === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
       <label><span class="noc-lbl">DEBIT ACCOUNT — confirm classification <input type="checkbox" data-ck="account" ${inv.fields_confirmed.includes("account") ? "checked" : ""}></span>
         <select id="ir-acct"><option>1200 Inventory Asset</option><option>5000 Cost of Goods Sold</option><option>6400 Supplies</option><option>6100 Utilities</option><option>1500 Fixed Assets</option><option>7000 Other Expenses</option></select></label></div>
     <div style="border:1.5px solid #4f6ba8;border-radius:8px;padding:10px;margin-top:10px">
       <label style="display:flex;gap:8px;align-items:flex-start"><input type="checkbox" id="ir-statement" style="margin-top:3px">
       <span><b>${esc(inv.statement)}</b><br><span style="opacity:.6;font-size:11px">Mandatory — AI confidence never bypasses human verification. Your username and timestamp are recorded.</span></span></label></div>`,
    async () => {
      const corrected = {}; $$("#modal-root [data-cf]").forEach(el => { corrected[el.dataset.cf] = el.value; });
      corrected.account = $("#ir-acct").value;
      const confirmed = $$("#modal-root [data-ck]").filter(el => el.checked).map(el => el.dataset.ck);
      const statement = $("#ir-statement").checked;
      await api("/purchasing/invoices/" + inv.id, { method: "PUT", body: { corrected, fields_confirmed: confirmed, vendor_id: $("#ir-ven").value, statement_accepted: statement } });
      if (statement && confirmed.length >= inv.required_fields.length) {
        try {
          const r = await api(`/purchasing/invoices/${inv.id}/post`, { method: "POST", body: { account: $("#ir-acct").value } });
          toast("✅ Invoice verified & posted — journal entry created");
        } catch (e) { toast("⚠ Saved, but not posted: " + e.message, "err"); }
      } else toast("💾 Review saved — " + (statement ? "confirm all required fields to post" : "sign the confirmation statement to post"));
      render();
    }, "Save review / Post");
}

/* ---------------- Workforce, Visitors & Access Control ---------------- */

/* Enterprise visitor dossier — opened by double-clicking a row in the
   Visitor Review Console. Identity header with portrait, status & badge
   validity, structured visit details, ID document gallery (click to zoom)
   and the full chain-of-custody event timeline. */
function visitorDossier(v) {
  const STATUS_META = {
    pending:     { led: "warn", label: "AWAITING APPROVAL", color: "#f59e0b" },
    approved:    { led: "ok",   label: "APPROVED — ON PREMISES SOON", color: "#22c55e" },
    checked_in:  { led: "ok",   label: "CHECKED IN — ON PREMISES", color: "#22c55e" },
    checked_out: { led: "err",  label: "CHECKED OUT — VISIT CLOSED", color: "#94a3b8" },
    denied:      { led: "err",  label: "ENTRY DENIED", color: "#ef4444" },
  };
  const sm = STATUS_META[v.status] || { led: "warn", label: v.status.toUpperCase(), color: "#94a3b8" };
  const dt = (s) => s ? new Date(s).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
  const dur = (a, b) => {
    if (!a) return "";
    const ms = (b ? new Date(b) : new Date()) - new Date(a);
    if (ms < 0) return "";
    const m = Math.floor(ms / 60000);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  };
  const field = (k, val, extra = "") => `<div style="padding:7px 0;border-bottom:1px solid #1b2745;display:flex;gap:12px">
      <span style="flex:none;width:118px;font-size:9.5px;font-weight:700;letter-spacing:.14em;color:#64748b;padding-top:2px">${k}</span>
      <span style="font-size:13px;font-weight:600;min-width:0;overflow-wrap:anywhere">${val || `<span style="opacity:.35">—</span>`}${extra}</span></div>`;
  const EV_META = {
    registered:      ["📝", "Registered at kiosk"],
    approved:        ["✅", "Approved"],
    denied:          ["⛔", "Denied"],
    checked_in:      ["🟢", "Checked in"],
    checked_out:     ["🔴", "Checked out"],
    badge_reprinted: ["🖨", "Badge reprinted — previous QR revoked"],
  };
  const timeline = (v.events || []).slice().reverse().map(ev => {
    const [icon, label] = EV_META[ev.event] || ["▫", ev.event];
    return `<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #16203a;font-size:12px;align-items:baseline">
      <span style="flex:none">${icon}</span>
      <span style="flex:1;font-weight:600">${esc(label)}${ev.by ? ` <span style="opacity:.55;font-weight:400">· by ${esc(ev.by)}</span>` : ""}</span>
      <span style="flex:none;font-size:10.5px;opacity:.55;font-variant-numeric:tabular-nums">${dt(ev.at)}</span></div>`;
  }).join("") || `<div style="opacity:.45;font-size:12px;padding:6px 0">No events recorded.</div>`;
  const docs = (v.doc_images || []).map(di => `
    <figure style="margin:0;text-align:center">
      <img src="${di.image}" class="wf-face-zoom" data-n="${esc(v.visitor_name)} — ${esc(di.label)}" data-png="${di.image}"
        title="${esc(di.label)} — click to enlarge"
        style="width:150px;height:96px;object-fit:cover;border-radius:8px;border:1px solid #2c3c63;cursor:zoom-in;background:#0b1220">
      <figcaption style="font-size:9.5px;letter-spacing:.1em;color:#64748b;margin-top:4px;text-transform:uppercase">${esc(di.label || "document")}</figcaption>
    </figure>`).join("");
  const onPrem = v.status === "checked_in";
  modal(`🛂 Visitor Dossier — ${v.visitor_name}`, `
    <div style="display:flex;gap:16px;align-items:flex-start;padding:12px;background:#0b1220;border:1px solid #22304e;border-radius:10px">
      ${v.face_photo
        ? `<img src="${v.face_photo}" class="wf-face-zoom" data-n="${esc(v.visitor_name)}" data-png="${v.face_photo}" title="Click to enlarge"
             style="width:86px;height:112px;object-fit:cover;border-radius:10px;border:2px solid #2c3c63;cursor:zoom-in;flex:none">`
        : `<div style="width:86px;height:112px;border-radius:10px;border:2px dashed #2c3c63;display:flex;align-items:center;justify-content:center;font-size:30px;opacity:.3;flex:none">👤</div>`}
      <div style="flex:1;min-width:0">
        <div style="font-size:19px;font-weight:800;letter-spacing:.01em">${esc(v.visitor_name)}</div>
        <div style="font-size:12.5px;color:#94a3b8;font-weight:600;margin-top:2px">${esc(v.company || "No company recorded")} · ${esc(v.category)}</div>
        <div style="margin-top:9px;display:inline-flex;align-items:center;gap:7px;padding:4px 12px;border-radius:20px;background:#111c33;border:1px solid #22304e;font-size:10.5px;font-weight:800;letter-spacing:.1em;color:${sm.color}">
          <span class="noc-led ${sm.led}"></span>${sm.label}</div>
        ${v.badge_expires_at ? `<div style="font-size:10.5px;margin-top:7px;color:${new Date(v.badge_expires_at) < new Date() ? "#ef4444" : "#94a3b8"}">
          🪪 Badge ${new Date(v.badge_expires_at) < new Date() ? "EXPIRED" : "valid until"} ${dt(v.badge_expires_at)}</div>` : ""}
      </div>
    </div>

    <div style="font-size:9.5px;font-weight:700;letter-spacing:.16em;color:#64748b;margin:16px 0 4px">VISIT DETAILS</div>
    <div style="padding:2px 12px;background:#0b1220;border:1px solid #22304e;border-radius:10px">
      ${field("HOST", esc(v.host))}
      ${field("PURPOSE", esc(v.purpose))}
      ${field("DESTINATION", esc(v.destination))}
      ${field("ID DOCUMENT", esc(v.id_doc_type || "none") + (v.id_number_masked ? ` · <code style="background:#111c33;padding:1px 6px;border-radius:4px">${esc(v.id_number_masked)}</code>` : ""))}
      ${field("CONSENT", v.consent ? `<span style="color:#22c55e">✔ Privacy consent recorded</span>` : `<span style="color:#ef4444">✘ Not recorded</span>`)}
      ${field("APPROVED BY", esc(v.approved_by))}
      ${field("REGISTERED", dt(v.created_at))}
      ${field("CHECKED IN", dt(v.checked_in_at))}
      ${field("CHECKED OUT", dt(v.checked_out_at), v.checked_in_at ? ` <span style="opacity:.5;font-size:11px">· on premises ${dur(v.checked_in_at, v.checked_out_at)}${onPrem ? " and counting" : ""}</span>` : "")}
      ${field("LANGUAGE", esc((v.language || "en").toUpperCase()))}
      ${field("VISIT REF", `<code style="background:#111c33;padding:1px 6px;border-radius:4px;user-select:all">${esc(v.id)}</code>`)}
    </div>

    <div style="font-size:9.5px;font-weight:700;letter-spacing:.16em;color:#64748b;margin:16px 0 6px">ID DOCUMENTS & CAPTURES — ${(v.doc_images || []).length} ON FILE</div>
    ${docs ? `<div style="display:flex;flex-wrap:wrap;gap:12px;padding:12px;background:#0b1220;border:1px solid #22304e;border-radius:10px">${docs}</div>`
           : `<div style="padding:12px;background:#0b1220;border:1px dashed #22304e;border-radius:10px;opacity:.45;font-size:12px">No document images captured for this visit.</div>`}

    <div style="font-size:9.5px;font-weight:700;letter-spacing:.16em;color:#64748b;margin:16px 0 6px">CHAIN OF CUSTODY — EVENT TIMELINE</div>
    <div style="padding:4px 12px;background:#0b1220;border:1px solid #22304e;border-radius:10px;max-height:180px;overflow:auto">${timeline}</div>
    <div style="font-size:9px;opacity:.4;letter-spacing:.06em;margin-top:10px">🔒 IDENTITY NUMBERS ARE ENCRYPTED AT REST AND ALWAYS DISPLAYED MASKED · ALL ACTIONS ARE AUDIT-LOGGED</div>`,
    null);
  // wire zoom on the images inside the dossier
  $$("#modal-root .wf-face-zoom").forEach(img => img.onclick = () => {
    const w = window.open("", "_blank");
    if (w) { w.document.write(`<body style="margin:0;background:#000;display:flex;align-items:center;justify-content:center;min-height:100vh"><img src="${img.dataset.png}" style="max-width:100vw;max-height:100vh"></body>`); w.document.title = img.dataset.n; }
  });
}

/* Enterprise visitor badge — 6″ × 4″ landscape label, auto-printed on
   approval via a hidden iframe (no popup blockers, no extra tab).
   Layout: corporate header band, VISITOR banner, identity block (name,
   company, purpose, host, destination), QR pass on the right, validity
   strip and compliance footer. */
function printVisitorBadge(visit, r) {
  const facility = (state.bizWs && state.bizWs.company_name) || "SECURITY & RECEPTION";
  const exp = r.badge_expires_at ? new Date(r.badge_expires_at) : null;
  const issued = new Date();
  const fmt = (d) => d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Visitor Badge</title><style>
    @page { size: 6in 4in landscape; margin: 0; }
    * { margin:0; padding:0; box-sizing:border-box; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    html,body { width:6in; height:4in; font-family:"Segoe UI",Arial,Helvetica,sans-serif; color:#0f172a; background:#fff; }
    .badge { width:6in; height:4in; display:flex; flex-direction:column; overflow:hidden; }
    .head { background:#0f2a52; color:#fff; padding:.14in .25in; display:flex; justify-content:space-between; align-items:center; }
    .head .org { font-size:15px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; }
    .head .lbl { font-size:9px; letter-spacing:.22em; opacity:.85; }
    .banner { background:#f59e0b; color:#0f172a; text-align:center; font-weight:900; font-size:21px; letter-spacing:.42em; padding:.05in 0 .04in .42em; }
    .body { flex:1; display:flex; padding:.16in .25in .1in; gap:.22in; }
    .id { flex:1; min-width:0; display:flex; flex-direction:column; }
    .name { font-size:27px; font-weight:800; line-height:1.12; letter-spacing:.01em; overflow:hidden; text-overflow:ellipsis; }
    .company { font-size:15px; font-weight:600; color:#334155; margin-top:.03in; }
    .rows { margin-top:.11in; border-top:1.5px solid #cbd5e1; }
    .row { display:flex; padding:.05in 0; border-bottom:1px solid #e2e8f0; font-size:11.5px; }
    .row .k { width:1.05in; flex:none; font-size:8.5px; font-weight:700; letter-spacing:.14em; color:#64748b; text-transform:uppercase; padding-top:2px; }
    .row .v { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .qrcol { width:1.72in; flex:none; display:flex; flex-direction:column; align-items:center; justify-content:flex-start; }
    .qrbox { border:2.5px solid #0f2a52; border-radius:.08in; padding:.06in; background:#fff; }
    .qrbox img { width:1.44in; height:1.44in; display:block; }
    .scan { font-size:8px; font-weight:700; letter-spacing:.18em; color:#0f2a52; margin-top:.05in; text-align:center; }
    .validity { display:flex; justify-content:space-between; align-items:center; background:#eef2f7; border-top:2px solid #0f2a52; padding:.07in .25in; }
    .validity .cell { font-size:10.5px; font-weight:700; }
    .validity .cell small { display:block; font-size:7.5px; font-weight:700; letter-spacing:.16em; color:#64748b; }
    .validity .exp { color:#b91c1c; }
    .foot { background:#0f2a52; color:#fff; font-size:7.5px; letter-spacing:.05em; padding:.05in .25in; display:flex; justify-content:space-between; opacity:.95; }
  </style></head><body><div class="badge">
    <div class="head"><span class="org">${esc(facility)}</span><span class="lbl">VISITOR ACCESS PASS</span></div>
    <div class="banner">VISITOR</div>
    <div class="body">
      <div class="id">
        <div class="name">${esc(visit.visitor_name || "Visitor")}</div>
        <div class="company">${esc(visit.company || "—")}</div>
        <div class="rows">
          <div class="row"><span class="k">Purpose</span><span class="v">${esc(visit.purpose || "—")}</span></div>
          <div class="row"><span class="k">Host</span><span class="v">${esc(visit.host || "—")}</span></div>
          <div class="row"><span class="k">Destination</span><span class="v">${esc(visit.destination || "—")}</span></div>
          <div class="row"><span class="k">Visit type</span><span class="v">${esc(visit.category || "walk-in")}</span></div>
        </div>
      </div>
      <div class="qrcol">
        <div class="qrbox"><img src="${r.qr_png}" alt="QR"></div>
        <div class="scan">SCAN AT KIOSK / DOOR</div>
      </div>
    </div>
    <div class="validity">
      <span class="cell"><small>ISSUED</small>${fmt(issued)}</span>
      <span class="cell exp"><small>EXPIRES</small>${exp ? fmt(exp) : "END OF DAY"}</span>
      <span class="cell"><small>BADGE ID</small>${esc(String(visit.id || "").slice(0, 8).toUpperCase() || "—")}</span>
    </div>
    <div class="foot"><span>ESCORT REQUIRED IN RESTRICTED AREAS · BADGE MUST BE WORN VISIBLY AT ALL TIMES</span><span>RETURN ON EXIT</span></div>
  </div></body></html>`;
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  document.body.appendChild(frame);
  frame.srcdoc = html;
  frame.onload = () => {
    const img = frame.contentDocument.querySelector(".qrbox img");
    const go = () => {
      try { frame.contentWindow.focus(); frame.contentWindow.print(); }
      catch { toast("Printing failed — use the Print badge button", "err"); }
      setTimeout(() => frame.remove(), 60000);
    };
    if (img && !img.complete) img.onload = go; else go();
  };
}


views.workforce = async (v) => {
  let badges, devices, visits, doors, batches, adjs, events;
  try {
    [badges, devices, visits, doors, batches, adjs, events] = await Promise.all([
      api("/workforce/badges"), api("/workforce/devices"), api("/visitor/visits"),
      api("/access/doors"), api("/workforce/payroll"),
      api("/workforce/adjustments"), api("/access/events")]);
  } catch (e) { v.innerHTML = `<div class="empty"><div class="big">🚫</div>${esc(e.message)}</div>`; return; }
  const pendVisits = visits.filter(x => x.status === "pending");
  const activeBadges = badges.filter(b => b.status === "active").length;
  const AGE = (iso) => iso ? new Date(iso).toLocaleString() : "—";
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="noc-lbl">ACTIVE BADGES</span><b>🪪 ${activeBadges} / ${badges.length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">ENROLLED KIOSKS</span><b>🖥 ${devices.filter(d => d.status === "enrolled").length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">VISITORS PENDING</span><b><span class="noc-led ${pendVisits.length ? "warn" : "ok"}"></span> ${pendVisits.length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">DOORS / GATES</span><b>🚪 ${doors.length}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">KIOSK PAGES</span><b><a href="/checkin" target="_blank" style="color:inherit">/checkin</a> · <a href="/visitor" target="_blank" style="color:inherit">/visitor</a></b></div>
  </div>

  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🪪 WORKER BADGES — QR contains only an opaque revocable token (zero PII)</span>
      <button class="btn small primary" id="wf-badge-add">➕ Issue badge</button></div>
    <div style="padding:0 14px 12px">${badges.length ? `<table class="noc-table">
      <tr><th>WORKER</th><th>STATUS</th><th>BADGE TOKEN</th><th>QR</th><th>ISSUED BY</th><th>LAST USED</th><th>EXPIRES</th><th></th></tr>
      ${badges.map(b => `<tr><td>${esc(b.worker_name)}</td>
        <td><span class="noc-led ${b.status === "active" ? "ok" : "err"}"></span> ${esc(b.status.toUpperCase())}${b.revoke_reason ? " · " + esc(b.revoke_reason) : ""}</td>
        <td style="white-space:nowrap">${b.token ? `<code style="font-size:10.5px;user-select:all;background:#0b1220;padding:2px 6px;border-radius:4px">${esc(b.token)}</code>
          <button class="btn small tok-copy" data-tok="${esc(b.token)}" title="Copy token">📋</button>` : "—"}</td>
        <td>${b.qr_png ? `<img src="${b.qr_png}" class="wf-qr-zoom" data-n="${esc(b.worker_name)}" data-png="${b.qr_png}" title="Click to enlarge / save" style="width:44px;height:44px;background:#fff;padding:2px;border-radius:4px;cursor:zoom-in;vertical-align:middle">` : "—"}</td>
        <td>${esc(b.issued_by)}</td><td>${AGE(b.last_used_at)}${b.last_used_site ? " @ " + esc(b.last_used_site) : ""}</td>
        <td>${b.expires_at ? AGE(b.expires_at) : "never"}</td>
        <td>${b.status === "active" ? `<button class="btn small danger wf-badge-rev" data-id="${b.id}">🔒 Revoke</button>` : ""}</td></tr>`).join("")}
    </table>` : `<div class="empty">No badges issued yet.</div>`}</div>
  </div>

  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🖥 KIOSK DEVICE FLEET — single-use enrollment codes, device-bound credentials, remote revocation</span>
      <button class="btn small" id="wf-dev-add">➕ Enrollment code</button></div>
    <div style="padding:0 14px 12px">${devices.length ? `<table class="noc-table">
      <tr><th>NAME</th><th>KIND</th><th>SITE</th><th>STATUS</th><th>ENROLL CODE</th><th>QR</th><th>LAST SEEN</th><th></th></tr>
      ${devices.map(d => `<tr><td>${esc(d.name)}</td><td>${d.kind === "visitor" ? "🛂 visitor" : "⏱ check-in"}</td>
        <td>${esc(d.site)}</td><td><span class="noc-led ${d.status === "enrolled" ? "ok" : d.status === "pending" ? "warn" : "err"}"></span> ${esc(d.status.toUpperCase())}</td>
        <td style="white-space:nowrap">${d.enroll_code ? `<code style="font-size:10.5px;user-select:all;background:#0b1220;padding:2px 6px;border-radius:4px">${esc(d.enroll_code)}</code>
          <button class="btn small tok-copy" data-tok="${esc(d.enroll_code)}" title="Copy code">📋</button>` : d.status === "pending" ? `<span style="opacity:.5">expired</span>` : "—"}</td>
        <td>${d.code_qr_png ? `<img src="${d.code_qr_png}" class="wf-qr-zoom" data-n="${esc(d.name)}" data-png="${d.code_qr_png}" title="Click to enlarge / save" style="width:44px;height:44px;background:#fff;padding:2px;border-radius:4px;cursor:zoom-in;vertical-align:middle">` : "—"}</td>
        <td>${AGE(d.last_seen_at)}</td>
        <td>${d.status !== "revoked" ? `<button class="btn small danger wf-dev-rev" data-id="${d.id}">🔒 Revoke</button>` : ""}</td></tr>`).join("")}
    </table>` : `<div class="empty">No kiosks enrolled — generate an enrollment code and enter it on the kiosk (/checkin or /visitor).</div>`}</div>
  </div>

  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🛂 VISITOR REVIEW CONSOLE — approve/deny; identity numbers always masked</span></div>
    <div style="padding:0 14px 12px">${visits.length ? `<table class="noc-table">
      <tr><th>PHOTO</th><th>VISITOR</th><th>COMPANY</th><th>TYPE</th><th>HOST</th><th>PURPOSE</th><th>DESTINATION</th><th>ID DOC</th><th>STATUS</th><th></th></tr>
      ${visits.slice(0, 30).map(x => `<tr class="wf-visit-row" data-vid="${x.id}" title="Double-click for the full visitor dossier" style="cursor:pointer">
        <td>${x.face_photo ? `<img src="${x.face_photo}" class="wf-face-zoom" data-n="${esc(x.visitor_name)}" data-png="${x.face_photo}" title="Click to enlarge" style="width:42px;height:56px;object-fit:cover;border-radius:6px;cursor:zoom-in;vertical-align:middle;border:1px solid #2c3c63">` : `<span style="opacity:.35">—</span>`}</td>
        <td>${esc(x.visitor_name)}</td><td>${x.company ? esc(x.company) : `<span style="opacity:.35">—</span>`}</td><td>${esc(x.category)}</td>
        <td>${esc(x.host)}</td><td>${esc(x.purpose)}</td><td>${esc(x.destination)}</td>
        <td style="white-space:nowrap">${esc(x.id_doc_type)}${x.id_number_masked ? " · " + esc(x.id_number_masked) : ""}
          ${(x.doc_images || []).map((di, i) => `<img src="${di.image}" class="wf-face-zoom" data-n="${esc(x.visitor_name)} — ${esc(di.label)}" data-png="${di.image}" title="${esc(di.label)} — click to enlarge" style="width:34px;height:22px;object-fit:cover;border-radius:3px;cursor:zoom-in;vertical-align:middle;margin-left:4px;border:1px solid #2c3c63">`).join("")}</td>
        <td><span class="noc-led ${x.status === "checked_in" || x.status === "approved" ? "ok" : x.status === "pending" ? "warn" : "err"}"></span> ${esc(x.status.toUpperCase())}</td>
        <td style="white-space:nowrap">${x.status === "pending" ? `
          <button class="btn small wf-visit-ok" data-id="${x.id}">✅ Approve</button>
          <button class="btn small danger wf-visit-no" data-id="${x.id}">⛔ Deny</button>` : ""}${
          (x.status === "approved" || x.status === "checked_in") &&
          new Date(x.checked_in_at || x.created_at).toDateString() === new Date().toDateString()
            ? `<button class="btn small wf-visit-reprint" data-id="${x.id}" title="Rotate the badge code and print a fresh label — the old QR stops working">🖨 Reprint badge</button>` : ""}</td></tr>`).join("")}
    </table>` : `<div class="empty">No visitor registrations yet — visitors register on the /visitor kiosk.</div>`}</div>
  </div>

  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">⏱ TIMECARDS & PAYROLL — Raw punches → approval → idempotent batch → journal</span>
      <span style="display:flex;gap:8px">
        <button class="btn small" id="wf-tc">📋 Timecard lookup</button>
        <button class="btn small primary" id="wf-pay">💰 Build payroll batch</button></span></div>
    <div style="padding:0 14px 12px">
      ${adjs.filter(a => a.status === "pending").length ? `<div style="margin-bottom:10px"><b style="font-size:12px">PENDING ADJUSTMENTS</b>
        <table class="noc-table"><tr><th>WORKER</th><th>DAY</th><th>Δ MIN</th><th>REASON</th><th></th></tr>
        ${adjs.filter(a => a.status === "pending").map(a => `<tr><td>${esc(a.worker)}</td><td>${esc(a.day)}</td>
          <td>${a.minutes_delta > 0 ? "+" : ""}${a.minutes_delta}</td><td>${esc(a.reason)}</td>
          <td><button class="btn small wf-adj" data-id="${a.id}" data-ok="1">✅</button>
              <button class="btn small danger wf-adj" data-id="${a.id}" data-ok="0">✕</button></td></tr>`).join("")}</table></div>` : ""}
      ${batches.length ? `<table class="noc-table"><tr><th>PERIOD</th><th>STATUS</th><th>GROSS</th><th>APPROVED BY</th><th></th></tr>
        ${batches.map(b => `<tr><td>${esc(b.period_start)} → ${esc(b.period_end)}</td>
          <td><span class="noc-led ${b.status === "posted" ? "ok" : "warn"}"></span> ${esc(b.status.toUpperCase())}</td>
          <td>$${b.total_gross.toFixed(2)}</td><td>${esc(b.approved_by || "—")}</td>
          <td style="white-space:nowrap">${b.status === "draft" ? `<button class="btn small wf-pay-post" data-id="${b.id}">📒 Approve & post</button>` : ""}
            <a class="btn small" href="/api/workforce/payroll/${b.id}/export.csv">⬇ CSV</a></td></tr>`).join("")}</table>`
      : `<div class="empty">No payroll batches yet.</div>`}</div>
  </div>

  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🚪 DOORS & ACCESS EVENTS — advisory decisions; life-safety hardware behavior is never overridden</span>
      <button class="btn small" id="wf-door-add">➕ Door / gate</button></div>
    <div style="padding:0 14px 12px;display:grid;grid-template-columns:1fr 1.4fr;gap:14px">
      <div>${doors.length ? `<table class="noc-table"><tr><th>DOOR</th><th>ZONE</th><th>MODE</th><th>VISITORS</th></tr>
        ${doors.map(d => `<tr><td>${esc(d.name)}</td><td>${esc(d.zone)}</td><td>${esc(d.mode)}</td>
          <td>${d.allow_visitors ? "✅" : "—"}</td></tr>`).join("")}</table>` : `<div class="empty">No doors configured.</div>`}</div>
      <div>${events.length ? `<table class="noc-table"><tr><th>WHEN</th><th>SUBJECT</th><th>DECISION</th><th>REASON</th></tr>
        ${events.slice(0, 15).map(e => `<tr><td>${new Date(e.at).toLocaleTimeString()}</td>
          <td>${e.subject_kind === "visitor" ? "🛂" : "🪪"} ${esc(e.subject_name || "unknown")}</td>
          <td><span class="noc-led ${e.decision === "allow" ? "ok" : "err"}"></span> ${e.decision.toUpperCase()}</td>
          <td><code style="font-size:10.5px">${esc(e.reason)}</code></td></tr>`).join("")}</table>` : `<div class="empty">No access events yet.</div>`}</div>
    </div>
  </div>`;

  $("#wf-badge-add").onclick = async () => {
    // Directory = Worker Information (HR) records — badges may only be
    // issued to verified, non-terminated staff.
    let people = [];
    try {
      people = (await api("/business/records?module=workers"))
        .filter(r => String(r.data.status || "active") !== "terminated")
        .map(r => ({ name: String(r.data.name || ""), title: String(r.data.role || ""),
                     status: String(r.data.status || "active") }))
        .filter(p => p.name);
    } catch {}
    modal("🪪 Issue Worker Badge — Enterprise Credential",
    `<div style="font-size:11px;opacity:.6;letter-spacing:.04em;line-height:1.7;margin-bottom:10px;padding:8px 12px;background:#0b1220;border:1px solid #22304e;border-radius:8px">
       🔒 The badge QR contains only an opaque revocable token — zero personal data.
       Identity is verified against <b>Worker Information (HR)</b> before issuance.</div>
     <label style="position:relative;display:block"><span class="noc-lbl">WORKER NAME — HR DIRECTORY</span>
       <input data-f="worker_name" required autocomplete="off" placeholder="Start typing to search HR directory…">
       <div id="wfb-suggest" style="display:none;position:absolute;left:0;right:0;top:100%;z-index:60;max-height:190px;overflow:auto;background:#0e1730;border:1px solid #2c3c63;border-radius:8px;box-shadow:0 12px 30px rgba(0,0,0,.5)"></div>
       <span style="font-size:10px;opacity:.55;letter-spacing:.02em">Must match a record in Worker Information (HR) — pick from the suggestions</span></label>
     <label style="display:block;margin-top:12px"><span class="noc-lbl">CREDENTIAL VALIDITY</span>
       <select data-f="expires_days">
         <option value="0">♾ Permanent — until revoked</option>
         <option value="1">1 day (temporary cover)</option>
         <option value="7">7 days (probation / contractor)</option>
         <option value="30">30 days</option>
         <option value="90">90 days (quarterly re-issue policy)</option>
         <option value="365">1 year (annual re-issue policy)</option></select>
       <span style="font-size:10px;opacity:.55;letter-spacing:.02em">Expired badges are denied automatically at every kiosk and door</span></label>`,
    async () => {
      const body = {}; $$("#modal-root [data-f]").forEach(el => body[el.dataset.f] = el.value);
      const w = String(body.worker_name || "").trim();
      if (!w) throw new Error("Worker name is required");
      if (!people.some(p => p.name.toLowerCase() === w.toLowerCase()))
        throw new Error(`"${w}" is not in Worker Information (HR) — pick a name from the suggestions`);
      const r = await api("/workforce/badges", { method: "POST", body });
      toast("🪪 Badge issued for " + w);
      const fname = "badge_" + (body.worker_name || "worker").replace(/[^\w-]+/g, "_") + ".png";
      modal("🔑 Badge token — shown only once",
        `<p>Encode this token as the worker's QR badge. It contains no personal data and can be revoked instantly.</p>
         ${r.qr_png ? `<div style="text-align:center;margin:8px 0">
            <img src="${r.qr_png}" alt="Badge QR" style="width:220px;height:220px;background:#fff;padding:8px;border-radius:8px"><br>
            <a class="btn small primary" download="${fname}" href="${r.qr_png}" style="margin-top:8px;display:inline-block">⬇ Save QR image</a>
          </div>` : ""}
         <pre style="user-select:all;background:#0b1220;padding:10px;border-radius:6px">${esc(r.badge_token)}</pre>`, null);
      render(); // refresh the badge list behind the token modal
    }, "Issue");
    // live HR-directory suggestion box under the worker name input
    const inp = $("#modal-root [data-f=worker_name]"), sug = $("#wfb-suggest");
    if (inp && sug) {
      const show = () => {
        const q = inp.value.trim().toLowerCase();
        const hits = people.filter(p => !q || p.name.toLowerCase().includes(q)).slice(0, 8);
        if (!hits.length) {
          sug.innerHTML = `<div style="padding:8px 12px;opacity:.55;font-size:11.5px">No matching worker in Worker Information (HR)</div>`;
          sug.style.display = "";
          return;
        }
        sug.innerHTML = hits.map(p => `<div class="wfb-opt" data-n="${esc(p.name)}" style="padding:8px 12px;cursor:pointer;display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #1b2745">
          <span>👷 ${esc(p.name)}</span><span style="opacity:.5;font-size:11px">${esc(p.title)}${p.status !== "active" ? " · " + esc(p.status.toUpperCase()) : ""}</span></div>`).join("");
        sug.style.display = "";
        sug.querySelectorAll(".wfb-opt").forEach(o => {
          o.onmouseenter = () => o.style.background = "#1b2745";
          o.onmouseleave = () => o.style.background = "";
          o.onpointerdown = (ev) => { ev.preventDefault(); inp.value = o.dataset.n; sug.style.display = "none"; };
        });
      };
      inp.oninput = show;
      inp.onfocus = show;
      inp.onblur = () => setTimeout(() => { sug.style.display = "none"; }, 150);
    }
  };
  $$(".wf-face-zoom").forEach(img => img.onclick = () => {
    modal(`🛂 Visitor photo — ${img.dataset.n}`,
      `<div style="text-align:center;margin:8px 0">
         <img src="${img.dataset.png}" alt="Visitor photo" style="width:280px;max-width:80vw;border-radius:12px;border:2px solid #2c3c63">
       </div>`, null);
  });
  $$(".wf-qr-zoom").forEach(img => img.onclick = () => {
    const fname = "badge_" + (img.dataset.n || "code").replace(/[^\w-]+/g, "_") + ".png";
    modal(`🪪 QR — ${img.dataset.n}`,
      `<div style="text-align:center;margin:8px 0">
         <img src="${img.dataset.png}" alt="QR" style="width:260px;height:260px;background:#fff;padding:10px;border-radius:10px"><br>
         <a class="btn small primary" download="${fname}" href="${img.dataset.png}" style="margin-top:10px;display:inline-block">⬇ Save QR image</a>
       </div>`, null);
  });
  $$(".tok-copy").forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.tok); toast("📋 Copied"); }
    catch { toast("❌ Clipboard blocked — select the text manually", "err"); }
  });
  $$(".wf-badge-rev").forEach(b => b.onclick = async () => {
    const reason = prompt("Revocation reason (lost / stolen / terminated / other):", "lost");
    if (reason === null) return;
    await api(`/workforce/badges/${b.dataset.id}/revoke`, { method: "POST", body: { reason } });
    toast("🔒 Badge revoked — effective immediately"); render();
  });
  $("#wf-dev-add").onclick = () => modal("🖥 Enroll Kiosk Device — Enterprise Provisioning",
    `<div style="font-size:11px;opacity:.6;letter-spacing:.04em;line-height:1.7;margin-bottom:10px;padding:8px 12px;background:#0b1220;border:1px solid #22304e;border-radius:8px">
       🔒 Zero-trust device onboarding — the code below works <b>exactly once</b>, expires in
       15 minutes and is exchanged on the device for a bound credential.
       The device can be revoked remotely at any time from the fleet table.</div>
     <label style="display:block"><span class="noc-lbl">KIOSK NAME</span>
       <input data-f="name" required autocomplete="off" placeholder="e.g. Main Entrance — Tablet 01">
       <span style="font-size:10px;opacity:.55;letter-spacing:.02em">Shown in the fleet table, audit log and every punch / visit recorded by this device</span></label>
     <label style="display:block;margin-top:12px"><span class="noc-lbl">DEVICE ROLE</span>
       <select data-f="kind">
         <option value="checkin">⏱ Worker Time Clock — badge scan IN / OUT (/checkin)</option>
         <option value="visitor">🛂 Visitor Reception — self-registration &amp; check-out (/visitor)</option></select>
       <span style="font-size:10px;opacity:.55;letter-spacing:.02em">Role-locked credential — a time-clock device can never act as a visitor kiosk, and vice-versa</span></label>
     <label style="display:block;margin-top:12px"><span class="noc-lbl">SITE / LOCATION</span>
       <input data-f="site" autocomplete="off" placeholder="e.g. HQ — Lobby, Warehouse B, Store #12">
       <span style="font-size:10px;opacity:.55;letter-spacing:.02em">Recorded on every punch and access event for multi-site reporting</span></label>`,
    async () => {
      const body = {}; $$("#modal-root [data-f]").forEach(el => body[el.dataset.f] = el.value);
      if (!String(body.name || "").trim()) throw new Error("Kiosk name is required");
      const r = await api("/workforce/devices/enroll-code", { method: "POST", body });
      const page = body.kind === "visitor" ? "/visitor" : "/checkin";
      modal("🔑 Enrollment Code — single use · expires in " + r.expires_minutes + " min",
        `<div style="font-size:11.5px;line-height:1.9;padding:8px 12px;background:#0b1220;border:1px solid #22304e;border-radius:8px;margin-bottom:8px">
           <b>DEPLOYMENT STEPS</b><br>
           1. On the kiosk device, open <a href="${secureOrigin()}${page}" target="_blank" style="color:#4f8ef7"><b>${secureOrigin()}${page}</b></a><br>
           2. Enter (or scan) the enrollment code below<br>
           3. The device exchanges it for a permanent bound credential — done<br>
           <span style="opacity:.6">The code self-destructs after first use or ${r.expires_minutes} minutes, whichever comes first.</span></div>
         ${r.qr_png ? `<div style="text-align:center;margin:8px 0">
            <img src="${r.qr_png}" alt="Enrollment QR" style="width:200px;height:200px;background:#fff;padding:8px;border-radius:8px"><br>
            <a class="btn small primary" download="enroll_${(body.name || 'kiosk').replace(/[^\w-]+/g, '_')}.png" href="${r.qr_png}" style="margin-top:8px;display:inline-block">⬇ Save QR image</a>
          </div>` : ""}
         <pre style="user-select:all;background:#0b1220;padding:10px;border-radius:6px">${esc(r.code)}</pre>`, null);
      render(); // refresh the device list behind the code modal
    }, "Generate code");
  $$(".wf-dev-rev").forEach(b => b.onclick = async () => {
    if (!confirm("Revoke this device? It must be re-enrolled with a new code.")) return;
    await api(`/workforce/devices/${b.dataset.id}/revoke`, { method: "POST", body: {} });
    toast("🔒 Device revoked"); render();
  });
  $$(".wf-visit-ok").forEach(b => b.onclick = async () => {
    const visit = visits.find(v => v.id === b.dataset.id) || {};
    const r = await api(`/visitor/visits/${b.dataset.id}/decide`, { method: "POST", body: { approve: true } });
    if (r.qr_png) {
      // enterprise label printer output — 6″ × 4″ landscape, auto-printed
      printVisitorBadge(visit, r);
      modal("🛂 Visitor badge — expires " + new Date(r.badge_expires_at).toLocaleTimeString(),
      `<p>The badge label (6″ × 4″ landscape) was sent to the printer automatically.</p>
       <div style="text-align:center;margin:8px 0">
         <img src="${r.qr_png}" alt="Visitor badge QR" style="width:200px;height:200px;background:#fff;padding:8px;border-radius:8px"><br>
         <button type="button" class="btn small primary" id="wf-badge-print" style="margin-top:8px">🖨 Print badge again</button>
         <a class="btn small" download="visitor_badge.png" href="${r.qr_png}" style="margin-top:8px;display:inline-block">⬇ Save QR image</a>
       </div>
       <pre style="user-select:all;background:#0b1220;padding:10px;border-radius:6px">${esc(r.badge_code)}</pre>`, null);
      const pb = $("#wf-badge-print");
      if (pb) pb.onclick = () => printVisitorBadge(visit, r);
    }
    else toast("✅ Visitor approved — badge expires " + new Date(r.badge_expires_at).toLocaleTimeString());
    render();
  });
  $$(".wf-visit-no").forEach(b => b.onclick = async () => {
    await api(`/visitor/visits/${b.dataset.id}/decide`, { method: "POST", body: { approve: false } });
    toast("⛔ Visitor denied"); render();
  });
  $$(".wf-visit-reprint").forEach(b => b.onclick = async () => {
    if (!confirm("Reprint this visitor badge? A NEW QR code is issued and the previously printed badge stops working immediately.")) return;
    const visit = visits.find(v => v.id === b.dataset.id) || {};
    try {
      const r = await api(`/visitor/visits/${b.dataset.id}/reprint`, { method: "POST", body: {} });
      printVisitorBadge(visit, r);
      toast("🖨 Badge reprinted for " + (visit.visitor_name || "visitor") + " — old QR revoked");
    } catch (e) { toast(e.message, "err"); }
  });
  // double-click a visitor row → full enterprise dossier
  $$(".wf-visit-row").forEach(row => row.ondblclick = (e) => {
    if (e.target.closest("button,img,a")) return;   // keep buttons/zooms intact
    const v = visits.find(x => x.id === row.dataset.vid);
    if (v) visitorDossier(v);
  });
  $$(".wf-adj").forEach(b => b.onclick = async () => {
    await api(`/workforce/adjustments/${b.dataset.id}/decide`, { method: "POST", body: { approve: b.dataset.ok === "1" } });
    toast(b.dataset.ok === "1" ? "✅ Adjustment approved" : "✕ Adjustment rejected"); render();
  });
  $("#wf-tc").onclick = () => modal("📋 Timecard lookup",
    `<label><span class="noc-lbl">WORKER NAME</span><input data-f="worker" required></label>
     <label><span class="noc-lbl">FROM (YYYY-MM-DD)</span><input data-f="day_from" value="${new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10)}"></label>
     <label><span class="noc-lbl">TO (YYYY-MM-DD)</span><input data-f="day_to" value="${new Date().toISOString().slice(0, 10)}"></label>`,
    async () => {
      const q = {}; $$("#modal-root [data-f]").forEach(el => q[el.dataset.f] = el.value);
      const tc = await api(`/workforce/timecard?worker=${encodeURIComponent(q.worker)}&day_from=${q.day_from}&day_to=${q.day_to}`);
      modal(`📋 ${esc(tc.worker)} — ${(tc.total_minutes / 60).toFixed(1)} h total`,
        `<table class="noc-table"><tr><th>DAY</th><th>MINUTES</th><th>PUNCHES</th><th>EXCEPTION</th></tr>
         ${Object.entries(tc.days).map(([d, x]) => `<tr><td>${d}</td><td>${x.minutes}</td><td>${x.punches}</td>
           <td>${x.missing_out ? "⚠ missing OUT" : ""}</td></tr>`).join("") || "<tr><td colspan=4>No time in range</td></tr>"}</table>`, null);
    }, "Look up");
  $("#wf-pay").onclick = () => modal("💰 Build payroll batch (idempotent per period)",
    `<label><span class="noc-lbl">PERIOD START</span><input data-f="period_start" value="${new Date(Date.now() - 13 * 864e5).toISOString().slice(0, 10)}"></label>
     <label><span class="noc-lbl">PERIOD END</span><input data-f="period_end" value="${new Date().toISOString().slice(0, 10)}"></label>
     <label><span class="noc-lbl">WAGES (worker=rate, one per line)</span><textarea data-f="wages" rows="3" placeholder="Alice Example=22.50"></textarea></label>`,
    async () => {
      const q = {}; $$("#modal-root [data-f]").forEach(el => q[el.dataset.f] = el.value);
      const wages = {};
      (q.wages || "").split("\n").forEach(l => { const m = l.split("="); if (m.length === 2) wages[m[0].trim()] = parseFloat(m[1]) || 0; });
      const r = await api("/workforce/payroll/batch", { method: "POST", body: { period_start: q.period_start, period_end: q.period_end, wages } });
      toast(r.existed ? "ℹ Batch already exists for this period (idempotent)" : `✅ Batch built — gross $${r.total_gross.toFixed(2)}`);
      render();
    }, "Build");
  $$(".wf-pay-post").forEach(b => b.onclick = async () => {
    if (!confirm("Approve & post this payroll batch to accounting? This creates a journal entry.")) return;
    const r = await api(`/workforce/payroll/${b.dataset.id}/post`, { method: "POST", body: {} });
    toast(r.posted ? "📒 Posted to accounting" : "ℹ Nothing to post"); render();
  });
  $("#wf-door-add").onclick = () => modal("🚪 New door / gate",
    `<label><span class="noc-lbl">NAME</span><input data-f="name" required></label>
     <label><span class="noc-lbl">ZONE</span><input data-f="zone"></label>
     <label><span class="noc-lbl">SITE</span><input data-f="site"></label>
     <label><span class="noc-lbl">SCHEDULE (HH:MM-HH:MM, blank = always)</span><input data-f="schedule" placeholder="08:00-18:00"></label>
     <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" data-f="allow_visitors" style="width:auto"> Allow approved visitors</label>`,
    async () => {
      const body = {}; $$("#modal-root [data-f]").forEach(el => body[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value);
      await api("/access/doors", { method: "POST", body });
      toast("✅ Door added"); render();
    }, "Create");
};

/* ---------------- Accounting ---------------- */
views.accounting = async (v) => {
  let accts, journals, pl, bs, cf;
  try {
    [accts, journals, pl, bs, cf] = await Promise.all([
      api("/accounting/accounts"), api("/accounting/journals"),
      api("/accounting/reports/pl"), api("/accounting/reports/balance"),
      api("/accounting/reports/cashflow")]);
  } catch (e) { v.innerHTML = `<div class="empty"><div class="big">🚫</div>${esc(e.message)}</div>`; return; }
  const yr = new Date().getFullYear();
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="noc-lbl">REVENUE YTD</span><b>$${pl.revenue.toLocaleString()}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">NET INCOME</span><b style="color:${pl.net_income >= 0 ? "#22c55e" : "#ef4444"}">$${pl.net_income.toLocaleString()}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">TOTAL ASSETS</span><b>$${bs.total_assets.toLocaleString()}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">BOOKS</span><b><span class="noc-led ${bs.balanced ? "ok" : "err"}"></span> ${bs.balanced ? "BALANCED" : "OUT OF BALANCE"}</b></div>
    <div class="noc-kpi"><span class="noc-lbl">DOUBLE ENTRY</span><b>✓ ENFORCED</b></div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">📚 GENERAL JOURNAL — draft → posted → reversal (no destructive edits)</span>
      <span><button class="btn small" id="je-add">➕ Journal entry</button>
      <a class="btn small primary" href="/api/accounting/export/xlsx?year=${yr}" target="_blank">📦 EXPORT TAX XLSX ${yr}</a></span></div>
    <div style="padding:0 14px 12px">${journals.length ? `<table class="noc-table"><tr><th>JE #</th><th>DATE</th><th>MEMO</th><th>AMOUNT</th><th>SOURCE</th><th>STATUS</th><th></th></tr>
      ${journals.map(j => `<tr><td>#${j.number}</td><td>${esc(j.at)}</td><td>${esc(j.memo.slice(0, 60))}</td><td>$${j.total.toFixed(2)}</td><td>${esc(j.source)}</td>
        <td><span class="noc-led ${j.status === "posted" ? "ok" : j.status === "reversed" ? "" : "warn"}"></span> ${j.status.toUpperCase()}</td>
        <td>${j.status === "draft" ? `<button class="btn small je-post" data-id="${j.id}">POST</button>` : ""}
        ${j.status === "posted" ? `<button class="btn small danger je-rev" data-id="${j.id}">↩ REVERSE</button>` : ""}</td></tr>`).join("")}</table>` : `<div class="empty">No journal entries yet — they are created automatically by invoice posting, or manually here.</div>`}</div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">📊 REPORTS</span></div>
    <div style="padding:10px 14px;display:grid;grid-template-columns:1fr 1fr;gap:14px">
      <div><span class="noc-lbl">PROFIT & LOSS ${yr}</span><table class="noc-table">
        <tr><td>Revenue</td><td style="text-align:right">$${pl.revenue.toFixed(2)}</td></tr>
        <tr><td>Cost of Goods Sold</td><td style="text-align:right">$${pl.cogs.toFixed(2)}</td></tr>
        <tr><td><b>Gross Profit</b></td><td style="text-align:right"><b>$${pl.gross_profit.toFixed(2)}</b></td></tr>
        <tr><td>Expenses</td><td style="text-align:right">$${pl.expenses.toFixed(2)}</td></tr>
        <tr><td><b>Net Income</b></td><td style="text-align:right"><b>$${pl.net_income.toFixed(2)}</b></td></tr></table>
        <span class="noc-lbl" style="display:block;margin-top:10px">CASH FLOW ${yr}</span><table class="noc-table">
        <tr><td>Beginning Cash</td><td style="text-align:right">$${cf.beginning_cash.toFixed(2)}</td></tr>
        <tr><td>Operating Activities</td><td style="text-align:right">$${cf.operating.toFixed(2)}</td></tr>
        <tr><td>Investing Activities</td><td style="text-align:right">$${cf.investing.toFixed(2)}</td></tr>
        <tr><td>Financing Activities</td><td style="text-align:right">$${cf.financing.toFixed(2)}</td></tr>
        <tr><td><b>Ending Cash</b></td><td style="text-align:right"><b>$${cf.ending_cash.toFixed(2)}</b></td></tr></table></div>
      <div><span class="noc-lbl">BALANCE SHEET</span><table class="noc-table">
        <tr><td>Total Assets</td><td style="text-align:right">$${bs.total_assets.toFixed(2)}</td></tr>
        <tr><td>Total Liabilities</td><td style="text-align:right">$${bs.total_liabilities.toFixed(2)}</td></tr>
        <tr><td>Total Equity</td><td style="text-align:right">$${bs.total_equity.toFixed(2)}</td></tr></table></div>
    </div>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">🧾 CHART OF ACCOUNTS (${accts.length})</span></div>
    <div style="padding:0 14px 12px;max-height:260px;overflow:auto"><table class="noc-table"><tr><th>#</th><th>ACCOUNT</th><th>TYPE</th></tr>
      ${accts.map(a => `<tr><td>${esc(a.number)}</td><td>${esc(a.name)}</td><td>${esc(a.type.toUpperCase())}</td></tr>`).join("")}</table></div>
  </div>`;

  $("#je-add").onclick = () => modal("➕ Journal Entry (must balance)",
    `<label><span class="noc-lbl">MEMO</span><input id="je-memo"></label>
     <label><span class="noc-lbl">LINES (one per line: account | debit | credit)</span>
     <textarea id="je-lines" rows="5" placeholder="6100 Utilities | 250 | 0\n1010 Bank Checking | 0 | 250"></textarea></label>
     <label>Post immediately <input type="checkbox" id="je-postnow" checked></label>`,
    async () => {
      const lines = $("#je-lines").value.split("\n").map(l => l.split("|").map(s => s.trim())).filter(a => a.length >= 3)
        .map(a => ({ account: a[0], debit: parseFloat(a[1]) || 0, credit: parseFloat(a[2]) || 0 }));
      await api("/accounting/journals", { method: "POST", body: { memo: $("#je-memo").value, lines, post: $("#je-postnow").checked } });
      toast("✅ Journal entry created"); render();
    }, "Create entry");
  $$(".je-post").forEach(b => b.onclick = async () => { await api(`/accounting/journals/${b.dataset.id}/post`, { method: "POST", body: {} }); toast("✅ Posted"); render(); });
  $$(".je-rev").forEach(b => b.onclick = async () => { if (!confirm("Create a reversing entry?")) return; await api(`/accounting/journals/${b.dataset.id}/reverse`, { method: "POST", body: {} }); toast("↩ Reversal created"); render(); });
};

views.approvals = async (v) => {
  const approvals = await api("/approvals");
  let smtpReady = false;
  try { const c = (await api("/config")).config; smtpReady = !!(c.smtp_host && c.smtp_username && c.smtp_password); } catch {}
  v.innerHTML = approvals.length ? approvals.map(a => {
    const d = a.draft;
    return `<div class="card" style="margin-bottom:14px">
      <h3>${a.kind === "send_email" ? "📧 Send email" : esc(a.kind)} <span class="pill ${esc(a.status)}">${esc(a.status)}</span></h3>
      <p class="muted" style="font-size:13px">${esc(a.summary)} · ${new Date(a.created_at).toLocaleString()}</p>
      ${d ? `<div class="email-review">
        <div class="row"><span class="k">From</span><b>${esc(d.from_address)}</b></div>
        <div class="row"><span class="k">To</span>${esc(d.to)}</div>
        ${d.cc ? `<div class="row"><span class="k">CC</span>${esc(d.cc)}</div>` : ""}
        <div class="row"><span class="k">Subject</span>${esc(d.subject)}</div>
        <pre>${esc(d.body)}</pre>
        <p class="muted" style="font-size:11px" id="email-provider-note">Delivery: checking…</p>
      </div>` : ""}
      ${a.status === "pending" ? `<div class="toolbar" style="margin-top:12px">
        <button class="btn success" data-approve="${a.id}">✓ Approve & execute</button>
        <button class="btn danger" data-reject="${a.id}">✗ Reject</button></div>` : ""}
    </div>`; }).join("")
    : `<div class="empty"><div class="big">🔔</div>No approval requests. Sensitive actions (like sending email) will appear here for your review.</div>`;
  $$("#email-provider-note", v).forEach(n => {
    n.innerHTML = smtpReady
      ? "Delivery: <b style='color:#22c55e'>REAL email via SMTP</b> — will be sent to the recipient's inbox"
      : "Delivery: <b style='color:#eab308'>⚠ SIMULATED (local-dev)</b> — no real email! Configure SMTP in ⚙️ Settings to enable real sending";
  });
  $$("[data-approve]", v).forEach(b => b.onclick = async () => {
    try {
      const r = await api(`/approvals/${b.dataset.approve}/approve`, { method: "POST" });
      if (r.ok && r.simulated) toast("⚠ Email was SIMULATED only — no real delivery! Configure SMTP in ⚙️ Settings (host/username/App Password) to send real email.", "err");
      else if (r.ok) toast(`Email sent for real ✓ provider ID: ${r.provider_message_id}`, "ok");
      else toast("Send failed: " + r.error, "err");
      refreshBadge(); render();
    } catch (e) { toast(e.message, "err"); }
  });
  $$("[data-reject]", v).forEach(b => b.onclick = async () => {
    await api(`/approvals/${b.dataset.reject}/reject`, { method: "POST" });
    toast("Rejected — draft cancelled", "ok"); refreshBadge(); render();
  });
};

/* ---------------- Skills ---------------- */
/* Skill wizard: guided 3-step creation with professional templates */
const SKILL_TEMPLATES = {
  "": { name: "", description: "", target: "both", instructions: "" },
  "basic": {
    name: "My first SkillScript plugin",
    description: "Dynamic skill written in SkillScript BASIC — computes its instructions at runtime.",
    target: "both",
    instructions: `PROGRAM DailyBriefing
' ═══ SkillScript BASIC — dynamic skill/plugin ═══
' Everything this program PRINTs becomes the live instructions
' injected into the agents. Full language: 40+ statements,
' 60+ functions — press \"\ud83d\udcd8 Language reference\" below.

CONST MAX_ITEMS = 5
LET today = WEEKDAY()

PRINT "## Daily context (generated " & NOW() & " on " & NODE$ & ")"

IF today = "Monday" THEN
  PRINT "* Start the week: summarize open tasks first."
ELSEIF today = "Friday" THEN
  PRINT "* End of week: include a weekly recap section in every report."
ELSE
  PRINT "* Mid-week focus: keep answers short and actionable."
ENDIF

' Persistent memory survives between runs
MEM GET runs = "briefing_runs"
LET runs = VAL(runs) + 1
MEM SET "briefing_runs", runs
LOG "run number " & runs

FOR i = 1 TO MAX_ITEMS
  PRINT "* Rule " & i & ": always cite the data source."
NEXT i

' Uncomment for live data / AI sub-calls (test-run only):
' HTTP news = GET "https://example.com/api/headlines"
' ASK summary = "Summarize in 3 bullets: " & news USING "codex"
' PRINT summary

END PROGRAM`
  },
  "suno": {
    name: "SUNO AI — GIMV rating, lyrics & style",
    description: "Rates songs with the GIMV framework and generates SUNO-ready lyrics + style prompts.",
    target: "both",
    instructions: `You are a SUNO AI music production expert.

WHEN THE USER ASKS FOR A SONG RATING — use the GIMV framework, scoring each 1-10 with a short justification:
  G — Genre fit: how well the track matches its target genre conventions.
  I — Impact: hook strength, memorability, emotional punch of the chorus.
  M — Musicality: melody, harmony, rhythm, structure, production quality.
  V — Vocals: vocal performance, clarity, delivery, style match.
Present as a table, give the total /40, and one paragraph of actionable improvement advice.

WHEN THE USER ASKS FOR LYRICS — output SUNO-compatible formatted lyrics:
  * Use section tags: [Intro], [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Outro].
  * Keep each line singable (max ~10 words); build clear rhyme schemes (AABB or ABAB).
  * The chorus must contain the title hook and repeat it at least twice.
  * Add vocal direction tags where useful: (whisper), (belt), (harmonies), (ad-lib).

WHEN THE USER ASKS FOR A STYLE PROMPT — produce a SUNO "Style of Music" string:
  * Comma-separated: genre, sub-genre, mood, tempo (BPM), key instruments, vocal type, production style.
  * Keep it under 120 characters, e.g. "melodic techno, dark, 124 BPM, analog synths, female ethereal vocals, cinematic".
  * Offer 3 variations: safe, adventurous, experimental.

Always answer in the language of the user's request. If information is missing (genre, mood, topic), ask one concise clarifying question first.`
  },
  "codestyle": {
    name: "Code style guide",
    description: "House rules for all generated code.",
    target: "both",
    instructions: "Always use type hints and docstrings. Prefer pathlib over os.path. Maximum line length 100. Write small pure functions. Add error handling with specific exception types — never bare except. Include usage examples in docstrings for public functions."
  },
  "brand": {
    name: "Brand voice & writing rules",
    description: "Tone and formatting for all outward-facing text (emails, documents).",
    target: "both",
    instructions: "Write in a professional, warm and concise tone. Use short paragraphs (max 3 sentences). Avoid jargon and buzzwords. Emails: greeting + 2-3 paragraphs + clear call-to-action + signature. Never overpromise; be specific with dates and numbers."
  },
  "imagestyle": {
    name: "Image style guide",
    description: "Visual style rules for all generated images.",
    target: "codex",
    instructions: "All generated images must use: modern minimal flat design, brand palette (deep navy #101826, electric blue #4f8ef7, white), generous whitespace, no stock-photo look, no watermarks or text unless requested. Prefer 16:9 for presentations and 1:1 for social."
  }
};

async function fillVersions() {
  try {
    const h = await fetch("/api/health").then(r => r.json());
    window.serverVersion = h.version;
    const cl = window.clientInfo;
    const txt = `Server v${h.version}` + (cl && cl.version ? ` · Client v${cl.version}` : "");
    const s = document.getElementById("ver-line"); if (s) s.textContent = txt;
    const a = document.getElementById("auth-ver"); if (a) a.textContent = txt;
  } catch { /* offline */ }
}

/* ---------------- backup & restore (all users) ---------------- */
/* ---------------- Calendar ---------------- */
let _calMonth = null; // Date at first of displayed month

views.calendar = async (v) => {
  if (!_calMonth) { const n = new Date(); _calMonth = new Date(n.getFullYear(), n.getMonth(), 1); }
  v.innerHTML = `<div class="card">
      <div class="toolbar" style="justify-content:space-between">
        <div><button class="btn" id="cal-prev">◀</button>
          <b id="cal-title" style="margin:0 10px;font-size:16px"></b>
          <button class="btn" id="cal-next">▶</button>
          <button class="btn" id="cal-today" style="margin-left:8px">${t("Today")}</button></div>
        <button class="btn primary" id="cal-add">＋ ${t("New event")}</button>
      </div>
      <div id="cal-grid" style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:12px"></div>
      <p class="muted" style="font-size:12.5px;margin-top:10px">💡 ${t("You can also manage events by prompt in any chat")}: <code>add event "Dentist" on 2026-08-20 at 10am</code> · <code>move the dentist appointment to 3pm</code> · <code>cancel the dentist event</code></p>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>🍎 ${t("iCloud account — two-way sync")}</h3>
      <p class="muted" style="font-size:13px">${t("Only Apple iCloud Calendar is supported. Connect your iCloud account once and your calendar stays in sync everywhere: events created, edited or deleted in this program are pushed to iCloud automatically (and appear on your iPhone, iPad and Mac), and Sync now pulls new iCloud events into this program.")}</p>
      <p class="muted" style="font-size:11.5px;margin:4px 0 8px">${t("Apple offers no OAuth for iCloud Calendar — the official third-party method is an app-specific password. Create one at appleid.apple.com → Sign-In and Security → App-Specific Passwords, then sign in below. The password is stored encrypted and can be revoked at appleid.apple.com anytime.")}</p>
      <div id="ic-acct" style="font-size:12.5px;margin-bottom:8px"><span class="muted">⏳</span></div>
      <div class="toolbar" style="gap:8px;flex-wrap:wrap" id="ic-login-row">
        <input type="email" id="ic-id" placeholder="${t('Apple ID (email)')}" style="flex:1;min-width:150px;font-size:12.5px" autocomplete="off">
        <input type="password" id="ic-pw" placeholder="${t('app-specific password')}" style="flex:1;min-width:150px;font-size:12.5px" autocomplete="new-password">
        <button class="btn primary" id="ic-import">🍎 ${t("Sign in & import")}</button>
      </div>
      <div class="toolbar" style="gap:8px;margin-top:6px">
        <button class="btn primary hidden" id="ic-sync">🔄 ${t("Sync now (both directions)")}</button>
        <button class="btn hidden" id="ic-disconnect">✖ ${t("Disconnect")}</button>
      </div>
      <div id="ic-import-res" class="muted" style="font-size:12.5px;margin-top:8px"></div>
    </div>`;

  let events = [];
  const load = async () => { events = (await api("/calendar/events")).events; drawGrid(); };

  const drawGrid = () => {
    const grid = $("#cal-grid"); if (!grid) return;
    const y = _calMonth.getFullYear(), m = _calMonth.getMonth();
    $("#cal-title").textContent = _calMonth.toLocaleDateString(undefined, { year: "numeric", month: "long" });
    const dows = [];
    for (let i = 0; i < 7; i++) dows.push(new Date(2024, 0, i + 1).toLocaleDateString(undefined, { weekday: "short" }));
    const first = new Date(y, m, 1), startDow = first.getDay();
    const days = new Date(y, m + 1, 0).getDate();
    const today = new Date(); today.setHours(0, 0, 0, 0);
    let html = dows.map(d => `<div class="muted" style="text-align:center;font-size:12px;padding:4px">${esc(d)}</div>`).join("");
    for (let i = 0; i < startDow; i++) html += "<div></div>";
    for (let d = 1; d <= days; d++) {
      const cur = new Date(y, m, d);
      const dayEvs = events.filter(e => {
        const s = new Date(e.start_at); return s.getFullYear() === y && s.getMonth() === m && s.getDate() === d;
      });
      const isToday = cur.getTime() === today.getTime();
      html += `<div class="cal-day" data-day="${d}" style="min-height:76px;border:1px solid var(--border);border-radius:8px;padding:4px;cursor:pointer;${isToday ? "outline:2px solid var(--accent)" : ""}">
        <div style="font-size:12px;font-weight:600;${isToday ? "color:var(--accent)" : ""}">${d}</div>
        ${dayEvs.slice(0, 3).map(e => `<div class="cal-ev" data-ev="${e.id}" title="${esc(e.title)}" style="font-size:11px;background:var(--accent);color:#fff;border-radius:4px;padding:1px 4px;margin-top:2px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${e.all_day ? "" : new Date(e.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + " "}${esc(e.title)}</div>`).join("")}
        ${dayEvs.length > 3 ? `<div class="muted" style="font-size:10px">+${dayEvs.length - 3}</div>` : ""}
      </div>`;
    }
    grid.innerHTML = html;
    grid.querySelectorAll(".cal-ev").forEach(el => {
      el.onclick = ev => { ev.stopPropagation(); editEvent(events.find(e => e.id === el.dataset.ev)); };
    });
    grid.querySelectorAll(".cal-day").forEach(el => {
      el.onclick = () => editEvent(null, new Date(y, m, +el.dataset.day, 9, 0));
    });
  };

  const editEvent = (ev, defStart) => {
    const s = ev ? new Date(ev.start_at) : (defStart || new Date());
    const e2 = ev ? new Date(ev.end_at) : new Date(s.getTime() + 3600000);
    const dstr = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const tstr = d => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    modal(ev ? t("Edit event") : t("New event"), `
      <label>${t("Title")}<input name="title" required value="${ev ? esc(ev.title) : ""}"></label>
      <label>${t("Date")}<input type="date" name="date" required value="${dstr(s)}"></label>
      <div style="display:flex;gap:10px"><label style="flex:1">${t("Start")}<input type="time" name="st" value="${tstr(s)}"></label>
      <label style="flex:1">${t("End")}<input type="time" name="et" value="${tstr(e2)}"></label></div>
      <label><input type="checkbox" name="allday" ${ev && ev.all_day ? "checked" : ""}> ${t("All day")}</label>
      <label>${t("Location")}<input name="location" value="${ev ? esc(ev.location || "") : ""}"></label>
      <label>${t("Description")}<textarea name="description" rows="2">${ev ? esc(ev.description || "") : ""}</textarea></label>
      ${ev ? `<button type="button" class="btn" id="cal-del" style="color:var(--red)">🗑 ${t("Delete event")}</button>` : ""}`,
      async fd => {
        const allday = !!fd.get("allday");
        const body = {
          title: fd.get("title"), location: fd.get("location"), description: fd.get("description"),
          all_day: allday,
          start_at: fd.get("date") + "T" + (allday ? "00:00" : fd.get("st") || "09:00"),
          end_at: fd.get("date") + "T" + (allday ? "23:59" : fd.get("et") || fd.get("st") || "10:00"),
        };
        if (ev) await api("/calendar/events/" + ev.id, { method: "PUT", body });
        else await api("/calendar/events", { method: "POST", body });
        toast(t("Event saved"), "ok");
        load();
      });
    const del = $("#cal-del");
    if (del) del.onclick = async () => {
      if (!confirm(t("Delete this event?"))) return;
      await api("/calendar/events/" + ev.id, { method: "DELETE" });
      $("#modal-root").innerHTML = "";
      toast(t("Event deleted"), "ok"); load();
    };
  };

  $("#cal-prev").onclick = () => { _calMonth = new Date(_calMonth.getFullYear(), _calMonth.getMonth() - 1, 1); drawGrid(); };
  $("#cal-next").onclick = () => { _calMonth = new Date(_calMonth.getFullYear(), _calMonth.getMonth() + 1, 1); drawGrid(); };
  $("#cal-today").onclick = () => { const n = new Date(); _calMonth = new Date(n.getFullYear(), n.getMonth(), 1); drawGrid(); };
  $("#cal-add").onclick = () => editEvent(null);

  load();

  /* Cloud calendar accounts (CalDAV + app password): iCloud & Google */
  const wireCloud = (px, ep, name) => {
    const acctBox = $(`#${px}-acct`);
    const refresh = async () => {
      if (!acctBox) return;
      try {
        const a = await api(`/calendar/${ep}/account`);
        const syncBtn = $(`#${px}-sync`), discBtn = $(`#${px}-disconnect`), row = $(`#${px}-login-row`);
        if (a.connected) {
          acctBox.innerHTML = `✅ ${t("Connected as")} <b>${esc(a.label)}</b>` +
            (a.last_sync_at ? ` <span class="muted">· ${t("last sync")} ${new Date(a.last_sync_at + "Z").toLocaleString()}</span>` : "");
          syncBtn.classList.remove("hidden"); discBtn.classList.remove("hidden");
          row.classList.add("hidden");
        } else if (a.status === "error") {
          acctBox.innerHTML = `⚠️ <b>${esc(a.label)}</b> — ${esc(a.last_error || t("sync error"))} · ${t("sign in again below")}`;
          syncBtn.classList.add("hidden"); discBtn.classList.remove("hidden");
          row.classList.remove("hidden");
        } else {
          acctBox.innerHTML = `<span class="muted">${t("Not connected")}</span>`;
          syncBtn.classList.add("hidden"); discBtn.classList.add("hidden");
          row.classList.remove("hidden");
        }
      } catch { acctBox.textContent = ""; }
    };
    refresh();

    const impBtn = $(`#${px}-import`);
    if (impBtn) impBtn.onclick = async () => {
      const res = $(`#${px}-import-res`);
      const apple_id = ($(`#${px}-id`).value || "").trim();
      const app_password = ($(`#${px}-pw`).value || "").trim();
      if (!apple_id || !app_password) { res.textContent = t("Enter the account email and app password."); return; }
      res.textContent = "⏳ " + t("Signing in and downloading calendars… (can take ~15s)");
      impBtn.disabled = true;
      try {
        const j = await api(`/calendar/${ep}/import`, { method: "POST", body: { apple_id, app_password, save: true } });
        res.innerHTML = `✅ ${t("Imported")} <b>${j.imported}</b> ${t("event(s)")}, ${t("skipped")} ${j.skipped} ${t("duplicate(s)")}. ${t("Account connected — events you create here now sync automatically.")}`;
        $(`#${px}-pw`).value = "";
        toast(`${name} ${t("connected ✓")}`, "ok");
        load(); refresh();
      } catch (e) { res.textContent = "❌ " + e.message; }
      impBtn.disabled = false;
    };

    const syncBtn = $(`#${px}-sync`);
    if (syncBtn) syncBtn.onclick = async () => {
      const res = $(`#${px}-import-res`);
      res.textContent = `⏳ ${t("Syncing both directions with")} ${name}…`;
      syncBtn.disabled = true;
      try {
        const j = await api(`/calendar/${ep}/sync`, { method: "POST" });
        res.innerHTML = `✅ ${t("Pulled")} <b>${j.pulled.imported}</b>, ${t("pushed")} <b>${j.pushed}</b>.` +
          (j.last_error ? ` ⚠️ ${esc(j.last_error)}` : "");
        toast(`${name} ${t("synced ✓")}`, "ok");
        load(); refresh();
      } catch (e) { res.textContent = "❌ " + e.message; }
      syncBtn.disabled = false;
    };

    const discBtn = $(`#${px}-disconnect`);
    if (discBtn) discBtn.onclick = async () => {
      if (!confirm(`${t("Disconnect the account? Stored credentials are deleted.")}`)) return;
      await api(`/calendar/${ep}/account`, { method: "DELETE" });
      $(`#${px}-import-res`).textContent = "";
      toast(`${name} ${t("disconnected")}`, "ok");
      refresh();
    };
  };
  wireCloud("ic", "icloud", "iCloud");
};

views.backup = async (v) => {
  v.innerHTML = `<div class="grid cols-3">
    <div class="card">
      <h3>⬇ Export backup</h3>
      <p class="muted" style="font-size:13px">Download <b>everything ${state.user.is_admin ? "on this server (all users, licenses, settings and business data)" : "you own"}</b> — chats &amp; conversations, skills, companies, employees, tasks, projects and schedules — as a single JSON file. Keep it somewhere safe.</p>
      <a class="btn primary" href="/api/backup/export" download style="display:inline-block;text-decoration:none">⬇ Download backup file</a>
    </div>
    <div class="card">
      <h3>⬆ Import / restore</h3>
      <p class="muted" style="font-size:13px">Reinstalled the system or the program? Restore a previously exported backup file here — all your settings, chats, skills and data come back. Existing records with the same ID are updated, nothing is duplicated.</p>
      <input type="file" id="bk-file" accept=".json" style="margin-bottom:10px">
      <button class="btn primary" id="bk-import">⬆ Restore backup</button>
      <p id="bk-result" class="muted" style="font-size:12.5px;margin-top:8px"></p>
    </div>
    <div class="card">
      <h3>⏰ Automatic backups (by prompt)</h3>
      <p class="muted" style="font-size:13px">Type <code>/backup</code> in any chat to snapshot everything you own on the server — or schedule it with a prompt like:</p>
      <pre style="font-size:12px;background:var(--bg);padding:10px;border-radius:8px;white-space:pre-wrap">every day at 2am /backup</pre>
      <p class="muted" style="font-size:13px">The agent turns that into a cron job (see ⏰ Schedules); each run saves a snapshot to <code>platform/data/backups/</code> (the 30 most recent are kept).</p>
      <button class="btn" id="bk-snap">📸 Snapshot now (server-side)</button>
      <p id="bk-snap-out" class="muted" style="font-size:12.5px;margin-top:8px"></p>
    </div>
  </div>
  ${state.user.is_admin ? `
  <div class="card" style="margin-top:16px">
    <h3>🚚 Migration set — move NexaCrew to another computer</h3>
    <p class="muted" style="font-size:13px">Creates a complete migration package on a USB flash drive: the whole
      program, a full data backup and automatic installers for <b>Windows, macOS (10.8 Mountain Lion or newer) and
      Linux</b>. The installer detects the target OS version and installs a compatible Python automatically
      (e.g. Windows 7 → Python 3.8 · Windows 8/8.1 → 3.9 · Windows 10/11 → 3.12 · minimum Python 3.4).</p>
    <div id="mig-usb" style="margin:10px 0"><span class="muted">🔌 Plug in a USB flash drive — detecting…</span></div>
    <div class="toolbar"><button class="btn primary" id="mig-start" disabled>🚚 Start migrating</button></div>
    <div id="mig-prog" class="hidden" style="margin-top:10px">
      <div class="progress-info" style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:5px">
        <span id="mig-step">Preparing…</span><b id="mig-pct">0%</b></div>
      <div class="pbar"><div class="pbar-fill" id="mig-bar" style="width:0%"></div></div>
    </div>
    <div id="mig-result" class="hidden" style="margin-top:12px"></div>
  </div>` : ""}`;
  /* ---- migration UI (admin) ---- */
  if (state.user.is_admin) {
    let usbSel = null;
    const usbBox = $("#mig-usb"), startBtn = $("#mig-start");
    const pollUsb = async () => {
      if (state.view !== "backup" || !usbBox.isConnected) { clearInterval(window._migUsbPoll); return; }
      try {
        const { drives } = await api("/migration/usb");
        if (!drives.length) {
          usbBox.innerHTML = `<span class="muted">🔌 No USB flash drive detected — plug one in (checked automatically every 3 s)…</span>
            <button class="btn" id="mig-refresh" style="margin-left:8px">🔄 Check now</button>`;
          $("#mig-refresh").onclick = pollUsb;
          startBtn.disabled = true; usbSel = null; return;
        }
        if (!usbSel || !drives.find(d => d.path === usbSel)) usbSel = drives[0].path;
        usbBox.innerHTML = `✅ USB drive detected:
          <select id="mig-drive" style="margin:0 8px">${drives.map(d =>
            `<option value="${esc(d.path)}" ${d.path === usbSel ? "selected" : ""}>💾 ${esc(d.label)} — ${d.free_gb} GB free of ${d.total_gb} GB</option>`).join("")}</select>`;
        $("#mig-drive").onchange = e => { usbSel = e.target.value; };
        startBtn.disabled = false;
      } catch (e) {
        usbBox.innerHTML = `<span style="color:var(--red)">⚠ USB detection error: ${esc(e.message)}</span>
          <button class="btn" id="mig-refresh" style="margin-left:8px">🔄 Retry</button>`;
        $("#mig-refresh").onclick = pollUsb;
        startBtn.disabled = true;
      }
    };
    clearInterval(window._migUsbPoll);
    window._migUsbPoll = setInterval(pollUsb, 3000);
    pollUsb();

    const showResult = (st) => {
      const box = $("#mig-result");
      box.classList.remove("hidden");
      if (st.status === "error") {
        box.innerHTML = `<p style="color:var(--red)">❌ Migration failed: ${esc(st.error)}</p>`;
        return;
      }
      const r = st.result || {};
      box.innerHTML = `
        <p style="color:var(--green);font-weight:600">✅ Migration set created successfully!</p>
        <p style="font-size:13px">📦 File: <code>${esc(r.file || "")}</code> · ${r.size_mb} MB · ${r.files} program files + full data backup</p>
        <div style="background:var(--bg);border-radius:10px;padding:14px 18px;margin-top:8px">
          <b>📖 How to migrate to the new computer</b>
          <ol style="font-size:13px;line-height:1.8;margin:8px 0 0;padding-left:20px">
            <li>Safely eject this USB drive and plug it into the <b>new computer</b>.</li>
            <li>Unzip <code>${esc((r.file || "").split(/[\\/]/).pop() || "the migration zip")}</code> anywhere (e.g. the Desktop).</li>
            <li>Run the installer for the new computer's operating system:<br>
              🪟 <b>Windows</b> — double-click <code>install_windows.bat</code><br>
              🍎 <b>macOS</b> (10.8 Mountain Lion or newer) — Terminal: <code>sh install_mac_linux.sh</code><br>
              🐧 <b>Linux</b> — terminal: <code>sh install_mac_linux.sh</code></li>
            <li>The installer detects the OS version and <b>installs a compatible Python automatically</b>
              (Windows 7 → 3.8, Windows 8/8.1 → 3.9, Windows 10/11 → 3.12, macOS/Linux → newest supported; minimum 3.4).</li>
            <li>NexaCrew starts automatically with <b>all your data included</b> — sign in with your existing account.</li>
          </ol>
          <p class="muted" style="font-size:12px;margin-top:8px">A copy of these instructions is on the USB drive as <code>README_MIGRATION.txt</code>.</p>
        </div>`;
    };

    startBtn.onclick = async () => {
      if (!usbSel) return;
      startBtn.disabled = true;
      $("#mig-prog").classList.remove("hidden");
      $("#mig-result").classList.add("hidden");
      try { await api("/migration/start", { method: "POST", body: { usb_path: usbSel } }); }
      catch (e) { toast(e.message, "err"); startBtn.disabled = false; return; }
      const t = setInterval(async () => {
        try {
          const st = await api("/migration/status");
          $("#mig-step").textContent = st.step;
          $("#mig-pct").textContent = st.percent + "%";
          $("#mig-bar").style.width = st.percent + "%";
          if (st.status === "done" || st.status === "error") {
            clearInterval(t);
            startBtn.disabled = false;
            showResult(st);
            toast(st.status === "done" ? "🚚 Migration set ready ✓" : "Migration failed", st.status === "done" ? "ok" : "err");
          }
        } catch { /* transient */ }
      }, 800);
    };
  }
  $("#bk-import").onclick = async () => {
    const f = $("#bk-file").files[0];
    if (!f) { toast("Choose a backup .json file first", "err"); return; }
    const fd = new FormData();
    fd.append("file", f);
    $("#bk-result").textContent = "Restoring…";
    try {
      const r = await fetch("/api/backup/import", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || "Import failed");
      $("#bk-result").textContent = "✅ Restored: " + Object.entries(j.restored).map(([k, n]) => `${k} ${n}`).join(", ");
      toast("Backup restored ✓", "ok");
    } catch (e) { $("#bk-result").textContent = "❌ " + e.message; }
  };
  $("#bk-snap").onclick = async () => {
    try {
      const r = await api("/backup/snapshot", { method: "POST" });
      $("#bk-snap-out").textContent = "✅ Saved: " + r.path;
    } catch (e) { $("#bk-snap-out").textContent = "❌ " + e.message; }
  };
};

views.skills = async (v) => {
  const skills = await api("/skills");
  const targetLabel = { codex: "CODEX", claude: "CLAUDE CODE", both: "CODEX + CLAUDE" };
  const isPlug = (s) => /^\s*(\d+\s+)?PROGRAM\s/im.test((s.instructions.split("\n").find(l => l.trim() && !l.trim().startsWith("'") && !/^REM/i.test(l.trim()))) || "");
  const nPlug = skills.filter(isPlug).length;
  const nOn = skills.filter(s => s.enabled).length;
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Skills</span><span class="v">${skills.length}</span></div>
    <div class="noc-kpi"><span class="k">Enabled</span><span class="v" style="color:#22c55e">${nOn}</span></div>
    <div class="noc-kpi"><span class="k">Prompt</span><span class="v">${skills.length - nPlug}</span></div>
    <div class="noc-kpi"><span class="k">Plug-ins</span><span class="v">${nPlug}</span></div>
    <span class="spacer"></span>
    <button class="btn" id="new-plugin">New plug-in — SkillScript IDE</button>
    <button class="btn primary" id="new-skill">+ New skill</button>
  </div>
  <div class="noc-panel">
    <div class="noc-head"><span class="noc-lbl">AGENT CAPABILITY REGISTRY</span><span class="spacer"></span>
      <small>${state.user.is_admin ? "ADMIN VIEW · ALL USERS" : "PRIVATE · OWNER ONLY"}</small></div>
    <div class="noc-body" style="padding:0">
    ${skills.length ? `<table class="noc-table"><thead><tr>
      <th>SKILL</th><th style="width:96px">TYPE</th><th style="width:130px">TARGET</th><th style="width:80px">STATE</th>
      <th>DESCRIPTION</th><th style="width:90px">SIZE</th><th style="width:250px"></th></tr></thead><tbody>
      ${skills.map(s => {
        const plug = isPlug(s);
        return `<tr>
        <td><b>${esc(s.name)}</b></td>
        <td><span style="font-size:10px;font-family:Consolas,monospace;letter-spacing:1px;color:${plug ? "#a78bfa" : "#4f8ef7"};border:1px solid ${plug ? "#a78bfa" : "#4f8ef7"};border-radius:4px;padding:1.5px 7px">${plug ? "PLUG-IN" : "PROMPT"}</span></td>
        <td style="font-size:10.5px;font-family:Consolas,monospace;letter-spacing:.6px;color:var(--muted)">${targetLabel[s.target] || esc((s.target || "").toUpperCase())}</td>
        <td><span class="noc-led ${s.enabled ? "ok" : "off"}"></span><span style="font-size:10.5px;font-family:Consolas,monospace">${s.enabled ? "ENABLED" : "DISABLED"}</span></td>
        <td class="muted" style="max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(s.description || "")}">${esc(s.description || "—")}</td>
        <td style="font-size:10.5px;font-family:Consolas,monospace;color:var(--muted)">${(s.instructions.length / 1000).toFixed(1)} KB</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn small" data-view="${s.id}">SOURCE</button>
          ${plug ? `<button class="btn small" data-ide="${s.id}">IDE</button>` : ""}
          <button class="btn small" data-edit="${s.id}">EDIT</button>
          <button class="btn small" data-toggle="${s.id}">${s.enabled ? "DISABLE" : "ENABLE"}</button>
          <button class="btn small danger" data-del="${s.id}">DELETE</button>
        </td></tr>`; }).join("")}
      </tbody></table>`
      : `<div class="empty"><div class="big">🧩</div>No skills yet. Create a skill to teach Codex and Claude Code how you want things done — e.g. coding style, brand rules, image style guides.</div>`}
    </div>
  </div>
  <p class="muted" style="font-size:11.5px;margin-top:10px"><b>Skills</b> are plain-language instructions injected into Codex / Claude Code on every request. <b>Plug-ins</b> are SkillScript BASIC programs built in the dedicated IDE — their PRINT output becomes the injected instructions.</p>`;

  $$("[data-view]", v).forEach(b => b.onclick = () => {
    const s = skills.find(x => x.id === b.dataset.view);
    modal("Source — " + s.name, `
      <div style="font-size:10px;font-family:Consolas,monospace;letter-spacing:1.2px;color:var(--muted);margin-bottom:6px">${isPlug(s) ? "SKILLSCRIPT BASIC PROGRAM" : "INJECTED INSTRUCTIONS"} · ${s.instructions.length.toLocaleString()} CHARS</div>
      <pre style="font-size:11.5px;max-height:460px;overflow:auto;background:var(--bg);padding:12px;border-radius:8px;white-space:pre-wrap;border:1px solid var(--border)">${esc(s.instructions)}</pre>`,
      null, null);
  });

  const skillModal = (s = null, mode = "prompt") => {
    const plug = mode === "plugin";
    modal(s ? "Configure skill — " + s.name : (plug ? "New plug-in — SkillScript BASIC" : "New skill"), `
    ${s ? "" : plug ? `
    ${wizSect("01", "PLUG-IN MODE", "A SkillScript BASIC program — runs in a sandbox; its PRINT output becomes the live instructions injected into the agents. Variables, IF/FOR/WHILE, HTTP, FILE, persistent MEM, ASK (AI calls) and 60+ functions. Use Validate and Test run while you build.")}` : `
    ${wizSect("01", "TEMPLATE", "A good skill = clear rules in plain language — no programming needed. Templates show the right structure.")}
    <label>Start from<select id="skill-tmpl">
      <option value="">— blank skill —</option>
      <option value="suno">SUNO AI — GIMV rating, lyrics & style</option>
      <option value="codestyle">Code style guide</option>
      <option value="brand">Brand voice & writing rules</option>
      <option value="imagestyle">Image style guide</option>
    </select></label>
    ${wizSect("02", "IDENTITY", "Name and routing of this capability")}`}
    <label>Skill name *<input name="name" required value="${s ? esc(s.name) : ""}" placeholder="e.g. Python code style"></label>
    <label>Description<input name="description" value="${s ? esc(s.description) : ""}" placeholder="Short summary — shown in the registry"></label>
    <label>Applies to<select name="target">
      <option value="both" ${!s || s.target === "both" ? "selected" : ""}>Both — Codex &amp; Claude Code (recommended)</option>
      <option value="codex" ${s && s.target === "codex" ? "selected" : ""}>Codex only (planning, Q&amp;A, images)</option>
      <option value="claude" ${s && s.target === "claude" ? "selected" : ""}>Claude Code only (implementation, files)</option>
    </select></label>
    ${s ? "" : plug ? wizSect("02", "PROGRAM", "PRINT output becomes the injected instructions") : `${wizSect("03", "INSTRUCTIONS", "Write imperative rules (\"Always…\", \"Never…\") · cover the WHEN (\"When the user asks for X, do Y\") · include output format examples · one rule per line")}`}
    <label>${plug ? "Program *" : "Instructions * (injected into the agent's prompt on every request)"}
      <textarea name="instructions" required style="min-height:200px${plug ? ";font-family:monospace;font-size:12px" : ""}" placeholder="e.g.&#10;When the user asks for a report:&#10;  * Always start with an executive summary.&#10;  * Use tables for numbers.&#10;Never exceed 2 pages unless asked.">${s ? esc(s.instructions) : plug ? esc(SKILL_TEMPLATES.basic.instructions) : ""}</textarea></label>
    <div class="toolbar" style="margin:6px 0">
      <span id="ss-tools" class="hidden">
        <button type="button" class="btn" id="ss-validate">✔ Validate script</button>
        <button type="button" class="btn" id="ss-run">▶ Test run</button>
        <button type="button" class="btn" id="ss-ref">Language reference</button>
      </span>
    </div>
    <pre id="ss-out" class="hidden" style="font-size:11px;max-height:220px;overflow:auto;background:var(--bg);padding:10px;border-radius:8px;white-space:pre-wrap"></pre>
    <p class="muted" id="skill-count" style="font-size:11px;margin-top:2px;font-family:Consolas,monospace"></p>`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (body.instructions.trim().length < 20) { toast("Instructions are too short — describe at least one clear rule", "err"); return; }
      body.enabled = s ? s.enabled : true;
      if (s) await api(`/skills/${s.id}`, { method: "PUT", body });
      else await api("/skills", { method: "POST", body });
      toast("Skill saved ✓", "ok"); render();
    }, "Save skill");
    const tmpl = $("#skill-tmpl");
    const ta = $('textarea[name="instructions"]');
    const count = $("#skill-count");
    const isScript = () => /^\s*(\d+\s+)?PROGRAM\s/im.test((ta && ta.value.split("\n").find(l => l.trim() && !l.trim().startsWith("'") && !/^REM/i.test(l.trim()))) || "");
    const updCount = () => {
      if (count && ta) count.textContent = `${ta.value.length.toLocaleString()} CHARS · ` + (isScript() ? "PLUG-IN (SKILLSCRIPT BASIC) — SANDBOXED" : "PROMPT SKILL — INJECTED AS WRITTEN");
      const tools = $("#ss-tools"); if (tools) tools.classList.toggle("hidden", !isScript());
    };
    if (ta) { ta.oninput = updCount; updCount(); }
    if (plug && !s) {
      $('input[name="name"]').value = SKILL_TEMPLATES.basic.name;
      $('input[name="description"]').value = SKILL_TEMPLATES.basic.description;
    }
    const ssOut = $("#ss-out");
    const show = (txt, ok) => { ssOut.classList.remove("hidden"); ssOut.style.borderLeft = `4px solid ${ok ? "#22c55e" : "#ef4444"}`; ssOut.textContent = txt; };
    $("#ss-ref").onclick = async () => {
      const r = await api("/skillscript/reference");
      show(r.reference, true);
    };
    $("#ss-validate").onclick = async () => {
      try {
        const r = await api("/skillscript/validate", { method: "POST", body: { code: ta.value } });
        show(r.ok
          ? `✅ Program "${r.name}" is valid — ${r.statements} statements` +
            (r.subs.length ? `\nSUBs: ${r.subs.join(", ")}` : "") +
            (r.labels.length ? `\nLabels: ${r.labels.join(", ")}` : "")
          : "❌ Validation failed:\n" + r.errors.join("\n"), r.ok);
      } catch (e) { show("❌ " + e.message, false); }
    };
    $("#ss-run").onclick = async () => {
      show("⏳ Running in sandbox…", true);
      try {
        const r = await api("/skillscript/run", { method: "POST", body: { code: ta.value, context: {} } });
        show(r.ok
          ? `✅ "${r.name}" finished in ${r.ms} ms (${r.steps} steps)\n\n── OUTPUT ──\n${r.output || "(empty)"}\n${r.trace.length ? "\n── TRACE ──\n" + r.trace.join("\n") : ""}`
          : `❌ ${r.error}\n${r.output ? "\n── partial OUTPUT ──\n" + r.output : ""}${r.trace.length ? "\n── TRACE ──\n" + r.trace.join("\n") : ""}`, r.ok);
      } catch (e) { show("❌ " + e.message, false); }
    };
    if (tmpl) tmpl.onchange = () => {
      const t = SKILL_TEMPLATES[tmpl.value]; if (!t) return;
      $('input[name="name"]').value = t.name;
      $('input[name="description"]').value = t.description;
      $('select[name="target"]').value = t.target;
      ta.value = t.instructions;
      updCount();
      toast("Template loaded — review and adjust, then Save", "ok");
    };
  };

  const openIDE = (id) => window.open("/static/ide.html" + (id ? "?skill=" + id : ""), "skillscript_ide" + (id || ""),
    "width=1400,height=900,menubar=no,toolbar=no,location=no");
  $("#new-skill").onclick = () => skillModal(null, "prompt");
  $("#new-plugin").onclick = () => openIDE();
  $$("[data-ide]", v).forEach(b => b.onclick = () => openIDE(b.dataset.ide));
  $$("[data-edit]", v).forEach(b => b.onclick = () => skillModal(skills.find(s => s.id === b.dataset.edit)));
  $$("[data-toggle]", v).forEach(b => b.onclick = async () => {
    const s = skills.find(x => x.id === b.dataset.toggle);
    await api(`/skills/${s.id}`, { method: "PUT", body: { name: s.name, description: s.description, instructions: s.instructions, target: s.target, enabled: !s.enabled } });
    toast(s.enabled ? "Skill disabled" : "Skill enabled", "ok"); render();
  });
  $$("[data-del]", v).forEach(b => b.onclick = async () => {
    if (!confirm("Delete this skill?")) return;
    await api(`/skills/${b.dataset.del}`, { method: "DELETE" });
    toast("Skill deleted", "ok"); render();
  });
};

/* ---------------- Token usage analytics ---------------- */
const AGENT_COLORS = { codex: "#4f8ef7", claude_code: "#a78bfa", copilot_relay: "#22c55e" };
const agentColor = (a, i) => AGENT_COLORS[a] || ["#f97316", "#06b6d4", "#eab308", "#ef4444", "#f472b6", "#14b8a6"][i % 6];
const AGENT_NAME = { codex: "CODEX", claude_code: "CLAUDE CODE", copilot_relay: "COPILOT RELAY" };
const agentName = (a) => AGENT_NAME[a] || a.replace(/^api:/, "API · ").toUpperCase();

/* Professional multi-series SVG line chart: grid, Y-axis ticks, day X-labels,
   smooth polylines with area fill, hover-friendly dots on last point. */
function lineChart(series, labels, { height = 220, unit = "tokens" } = {}) {
  const W = 860, H = height, PL = 62, PR = 14, PT = 14, PB = 30;
  const iw = W - PL - PR, ih = H - PT - PB;
  const maxV = Math.max(1, ...series.flatMap(s => s.data));
  const nice = (v) => { const p = Math.pow(10, Math.floor(Math.log10(v))); return Math.ceil(v / p) * p; };
  const top = nice(maxV);
  const x = (i) => PL + (labels.length < 2 ? iw / 2 : i / (labels.length - 1) * iw);
  const y = (v) => PT + ih - (v / top) * ih;
  const fmtV = (v) => v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(v >= 1e4 ? 0 : 1) + "K" : String(v);
  const ticks = [0, .25, .5, .75, 1].map(f => Math.round(top * f));
  const step = Math.max(1, Math.ceil(labels.length / 10));
  const path = (data) => data.map((v, i) => `${i ? "L" : "M"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
    <rect x="${PL}" y="${PT}" width="${iw}" height="${ih}" fill="rgba(148,163,184,.03)"/>
    ${ticks.map(t => `<line x1="${PL}" y1="${y(t)}" x2="${W - PR}" y2="${y(t)}" stroke="rgba(148,163,184,.13)" stroke-width="1"/>
      <text x="${PL - 8}" y="${y(t) + 3.5}" text-anchor="end" font-size="9.5" font-family="Consolas,monospace" fill="var(--muted,#8b93a7)">${fmtV(t)}</text>`).join("")}
    ${labels.map((l, i) => i % step ? "" : `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" font-size="9" font-family="Consolas,monospace" fill="var(--muted,#8b93a7)">${l.slice(5)}</text>`).join("")}
    ${series.map((s, si) => `
      <path d="${path(s.data)} L ${x(s.data.length - 1)} ${y(0)} L ${x(0)} ${y(0)} Z" fill="${s.color}" opacity=".07"/>
      <path d="${path(s.data)}" fill="none" stroke="${s.color}" stroke-width="1.8" stroke-linejoin="round"/>
      ${s.data.map((v, i) => v ? `<circle cx="${x(i)}" cy="${y(v)}" r="2.2" fill="${s.color}"><title>${s.name} · ${labels[i]} · ${v.toLocaleString()} ${unit}</title></circle>` : "").join("")}`).join("")}
    <line x1="${PL}" y1="${PT + ih}" x2="${W - PR}" y2="${PT + ih}" stroke="rgba(148,163,184,.35)" stroke-width="1"/>
  </svg>
  <div style="display:flex;gap:16px;flex-wrap:wrap;padding:8px 4px 0">
    ${series.map(s => `<span style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.8px;color:var(--muted)">
      <span style="display:inline-block;width:14px;height:3px;background:${s.color};vertical-align:3px;margin-right:6px"></span>${esc(s.name)}</span>`).join("")}
  </div>`;
}

/* ---------------- Email (personal IMAP accounts) ---------------- */
function mailAccountModal(acct) {
  const a = acct || {};
  modal(acct ? "Edit mail account" : "Connect mail account", `
    <div class="wiz-sect"><span class="wiz-sect-num">01</span><b>ACCOUNT IDENTITY</b></div>
    <label>Display label <input name="label" value="${esc(a.label || "")}" placeholder="e.g. peter@example.com"></label>
    <label>Username / email address <input name="username" required value="${esc(a.username || "")}" placeholder="user@example.com"></label>
    <div class="wiz-sect"><span class="wiz-sect-num">02</span><b>IMAP SERVER</b></div>
    <div class="grid cols-2">
      <label>IMAP server address <input name="imap_host" required value="${esc(a.imap_host || "")}" placeholder="imap.example.com"></label>
      <label>Port <input name="imap_port" type="number" value="${a.imap_port || 993}"></label>
    </div>
    <label style="display:flex;align-items:center;gap:8px"><input type="checkbox" name="use_ssl" ${a.use_ssl === false ? "" : "checked"} style="width:auto"> Use SSL/TLS (port 993) — unchecked = STARTTLS on port 143</label>
    <div class="wiz-sect"><span class="wiz-sect-num">03</span><b>AUTHORIZATION</b></div>
    <label>Authorization method <select name="auth_method">
      <option value="password" ${a.auth_method !== "oauth2" ? "selected" : ""}>Password / app-specific password (LOGIN)</option>
      <option value="oauth2" ${a.auth_method === "oauth2" ? "selected" : ""}>OAuth2 access token (XOAUTH2)</option></select></label>
    <label>Password / token <input name="password" type="password" ${acct ? "placeholder=\"•••••• unchanged — fill to replace\"" : "required"} autocomplete="new-password"></label>
    <div class="wiz-sect"><span class="wiz-sect-num">04</span><b>OUTBOUND — SMTP (REPLY / FORWARD / COMPOSE)</b></div>
    <div class="grid cols-2">
      <label>SMTP server address <input name="smtp_host" value="${esc(a.smtp_host || "")}" placeholder="auto — e.g. smtp.gmail.com"></label>
      <label>SMTP port <input name="smtp_port" type="number" value="${a.smtp_port || 465}" placeholder="465 SSL / 587 STARTTLS"></label>
    </div>
    <p class="muted" style="font-size:10.5px;font-family:Consolas,monospace">CREDENTIALS ARE ENCRYPTED AT REST (FERNET) · CONNECTION IS VERIFIED ON SAVE · GMAIL/ICLOUD: USE AN APP-SPECIFIC PASSWORD · SMTP LEFT BLANK = AUTO-DERIVED FROM THE IMAP HOST</p>`,
    async (fd) => {
      const body = {
        label: fd.get("label") || "", username: fd.get("username").trim(),
        imap_host: fd.get("imap_host").trim(), imap_port: +(fd.get("imap_port") || 993),
        use_ssl: !!fd.get("use_ssl"), auth_method: fd.get("auth_method"),
        password: fd.get("password") || "",
        smtp_host: (fd.get("smtp_host") || "").trim(), smtp_port: +(fd.get("smtp_port") || 465),
      };
      const r = acct
        ? await api(`/mail/accounts/${acct.id}`, { method: "PUT", body })
        : await api("/mail/accounts", { method: "POST", body });
      if (r.test && !r.test.ok) toast("Saved, but sign-in failed: " + (r.test.error || ""), "err");
      else toast("Mail account connected ✓");
      render();
    }, acct ? "Save & verify" : "Connect & verify");
}

views.email = async (v) => {
  const accts = await api("/mail/accounts");
  state.mailAcct = accts.find(a => a.id === state.mailAcct)?.id || (accts[0] || {}).id || null;
  const cur = accts.find(a => a.id === state.mailAcct);
  const connected = accts.filter(a => a.status === "connected").length;

  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Accounts</span><span class="v">${accts.length}</span></div>
    <div class="noc-kpi"><span class="k">Connected</span><span class="v" style="color:#22c55e">${connected}</span></div>
    <div class="noc-kpi"><span class="k">Active account</span><span class="v">${esc(cur ? (cur.label || cur.username) : "—")}</span></div>
    <div class="noc-kpi"><span class="k">Unread</span><span class="v" id="mail-kpi-unread">—</span></div>
    <span class="spacer"></span>
    ${cur ? `<button class="btn" id="mail-compose">✉ Compose</button>` : ""}
    <button class="btn primary" id="mail-add">+ Connect account</button>
  </div>
  <div style="display:grid;grid-template-columns:280px 1fr;gap:14px;align-items:start">
    <div>
      <div class="noc-panel" style="margin-bottom:14px">
        <div class="noc-head"><span class="noc-lbl">MAIL ACCOUNTS</span><span class="spacer"></span><small>${accts.length}</small></div>
        <div class="noc-body" style="padding:6px">
          ${accts.length ? accts.map(a => `
          <div class="mail-acct ${a.id === state.mailAcct ? "active" : ""}" data-acct="${a.id}" style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;cursor:pointer;${a.id === state.mailAcct ? "background:rgba(79,142,247,.12);outline:1px solid rgba(79,142,247,.4)" : ""}">
            <span class="noc-led ${a.status === "connected" ? "ok" : "off"}" title="${esc(a.status)}"></span>
            <div style="min-width:0;flex:1">
              <div style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.label || a.username)}</div>
              <div class="muted" style="font-family:Consolas,monospace;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.imap_host)}:${a.imap_port} · ${a.use_ssl ? "SSL" : "STARTTLS"} · ${esc((a.auth_method || "password").toUpperCase())}</div>
            </div>
            <button class="btn small" data-acct-edit="${a.id}" title="Settings">⚙</button>
            <button class="btn small danger" data-acct-del="${a.id}" title="Disconnect">✕</button>
          </div>`).join("")
          : `<div class="empty" style="padding:20px"><div class="big">📧</div>No mail accounts yet.<br>Connect your IMAP mailbox to read email here and by chat prompt.</div>`}
        </div>
      </div>
      <div class="noc-panel">
        <div class="noc-head"><span class="noc-lbl">FOLDERS</span><span class="spacer"></span><small id="mail-folders-n"></small></div>
        <div class="noc-body" style="padding:6px" id="mail-folders"><p class="muted" style="padding:8px">${cur ? "Loading…" : "Connect an account first."}</p></div>
      </div>
    </div>
    <div class="noc-panel">
      <div class="noc-head"><span class="noc-lbl" id="mail-list-title">MESSAGES</span><span class="spacer"></span>
        <input id="mail-search" placeholder="Search subject / sender…" style="width:220px;margin:0">
        <button class="btn small" id="mail-refresh" title="Refresh">⟳</button></div>
      <div id="mail-cats" class="hidden" style="display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border)"></div>
      <div class="noc-body" style="padding:0" id="mail-list">
        ${cur ? `<p class="muted" style="padding:14px">Loading…</p>` : `<div class="empty"><div class="big">📬</div>No account selected.</div>`}
      </div>
    </div>
  </div>
  <p class="muted" style="font-size:10.5px;font-family:Consolas,monospace;margin-top:10px">💡 CHAT PROMPTS WORK TOO: <b>check my email</b> · <b>read the email from …</b> · <b>reply to the email from … with: …</b> · <b>forward the email about … to addr@example.com</b> · <b>mark the email from … as read</b> · <b>delete the email about …</b></p>`;

  $("#mail-add").onclick = () => mailAccountModal(null);
  $$("[data-acct-edit]", v).forEach(b => b.onclick = (e) => {
    e.stopPropagation(); mailAccountModal(accts.find(a => a.id === b.dataset.acctEdit));
  });
  $$("[data-acct-del]", v).forEach(b => b.onclick = async (e) => {
    e.stopPropagation();
    if (!confirm("Disconnect this mail account?")) return;
    await api(`/mail/accounts/${b.dataset.acctDel}`, { method: "DELETE" });
    if (state.mailAcct === b.dataset.acctDel) state.mailAcct = null;
    render();
  });
  $$(".mail-acct", v).forEach(el => el.onclick = () => { state.mailAcct = el.dataset.acct; state.mailFolder = "INBOX"; state.mailPage = 0; state.mailCat = undefined; render(); });
  if (!cur) return;

  state.mailFolder = state.mailFolder || "INBOX";
  state.mailPage = state.mailPage || 0;
  state.mailPageSize = state.mailPageSize || 50;
  // Gmail splits the inbox into category tabs — mirror them so the list
  // matches what the user sees in the Gmail app (default: PRIMARY).
  const gmailTabs = [["primary", "PRIMARY"], ["promotions", "PROMOTIONS"], ["social", "SOCIAL"], ["updates", "UPDATES"], ["forums", "FORUMS"], ["", "ALL MAIL"]];
  if (state.mailCat === undefined) state.mailCat = cur.is_gmail ? "primary" : "";
  const renderCats = () => {
    const bar = $("#mail-cats");
    const show = cur.is_gmail && state.mailFolder.toUpperCase() === "INBOX";
    bar.classList.toggle("hidden", !show);
    bar.style.display = show ? "flex" : "none";
    if (!show) return;
    bar.innerHTML = gmailTabs.map(([val, label]) =>
      `<button class="btn small ${state.mailCat === val ? "primary" : ""}" data-cat="${val}" style="font-family:Consolas,monospace;font-size:10px;letter-spacing:1px">${label}</button>`).join("");
    $$("#mail-cats [data-cat]").forEach(b => b.onclick = () => { state.mailCat = b.dataset.cat; state.mailPage = 0; renderCats(); loadMessages(); });
  };
  const fmtD = (iso) => {
    if (!iso) return "—";
    const t = new Date(iso);
    return t.toLocaleDateString(undefined, { month: "2-digit", day: "2-digit" }) + " " +
      t.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  };

  const loadMessages = async () => {
    const q = $("#mail-search").value.trim();
    const size = state.mailPageSize;
    const inInbox = state.mailFolder.toUpperCase() === "INBOX";
    const cat = (cur.is_gmail && inInbox) ? state.mailCat : "";
    $("#mail-list").innerHTML = `<p class="muted" style="padding:14px">Loading…</p>`;
    $("#mail-list-title").textContent = `MESSAGES — ${state.mailFolder.toUpperCase()}${cat ? " · " + cat.toUpperCase() : ""}`;
    let d;
    try {
      d = await api(`/mail/accounts/${cur.id}/messages?folder=${encodeURIComponent(state.mailFolder)}&limit=${size}&page=${state.mailPage}${q ? `&q=${encodeURIComponent(q)}` : ""}${cat ? `&category=${encodeURIComponent(cat)}` : ""}`);
    } catch (e) {
      $("#mail-list").innerHTML = `<div class="empty"><div class="big">⚠️</div>${esc(e.message)}</div>`;
      return;
    }
    const pages = Math.max(1, Math.ceil(d.total / size));
    if (state.mailPage >= pages) { state.mailPage = pages - 1; return loadMessages(); }
    const first = d.total ? state.mailPage * size + 1 : 0;
    const last = Math.min(d.total, (state.mailPage + 1) * size);
    const pagerBar = `
    <div style="display:flex;align-items:center;gap:10px;padding:8px 12px;border-top:1px solid var(--border)">
      <span class="muted" style="font-size:10px;font-family:Consolas,monospace;letter-spacing:.5px">${d.total.toLocaleString()} MESSAGE(S) · SHOWING ${first.toLocaleString()}–${last.toLocaleString()} · NEWEST FIRST</span>
      <span class="spacer" style="flex:1"></span>
      <select id="mail-psize" style="margin:0;width:auto">${[25, 50, 100].map(n => `<option value="${n}" ${n === size ? "selected" : ""}>${n} / page</option>`).join("")}</select>
      <button class="btn small" id="mail-pg-first" ${state.mailPage === 0 ? "disabled" : ""} title="Newest">«</button>
      <button class="btn small" id="mail-pg-prev" ${state.mailPage === 0 ? "disabled" : ""} title="Newer">‹</button>
      <span style="font-family:Consolas,monospace;font-size:11px;min-width:90px;text-align:center">PAGE ${(state.mailPage + 1).toLocaleString()} / ${pages.toLocaleString()}</span>
      <button class="btn small" id="mail-pg-next" ${state.mailPage >= pages - 1 ? "disabled" : ""} title="Older">›</button>
      <button class="btn small" id="mail-pg-last" ${state.mailPage >= pages - 1 ? "disabled" : ""} title="Oldest">»</button>
    </div>`;
    if (!d.messages.length) {
      $("#mail-list").innerHTML = `<div class="empty"><div class="big">📭</div>No messages${q ? " matching your search" : ""}.</div>`;
      return;
    }
    // ---- client-side sort of the current page ----
    state.mailSort = state.mailSort || { col: "date", dir: -1 };
    const { col: sCol, dir: sDir } = state.mailSort;
    const sortKey = (m) => sCol === "from" ? m.from.toLowerCase().replace(/^["'\s]+/, "")
      : sCol === "subject" ? m.subject.toLowerCase()
      : sCol === "status" ? (m.seen ? 1 : 0)
      : (Date.parse(m.date) || 0);   // full date + time, timezone-normalized epoch
    const msgs = [...d.messages].sort((a, b) => {
      const ka = sortKey(a), kb = sortKey(b);
      return (ka < kb ? -1 : ka > kb ? 1 : 0) * sDir;
    });
    const arrow = (c) => sCol === c ? (sDir === 1 ? " ▲" : " ▼") : "";
    const hd = (c, label, extra) => `<th data-sort="${c}" style="cursor:pointer;user-select:none;${extra || ""}" title="Sort by ${label.toLowerCase()}">${label}${arrow(c)}</th>`;
    $("#mail-list").innerHTML = `
    <div id="mail-bulkbar" class="hidden" style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(79,142,247,.08);border-bottom:1px solid var(--border)">
      <span style="font-family:Consolas,monospace;font-size:11px;letter-spacing:.5px"><b id="mail-selcount">0</b> SELECTED</span>
      <span class="spacer" style="flex:1"></span>
      <button class="btn small" id="mail-bulk-read">📖 MARK READ</button>
      <button class="btn small" id="mail-bulk-unread">✉ MARK UNREAD</button>
      <button class="btn small danger" id="mail-bulk-delete">🗑 DELETE SELECTED</button>
    </div>
    <table class="noc-table" style="margin:0"><thead><tr>
      <th style="width:30px"><input type="checkbox" id="mail-sel-all" style="width:auto;margin:0" title="Select all on this page"></th>
      ${hd("status", "", "width:26px")}${hd("from", "FROM", "width:220px")}${hd("subject", "SUBJECT")}
      ${hd("date", "DATE · TIME", "width:120px")}<th style="width:140px;text-align:right">ACTIONS</th></tr></thead><tbody>
      ${msgs.map(m => `<tr data-uid="${m.uid}" style="cursor:pointer;${m.seen ? "" : "background:rgba(79,142,247,.06)"}">
        <td><input type="checkbox" class="mail-sel" data-uid="${m.uid}" style="width:auto;margin:0"></td>
        <td>${m.seen ? "" : `<span class="noc-led ok" title="Unread"></span>`}${m.flagged ? " 🚩" : ""}</td>
        <td style="${m.seen ? "" : "font-weight:700"};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px">${esc(m.from)}</td>
        <td style="${m.seen ? "" : "font-weight:700"};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:420px">${esc(m.subject)}</td>
        <td style="font-family:Consolas,monospace;font-size:11px;white-space:nowrap">${fmtD(m.date)}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="btn small" data-act="${m.seen ? "unread" : "read"}" data-uid="${m.uid}" title="Mark ${m.seen ? "unread" : "read"}">${m.seen ? "✉" : "📖"}</button>
          <button class="btn small danger" data-act="delete" data-uid="${m.uid}" title="Delete">🗑</button></td></tr>`).join("")}
    </tbody></table>
    ${pagerBar}`;

    // ---- header sorting ----
    $$("#mail-list th[data-sort]").forEach(th => th.onclick = () => {
      const c = th.dataset.sort;
      state.mailSort = { col: c, dir: state.mailSort.col === c ? -state.mailSort.dir : (c === "date" ? -1 : 1) };
      loadMessages();
    });

    // ---- multi-select + bulk operations ----
    const selected = () => $$(".mail-sel:checked").map(cb => cb.dataset.uid);
    const syncBulk = () => {
      const n = selected().length;
      $("#mail-bulkbar").classList.toggle("hidden", n === 0);
      $("#mail-selcount").textContent = n;
      const all = $$(".mail-sel");
      $("#mail-sel-all").checked = n > 0 && n === all.length;
    };
    $$(".mail-sel").forEach(cb => {
      cb.onclick = (e) => { e.stopPropagation(); syncBulk(); };
    });
    $("#mail-sel-all").onclick = (e) => {
      e.stopPropagation();
      $$(".mail-sel").forEach(cb => cb.checked = e.target.checked);
      syncBulk();
    };
    const bulkAct = async (action) => {
      const uids = selected();
      if (!uids.length) return;
      if (action === "delete" && !confirm(`Delete ${uids.length} email(s) from the server? This cannot be undone.`)) return;
      const btns = ["mail-bulk-read", "mail-bulk-unread", "mail-bulk-delete"];
      btns.forEach(id => { const b = document.getElementById(id); if (b) b.disabled = true; });
      try {
        // IMAP UID sets — one round-trip for the whole batch
        await api(`/mail/accounts/${cur.id}/messages/${uids.join(",")}/action`,
          { method: "POST", body: { action, folder: state.mailFolder } });
        toast(action === "delete" ? `${uids.length} email(s) deleted` : `${uids.length} email(s) updated ✓`);
        loadMessages(); loadFolders();
      } catch (e) { toast(e.message, "err"); btns.forEach(id => { const b = document.getElementById(id); if (b) b.disabled = false; }); }
    };
    $("#mail-bulk-delete").onclick = () => bulkAct("delete");
    $("#mail-bulk-read").onclick = () => bulkAct("read");
    $("#mail-bulk-unread").onclick = () => bulkAct("unread");

    const go = (p) => { state.mailPage = p; loadMessages(); };
    const el = (id) => document.getElementById(id);
    if (el("mail-pg-first")) el("mail-pg-first").onclick = () => go(0);
    if (el("mail-pg-prev")) el("mail-pg-prev").onclick = () => go(Math.max(0, state.mailPage - 1));
    if (el("mail-pg-next")) el("mail-pg-next").onclick = () => go(Math.min(pages - 1, state.mailPage + 1));
    if (el("mail-pg-last")) el("mail-pg-last").onclick = () => go(pages - 1);
    if (el("mail-psize")) el("mail-psize").onchange = (e) => { state.mailPageSize = +e.target.value; state.mailPage = 0; loadMessages(); };

    $$("#mail-list [data-act]").forEach(b => b.onclick = async (e) => {
      e.stopPropagation();
      if (b.dataset.act === "delete" && !confirm("Delete this email from the server?")) return;
      try {
        await api(`/mail/accounts/${cur.id}/messages/${b.dataset.uid}/action`,
          { method: "POST", body: { action: b.dataset.act, folder: state.mailFolder } });
        toast(b.dataset.act === "delete" ? "Email deleted" : "Done ✓");
        loadMessages(); loadFolders();
      } catch (err) { toast(err.message, "err"); }
    });
    $$("#mail-list tr[data-uid]").forEach(row => row.onclick = async () => {
      let msg;
      try { msg = await api(`/mail/accounts/${cur.id}/messages/${row.dataset.uid}?folder=${encodeURIComponent(state.mailFolder)}`); }
      catch (e) { toast(e.message, "err"); return; }
      const body = msg.text ? `<pre style="white-space:pre-wrap;font-family:inherit;font-size:13px;margin:0">${esc(msg.text)}</pre>`
        : (msg.html ? `<iframe sandbox="" style="width:100%;height:400px;border:1px solid var(--border);border-radius:8px;background:#fff" srcdoc="${esc(msg.html)}"></iframe>`
          : `<p class="muted">(empty body)</p>`);
      modal(msg.subject, `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
          <button type="button" class="btn small primary" id="mm-reply">↩ REPLY</button>
          <button type="button" class="btn small" id="mm-replyall">↩↩ REPLY ALL</button>
          <button type="button" class="btn small" id="mm-forward">↗ FORWARD</button>
          <span class="spacer" style="flex:1"></span>
          <button type="button" class="btn small" id="mm-unread">✉ MARK UNREAD</button>
          <button type="button" class="btn small danger" id="mm-delete">🗑 DELETE</button>
        </div>
        <div style="font-family:Consolas,monospace;font-size:11px;color:var(--muted);line-height:1.7;border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:12px">
          <span style="letter-spacing:1px">FROM</span>&nbsp;&nbsp;${esc(msg.from)}<br>
          <span style="letter-spacing:1px">TO</span>&nbsp;&nbsp;&nbsp;&nbsp;${esc(msg.to)}${msg.cc ? `<br><span style="letter-spacing:1px">CC</span>&nbsp;&nbsp;&nbsp;&nbsp;${esc(msg.cc)}` : ""}<br>
          <span style="letter-spacing:1px">DATE</span>&nbsp;&nbsp;${esc((msg.date || "").slice(0, 16).replace("T", " "))}
          ${msg.attachments.length ? `<br><span style="letter-spacing:1px">FILES</span>&nbsp;${msg.attachments.map(esc).join(", ")}` : ""}
        </div>
        <div style="max-height:420px;overflow:auto">${body}</div>
        <div id="mm-panel" class="hidden" style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px">
          <div class="wiz-sect"><span class="wiz-sect-num" id="mm-panel-num">↩</span><b id="mm-panel-title">REPLY</b></div>
          <label id="mm-to-wrap" class="hidden">To <input id="mm-to" placeholder="recipient@example.com"></label>
          <label>Message <textarea id="mm-body" rows="5" placeholder="Write your message…"></textarea></label>
          <div style="display:flex;justify-content:flex-end;gap:8px">
            <button type="button" class="btn small" id="mm-send-cancel">Cancel</button>
            <button type="button" class="btn small primary" id="mm-send">SEND ▸</button>
          </div>
        </div>`, null, null);

      let sendMode = "reply";
      const openPanel = (mode, title, needTo) => {
        sendMode = mode;
        $("#mm-panel").classList.remove("hidden");
        $("#mm-panel-title").textContent = title;
        $("#mm-to-wrap").classList.toggle("hidden", !needTo);
        (needTo ? $("#mm-to") : $("#mm-body")).focus();
      };
      $("#mm-reply").onclick = () => openPanel("reply", `REPLY — ${msg.from.slice(0, 60)}`, false);
      $("#mm-replyall").onclick = () => openPanel("replyall", "REPLY ALL", false);
      $("#mm-forward").onclick = () => openPanel("forward", "FORWARD", true);
      $("#mm-send-cancel").onclick = () => $("#mm-panel").classList.add("hidden");
      $("#mm-send").onclick = async () => {
        const bodyTxt = $("#mm-body").value.trim();
        const toAddr = $("#mm-to").value.trim();
        if (!bodyTxt && sendMode !== "forward") { toast("Write a message first", "err"); return; }
        if (sendMode === "forward" && !toAddr) { toast("Enter a recipient address", "err"); return; }
        $("#mm-send").disabled = true; $("#mm-send").textContent = "SENDING…";
        try {
          await api(`/mail/accounts/${cur.id}/send`, { method: "POST", body: {
            mode: sendMode, folder: state.mailFolder, uid: msg.uid,
            to: toAddr, body: bodyTxt } });
          toast(sendMode === "forward" ? "Forwarded ✓" : "Reply sent ✓");
          $("#modal-root").innerHTML = "";
          loadMessages(); loadFolders();
        } catch (e) {
          toast(e.message, "err");
          $("#mm-send").disabled = false; $("#mm-send").textContent = "SEND ▸";
        }
      };
      $("#mm-unread").onclick = async () => {
        try {
          await api(`/mail/accounts/${cur.id}/messages/${msg.uid}/action`,
            { method: "POST", body: { action: "unread", folder: state.mailFolder } });
          toast("Marked unread ✓"); $("#modal-root").innerHTML = "";
          loadMessages(); loadFolders();
        } catch (e) { toast(e.message, "err"); }
      };
      $("#mm-delete").onclick = async () => {
        if (!confirm("Delete this email from the server?")) return;
        try {
          await api(`/mail/accounts/${cur.id}/messages/${msg.uid}/action`,
            { method: "POST", body: { action: "delete", folder: state.mailFolder } });
          toast("Email deleted"); $("#modal-root").innerHTML = "";
          loadMessages(); loadFolders();
        } catch (e) { toast(e.message, "err"); }
      };
    });
  };

  const loadFolders = async () => {
    let folders;
    try { folders = await api(`/mail/accounts/${cur.id}/folders`); }
    catch (e) {
      $("#mail-folders").innerHTML = `<p class="muted" style="padding:8px">⚠️ ${esc(e.message)}</p>`;
      return;
    }
    $("#mail-folders-n").textContent = folders.length;
    const unreadInbox = (folders.find(f => f.name.toUpperCase() === "INBOX") || {}).unseen || 0;
    $("#mail-kpi-unread").textContent = unreadInbox;
    $("#mail-kpi-unread").style.color = unreadInbox ? "#4f8ef7" : "";
    $("#mail-folders").innerHTML = folders.map(f => `
      <div class="mail-folder" data-folder="${esc(f.name)}" style="display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:8px;cursor:pointer;${f.name === state.mailFolder ? "background:rgba(79,142,247,.12);outline:1px solid rgba(79,142,247,.4)" : ""}">
        <span style="font-size:13px">${f.name.toUpperCase() === "INBOX" ? "📥" : /sent/i.test(f.display) ? "📤" : /trash|deleted/i.test(f.display) ? "🗑" : /junk|spam/i.test(f.display) ? "⚠️" : /draft/i.test(f.display) ? "📝" : "📁"}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;${f.name === state.mailFolder ? "font-weight:700" : ""}">${esc(f.display)}</span>
        ${f.unseen ? `<span class="badge" style="position:static">${f.unseen}</span>` : `<small class="muted" style="font-family:Consolas,monospace;font-size:10px">${f.total}</small>`}
      </div>`).join("");
    $$(".mail-folder", v).forEach(el => el.onclick = () => { state.mailFolder = el.dataset.folder; state.mailPage = 0; renderCats(); loadFolders(); loadMessages(); });
  };

  $("#mail-refresh").onclick = () => { loadFolders(); loadMessages(); };
  const composeBtn = $("#mail-compose");
  if (composeBtn) composeBtn.onclick = () => {
    modal("Compose email", `
      <div class="wiz-sect"><span class="wiz-sect-num">01</span><b>ENVELOPE — FROM ${esc(cur.username.toUpperCase())}</b></div>
      <label>To <input name="to" required placeholder="recipient@example.com"></label>
      <label>Cc <input name="cc" placeholder="optional"></label>
      <label>Subject <input name="subject" required></label>
      <div class="wiz-sect"><span class="wiz-sect-num">02</span><b>MESSAGE</b></div>
      <label><textarea name="body" rows="9" required placeholder="Write your message…"></textarea></label>
      <p class="muted" style="font-size:10.5px;font-family:Consolas,monospace">SENT VIA ${esc((cur.smtp_host || ("SMTP." + cur.imap_host.replace(/^imap\./i, ""))).toUpperCase())} · A COPY IS FILED TO YOUR SENT FOLDER</p>`,
      async (fd) => {
        await api(`/mail/accounts/${cur.id}/send`, { method: "POST", body: {
          mode: "compose", to: fd.get("to").trim(), cc: (fd.get("cc") || "").trim(),
          subject: fd.get("subject").trim(), body: fd.get("body") } });
        toast("Email sent ✓");
        loadMessages(); loadFolders();
      }, "Send email");
  };
  let searchT;
  $("#mail-search").oninput = () => { clearTimeout(searchT); searchT = setTimeout(() => { state.mailPage = 0; loadMessages(); }, 500); };
  renderCats();
  loadFolders();
  loadMessages();
};

views.usage = async (v) => {
  const days = state.usageDays || 30;
  const scope = (state.usageScope === "all") ? "all" : "me";
  let data;
  try { data = await api(`/usage/tokens?days=${days}&scope=${scope}`); }
  catch (e) { state.usageScope = "me"; data = await api(`/usage/tokens?days=${days}&scope=me`); }
  const agents = Object.entries(data.agents);
  const totalIn = agents.reduce((s, [, a]) => s + a.total_in, 0);
  const totalOut = agents.reduce((s, [, a]) => s + a.total_out, 0);
  const totalCalls = agents.reduce((s, [, a]) => s + a.calls, 0);
  const seriesOf = (daily, key) => data.days.map(d => (daily[d] || {})[key] || 0);
  v.innerHTML = `
  <div class="noc-topbar">
    <div class="noc-kpi"><span class="k">Window</span><span class="v">${days}D</span></div>
    <div class="noc-kpi"><span class="k">Input tokens</span><span class="v">${totalIn.toLocaleString()}</span></div>
    <div class="noc-kpi"><span class="k">Output tokens</span><span class="v" style="color:#22c55e">${totalOut.toLocaleString()}</span></div>
    <div class="noc-kpi"><span class="k">Calls</span><span class="v">${totalCalls.toLocaleString()}</span></div>
    <div class="noc-kpi"><span class="k">Models</span><span class="v">${agents.length}</span></div>
    <span class="spacer"></span>
    <select id="usage-days">${[7, 14, 30, 90, 180].map(d => `<option value="${d}" ${d === days ? "selected" : ""}>Last ${d} days</option>`).join("")}</select>
    ${data.is_admin ? `<select id="usage-scope">
      <option value="me" ${scope === "me" ? "selected" : ""}>My usage</option>
      <option value="all" ${scope === "all" ? "selected" : ""}>All clients (admin)</option></select>` : ""}
  </div>
  ${data.users ? `
  <div class="noc-panel" style="margin-bottom:14px">
    <div class="noc-head"><span class="noc-lbl">PER-CLIENT CONSUMPTION — ADMINISTRATOR VIEW</span>
      <span class="spacer"></span><small>${Object.keys(data.users).length} CLIENT(S) · CLICK A CLIENT FOR THE ITEMIZED LEDGER</small></div>
    <div class="noc-body">
      ${Object.keys(data.users).length
        ? lineChart(Object.entries(data.users).map(([uid, u], i) => ({
            name: u.username.toUpperCase(), color: agentColor("u" + uid, i),
            data: data.days.map(d => (u.daily[d] || { in: 0, out: 0 }).in + (u.daily[d] || { in: 0, out: 0 }).out) })), data.days)
        : `<p class="muted">No client usage in this window.</p>`}
      ${Object.keys(data.users).length ? `<table class="noc-table" style="margin-top:14px"><thead><tr>
        <th>CLIENT</th><th>INPUT TOKENS</th><th>OUTPUT TOKENS</th><th>TOTAL</th><th style="width:110px"></th></tr></thead><tbody>
        ${Object.entries(data.users).sort((a, b) => (b[1].total_in + b[1].total_out) - (a[1].total_in + a[1].total_out)).map(([uid, u]) => `<tr data-udetail="${uid}" style="cursor:pointer" title="Open itemized token ledger for ${esc(u.username)}">
          <td><b>${esc(u.username)}</b></td>
          <td style="font-family:Consolas,monospace">${u.total_in.toLocaleString()}</td>
          <td style="font-family:Consolas,monospace">${u.total_out.toLocaleString()}</td>
          <td style="font-family:Consolas,monospace"><b>${(u.total_in + u.total_out).toLocaleString()}</b></td>
          <td style="text-align:right"><button class="btn small" data-udetail="${uid}">LEDGER</button></td></tr>`).join("")}
      </tbody></table>` : ""}
    </div>
  </div>` : ""}
  <div class="noc-panel" style="margin-bottom:14px">
    <div class="noc-head"><span class="noc-lbl">TOKEN CONSUMPTION — ALL MODELS &amp; AGENTS</span>
      <span class="spacer"></span><small>ESTIMATED · DAILY AGGREGATE · UTC</small></div>
    <div class="noc-body">
      ${agents.length
        ? lineChart(agents.map(([name, a], i) => ({
            name: agentName(name), color: agentColor(name, i),
            data: data.days.map(d => (a.daily[d] || { in: 0, out: 0 }).in + (a.daily[d] || { in: 0, out: 0 }).out) })), data.days)
        : `<div class="empty"><div class="big">📊</div>No token usage recorded yet in this window — run a prompt and it will appear here.</div>`}
    </div>
  </div>
  ${agents.map(([name, a], i) => `
  <div class="noc-panel" style="margin-bottom:14px">
    <div class="noc-head"><span class="noc-lbl">${esc(agentName(name))}</span><span class="spacer"></span>
      <small>IN ${a.total_in.toLocaleString()} · OUT ${a.total_out.toLocaleString()} · ${a.calls} CALL(S)</small></div>
    <div class="noc-body">
      ${lineChart([
        { name: "INPUT", color: agentColor(name, i), data: seriesOf(a.daily, "in") },
        { name: "OUTPUT", color: "#22c55e", data: seriesOf(a.daily, "out") },
      ], data.days, { height: 180 })}
    </div>
  </div>`).join("")}
  <p class="muted" style="font-size:10.5px;font-family:Consolas,monospace">TOKEN COUNTS ARE ESTIMATED FROM CHARACTER VOLUME — CLI AGENTS DO NOT EXPOSE EXACT METER READINGS. VS CODE HANDOFFS ARE BILLED TO COPILOT AND NOT COUNTED HERE.</p>`;
  $("#usage-days").onchange = (e) => { state.usageDays = +e.target.value; render(); };
  const sc = $("#usage-scope");
  if (sc) sc.onchange = (e) => { state.usageScope = e.target.value; render(); };

  // itemized per-user ledger (admin drill-down / self-service)
  const openLedger = async (uid) => {
    let d;
    try { d = await api(`/usage/tokens/detail?user_id=${encodeURIComponent(uid)}&days=${days}`); }
    catch (e) { toast(e.message, "err"); return; }
    const fmtT = (iso) => { const t = new Date(iso); return t.toLocaleDateString(undefined, { year: "numeric", month: "2-digit", day: "2-digit" }) + " " + t.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }); };
    modal(`Token ledger — ${d.username}`, `
      <div style="display:flex;gap:20px;margin-bottom:12px;font-family:Consolas,monospace">
        <span style="font-size:10px;letter-spacing:1px;color:var(--muted)">WINDOW<br><b style="font-size:15px;color:var(--text)">${d.days}D</b></span>
        <span style="font-size:10px;letter-spacing:1px;color:var(--muted)">RECORDS<br><b style="font-size:15px;color:var(--text)">${d.records.length}</b></span>
        <span style="font-size:10px;letter-spacing:1px;color:var(--muted)">INPUT<br><b style="font-size:15px;color:var(--text)">${d.total_in.toLocaleString()}</b></span>
        <span style="font-size:10px;letter-spacing:1px;color:var(--muted)">OUTPUT<br><b style="font-size:15px;color:#22c55e">${d.total_out.toLocaleString()}</b></span>
        <span style="font-size:10px;letter-spacing:1px;color:var(--muted)">TOTAL<br><b style="font-size:15px;color:#4f8ef7">${(d.total_in + d.total_out).toLocaleString()}</b></span>
      </div>
      ${d.records.length ? `<div style="max-height:440px;overflow:auto;border:1px solid var(--border);border-radius:8px">
      <table class="noc-table" style="margin:0"><thead><tr>
        <th style="width:150px">DATE · TIME</th><th style="width:130px">MODEL / AGENT</th>
        <th style="width:80px">IN</th><th style="width:80px">OUT</th><th style="width:80px">TOTAL</th><th>REQUEST</th></tr></thead><tbody>
        ${d.records.map(r => `<tr>
          <td style="font-family:Consolas,monospace;font-size:11px;white-space:nowrap">${r.at ? esc(fmtT(r.at)) : "—"}</td>
          <td><span style="font-size:9.5px;font-family:Consolas,monospace;letter-spacing:.8px;color:${agentColor(r.agent, 0)};border:1px solid ${agentColor(r.agent, 0)};border-radius:4px;padding:1px 6px">${esc(agentName(r.agent))}</span></td>
          <td style="font-family:Consolas,monospace;font-size:11.5px">${r.input_tokens.toLocaleString()}</td>
          <td style="font-family:Consolas,monospace;font-size:11.5px;color:#22c55e">${r.output_tokens.toLocaleString()}</td>
          <td style="font-family:Consolas,monospace;font-size:11.5px"><b>${(r.input_tokens + r.output_tokens).toLocaleString()}</b></td>
          <td class="muted" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11.5px" title="${esc(r.prompt || "")}">${esc(r.prompt || "—")}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="muted">No usage records for this user in the selected window.</p>`}
      <p class="muted" style="font-size:10px;font-family:Consolas,monospace;margin-top:8px">ONE ROW PER MODEL PER REQUEST · NEWEST FIRST · LOCAL TIME · MAX 500 RECORDS</p>`,
      null, null);
  };
  $$("[data-udetail]", v).forEach(el => el.onclick = (e) => { e.stopPropagation(); openLedger(el.dataset.udetail); });
};

/* ---------------- Audit ---------------- */
views.audit = async (v) => {
  const rows = await api("/audit");
  v.innerHTML = rows.length ? `<table><tr><th>When</th><th>Action</th><th>Detail</th><th>Hash</th></tr>
    ${rows.map(a => `<tr><td>${new Date(a.created_at).toLocaleString()}</td><td>${esc(a.action)}</td>
    <td>${esc((a.detail || "").slice(0,120))}</td><td class="muted" style="font-family:monospace;font-size:11px">${esc(a.entry_hash.slice(0,12))}…</td></tr>`).join("")}</table>`
    : `<div class="empty"><div class="big">📜</div>No audit events yet.</div>`;
};

/* ---------------- Settings ---------------- */
function cfgField(k, m, config) {
  const help = m.label.includes("(") ? m.label.slice(m.label.indexOf("(")) : "";
  const title = help ? m.label.slice(0, m.label.indexOf("(")).trim() : m.label;
  let input;
  if (m.type === "select") {
    input = `<select name="${k}">${m.options.map(o =>
      `<option value="${esc(o)}" ${config[k] === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  } else if (m.type === "password") {
    input = `<div class="pw-wrap"><input name="${k}" type="password" value="${esc(config[k])}" autocomplete="new-password">
      <button type="button" class="pw-eye" tabindex="-1">👁</button></div>`;
  } else {
    input = `<input name="${k}" type="${m.type}" value="${esc(config[k])}"
      ${m.type === "number" ? `min="${m.min}" max="${m.max}"` : ""}>`;
  }
  return `<div class="cfg-field"><label>${esc(title)}</label>${input}
    ${help ? `<div class="cfg-help">${esc(help.replace(/^\(|\)$/g, ""))}</div>` : ""}</div>`;
}

const API_TYPE_OPTS = ["openai-compatible", "anthropic"];
function apiRow(a, i) {
  return `<div class="api-row card" data-i="${i}">
    <div class="api-row-head">
      <span class="api-idx">#${i + 1}</span>
      <input class="a-name" placeholder="Name (e.g. OpenAI main, Ollama local)" value="${esc(a.name || "")}" style="flex:1">
      <label class="switch" title="Enabled"><input type="checkbox" class="a-enabled" ${a.enabled !== false ? "checked" : ""}><span class="slider"></span></label>
      <button type="button" class="btn danger a-del" title="Remove">🗑</button>
    </div>
    <div class="api-row-grid">
      <div class="cfg-field"><label>Type</label>
        <select class="a-type">${API_TYPE_OPTS.map(o => `<option ${a.type === o ? "selected" : ""}>${o}</option>`).join("")}</select></div>
      <div class="cfg-field"><label>Base URL</label>
        <input class="a-base" placeholder="https://api.openai.com/v1" value="${esc(a.base_url || "")}">
        <div class="cfg-help">OpenAI · Azure · Ollama (http://localhost:11434/v1) · LM Studio · Groq · DeepSeek…</div></div>
      <div class="cfg-field"><label>API key</label>
        <div class="pw-wrap"><input class="a-key" type="password" value="${esc(a.key || "")}" autocomplete="new-password">
        <button type="button" class="pw-eye" tabindex="-1">👁</button></div></div>
      <div class="cfg-field"><label>Model</label>
        <input class="a-model" placeholder="gpt-4o / claude-sonnet-4-5 / llama3.1" value="${esc(a.model || "")}"></div>
    </div>
  </div>`;
}

views.clients = async (v) => {
  const render = async () => {
    let data, seats = null;
    try {
      const [d, lic] = await Promise.all([
        api("/clients"),
        api("/licenses").catch(() => null),        // license/seat telemetry is optional
      ]);
      data = d; seats = lic && lic.seats ? lic.seats : null;
    }
    catch (e) { v.innerHTML = `<p class="error">❌ ${esc(e.message)}</p>`; return; }
    const cs = data.clients;
    const devs = data.devices || [];
    // deterministic, operations-friendly ordering: online first, then by name
    cs.sort((a, b) => (b.online - a.online) || (a.hostname || a.note || "").localeCompare(b.hostname || b.note || ""));
    devs.sort((a, b) => (b.online - a.online) || (a.model || "").localeCompare(b.model || ""));
    const online = cs.filter(c => c.online).length;
    const offline = cs.filter(c => c.status === "offline").length;
    const outdated = cs.filter(c => c.outdated).length;

    /* ---- tiered data-center topology: cluster tier ↑ · core ● · client tier ↓ ---- */
    const cluster = data.cluster || { role: "standalone", nodes: [] };
    const cNodes = (cluster.nodes || []).filter(n => n.role === "worker");
    const clNodes = cluster.role === "worker"
      ? [{ name: "Controller", host: cluster.controller_ip, port: cluster.controller_port,
           role: "controller", online: true }]
      : cNodes;
    const NW = 176, NH = 86;                    // node card size
    const perRow = Math.max(1, Math.floor(1140 / (NW + 26)));
    const rowsCl = clNodes.length ? Math.ceil(clNodes.length / perRow) : 0;
    const accessN = cs.length + devs.length;
    const rowsC = accessN ? Math.ceil(accessN / perRow) : 0;
    const tierH = NH + 46;
    const W = 1200;
    const coreY = 88 + rowsCl * tierH + 70;
    const H = coreY + 96 + (rowsC ? 60 + rowsC * tierH : 40);
    const cx = W / 2;
    const rowXY = (i, total, baseY) => {
      const row = Math.floor(i / perRow);
      const inRow = Math.min(perRow, total - row * perRow);
      const x = cx + ((i % perRow) - (inRow - 1) / 2) * (NW + 26);
      return [x, baseY + row * tierH];
    };
    const elbow = (x, y, ty) => {                // orthogonal bus-style link
      const my = (y + ty) / 2;
      return `M ${x} ${y} L ${x} ${my} L ${cx} ${my} L ${cx} ${ty}`;
    };
    const card = (x, y, { col, name, role, l1, l2, l3, online, cpu = null, ram = null, cls = "", attrs = "", shape = "rect" }) => {
      const L = -NW / 2, T = -NH / 2;
      // silhouette by device type / usage — not only rectangles:
      //   rect   = installed desktop client        phone = mobile phone
      //   tablet = tablet / iPad                   hex   = kiosk / station terminal
      let outline;
      if (shape === "phone") {
        outline = `
        <rect x="${L}" y="${T}" width="${NW}" height="${NH}" rx="16"
          fill="var(--panel2,#141b2d)" stroke="rgba(148,163,184,.25)" stroke-width="1"/>
        <rect x="${-14}" y="${T + 3}" width="28" height="3.5" rx="1.75" fill="${col}" opacity=".55"/>
        <rect x="${-11}" y="${T + NH - 6}" width="22" height="2.5" rx="1.25" fill="#475569"/>
        <rect x="${L}" y="${T + 16}" width="3" height="${NH - 32}" fill="${col}" opacity="${online ? 1 : .45}"/>`;
      } else if (shape === "tablet") {
        outline = `
        <rect x="${L}" y="${T}" width="${NW}" height="${NH}" rx="10"
          fill="var(--panel2,#141b2d)" stroke="rgba(148,163,184,.25)" stroke-width="1"/>
        <circle cx="${L + NW - 8}" cy="0" r="2.5" fill="#475569"/>
        <rect x="${L}" y="${T + 10}" width="3" height="${NH - 20}" fill="${col}" opacity="${online ? 1 : .45}"/>`;
      } else if (shape === "hex") {
        const c8 = 14;   // corner cut → elongated hexagon (kiosk terminal)
        outline = `
        <polygon points="${L + c8},${T} ${L + NW - c8},${T} ${L + NW},0 ${L + NW - c8},${T + NH} ${L + c8},${T + NH} ${L},0"
          fill="var(--panel2,#141b2d)" stroke="rgba(148,163,184,.25)" stroke-width="1"/>
        <polygon points="${L + c8},${T} ${L + c8 + 3},${T} ${L + 3},0 ${L + c8 + 3},${T + NH} ${L + c8},${T + NH} ${L},0"
          fill="${col}" opacity="${online ? 1 : .45}"/>`;
      } else {
        outline = `
        <rect x="${L}" y="${T}" width="${NW}" height="${NH}" rx="4"
          fill="var(--panel2,#141b2d)" stroke="rgba(148,163,184,.25)" stroke-width="1"/>
        <rect x="${L}" y="${T}" width="3" height="${NH}" fill="${col}" opacity="${online ? 1 : .45}"/>`;
      }
      const bar = (label, val, by) => val == null ? "" : `
        <text x="${L + 12}" y="${by + 3.5}" font-size="7.5" fill="#64748b" font-family="Consolas,monospace">${label}</text>
        <rect x="${L + 36}" y="${by - 2}" width="${NW - 78}" height="5" rx="2.5" fill="rgba(148,163,184,.12)"/>
        <rect x="${L + 36}" y="${by - 2}" width="${Math.max(2, (NW - 78) * Math.min(val, 100) / 100)}" height="5" rx="2.5"
          fill="${val > 85 ? "#ef4444" : val > 65 ? "#eab308" : col}"/>
        <text x="${L + NW - 12}" y="${by + 3.5}" text-anchor="end" font-size="7.5" fill="#94a3b8" font-family="Consolas,monospace">${Math.round(val)}%</text>`;
      return `
      <g class="${cls}" ${attrs} transform="translate(${x},${y})">
        ${outline}
        <line x1="${L}" y1="${T + 20}" x2="${L + NW}" y2="${T + 20}" stroke="rgba(148,163,184,.15)"/>
        <circle cx="${L + 13}" cy="${T + 10}" r="3" fill="${online ? col : "#475569"}">
          ${online ? '<animate attributeName="opacity" values="1;.3;1" dur="2s" repeatCount="indefinite"/>' : ""}
        </circle>
        <text x="${L + 23}" y="${T + 13.5}" font-size="10.5" font-weight="700" fill="var(--text,#e2e8f0)"
          font-family="Consolas,monospace" letter-spacing=".5">${esc(name).slice(0, 17).toUpperCase()}</text>
        <text x="${L + NW - 8}" y="${T + 13.5}" text-anchor="end" font-size="7" fill="${col}"
          font-family="Consolas,monospace" letter-spacing="1">${role}</text>
        <text x="${L + 12}" y="${T + 34}" font-size="8.5" fill="#94a3b8" font-family="Consolas,monospace">${esc(l1)}</text>
        ${cpu != null ? bar("CPU", cpu, T + 45) + bar("MEM", ram, T + 57) : `
          <text x="${L + 12}" y="${T + 48}" font-size="8.5" fill="#94a3b8" font-family="Consolas,monospace">${esc(l2)}</text>`}
        <text x="${L + 12}" y="${T + NH - 8}" font-size="7.5" fill="#64748b" font-family="Consolas,monospace">${esc(l3)}</text>
        <text x="${L + NW - 8}" y="${T + NH - 8}" text-anchor="end" font-size="7.5"
          fill="${online ? col : "#475569"}" font-family="Consolas,monospace" letter-spacing="1">${online ? "LINK UP" : "NO LINK"}</text>
      </g>`;
    };
    const tierLabel = (y, txt, col = "#64748b") => `
      <text x="24" y="${y}" font-size="9.5" fill="${col}" font-family="Consolas,monospace" letter-spacing="2">${txt}</text>
      <line x1="${24 + txt.length * 7 + 14}" y1="${y - 3}" x2="${W - 24}" y2="${y - 3}" stroke="rgba(148,163,184,.10)"/>`;

    let linkParts = [];                  // rendered FIRST (beneath all cards)
    let svgParts = [];                   // node cards — rendered above links
    const geo = [];                      // draggable node geometry (key, base x/y, link side)
    /* cluster tier (above core) */
    if (clNodes.length) {
      svgParts.push(tierLabel(46, cluster.role === "worker" ? "CLUSTER CONTROLLER" : "CLUSTER · WORKER SERVERS", "#a78bfa"));
      clNodes.forEach((n, i) => {
        const [x, y] = rowXY(i, clNodes.length, 66 + NH / 2);
        const on = n.online !== false;
        const key = "c:" + (n.node_id || n.host || i);
        geo.push({ key, bx: x, by: y, side: "up" });
        linkParts.push(`<path data-key="${esc(key)}" d="${elbow(x, y + NH / 2, coreY - 54)}" fill="none" class="${on ? "nm-link-on" : "nm-link-off"}"/>`);
        svgParts.push(card(x, y, {
          col: on ? "#a78bfa" : "#ef4444", name: n.name || n.host || "NODE",
          role: n.role === "controller" ? "CTRL" : "COMPUTE",
          l1: `${n.host || ""}${n.port ? ":" + n.port : ""}`,
          l2: on ? `JOBS ${n.active_jobs || 0} ACT / ${n.total_jobs || 0} TOT` : "LINK DOWN",
          l3: `${(n.os || "").toUpperCase().slice(0, 14)}${n.gpu_count ? ` · GPU×${n.gpu_count}` : ""}`,
          cpu: on && n.cpu_percent != null ? n.cpu_percent : null,
          ram: on && n.ram_percent != null ? n.ram_percent : null,
          online: on, cls: "nm-node", attrs: `data-cnode="${esc(n.node_id || n.host || i)}" data-key="${esc(key)}"`,
        }));
      });
    }
    /* core node — rack-panel chassis */
    const CW = 300, CH = 108, CL = cx - CW / 2, CT = coreY - CH / 2;
    svgParts.push(`<g data-key="core" style="cursor:move">
      <rect x="${CL}" y="${CT}" width="${CW}" height="${CH}" rx="5"
        fill="var(--panel2,#141b2d)" stroke="#4f8ef7" stroke-width="1.4"/>
      <rect x="${CL}" y="${CT}" width="${CW}" height="${CH}" rx="5" fill="none"
        stroke="#4f8ef7" stroke-width="1.4" opacity=".3">
        <animate attributeName="stroke-width" values="1.4;4;1.4" dur="3.5s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values=".3;0;.3" dur="3.5s" repeatCount="indefinite"/>
      </rect>
      <rect x="${CL}" y="${CT}" width="${CW}" height="24" fill="#4f8ef7" opacity=".08"/>
      <line x1="${CL}" y1="${CT + 24}" x2="${CL + CW}" y2="${CT + 24}" stroke="rgba(79,142,247,.35)"/>
      <circle cx="${CL + 15}" cy="${CT + 12}" r="3.5" fill="#22c55e">
        <animate attributeName="opacity" values="1;.3;1" dur="2s" repeatCount="indefinite"/>
      </circle>
      <text x="${CL + 27}" y="${CT + 16}" font-size="12.5" font-weight="800" fill="var(--text,#e2e8f0)"
        font-family="Consolas,monospace" letter-spacing="1">${esc((data.server_hostname || "SERVER").toUpperCase())}</text>
      <text x="${CL + CW - 10}" y="${CT + 16}" text-anchor="end" font-size="7.5" fill="#4f8ef7"
        font-family="Consolas,monospace" letter-spacing="1.5">CORE · v${esc(data.server_version)}</text>
      <text x="${CL + 15}" y="${CT + 42}" font-size="8" fill="#64748b" font-family="Consolas,monospace" letter-spacing="1">ENDPOINT</text>
      <text x="${CL + CW - 15}" y="${CT + 42}" text-anchor="end" font-size="9" fill="#e2e8f0" font-family="Consolas,monospace">${esc(location.host)}</text>
      <text x="${CL + 15}" y="${CT + 58}" font-size="8" fill="#64748b" font-family="Consolas,monospace" letter-spacing="1">CLIENT LINKS</text>
      <text x="${CL + CW - 15}" y="${CT + 58}" text-anchor="end" font-size="9" fill="${online === cs.length ? "#22c55e" : "#eab308"}" font-family="Consolas,monospace">${online} / ${cs.length} UP</text>
      <text x="${CL + 15}" y="${CT + 74}" font-size="8" fill="#64748b" font-family="Consolas,monospace" letter-spacing="1">CLUSTER</text>
      <text x="${CL + CW - 15}" y="${CT + 74}" text-anchor="end" font-size="9" fill="${clNodes.length ? "#a78bfa" : "#64748b"}" font-family="Consolas,monospace">${clNodes.length ? `${clNodes.filter(n => n.online !== false).length} / ${clNodes.length} NODES` : "NOT CONFIGURED"}</text>
      <text x="${CL + 15}" y="${CT + 90}" font-size="8" fill="#64748b" font-family="Consolas,monospace" letter-spacing="1">ROLE</text>
      <text x="${CL + CW - 15}" y="${CT + 90}" text-anchor="end" font-size="9" fill="#94a3b8" font-family="Consolas,monospace">${esc((cluster.role || "standalone").toUpperCase())}</text>
    </g>`);
    /* client tier (below core) — installed clients + browser devices */
    if (accessN) {
      const baseY = coreY + 96 + NH / 2;
      svgParts.push(tierLabel(coreY + 80, "ACCESS · CLIENT WORKSTATIONS & DEVICES", "#22c55e"));
      cs.forEach((c, i) => {
        const [x, y] = rowXY(i, accessN, baseY);
        const col = c.online ? "#22c55e" : c.status === "revoked" ? "#ef4444" : c.claimed ? "#ef4444" : "#64748b";
        const key = "l:" + c.license_id;
        geo.push({ key, bx: x, by: y, side: "down" });
        linkParts.push(`<path data-key="${esc(key)}" d="${elbow(x, y - NH / 2, coreY + 54)}" fill="none" class="${c.online ? "nm-link-on" : c.claimed ? "nm-link-off" : "nm-link-idle"}"/>`);
        svgParts.push(card(x, y, {
          col, name: c.note || c.hostname || c.license_key.slice(0, 10),
          role: "CLIENT",
          l1: `HOST ${(c.hostname || "—").toUpperCase()} · ${c.ip || "UNCLAIMED"}`,
          l2: c.version ? `${(c.os || "—").split(" ")[0].toUpperCase()} · v${c.version}${c.outdated ? " ▲" : ""}` : "NOT INSTALLED",
          l3: `${c.mac ? "MAC " + c.mac + " · " : ""}KEY ${c.license_key.slice(0, 10)}…`,
          cpu: c.online && c.cpu != null ? c.cpu : null,
          ram: c.online && c.ram != null ? c.ram : null,
          online: c.online, cls: "nm-node", attrs: `data-lid="${c.license_id}" data-key="${esc(key)}"`,
          shape: (c.usage || "").startsWith("kiosk") ? "hex" : "rect",
        }));
      });
      devs.forEach((d, j) => {
        const i = cs.length + j;
        const [x, y] = rowXY(i, accessN, baseY);
        const col = d.online ? "#38bdf8" : "#64748b";
        const key = "d:" + d.id;
        geo.push({ key, bx: x, by: y, side: "down" });
        linkParts.push(`<path data-key="${esc(key)}" d="${elbow(x, y - NH / 2, coreY + 54)}" fill="none" class="${d.online ? "nm-link-on" : "nm-link-idle"}"/>`);
        const usage = (d.usage || "").replace("station:", "STN ").replace("kiosk:", "KSK ");
        svgParts.push(card(x, y, {
          col, name: d.model ? d.model.split(";")[0] : (d.os || "DEVICE"),
          role: d.kind === "tablet" ? "TABLET" : d.kind === "mobile" ? "MOBILE" : "BROWSER",
          l1: `${(d.os || "—").toUpperCase()} · ${d.ip || "?"}`,
          l2: usage ? usage.toUpperCase() : "WEB TERMINAL",
          l3: `${d.mac ? "MAC " + d.mac + " · " : ""}👤 ${(d.user || "—").toUpperCase().slice(0, 16)}`,
          online: d.online, cls: "nm-node", attrs: `data-key="${esc(key)}"`,
          shape: (d.usage || "").startsWith("station") && d.kind === "desktop-browser" ? "hex"
            : d.kind === "tablet" ? "tablet" : d.kind === "mobile" ? "phone" : "hex",
        }));
      });
    }
    const mapSvg = `
    <svg viewBox="0 0 ${W} ${H}" style="height:${Math.min(H, 640)}px"><g class="nm-links">${linkParts.join("")}</g>${svgParts.join("")}</svg>
    <div class="nm-legend" style="font-family:Consolas,monospace;font-size:10px;letter-spacing:1px">
      <span><span class="noc-led ok"></span>LINK UP</span>
      <span><span class="noc-led crit"></span>LINK DOWN</span>
      <span><span class="noc-led off"></span>UNCLAIMED</span>
      ${clNodes.length ? '<span style="color:#a78bfa">▬ CLUSTER TIER</span>' : ""}
      <span style="color:#22c55e">▬ ACCESS TIER</span>
      <span style="color:#4f8ef7">▬ CORE</span>
      <span style="color:#94a3b8">▭ DESKTOP</span>
      <span style="color:#38bdf8">▢ MOBILE</span>
      <span style="color:#38bdf8">⬡ KIOSK/STATION</span>
      <span class="spacer"></span>
      <span style="color:#64748b">SCROLL · ZOOM &nbsp;·&nbsp; DRAG BG · PAN &nbsp;·&nbsp; DRAG NODE · MOVE &nbsp;·&nbsp; DBL-CLICK · RESET</span>
    </div>`;

    const badge = (c) =>
      c.status === "online" ? '<span class="pill" style="background:#22c55e33">🟢 online</span>' :
      c.status === "offline" ? '<span class="pill" style="background:#ef444433">🔴 offline</span>' :
      c.status === "revoked" ? '<span class="pill" style="background:#ef444433">⛔ revoked</span>' :
      '<span class="pill">⚪ never connected</span>';

    v.innerHTML = `
    <div class="noc-topbar">
      <div class="noc-kpi"><span class="k">Fleet status</span>
        <span class="v"><span class="noc-led ${offline ? "warn" : "ok"}"></span>${offline ? "DEGRADED" : "NOMINAL"}</span></div>
      <div class="noc-kpi"><span class="k">Links up</span><span class="v" style="color:#22c55e">${online} <small>/ ${cs.length}</small></span></div>
      <div class="noc-kpi"><span class="k">Links down</span><span class="v" style="color:${offline ? "#ef4444" : "inherit"}">${offline}</span></div>
      <div class="noc-kpi"><span class="k">Updating</span><span class="v" style="color:${outdated ? "#eab308" : "inherit"}">${outdated}</span></div>
      <div class="noc-kpi"><span class="k">Cluster</span><span class="v" style="font-size:16px;color:${clNodes.length ? "#a78bfa" : "inherit"}">${cluster.role === "standalone" && !clNodes.length ? "—" : `${clNodes.filter(n => n.online !== false).length}/${clNodes.length} <small>${esc(cluster.role)}</small>`}</span></div>
      ${seats ? `<div class="noc-kpi"><span class="k">Seats</span>
        <span class="v" style="color:${seats.limit > 0 && seats.used >= seats.limit ? "#ef4444" : seats.limit > 0 && seats.used >= seats.limit * .8 ? "#eab308" : "#22c55e"}">${seats.used}${seats.limit > 0 ? ` <small>/ ${seats.limit}</small>` : " <small>/ ∞</small>"}</span></div>
      <div class="noc-kpi"><span class="k">License</span>
        <span class="v" style="font-size:14px;color:${seats.plan ? "#4f8ef7" : "#eab308"}">${seats.plan ? esc(seats.plan.toUpperCase()) : "EVALUATION"}</span></div>` : ""}
      <div class="noc-kpi"><span class="k">Core version</span><span class="v">v${esc(data.server_version)}</span></div>
      <span class="spacer"></span>
      <span class="muted" style="font-size:11px;font-family:Consolas,monospace">HEARTBEAT 30s · OFFLINE &gt;${data.online_window_s}s · REFRESH 10s</span>
      <button class="btn" id="cl-refresh">🔄 Refresh</button>
    </div>
    <div class="noc-panel" style="margin-bottom:14px">
      <div class="noc-head"><span class="noc-led ${online || clNodes.length ? "ok" : "off"}"></span><b>Network topology</b>
        ${seats && seats.company ? `<small style="margin-left:12px;color:#4f8ef7">LICENSED TO ${esc(seats.company.toUpperCase())}</small>` : ""}
        <span class="spacer"></span><small>${new Date().toISOString().slice(0, 19).replace("T", " ")} UTC · CLICK ANY NODE TO CONFIGURE IT REMOTELY</small></div>
      <div class="netmap-wrap">${accessN || clNodes.length ? mapSvg :
        '<div class="empty" style="padding:60px 20px"><div class="big">🖥</div>No client licenses yet.<br>Register purchased license keys in <b>⚙️ Settings → 🔑 License keys</b> — installed clients appear on this map automatically.</div>'}</div>
    </div>
    ${cs.length ? `<div class="noc-panel" style="margin-bottom:14px">
      <div class="noc-head"><b>Connection inventory — installed clients</b><span class="spacer"></span><small>${cs.length} LICENSE(S)</small></div>
      <table class="noc-table"><thead><tr>
        <th>Status</th><th>Type</th><th>Computer</th><th>OS</th><th>IP address</th><th>MAC address</th><th>CPU serial</th><th>Disk serial</th><th>Usage</th><th>Version</th><th>License key</th><th>Last seen</th><th></th>
      </tr></thead><tbody>` + cs.map(c => `<tr>
        <td>${badge(c)}</td>
        <td>🖥 ${esc(c.device_type || "desktop")}</td>
        <td><b>${esc(c.hostname || "—")}</b></td>
        <td>${esc(c.os || "—")}</td>
        <td class="num">${esc(c.ip || "—")}</td>
        <td class="num">${esc(c.mac || "—")}</td>
        <td class="num" title="${esc(c.cpu_serial || "")}">${esc((c.cpu_serial || "—").slice(0, 14))}${(c.cpu_serial || "").length > 14 ? "…" : ""}</td>
        <td class="num" title="${esc(c.disk_serial || "")}">${esc((c.disk_serial || "—").slice(0, 14))}${(c.disk_serial || "").length > 14 ? "…" : ""}</td>
        <td>${esc(c.usage || "operation")}</td>
        <td class="num">${c.version ? "v" + esc(c.version) + (c.outdated ? ' <span class="pill" style="background:#f59e0b33" title="Older than the server — forced update on next heartbeat">⬆</span>' : "") : "—"}</td>
        <td class="num">${esc(c.license_key)}</td>
        <td class="num muted">${c.last_seen_at ? new Date(c.last_seen_at + "Z").toLocaleString() : "—"}</td>
        <td><button class="btn" data-cfg="${c.license_id}" style="padding:3px 10px;font-size:12px">⚙ Configure</button></td>
      </tr>`).join("") + `</tbody></table></div>` : ""}
    ${devs.length ? `<div class="noc-panel">
      <div class="noc-head"><b>Browser devices — mobile / tablet / kiosk terminals (no install)</b><span class="spacer"></span><small>${devs.length} DEVICE(S)</small></div>
      <table class="noc-table"><thead><tr>
        <th>Status</th><th>Type</th><th>Device</th><th>OS</th><th>IP address</th><th>MAC address</th><th>Usage</th><th>Operator</th><th>Last seen</th>
      </tr></thead><tbody>` + devs.map(d => `<tr>
        <td>${d.online ? '<span class="pill" style="background:#38bdf833">📱 online</span>' : '<span class="pill">⚪ offline</span>'}</td>
        <td>${d.kind === "tablet" ? "📟 tablet" : d.kind === "mobile" ? "📱 mobile" : "🌐 browser"}</td>
        <td><b>${esc((d.model || d.device_uid).slice(0, 34))}</b></td>
        <td>${esc(d.os || "—")}</td>
        <td class="num">${esc(d.ip || "—")}</td>
        <td class="num" title="Browsers cannot expose the WiFi MAC address — recorded from managed-device enrollment when available">${esc(d.mac || "— (browser)")}</td>
        <td>${esc(d.usage || "—")}</td>
        <td>${esc(d.user || "—")}</td>
        <td class="num muted">${d.last_seen_at ? new Date(d.last_seen_at + "Z").toLocaleString() : "—"}</td>
      </tr>`).join("") + `</tbody></table></div>` : ""}`;

    $("#cl-refresh").onclick = render;

    /* ---- interactive map: scroll = zoom · drag background = pan · drag node = move ---- */
    let suppressClick = false;
    const svgEl = v.querySelector(".netmap-wrap svg");
    if (svgEl) {
      const OFFK = "nmOffsets";
      const off = () => { try { return JSON.parse(localStorage.getItem(OFFK) || "{}"); } catch { return {}; } };
      const saveOff = (o) => localStorage.setItem(OFFK, JSON.stringify(o));
      const corePos = () => { const o = off().core || [0, 0]; return [cx + o[0], coreY + o[1]]; };
      const redraw = () => {
        const [ccx, ccy] = corePos();
        const coreEl = svgEl.querySelector("g[data-key='core']");
        if (coreEl) coreEl.setAttribute("transform", `translate(${ccx - cx},${ccy - coreY})`);
        geo.forEach(g => {
          const o = off()[g.key] || [0, 0];
          const x = g.bx + o[0], y = g.by + o[1];
          const node = svgEl.querySelector(`g[data-key='${g.key}']`);
          const link = svgEl.querySelector(`path[data-key='${g.key}']`);
          if (node) node.setAttribute("transform", `translate(${x},${y})`);
          if (link) {
            const sy = g.side === "up" ? y + NH / 2 : y - NH / 2;
            const ty = g.side === "up" ? ccy - 54 : ccy + 54;
            const my = (sy + ty) / 2;
            link.setAttribute("d", `M ${x} ${sy} L ${x} ${my} L ${ccx} ${my} L ${ccx} ${ty}`);
          }
        });
      };
      redraw();
      let vb = [0, 0, W, H];
      const setVB = () => svgEl.setAttribute("viewBox", vb.join(" "));
      svgEl.style.cursor = "grab";
      svgEl.addEventListener("wheel", (e) => {
        e.preventDefault();
        const r = svgEl.getBoundingClientRect();
        const mx = vb[0] + (e.clientX - r.left) / r.width * vb[2];
        const my = vb[1] + (e.clientY - r.top) / r.height * vb[3];
        const nw = Math.min(Math.max(vb[2] * (e.deltaY > 0 ? 1.15 : 1 / 1.15), W / 8), W * 3);
        const s = nw / vb[2];
        vb = [mx - (mx - vb[0]) * s, my - (my - vb[1]) * s, nw, vb[3] * s];
        setVB();
      }, { passive: false });
      svgEl.addEventListener("dblclick", (e) => {
        if (e.target.closest("g[data-key]")) return;
        vb = [0, 0, W, H]; setVB();
        saveOff({}); redraw();                      // reset layout too
      });
      let drag = null;
      svgEl.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        const nodeEl = e.target.closest("g[data-key]");
        drag = { key: nodeEl ? nodeEl.dataset.key : null,
                 cx0: e.clientX, cy0: e.clientY, vb0: [...vb],
                 o0: nodeEl ? (off()[nodeEl.dataset.key] || [0, 0]) : null, moved: false };
        svgEl.setPointerCapture(e.pointerId);
        svgEl.style.cursor = "grabbing";
      });
      svgEl.addEventListener("pointermove", (e) => {
        if (!drag) return;
        if (Math.abs(e.clientX - drag.cx0) + Math.abs(e.clientY - drag.cy0) > 4) drag.moved = true;
        if (!drag.moved) return;
        const r = svgEl.getBoundingClientRect();
        if (drag.key) {                              // move a node (layout persists)
          const dx = (e.clientX - drag.cx0) / r.width * vb[2];
          const dy = (e.clientY - drag.cy0) / r.height * vb[3];
          const o = off(); o[drag.key] = [drag.o0[0] + dx, drag.o0[1] + dy];
          saveOff(o); redraw();
        } else {                                     // pan the viewport
          vb[0] = drag.vb0[0] - (e.clientX - drag.cx0) / r.width * drag.vb0[2];
          vb[1] = drag.vb0[1] - (e.clientY - drag.cy0) / r.height * drag.vb0[3];
          setVB();
        }
      });
      const endDrag = () => {
        if (!drag) return;
        suppressClick = drag.moved;
        setTimeout(() => { suppressClick = false; }, 50);
        drag = null; svgEl.style.cursor = "grab";
      };
      svgEl.addEventListener("pointerup", endDrag);
      svgEl.addEventListener("pointercancel", endDrag);
    }

    const open = (lid) => { const c = cs.find(x => x.license_id === lid); if (c) clientConfigModal(c, render); };
    v.querySelectorAll(".nm-node").forEach(n => n.addEventListener("click", () => {
      if (suppressClick) return;
      if (n.dataset.lid) return open(n.dataset.lid);
      const cn = clNodes.find(x => String(x.node_id || x.host) === n.dataset.cnode) ||
                 clNodes[[...v.querySelectorAll("[data-cnode]")].indexOf(n)];
      if (cn) clusterNodeModal(cn, cluster);
    }));
    v.querySelectorAll("[data-cfg]").forEach(b => b.onclick = () => open(b.dataset.cfg));
  };
  await render();
  const t = setInterval(() => {
    if (state.view !== "clients") { clearInterval(t); return; }
    if (!$("#modal-root").innerHTML) render();       // don't refresh under an open dialog
  }, 10000);
};

/* Remote configuration of a client program — delivered on its next heartbeat
   (≤30 s); the client merges it into platform/data/config.json and restarts. */
async function clientConfigModal(c, onDone) {
  let cur = { config: {}, config_rev: 0 };
  try { cur = await api(`/clients/${c.license_id}/config`); } catch { /* defaults */ }
  const g = (k, d = "") => cur.config[k] ?? d;
  modal(`Client configuration — ${c.hostname || c.license_key}`, `
    ${wizSect("🖥", "Client node", "Live state reported by this computer")}
    <table class="noc-table" style="margin-top:6px">
      <tr><td>Status</td><td>${c.online ? '<span class="noc-led ok"></span>online' : '<span class="noc-led crit"></span>' + esc(c.status)}</td>
          <td>IP</td><td class="num">${esc(c.ip || "—")}</td></tr>
      <tr><td>OS</td><td>${esc(c.os || "—")}</td>
          <td>Version</td><td class="num">${c.version ? "v" + esc(c.version) : "—"}${c.outdated ? " ⬆ updating" : ""}</td></tr>
      <tr><td>License</td><td class="num" colspan="3">${esc(c.license_key)}</td></tr>
    </table>
    ${wizSect("🏷", "Label", "Shown on the network map and in the inventory")}
    <label>Note<input name="note" value="${esc(c.note || "")}" placeholder="e.g. Peter's laptop — Sales dept."></label>
    ${wizSect("⚙", "Program settings", "Pushed on the next heartbeat (≤30 s) — the client applies them and restarts automatically")}
    <div class="wiz-grid">
      <label>Server IP the client connects to<input name="client_server_ip" value="${esc(g("client_server_ip"))}" placeholder="keep current"></label>
      <label>Server port<input name="client_server_port" value="${esc(g("client_server_port"))}" placeholder="keep current" inputmode="numeric"></label>
    </div>
    <label>Advanced — extra config.json keys (JSON object)
      <textarea name="extra" placeholder='e.g. {"language": "en"}' style="font-family:Consolas,monospace;font-size:12.5px">${esc(JSON.stringify(Object.fromEntries(Object.entries(cur.config).filter(([k]) => !["client_server_ip", "client_server_port"].includes(k))), null, 2).replace(/^\{\}$/, ""))}</textarea></label>
    <p class="muted" style="font-size:11px;margin-top:6px">🛡 license_key and deploy_mode can never be changed remotely. Current push revision: ${cur.config_rev}${c.config_rev ? " · applied by client: heartbeat-confirmed" : ""}</p>`,
    async (fd) => {
      const cfg = {};
      const ip = fd.get("client_server_ip").trim(), port = fd.get("client_server_port").trim();
      if (ip) cfg.client_server_ip = ip;
      if (port) { const p = parseInt(port, 10); if (!p) throw new Error("Server port must be a number"); cfg.client_server_port = p; }
      const extra = fd.get("extra").trim();
      if (extra) {
        let obj; try { obj = JSON.parse(extra); } catch { throw new Error("Advanced settings must be a valid JSON object"); }
        if (typeof obj !== "object" || Array.isArray(obj)) throw new Error("Advanced settings must be a JSON object");
        Object.assign(cfg, obj);
      }
      await api(`/clients/${c.license_id}/config`, { method: "PUT", body: { config: cfg, note: fd.get("note") } });
      toast(Object.keys(cfg).length
        ? "Configuration pushed — the client applies it on its next heartbeat (≤30 s) and restarts"
        : "Configuration cleared", "ok");
      onDone && onDone();
    }, "Push to client");
}

/* Cluster server node clicked on the network map — live details + management
   actions. Cluster nodes are configured through 🖧 Cluster (shared secret,
   role, controller address); this dialog opens the node's own web console. */
function clusterNodeModal(n, cluster) {
  const on = n.online !== false;
  const addr = `${n.host || ""}${n.port ? ":" + n.port : ""}`;
  modal(`Cluster server — ${n.name || n.host || "node"}`, `
    ${wizSect("🗄", "Cluster node", "Live state reported over the cluster heartbeat (every 10 s)")}
    <table class="noc-table" style="margin-top:6px">
      <tr><td>Status</td><td>${on ? '<span class="noc-led ok"></span>online' : '<span class="noc-led crit"></span>offline' + (n.last_seen_s != null ? ` (${n.last_seen_s}s)` : "")}</td>
          <td>Role</td><td>${esc(n.role || "worker").toUpperCase()}</td></tr>
      <tr><td>Address</td><td class="num">${esc(addr || "—")}</td>
          <td>OS</td><td>${esc(n.os || "—")}</td></tr>
      <tr><td>CPU cores</td><td class="num">${n.cpu_count || "—"}${n.cpu_percent != null ? ` · ${n.cpu_percent}% load` : ""}</td>
          <td>GPUs</td><td>${n.gpu_count ? `🎮 ${n.gpu_count} — ${esc(n.gpu_names || "")}` : "—"}</td></tr>
      <tr><td>Active jobs</td><td class="num">${n.active_jobs || 0}</td>
          <td>Total jobs</td><td class="num">${(n.total_jobs || 0).toLocaleString()}</td></tr>
    </table>
    ${wizSect("⚙", "Configure this server", "Each cluster server manages its own settings through its web console")}
    <p class="muted" style="font-size:12.5px;margin:4px 0 8px">
      Open the node's console to change its configuration (providers, ports,
      role, secrets). Cluster membership (role · controller address · shared
      secret) is set in <b>🖧 Cluster → ⚙ Cluster configuration</b> on each node.</p>
    <div class="toolbar" style="gap:8px">
      <a class="btn primary" href="http://${esc(addr)}" target="_blank" rel="noopener">🔗 Open node console</a>
      <a class="btn" href="#" id="cn-goto-cluster">🖧 Cluster settings</a>
    </div>`,
    async () => { /* informational — no submit action */ }, "Close");
  const go = $("#cn-goto-cluster");
  if (go) go.onclick = (e) => { e.preventDefault(); $("#modal-root").innerHTML = ""; nav("cluster"); };
}

views.settings = async (v) => {
  const [{ config, meta }, gpu] = await Promise.all([api("/config"), api("/gpu").catch(() => null)]);
  const apis = Array.isArray(config.ai_apis) ? config.ai_apis : [];
  const grp = (g) => Object.entries(meta).filter(([, m]) => m.group === g)
    .map(([k, m]) => cfgField(k, m, config)).join("");
  const gpuHtml = gpu ? `
    <p style="font-size:13px;margin:4px 0">${gpu.gpu_enabled
      ? `<b style="color:#22c55e">✅ ${gpu.gpu_count} GPU${gpu.gpu_count > 1 ? "s" : ""} detected — GPU processing is FORCED</b>`
      : `<b style="color:#eab308">⚠️ No GPU detected — running on CPU only</b>`}</p>
    <p class="muted" style="font-size:12px;margin-top:0">${esc(gpu.policy)}</p>
    ${gpu.gpus.map(g => `<div class="card" style="padding:10px;margin:6px 0">
      <b>🎮 GPU ${g.index}: ${esc(g.name)}</b> <span class="pill">${esc(g.vendor)}</span>${g.cuda ? ' <span class="pill" style="background:#22c55e33">CUDA</span>' : ""}
      <div class="muted" style="font-size:12px;margin-top:4px">
        ${g.memory_total_mb != null ? `VRAM: ${g.memory_used_mb} / ${g.memory_total_mb} MB · ` : ""}
        ${g.utilization_pct != null ? `Utilization: ${g.utilization_pct}% · ` : ""}
        ${g.temperature_c != null ? `Temp: ${g.temperature_c}°C · ` : ""}
        ${g.driver ? `Driver: ${esc(g.driver)}` : ""}</div>
      ${g.memory_total_mb ? `<div class="pbar" style="margin-top:6px"><div class="pbar-fill" style="width:${Math.round(g.memory_used_mb / g.memory_total_mb * 100)}%"></div></div>` : ""}
    </div>`).join("")}` : "<p class='muted'>GPU information unavailable.</p>";

  const TABS = [
    ["deploy", "🌐 Deployment"], ["apis", "🔌 AI APIs"],
    ["agents", "⚙️ Agents"], ["cameras", "📷 Cameras"], ["email", "📧 Email"], ["mobile", "📱 Mobile"],
    ["licenses", "🔑 License keys"], ["gpu", "🎮 GPU"], ["about", "ℹ️ About"],
  ];
  v.innerHTML = `<div class="settings-wrap">
    <div class="settings-tabs">${TABS.map(([id, l], i) =>
      `<button class="stab ${i === 0 ? "active" : ""}" data-tab="${id}">${l}</button>`).join("")}</div>
    <form id="cfg-form" class="settings-body card">

      <section class="spane active" data-pane="deploy">
        <h3>🌐 Deployment</h3>
        <p class="muted sdesc">Server mode runs the platform on this machine (choose any port). Client mode connects this program to a company server. Changes take effect the next time <code>start.py</code> runs.</p>
        <div class="cfg-grid">${grp("deploy")}</div>
        <div class="toolbar" style="margin:10px 0"><button type="button" class="btn" id="lan-detect">🔍 Auto-detect servers on LAN</button>
          <span id="lan-detect-out" class="muted" style="font-size:12px"></span></div>
      </section>

      <section class="spane" data-pane="apis">
        <h3>🔌 AI APIs</h3>
        <p class="muted sdesc">Connect one or more AI APIs — OpenAI-compatible (OpenAI, Azure, Ollama, LM Studio, Groq, DeepSeek…) or Anthropic. They are used automatically when the Codex / Claude Code CLIs are missing, tried <b>in order from top to bottom with automatic failover</b>. Server mode shares these APIs with all connected clients.</p>
        <div id="api-list">${apis.map(apiRow).join("") ||
          `<div class="empty" id="api-empty"><div class="big">🔌</div>No AI APIs configured yet. Add your first one below.</div>`}</div>
        <button type="button" class="btn" id="api-add">➕ Add AI API</button>
      </section>

      <section class="spane" data-pane="agents">
        <h3>⚙️ Agent settings</h3>
        <p class="muted sdesc">How agents run on this computer: timeouts, output folders and pipelines.</p>
        <div class="cfg-grid">${grp("agents")}</div>
      </section>

      <section class="spane" data-pane="cameras">
        <h3>📷 Cameras — face recognition &amp; serial-number capture</h3>
        <p class="muted sdesc"><b>Internal camera</b> silently captures the operator's face for every operations-log
          entry (biometric attribution). <b>External camera</b> is used for serial-number OCR capture and future
          scanning features. Enter part of the camera's device name (e.g. <code>integrated</code>, <code>USB</code>) —
          these are the <b>server-wide defaults</b>; each client computer can override them in its own
          tray settings or Setup page, and the client's own setting always wins.</p>
        <div class="cfg-grid">${grp("cameras")}</div>
      </section>

      <section class="spane" data-pane="email">
        <h3>📧 Email (SMTP)</h3>
        <p class="muted sdesc">Real email delivery. Leave the host empty to simulate sends into <code>platform/data/outbox/</code>. For Gmail, use an App Password.</p>
        <div class="cfg-grid">${grp("email")}</div>
        <h4 style="margin:14px 0 6px">Connection test</h4>
        <p class="muted" style="font-size:12px">Save first, then send a test email to verify connection, login and delivery.</p>
        <div style="display:flex;gap:8px;align-items:center;max-width:520px">
          <input id="smtp-test-to" type="email" value="apictrading.peter@gmail.com" placeholder="recipient@example.com" style="flex:1">
          <button type="button" class="btn" id="smtp-test-btn">📧 Send test email</button>
        </div>
        <p id="smtp-test-result" style="font-size:12px;margin-top:8px"></p>
      </section>

      <section class="spane" data-pane="mobile">
        <h3>📱 Mobile & notifications</h3>
        <p class="muted sdesc">WhatsApp/WeChat webhook, allowed senders and Twilio integration.</p>
        <div class="cfg-grid">${grp("mobile")}</div>
      </section>

      <section class="spane" data-pane="licenses">
        <h3>🌐 Server license (mapstudiousa.com)</h3>
        <p class="muted sdesc">Enter the license key <b>purchased at mapstudiousa.com</b> to activate this
          <b>server</b>. Until a key is validated, the platform runs in <b>evaluation mode</b>: no seat limit is
          enforced and connected devices are <b>not reported</b> to your mapstudiousa.com NexaCrew portal
          (the portal will show "server not yet activated" and 0 devices). Save settings, then click
          <b>Validate now</b>.</p>
        <div class="cfg-grid">${grp("license")}</div>
        <div class="toolbar" style="margin:10px 0">
          <button type="button" class="btn primary" id="auth-check">✅ Validate now</button>
          <span id="auth-status" class="muted" style="font-size:12px">Loading…</span>
        </div>
        <hr style="border:none;border-top:1px solid var(--border,#333);margin:16px 0">
        <h3>🔑 Client license keys</h3>
        <p class="muted sdesc">License keys are <b>no longer generated locally</b>. Purchase keys at
          <a href="https://mapstudiousa.com/nexacrew.php" target="_blank" rel="noopener">mapstudiousa.com</a> (or receive them from your administrator),
          then register them here — each key is verified online with the licensing authority before it is accepted.
          A registered key binds to the <b>first computer</b> that claims it.</p>
        <div class="toolbar" style="margin-bottom:10px;flex-wrap:wrap">
          <input id="lic-keys" placeholder="XXXXX-XXXXX-XXXXX-XXXXX (one or more, separated by spaces)" style="width:340px;font-family:Consolas,monospace">
          <input id="lic-note" placeholder="Note (e.g. Peter's laptop)" style="width:200px">
          <button type="button" class="btn primary" id="lic-gen">➕ Register key(s)</button>
        </div>
        <div id="lic-list"><p class="muted">Loading…</p></div>
      </section>

      <section class="spane" data-pane="gpu">
        <h3>🎮 GPU acceleration</h3>
        ${gpuHtml}
      </section>

      <section class="spane" data-pane="about">
        <h3>ℹ️ About</h3>
        <p style="font-size:13px">Signed in as <b>${esc(state.user.display_name || state.user.username)}</b></p>
        ${window.clientInfo && window.clientInfo.license_key ? `
        <p style="font-size:13px">🔑 This computer's client license:
          <code style="font-family:Consolas,monospace;letter-spacing:.5px">${esc(window.clientInfo.license_key)}</code>
          <span class="pill">client v${esc(window.clientInfo.version || "?")}</span></p>` : ""}
        <p style="font-size:13px">🧠 <b>Codex CLI</b> — planning & execution agent · 🤖 <b>Claude Code CLI</b> — implementation agent · ✉ <b>Email</b> — SMTP or simulated outbox</p>
        <h4>Security</h4>
        <p class="muted" style="font-size:13px">Credentials are encrypted at rest (Fernet). Sessions are HTTP-only cookies. Audit log is hash-chained for tamper evidence. Company data is isolated per user at the service layer.</p>
        <p class="muted" style="font-size:13px"><img src="/static/mapstudio_logo.jpg" alt="MAP Studio" class="brand-logo-sm"><br>🏢 <b>NexaCrew</b> — Virtual Company AI Agent Platform<br>Developed by <b>Sin Chi Chiu</b> · MAP Studio<br>Support Telephone : +1-949-331-6528<br>Email : <a href="mailto:peterchiu@mapstudiousa.com">peterchiu@mapstudiousa.com</a><br>Website : <a href="https://www.mapstudiousa.com" target="_blank" rel="noopener">www.mapstudiousa.com</a></p>
      </section>

      <div class="settings-save"><button class="btn primary" type="submit">💾 Save all settings</button>
        <span class="muted" style="font-size:12px">Saves every tab at once.</span></div>
    </form>
  </div>`;

  // tab switching
  $$(".stab", v).forEach(b => b.onclick = () => {
    $$(".stab", v).forEach(x => x.classList.toggle("active", x === b));
    $$(".spane", v).forEach(p => p.classList.toggle("active", p.dataset.pane === b.dataset.tab));
    if (b.dataset.tab === "licenses") { loadLicenses(); loadAuthority(); }
  });

  // ---- server license (authority) status ----
  function renderAuthority(a) {
    const el = $("#auth-status"); if (!el) return;
    if (!a || a.status === "unconfigured" || a.configured === false) {
      el.innerHTML = `<span style="color:#eab308">⚠ Evaluation mode — enter your purchased key above, save settings, then click Validate now.</span>`;
      return;
    }
    const ok = a.status === "active" || a.status === "grace";
    el.innerHTML = ok
      ? `<span style="color:#22c55e">✅ ${a.status === "grace" ? "Grace window" : "Licensed"}</span>` +
        ` — <b>${esc(a.company || "")}</b> · ${esc(a.plan || "?")} plan · ${a.seats > 0 ? a.seats + " seats" : "∞"}` +
        (a.expires_at ? ` · expires ${esc(String(a.expires_at).slice(0, 10))}` : "") +
        (a.last_ok_at ? ` · last validated ${new Date(a.last_ok_at * 1000).toLocaleString()}` : "")
      : `<span style="color:#ef4444">❌ ${esc(a.status || "error")}</span> — ${esc(a.detail || "")}`;
  }
  async function loadAuthority() {
    try { renderAuthority(await api("/license-authority")); }
    catch (e) { const el = $("#auth-status"); if (el) el.textContent = "Status unavailable: " + e.message; }
  }
  $("#auth-check").onclick = async () => {
    const el = $("#auth-status");
    const f = $("#cfg-form").elements;
    const key = (f.authority_license_key ? f.authority_license_key.value : "").trim().toUpperCase();
    if (!key) { toast("Enter the server license key purchased on mapstudiousa.com first", "err"); return; }
    if (!/^[A-F0-9]{5}(-[A-F0-9]{5}){3}$/.test(key)) {
      toast("Key format looks wrong — expected XXXXX-XXXXX-XXXXX-XXXXX", "err"); return;
    }
    el.textContent = "Saving license settings…";
    try {
      // auto-save the license fields so Validate always uses what's on screen
      await api("/config", { method: "PUT", body: {
        authority_url: (f.authority_url ? f.authority_url.value : "").trim(),
        authority_license_key: key,
        authority_check_hours: f.authority_check_hours ? f.authority_check_hours.value : 12,
      } });
    } catch (e) { el.textContent = "❌ save failed: " + e.message; toast("Could not save license settings: " + e.message, "err"); return; }
    el.textContent = "Contacting mapstudiousa.com…";
    try {
      const r = await api("/license-authority/check", { method: "POST" });
      renderAuthority(r);
      toast(r.status === "active" ? "License validated ✓ — devices now sync to your portal" :
            r.status === "unconfigured" ? "Enter the key above and SAVE settings first" :
            "Validation result: " + (r.detail || r.status), r.status === "active" ? "ok" : "err");
      loadLicenses();
    } catch (e) { el.textContent = "❌ " + e.message; toast("Validation failed: " + e.message, "err"); }
  };

  // license key manager
  async function loadLicenses() {
    const box = $("#lic-list");
    try {
      const { licenses, seats } = await api("/licenses");
      const s = seats || { limit: 0, used: 0 };
      const pct = s.limit > 0 ? Math.min(100, Math.round(s.used * 100 / s.limit)) : 0;
      const barColor = pct >= 90 ? "#ef4444" : pct >= 70 ? "#eab308" : "#22c55e";
      const TYPE_ICON = { server: "🖥", desktop: "💻", laptop: "💻", client: "💻",
                          mobile: "📱", phone: "📱", tablet: "📟", kiosk: "🧾" };
      const byType = s.by_type || {};
      const typePills = Object.entries(byType)
        .map(([t, n]) => `<span class="pill" style="margin-left:6px">${TYPE_ICON[t] || "🔌"} ${esc(t)}: ${n}</span>`).join("");
      const seatBar = `
        <div style="margin:0 0 14px;padding:12px 14px;border:1px solid var(--border,#2a3344);border-radius:10px">
          <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:13px">
            <span>💺 <b>Seats used: ${s.used} / ${s.limit > 0 ? s.limit : "∞ (evaluation)"}</b>
              ${s.plan ? `<span class="pill" style="margin-left:8px">${esc(s.plan)} plan</span>` : ""}
              ${s.company ? `<span class="muted" style="margin-left:6px">${esc(s.company)}</span>` : ""}</span>
            <span class="muted">🖥 Server: <b>${esc(s.server || "?")}</b> — every device counts one seat (server, desktop client, mobile, tablet, kiosk); counts sync to mapstudiousa.com on every validation</span>
          </div>
          ${typePills ? `<div style="margin-top:6px;font-size:12px">${typePills}</div>` : ""}
          ${s.limit > 0 ? `<div style="height:7px;background:#33415533;border-radius:4px;margin-top:8px">
            <div style="height:7px;border-radius:4px;width:${pct}%;background:${barColor}"></div></div>
          ${s.used >= s.limit ? `<div style="color:#ef4444;font-size:12px;margin-top:6px">⚠ Seat limit reached — new devices cannot claim a key. Upgrade the plan at mapstudiousa.com or delete an unused key below.</div>` : ""}` : ""}
        </div>`;
      if (!licenses.length) { box.innerHTML = seatBar + `<div class="empty"><div class="big">🔑</div>No license keys registered — purchase keys on <a href="https://mapstudiousa.com/nexacrew.php" target="_blank" rel="noopener">mapstudiousa.com</a> and register them above.</div>`; return; }
      box.innerHTML = seatBar + `<table class="table"><thead><tr>
          <th>License key</th><th>Status</th><th>Used by (server → client)</th><th>Client IP</th><th>Note</th><th>Claimed</th><th></th>
        </tr></thead><tbody>` + licenses.map(l => `<tr>
          <td style="font-family:Consolas,monospace;letter-spacing:.5px">${esc(l.key)}
            <button type="button" class="mini-btn" data-copy="${esc(l.key)}" title="Copy">📋</button></td>
          <td>${l.revoked ? '<span class="pill" style="background:#ef444433">revoked</span>'
              : l.used ? '<span class="pill" style="background:#eab30833">🔒 in use (1 seat)</span>'
              : '<span class="pill" style="background:#22c55e33">✅ unused</span>'}</td>
          <td>${l.used ? `🖥 <b>${esc(s.server || "server")}</b> → 💻 <b>${esc(l.used_by_host || "unknown device")}</b>` : '<span class="muted">—</span>'}</td>
          <td>${esc(l.used_by_ip || "—")}</td>
          <td>${esc(l.note || "")}</td>
          <td class="muted" style="font-size:12px">${l.used_at ? new Date(l.used_at).toLocaleString() : "—"}</td>
          <td><button type="button" class="mini-btn" data-del="${l.id}" title="Delete key (frees its seat)">🗑</button></td>
        </tr>`).join("") + `</tbody></table>`;
      $$("[data-copy]", box).forEach(b => b.onclick = async () => { const ok = await copyText(b.dataset.copy); toast(ok ? "Key copied" : "Copy failed", ok ? "ok" : "err"); });
      $$("[data-del]", box).forEach(b => b.onclick = async () => {
        if (!confirm("Delete this license key? A client using it will no longer validate.")) return;
        await api("/licenses/" + b.dataset.del, { method: "DELETE" });
        toast("License key deleted", "ok"); loadLicenses();
      });
    } catch (e) { box.innerHTML = `<p class="error">❌ ${esc(e.message)}</p>`; }
  }
  $("#lic-gen").onclick = async () => {
    const keys = $("#lic-keys").value.trim();
    if (!keys) { toast("Enter the license key(s) purchased on mapstudiousa.com", "err"); return; }
    try {
      const r = await api("/licenses", { method: "POST", body: {
        keys, note: $("#lic-note").value.trim() } });
      if (r.licenses.length) toast(`${r.licenses.length} key(s) verified with mapstudiousa.com and registered ✓`, "ok");
      (r.errors || []).forEach(e => toast(e, "err"));
      $("#lic-keys").value = ""; $("#lic-note").value = "";
      loadLicenses();
    } catch (e) { toast("Registration failed: " + e.message, "err"); }
  };
  // password reveal toggles (delegated, works for dynamically added API rows)
  v.addEventListener("click", (e) => {
    if (e.target.classList.contains("pw-eye")) {
      const inp = e.target.parentElement.querySelector("input");
      inp.type = inp.type === "password" ? "text" : "password";
    }
  });
  // AI API manager
  const list = $("#api-list");
  const bindRow = (row) => { row.querySelector(".a-del").onclick = () => { row.remove(); }; };
  $$(".api-row", list).forEach(bindRow);
  $("#api-add").onclick = () => {
    const empty = $("#api-empty"); if (empty) empty.remove();
    const div = document.createElement("div");
    div.innerHTML = apiRow({ type: "openai-compatible", enabled: true }, $$(".api-row", list).length);
    const row = div.firstElementChild;
    list.appendChild(row); bindRow(row);
    row.querySelector(".a-name").focus();
  };
  const collectApis = () => $$(".api-row", list).map(r => ({
    name: r.querySelector(".a-name").value.trim(),
    type: r.querySelector(".a-type").value,
    base_url: r.querySelector(".a-base").value.trim(),
    key: r.querySelector(".a-key").value.trim(),
    model: r.querySelector(".a-model").value.trim(),
    enabled: r.querySelector(".a-enabled").checked,
  })).filter(a => a.base_url);

  $("#cfg-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    body.ai_apis = collectApis();
    try {
      await api("/config", { method: "PUT", body });
      toast("Configuration saved ✓", "ok");
    } catch (err) { toast("Save failed: " + err.message, "err"); }
  };
  $("#lan-detect").onclick = async () => {
    const out = $("#lan-detect-out");
    out.textContent = "⏳ Broadcasting discovery probe (MAPSTUDIO-DISCOVER-V1)…";
    try {
      const r = await api("/cluster/discover", { method: "POST", body: {} });
      if (!r.servers.length) { out.textContent = "No servers answered on this LAN."; return; }
      out.innerHTML = r.servers.map(s =>
        `<button type="button" class="btn" data-use="${esc(s.host)}|${s.port}" style="margin:2px">✅ ${esc(s.name)} — ${esc(s.host)}:${s.port} (${esc(s.role)})</button>`).join(" ");
      $$("[data-use]", out).forEach(b => b.onclick = () => {
        const [ip, port] = b.dataset.use.split("|");
        const f = $("#cfg-form");
        f.elements.client_server_ip.value = ip; f.elements.client_server_port.value = port;
        toast(`Server ${ip}:${port} filled into the form — press Save`, "ok");
      });
    } catch (err) { out.textContent = "❌ " + err.message; }
  };
  $("#smtp-test-btn").onclick = async () => {
    const btn = $("#smtp-test-btn"), out = $("#smtp-test-result");
    btn.disabled = true; btn.textContent = "⏳ Testing…";
    out.innerHTML = "<span class='muted'>Connecting to SMTP server, logging in and sending…</span>";
    try {
      const r = await api("/config/test-smtp", { method: "POST", body: { to: $("#smtp-test-to").value.trim() } });
      out.innerHTML = `<b style="color:#22c55e">✅ ${esc(r.detail)}</b>`;
      toast("Test email sent ✓", "ok");
    } catch (err) {
      out.innerHTML = `<b style="color:#ef4444">❌ ${esc(err.message)}</b>`;
      toast("SMTP test failed", "err");
    }
    btn.disabled = false; btn.textContent = "📧 Send test email";
  };
};

/* ---------------- environment setup ---------------- */
views.setup = async (v) => {
  // ---- normal users: admin-credential gate, then CLIENT-SIDE settings only ----
  if (!state.user.is_admin) {
    if (!sessionStorage.getItem("setupUnlocked")) {
      v.innerHTML = `<div class="card" style="max-width:460px;margin:40px auto">
        <h3>🔒 Administrator authorization required</h3>
        <p class="muted" style="font-size:13px">Setup is protected. Ask your administrator to enter their
          username and password to unlock the <b>client-side settings of this computer</b>.</p>
        <label style="display:block;margin:10px 0 4px">Administrator username</label>
        <input id="su-user" autocomplete="off" style="width:100%">
        <label style="display:block;margin:10px 0 4px">Administrator password</label>
        <input id="su-pass" type="password" autocomplete="new-password" style="width:100%">
        <button class="btn primary" id="su-btn" style="margin-top:14px;width:100%">🔓 Unlock setup</button>
        <p id="su-err" class="error hidden" style="margin-top:8px"></p>
      </div>`;
      const go = async () => {
        try {
          await api("/auth/verify-admin", { method: "POST", body: {
            username: $("#su-user").value.trim(), password: $("#su-pass").value } });
          sessionStorage.setItem("setupUnlocked", "1");
          toast("Setup unlocked ✓", "ok");
          render();
        } catch (e) { const p = $("#su-err"); p.textContent = "❌ " + e.message; p.classList.remove("hidden"); }
      };
      $("#su-btn").onclick = go;
      $("#su-pass").addEventListener("keydown", e => { if (e.key === "Enter") go(); });
      return;
    }
    // unlocked — show ONLY this computer's client-side information & settings
    const cl = window.clientInfo;
    const vt = (s) => String(s || "0").split(".").map(n => parseInt(n) || 0);
    const cmp = (a, b) => { const x = vt(a), y = vt(b); for (let i = 0; i < 3; i++) { if ((x[i]||0) !== (y[i]||0)) return (x[i]||0) - (y[i]||0); } return 0; };
    const outdated = cl && cl.version && window.serverVersion && cmp(cl.version, window.serverVersion) < 0;
    v.innerHTML = `${outdated ? `<div class="card" style="max-width:640px;margin-bottom:14px;border:1px solid #3b82f6">
      <h3>⬆️ Client update in progress — v${esc(cl.version)} → v${esc(window.serverVersion)}</h3>
      <p class="muted" style="font-size:13px">The client program updates itself automatically in the background
        (checked every 30 seconds) and restarts when done — nothing to download or run manually.
        All your settings and data are kept.</p>
      <button class="btn primary" id="upd-now">⬆ Update now</button>
      <span id="upd-now-res" class="muted" style="font-size:12.5px;margin-left:8px"></span>
    </div>` : ""}<div class="card" style="max-width:640px">
      <h3>🖥 Client-side setup — this computer only</h3>
      <p class="muted" style="font-size:12.5px">Server-side settings are managed by the administrator on the
        server and are <b>not shown here</b>.</p>
      <table class="table" style="margin-top:8px">
        <tr><td>Connection to server</td><td><b style="color:#22c55e">● connected</b> — ${esc(location.host)}</td></tr>
        <tr><td>Client program</td><td>${cl ? `detected ✓ <span class="pill">client v${esc(cl.version || "?")}</span>` : "not detected on this computer"}</td></tr>
        ${cl && cl.license_key ? `<tr><td>License key of this computer</td><td><code style="font-family:Consolas,monospace;letter-spacing:.5px">${esc(cl.license_key)}</code></td></tr>` : ""}
        <tr><td>Signed in as</td><td>${esc(state.user.display_name || state.user.username)}</td></tr>
      </table>
      <p class="muted" style="font-size:12.5px;margin-top:10px">⚙️ To change this computer's connection settings
        (server IP address, port, license key), <b>double-click the NexaCrew icon in the system tray</b> of this
        computer — the status &amp; settings panel edits the local configuration file directly.
        ${outdated ? "<b style='color:#3b82f6'>The client is updating itself in the background — the tray icon appears after it restarts.</b>" : ""}</p>
      <button class="btn" id="su-lock" style="margin-top:6px">🔒 Lock setup again</button>
    </div>
    <div class="card" style="max-width:640px;margin-top:14px">
      <h3>📷 Camera assignment — this computer only</h3>
      <p class="muted" style="font-size:12.5px"><b>Internal camera</b> silently captures the operator's face for the
        operations log. <b>External camera</b> is used for serial-number capture (and future scanning features).
        The choice is saved on this computer (tray settings hold the same values).</p>
      <table class="table" style="margin-top:8px">
        <tr><td style="width:220px">🤳 Internal camera (face capture)</td>
          <td><select id="cam-int" style="width:100%"></select></td></tr>
        <tr><td>🔍 External camera (serial number)</td>
          <td><select id="cam-ext" style="width:100%"></select></td></tr>
      </table>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
        <button class="btn primary" id="cam-save">💾 Save camera assignment</button>
        <button class="btn" id="cam-test-int">🎥 Test internal</button>
        <button class="btn" id="cam-test-ext">🎥 Test external</button>
        <span id="cam-res" class="muted" style="font-size:12.5px"></span>
      </div>
    </div>`;
    $("#su-lock").onclick = () => { sessionStorage.removeItem("setupUnlocked"); render(); };
    // ---- camera role assignment: enumerate devices, save locally + to client config ----
    (async () => {
      const selI = $("#cam-int"), selE = $("#cam-ext"), res = $("#cam-res");
      const fill = (sel, cur) => (devs) => {
        sel.innerHTML = `<option value="">— automatic (${sel === selI ? "front/user" : "rear/environment"}) —</option>` +
          devs.map(d => `<option value="${esc(d.label || d.deviceId)}" ${cur && ((d.label || "").toLowerCase().includes(cur.toLowerCase()) || d.deviceId === cur) ? "selected" : ""}>${esc(d.label || "Camera " + d.deviceId.slice(0, 8))}</option>`).join("");
      };
      try {
        // a short permission grab so device labels become visible
        try { (await navigator.mediaDevices.getUserMedia({ video: true })).getTracks().forEach(tr => tr.stop()); } catch { }
        const devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
        if (!devs.length) { res.textContent = "⚠ No cameras detected on this computer."; }
        fill(selI, cameraPref("internal"))(devs);
        fill(selE, cameraPref("external"))(devs);
      } catch (e) { res.textContent = "⚠ " + (e.message || e); }
      $("#cam-save").onclick = async () => {
        const iv = selI.value, ev = selE.value;
        try { localStorage.setItem("camera_internal", iv); localStorage.setItem("camera_external", ev); } catch { }
        // push into the client program's config.json via the local beacon so the
        // tray panel and every browser on this computer share the same setting
        let saved = "browser";
        try {
          const r = await fetch(`http://127.0.0.1:8600/api/camera?internal=${encodeURIComponent(iv)}&external=${encodeURIComponent(ev)}`, { cache: "no-store" });
          const j = await r.json();
          if (j.ok) { saved = "browser + client config"; if (window.clientInfo) { window.clientInfo.camera_internal = iv; window.clientInfo.camera_external = ev; } }
        } catch { /* beacon not running — browser-only setting still applies */ }
        res.textContent = `✅ Saved (${saved}).`;
        toast("📷 Camera assignment saved", "ok");
      };
      const test = (kind) => async () => {
        res.textContent = "⏳ opening " + kind + " camera…";
        try {
          // honour the UNSAVED selection during the test
          const want = (kind === "internal" ? selI.value : selE.value).toLowerCase();
          const devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
          const hit = want && (devs.find(d => (d.label || "").toLowerCase().includes(want)) || devs.find(d => d.deviceId === want));
          const vc = hit ? { deviceId: { exact: hit.deviceId } } : await cameraConstraints(kind);
          const st = await navigator.mediaDevices.getUserMedia({ video: vc, audio: false });
          const lbl = st.getVideoTracks()[0].label;
          st.getTracks().forEach(tr => tr.stop());
          res.textContent = `✅ ${kind} camera OK — ${lbl}`;
        } catch (e) { res.textContent = `❌ ${kind} camera failed — ${e.message || e}`; }
      };
      $("#cam-test-int").onclick = test("internal");
      $("#cam-test-ext").onclick = test("external");
    })();
    const updNow = $("#upd-now");
    if (updNow) updNow.onclick = async () => {
      const res = $("#upd-now-res");
      res.textContent = "⏳ asking the client to update…";
      updNow.disabled = true;
      try {
        const r = await fetch("http://127.0.0.1:8600/api/update", { cache: "no-store" });
        const j = await r.json();
        res.textContent = "✅ " + (j.detail || "Background update started — the client restarts itself.");
      } catch {
        res.textContent = "The client updates itself automatically within 30 seconds — no action needed.";
      }
    };
    return;
  }
  const s = await api("/setup/status");
  const pct = Math.round((s.steps_done / s.steps_total) * 100);
  const row = (key, t) => {
    const inst = t.installed;
    const login = t.logged_in; // null = not applicable
    const installing = t.install && t.install.status === "running";
    const installErr = t.install && t.install.status === "error";
    return `<div class="setup-row ${inst && login !== false ? "ok" : ""}">
      <div class="setup-icon">${inst ? (login === false ? "🔑" : "✅") : "❌"}</div>
      <div class="setup-info">
        <b>${esc(t.label)}</b>
        <div class="muted" style="font-size:12px">Needed for: ${esc(t.required_for)}</div>
        <div class="muted" style="font-size:11px">${inst ? "Installed: " + esc(t.path || "") : "Not installed"}
          ${login === true ? " · <span style='color:#22c55e'>logged in ✓</span>" : ""}
          ${login === false && inst ? " · <span style='color:#eab308'>not logged in</span>" : ""}</div>
        ${installing ? `<div style="font-size:12px;color:#eab308">⏳ Installing… this can take a few minutes. The list refreshes automatically.</div>` : ""}
        ${installErr ? `<pre style="font-size:11px;max-height:90px;overflow:auto;color:#ef4444">${esc(t.install.log)}</pre>` : ""}
      </div>
      <div class="setup-actions">
        ${!inst && !installing ? `<button class="btn primary" data-install="${key}">⬇ Install automatically</button>` : ""}
        ${inst && login === false ? `<button class="btn primary" data-login="${key}">🔑 Login</button>` : ""}
        ${key === "vscode" && inst ? `<button class="btn" data-login="vscode">Open & sign in Copilot</button>` : ""}
      </div>
    </div>`;
  };
  v.innerHTML = `
    ${s.os ? `<div class="card" style="max-width:860px;margin-bottom:14px">
      <h3>🖥 Operating system compatibility</h3>
      <p style="font-size:13.5px;margin:6px 0">Detected: <b>${esc(s.os.label)}</b> ${s.os.simulated ? '<span class="pill" style="background:#eab30833">simulated</span>' : ""}
        — mode: ${s.os.tier === "full" ? '<span class="pill" style="background:#22c55e33">✅ Full (Codex + Claude CLIs + VS Code)</span>'
        : s.os.tier === "legacy_copilot" ? '<span class="pill" style="background:#4f8ef733">🔁 Copilot relay — prompts run via GitHub Copilot in VS Code 1.85.2</span>'
        : '<span class="pill" style="background:#eab30833">🔌 AI API mode — CLIs/VS Code unavailable on this OS</span>'}</p>
      ${s.os.tier !== "full" ? `<p class="muted" style="font-size:12.5px">Compatible tool versions for this OS — Python: <b>${esc(s.os.tools.python || "—")}</b> · Node.js: <b>${esc(s.os.tools.node || "—")}</b> · VS Code: <b>${esc(s.os.tools.vscode || "not installable")}</b> · Office: <b>${esc(s.os.tools.office || "—")}</b>. Installers pick these automatically.</p>` : ""}
      <p class="muted" style="font-size:12px;border-top:1px solid var(--border);padding-top:8px;margin-top:8px">
        📋 <b>Minimum requirements:</b> ${esc(s.os.min_requirements.windows)} · ${esc(s.os.min_requirements.macos)} · ${esc(s.os.min_requirements.linux)} · Python ${esc(s.os.min_requirements.python)} · RAM ${esc(s.os.min_requirements.ram)} · Disk ${esc(s.os.min_requirements.disk)}.
        Below these, installation is refused to prevent issues.</p>
    </div>` : ""}
    <div class="card" style="max-width:860px">
      <h3>🛠️ Environment Setup</h3>
      <p class="muted" style="font-size:13px">This platform needs the agent CLIs on this computer. Progress below shows what's ready.</p>
      <div class="progress-info" style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px">
        <span>Setup progress: <b>${s.steps_done}/${s.steps_total} steps (${pct}%)</b></span>
        <span>${s.complete ? "🎉 <b style='color:#22c55e'>Setup complete — all agents ready!</b>" : "<b style='color:#eab308'>Setup incomplete</b>"}</span>
      </div>
      <div class="pbar" style="height:12px;background:var(--bg);border:1px solid var(--border);border-radius:999px;overflow:hidden;margin-bottom:16px">
        <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#3b82f6,#22c55e);transition:width .5s"></div>
      </div>
      ${row("node", s.tools.node)}
      ${row("codex", s.tools.codex)}
      ${row("claude", s.tools.claude)}
      ${row("vscode", s.tools.vscode)}
      <div class="toolbar" style="margin-top:14px">
        <button class="btn" id="setup-recheck">🔄 Re-check</button>
      </div>
    </div>
    ${s.complete ? "" : `
    <div class="card" style="max-width:860px;margin-top:16px">
      <h3>📖 Full setup tutorial</h3>
      <ol style="font-size:13px;line-height:2">
        <li><b>Install Node.js</b> — click "Install automatically" above (uses winget), or download from <a href="https://nodejs.org" target="_blank" style="color:#60a5fa">nodejs.org</a>. Node is required to install the agent CLIs.</li>
        <li><b>Install Codex CLI</b> — click "Install automatically" (runs <code>npm install -g @openai/codex</code>).</li>
        <li><b>Login to Codex</b> — click "Login". A terminal window opens; choose "Sign in with ChatGPT" and finish in the browser. Requires a ChatGPT Plus/Pro/Team account.</li>
        <li><b>Install Claude Code CLI</b> — click "Install automatically" (runs <code>npm install -g @anthropic-ai/claude-code</code>).</li>
        <li><b>Login to Claude Code</b> — click "Login". A terminal opens; follow the browser OAuth flow. Requires a Claude Pro/Max account.</li>
        <li><b>Install VS Code</b> — click "Install automatically" (uses winget), or download from <a href="https://code.visualstudio.com" target="_blank" style="color:#60a5fa">code.visualstudio.com</a>.</li>
        <li><b>Sign in to Copilot</b> — click "Open & sign in Copilot": in VS Code use the Accounts icon (bottom-left) → "Sign in with GitHub" and enable GitHub Copilot (Claude Fable 5 model).</li>
        <li>After each step click <b>🔄 Re-check</b> — when all rows show ✅ and the bar reaches 100%, the platform is fully operational.</li>
      </ol>
      <p class="muted" style="font-size:12px">⚠ If "Install automatically" fails (e.g. winget missing), install manually from the official sites, restart this server, then Re-check.</p>
    </div>`}`;
  $("#setup-recheck").onclick = () => render();
  $$("[data-install]", v).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "⏳ Installing…";
    try { await api("/setup/install", { method: "POST", body: { tool: b.dataset.install } }); toast("Installation started — the page will refresh automatically", "ok"); }
    catch (e) { toast(e.message, "err"); }
    setTimeout(render, 4000);
  });
  $$("[data-login]", v).forEach(b => b.onclick = async () => {
    try {
      const r = await api("/setup/login", { method: "POST", body: { tool: b.dataset.login } });
      toast(r.message || "Login window opened", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
  // auto-refresh while an install is running
  if (Object.values(s.tools).some(t => t.install && t.install.status === "running")) {
    setTimeout(() => { if (state.view === "setup") render(); }, 5000);
  }
};

/* ---------------- Schedules (cron) ---------------- */
function schedStatus(j) {
  const isOnce = j.cron.startsWith("once:");
  const ran = !!j.last_run_at;
  const failed = ran && j.last_status && !j.last_status.startsWith("ok");
  if (isOnce) {
    if (!j.enabled && ran && !failed) return { key: "completed", badge: "✅ Completed", color: "#22c55e" };
    if (failed) return { key: "failed", badge: "❌ Failed", color: "#ef4444" };
    if (!j.enabled) return { key: "disabled", badge: "⏸ Disabled", color: "#94a3b8" };
    const due = new Date(j.cron.slice(5));
    if (!isNaN(due) && due < new Date()) return { key: "overdue", badge: "⌛ Past due", color: "#eab308" };
    return { key: "scheduled", badge: "🕒 Scheduled", color: "#4f8ef7" };
  }
  if (!j.enabled) return { key: "disabled", badge: "⏸ Disabled", color: "#94a3b8" };
  if (failed) return { key: "failed", badge: "❌ Last run failed", color: "#ef4444" };
  return { key: "scheduled", badge: "🔁 Active (recurring)", color: "#4f8ef7" };
}

views.schedules = async (v) => {
  const [jobs, chats] = await Promise.all([api("/schedules"), api("/chats")]);
  const counts = { scheduled: 0, completed: 0, failed: 0, disabled: 0, overdue: 0 };
  jobs.forEach(j => counts[schedStatus(j).key]++);
  v.innerHTML = `<div class="toolbar"><button class="btn primary" id="new-sched">+ New Schedule</button>
    <span class="pill" style="border-color:#4f8ef7">🕒 Scheduled: ${counts.scheduled + counts.overdue}</span>
    <span class="pill" style="border-color:#22c55e">✅ Completed: ${counts.completed}</span>
    ${counts.failed ? `<span class="pill" style="border-color:#ef4444">❌ Failed: ${counts.failed}</span>` : ""}
    ${counts.disabled ? `<span class="pill">⏸ Disabled: ${counts.disabled}</span>` : ""}
    <span class="muted" style="font-size:12px">Cron jobs run the prompt through the agent pipeline in the selected chat. Tip: you can also just tell the agent in any chat, e.g. “every day at 9am create a sales report PDF”.</span></div>
  <div class="grid cols-2">${jobs.map(j => { const st = schedStatus(j); return `
    <div class="card" style="border-left:3px solid ${st.color}">
      <h3>⏰ ${esc(j.name)} <span class="pill" style="border-color:${st.color};color:${st.color}">${st.badge}</span></h3>
      <p><span class="pill">${esc(j.cron_human)}</span> <span class="muted" style="font-size:11px">cron: <code>${esc(j.cron)}</code></span></p>
      <p class="muted" style="font-size:12px">Chat: 💬 ${esc(j.chat_title)}</p>
      <pre style="font-size:12px;max-height:90px;overflow:auto;background:var(--bg);padding:8px;border-radius:6px;white-space:pre-wrap">${esc(j.prompt.slice(0, 300))}</pre>
      <p class="muted" style="font-size:11px">Last run: ${j.last_run_at ? new Date(j.last_run_at + "Z").toLocaleString() + " — " + esc(j.last_status || "") : "never (waiting for its time)"}</p>
      <div class="toolbar" style="margin-top:8px">
        <button class="btn" data-edit="${j.id}">Edit</button>
        <button class="btn" data-toggle="${j.id}">${j.enabled ? "Disable" : "Enable"}</button>
        <button class="btn danger" data-del="${j.id}">Delete</button>
      </div>
    </div>`; }).join("")
    || `<div class="empty"><div class="big">⏰</div>No schedules yet. Create one here, or simply ask the agent in a chat: “every Monday at 8:00 email me the project status”.</div>`}</div>`;

  const schedModal = (j = null) => {
    const isOnce = j ? j.cron.startsWith("once:") : false;
    const onceVal = isOnce ? j.cron.slice(5) : "";
    modal(j ? "Edit schedule" : "New schedule", `
    <label>Name *<input name="name" required value="${j ? esc(j.name) : ""}" placeholder="e.g. Daily sales report"></label>
    <label>Type<select name="sched_type" id="sched-type">
      <option value="cron" ${!isOnce ? "selected" : ""}>🔁 Recurring (cron)</option>
      <option value="once" ${isOnce ? "selected" : ""}>1️⃣ One-time (date &amp; time)</option>
    </select></label>
    <div id="cron-row" style="${isOnce ? "display:none" : ""}">
      <label>Cron (min hour dom month dow) *<input name="cron" value="${j && !isOnce ? esc(j.cron) : "0 9 * * *"}" placeholder="0 9 * * *"></label>
      <p class="muted" style="font-size:11px;margin:2px 0 8px">Examples: <code>0 9 * * *</code> = daily 09:00 · <code>30 18 * * 1</code> = Mondays 18:30 · <code>*/15 * * * *</code> = every 15 min</p>
    </div>
    <div id="once-row" style="${isOnce ? "" : "display:none"}">
      <label>Run date &amp; time *<input type="datetime-local" name="once_at" value="${esc(onceVal)}"></label>
      <p class="muted" style="font-size:11px;margin:2px 0 8px">Runs exactly once at this local time, then disables itself. Saving re-arms an already-executed one-time job.</p>
    </div>
    <label>Chat<select name="chat_id">${chats.map(c => `<option value="${c.id}" ${j && j.chat_id === c.id ? "selected" : ""}>${esc(c.title)}</option>`).join("")}</select></label>
    <label>Task prompt *<textarea name="prompt" required rows="4" placeholder="What must the agent do at each run?">${j ? esc(j.prompt) : ""}</textarea></label>`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (body.sched_type === "once") {
        if (!body.once_at) { toast("Please pick a date & time", "err"); return; }
        body.cron = "once:" + body.once_at.slice(0, 16);
        body.enabled = true; // revising the time re-arms an executed one-time job
      }
      delete body.sched_type; delete body.once_at;
      if (!body.cron) { toast("Cron expression is required", "err"); return; }
      if (j) await api(`/schedules/${j.id}`, { method: "PUT", body });
      else await api("/schedules", { method: "POST", body });
      toast("Schedule saved ✓", "ok"); render();
    }, "Save");
    const typeSel = $("#sched-type");
    if (typeSel) typeSel.onchange = () => {
      const once = typeSel.value === "once";
      $("#cron-row").style.display = once ? "none" : "";
      $("#once-row").style.display = once ? "" : "none";
    };
  };
  $("#new-sched").onclick = () => schedModal();
  $$("[data-edit]", v).forEach(b => b.onclick = () => schedModal(jobs.find(x => x.id === b.dataset.edit)));
  $$("[data-toggle]", v).forEach(b => b.onclick = async () => {
    const j = jobs.find(x => x.id === b.dataset.toggle);
    await api(`/schedules/${j.id}`, { method: "PUT", body: { enabled: !j.enabled } }); render();
  });
  $$("[data-del]", v).forEach(b => b.onclick = async () => {
    if (!confirm("Delete this schedule?")) return;
    await api(`/schedules/${b.dataset.del}`, { method: "DELETE" }); render();
  });
};

/* ---------------- enterprise cluster: network graph ---------------- */
let clusterTimer = null;
views.cluster = async (v) => {
  clearInterval(clusterTimer);
  // page skeleton: live graph on top, configuration below (was in Settings — merged here)
  const { config, meta } = await api("/config");
  const cfgFields = Object.entries(meta).filter(([, m]) => m.group === "cluster")
    .map(([k, m]) => cfgField(k, m, config)).join("");
  v.innerHTML = `
    <div id="cluster-graph"><div class="card"><p class="muted">⏳ Loading cluster status…</p></div></div>
    <form id="cluster-cfg-form" class="noc-panel" style="margin-top:14px">
      <div class="noc-head"><span class="noc-led off"></span><b>⚙ Cluster configuration</b>
        <span class="spacer"></span><small>APPLIED ON NEXT START.PY RUN</small></div>
      <div class="noc-body">
        <p class="muted sdesc" style="margin-top:0">Run several servers together. One node is the <b>controller</b> (master); <b>worker</b> (slave) nodes register with it and agent workloads are load-balanced automatically. All nodes must share the same cluster secret.</p>
        <div class="cfg-grid">${cfgFields}</div>
        <div class="settings-save" style="margin-top:10px"><button class="btn primary" type="submit">💾 Save cluster settings</button></div>
      </div>
    </form>`;
  $("#cluster-cfg-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target).entries());
    try {
      await api("/config", { method: "PUT", body });
      toast("Cluster configuration saved ✓", "ok");
    } catch (err) { toast("Save failed: " + err.message, "err"); }
  };
  v.addEventListener("click", (e) => {
    if (e.target.classList.contains("pw-eye")) {
      const inp = e.target.parentElement.querySelector("input");
      inp.type = inp.type === "password" ? "text" : "password";
    }
  });
  const draw = async () => {
    const gbox = $("#cluster-graph");
    if (!gbox) { clearInterval(clusterTimer); return; }
    let s;
    try { s = await api("/cluster/status"); } catch { return; }
    const nodes = s.nodes || [];
    const me = s.self || {};
    const workers = nodes.filter(n => n.role === "worker");
    const onlineWorkers = workers.filter(n => n.online !== false).length;
    const totalActive = (me.active_jobs || 0) + workers.reduce((a, n) => a + (n.active_jobs || 0), 0);
    const totalJobs = (me.total_jobs || 0) + workers.reduce((a, n) => a + (n.total_jobs || 0), 0);
    const degraded = workers.length && onlineWorkers < workers.length;

    const W = 1200, H = 460, cx = W / 2, cy = H / 2;
    const boxNode = (n, x, y, kind) => {
      /* kind: controller | worker | standalone */
      const online = n.online !== false;
      const outdated = kind === "worker" && n.outdated && online;
      const col = kind === "controller" || kind === "standalone" ? "#4f8ef7" : outdated ? "#f59e0b" : online ? "#22c55e" : "#ef4444";
      const role = kind === "controller" ? "CONTROLLER" : kind === "standalone" ? "STANDALONE CORE" : "WORKER";
      const l3 = online
        ? outdated
          ? `⬆ v${n.version || "?"} — ${t("UPDATING TO")} v${me.version || s.version || "?"}`
          : `⚡ ${n.active_jobs || 0} active · ${n.total_jobs || 0} jobs${n.cpu_percent != null ? ` · CPU ${n.cpu_percent}%` : ""}`
        : "LINK DOWN";
      const wide = kind !== "worker";
      const w2 = wide ? 105 : 88, h2 = wide ? 46 : 38;
      return `<g transform="translate(${x},${y})">
        <rect x="${-w2}" y="${-h2}" width="${w2 * 2}" height="${h2 * 2}" rx="11"
          fill="var(--panel2,#141b2d)" stroke="${col}" stroke-width="${wide ? 1.7 : 1.3}"/>
        ${wide ? `<rect x="${-w2}" y="${-h2}" width="${w2 * 2}" height="${h2 * 2}" rx="11" fill="none"
          stroke="${col}" stroke-width="1.7" opacity=".35">
          <animate attributeName="stroke-width" values="1.7;5;1.7" dur="3s" repeatCount="indefinite"/>
          <animate attributeName="opacity" values=".35;0;.35" dur="3s" repeatCount="indefinite"/></rect>` : ""}
        <circle cx="${-w2 + 14}" cy="${-h2 + 14}" r="4" fill="${online ? col : "#ef4444"}">
          ${online ? `<animate attributeName="opacity" values="1;.35;1" dur="2s" repeatCount="indefinite"/>` : ""}
        </circle>
        <text x="${-w2 + 26}" y="${-h2 + 18}" font-size="${wide ? 13 : 12}" font-weight="800" fill="var(--text,#e2e8f0)">${kind === "worker" ? "🗄" : "🏢"} ${esc((n.name || "?").slice(0, 16))}</text>
        <text x="${-w2 + 14}" y="${-h2 + (wide ? 40 : 36)}" font-size="10" fill="${col}" font-family="Consolas,monospace">${role}${wide && s.version ? " · v" + esc(s.version) : ""}</text>
        <text x="${-w2 + 14}" y="${-h2 + (wide ? 58 : 52)}" font-size="10" fill="#94a3b8" font-family="Consolas,monospace">${esc(n.host || "")}${n.port ? ":" + n.port : ""}</text>
        <text x="${-w2 + 14}" y="${-h2 + (wide ? 76 : 68)}" font-size="9.5" fill="${online ? "#94a3b8" : "#ef4444"}" font-family="Consolas,monospace">${esc(l3)}</text>
      </g>`;
    };
    let svg = "";
    if (s.role === "controller") {
      const R = Math.min(cx - 180, cy - 80);
      svg = `<circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="rgba(148,163,184,.12)" stroke-dasharray="2 6"/>` +
        workers.map((n, i) => {
          const ang = (2 * Math.PI * i) / Math.max(workers.length, 1) - Math.PI / 2;
          const x = cx + Math.cos(ang) * R, y = cy + Math.sin(ang) * (R * .82);
          const online = n.online !== false;
          return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" class="${online ? "nm-link-on" : "nm-link-off"}"/>` +
            boxNode(n, x, y, "worker");
        }).join("") + boxNode(me, cx, cy, "controller");
    } else if (s.role === "worker") {
      svg = `<line x1="${cx - 220}" y1="${cy}" x2="${cx + 220}" y2="${cy}" class="nm-link-on"/>` +
        boxNode({ name: "Controller", host: s.controller_ip, port: s.controller_port, online: true }, cx - 220, cy, "controller") +
        boxNode(me, cx + 220, cy, "worker");
    } else {
      svg = `<circle cx="${cx}" cy="${cy}" r="150" fill="none" stroke="rgba(148,163,184,.12)" stroke-dasharray="2 6"/>` +
        boxNode(me, cx, cy, "standalone");
    }

    gbox.innerHTML = `
    <div class="noc-topbar">
      <div class="noc-kpi"><span class="k">Cluster state</span>
        <span class="v" style="color:${degraded ? "#eab308" : "#22c55e"}"><span class="noc-led ${degraded ? "warn" : "ok"}"></span>${s.role === "standalone" ? "STANDALONE" : degraded ? "DEGRADED" : "NOMINAL"}</span></div>
      <div class="noc-kpi"><span class="k">Role</span><span class="v" style="font-size:16px">${esc(s.role).toUpperCase()}</span></div>
      <div class="noc-kpi"><span class="k">Worker nodes</span><span class="v" style="color:#22c55e">${onlineWorkers} <small>/ ${workers.length}</small></span></div>
      <div class="noc-kpi"><span class="k">Active jobs</span><span class="v">${totalActive}</span></div>
      <div class="noc-kpi"><span class="k">Jobs lifetime</span><span class="v">${totalJobs.toLocaleString()}</span></div>
      <span class="spacer"></span>
      <span class="muted" style="font-size:11px;font-family:Consolas,monospace">LOAD-BALANCED DISPATCH · REFRESH 5s</span>
      <button class="btn" id="cl-discover">📡 Scan LAN</button>
    </div>
    <div class="noc-panel">
      <div class="noc-head"><span class="noc-led ${degraded ? "warn" : "ok"}"></span><b>Cluster topology</b>
        <span class="spacer"></span><small>${s.role === "controller"
          ? "CONTROLLER DISPATCHES AGENT WORKLOADS TO THE LEAST-BUSY WORKER"
          : s.role === "worker" ? "REGISTERED WITH THE CONTROLLER — EXECUTING DISPATCHED RUNS"
          : "SINGLE-NODE OPERATION — SET A CONTROLLER/WORKER ROLE BELOW TO FORM A CLUSTER"}</small></div>
      <div class="netmap-wrap">
        <svg viewBox="0 0 ${W} ${H}" style="height:${Math.min(H, 470)}px">${svg}</svg>
        <div class="nm-legend">
          <span><span class="noc-led ok"></span>link up</span>
          <span><span class="noc-led crit"></span>link down</span>
          <span style="color:#4f8ef7">■ controller</span>
        </div>
      </div>
      <div class="noc-body" style="padding-top:0">
        <span id="cl-discover-out" class="muted" style="font-size:11.5px;font-family:Consolas,monospace"></span>
      </div>
    </div>
    ${nodes.length ? `<div class="noc-panel" style="margin-top:14px">
      <div class="noc-head"><b>Node inventory</b><span class="spacer"></span><small>${nodes.length} NODE(S)</small></div>
      <table class="noc-table"><thead><tr>
        <th>Status</th><th>Node</th><th>Address</th><th>Role</th><th>OS</th><th>CPU cores</th><th>GPUs</th><th>Active</th><th>Total jobs</th>
      </tr></thead><tbody>
        ${nodes.map(n => `<tr>
          <td>${n.online ? '<span class="noc-led ok"></span>online' : `<span class="noc-led crit"></span>offline (${n.last_seen_s}s)`}</td>
          <td><b>${esc(n.name)}</b></td><td class="num">${esc(n.host)}:${n.port}</td>
          <td>${esc(n.role)}</td><td>${esc(n.os || "—")}</td>
          <td class="num">${n.cpu_count || "?"}</td>
          <td>${n.gpu_count ? `🎮 ${n.gpu_count} — ${esc(n.gpu_names || "")}` : "—"}</td>
          <td class="num">${n.active_jobs || 0}</td><td class="num">${(n.total_jobs || 0).toLocaleString()}</td>
        </tr>`).join("")}</tbody></table></div>` : ""}`;
    $("#cl-discover").onclick = async () => {
      const out = $("#cl-discover-out");
      out.textContent = "⏳ BROADCASTING MAPSTUDIO-DISCOVER-V1 PROBE…";
      try {
        const r = await api("/cluster/discover", { method: "POST", body: {} });
        out.textContent = r.servers.length
          ? "FOUND: " + r.servers.map(x => `${x.name} (${x.host}:${x.port}, ${x.role})`).join(" · ")
          : "NO OTHER SERVERS ANSWERED ON THIS LAN.";
      } catch (e) { out.textContent = "❌ " + e.message; }
    };
  };
  await draw();
  clusterTimer = setInterval(() => { if (state.view === "cluster") draw(); else clearInterval(clusterTimer); }, 5000);
};

/* ---------------- system status: real-time telemetry ---------------- */
let sysTimer = null;
function fmtBps(bps) {
  if (bps == null) return "—";
  const bits = bps * 8;
  if (bits >= 1e9) return (bits / 1e9).toFixed(2) + " Gbps";
  if (bits >= 1e6) return (bits / 1e6).toFixed(2) + " Mbps";
  if (bits >= 1e3) return (bits / 1e3).toFixed(1) + " Kbps";
  return Math.round(bits) + " bps";
}
function fmtBytes(b) {
  if (b == null) return "—";
  if (b >= 2 ** 30) return (b / 2 ** 30).toFixed(2) + " GB";
  if (b >= 2 ** 20) return (b / 2 ** 20).toFixed(1) + " MB";
  if (b >= 1024) return (b / 1024).toFixed(1) + " KB";
  return b + " B";
}
function sparkline(values, { w = 260, h = 56, color = "#4f8ef7", max = null } = {}) {
  const vals = values.map(v => v == null ? 0 : v);
  const mx = max != null ? max : Math.max(...vals, 1);
  const pts = vals.map((v, i) => `${(i / Math.max(vals.length - 1, 1)) * w},${h - (Math.min(v, mx) / mx) * (h - 4) - 2}`);
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px" preserveAspectRatio="none">
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.8"/>
    <polygon points="0,${h} ${pts.join(" ")} ${w},${h}" fill="${color}22" stroke="none"/></svg>`;
}
function gauge(pct, label, color) {
  const p = Math.max(0, Math.min(100, pct == null ? 0 : pct));
  const c = color || (p > 90 ? "#ef4444" : p > 70 ? "#eab308" : "#22c55e");
  return `<div style="text-align:center;min-width:120px">
    <div style="position:relative;width:92px;height:92px;margin:0 auto;border-radius:50%;
      background:conic-gradient(${c} ${p * 3.6}deg, var(--border) 0)">
      <div style="position:absolute;inset:9px;border-radius:50%;background:var(--panel);
        display:flex;align-items:center;justify-content:center;font-size:17px;font-weight:700">${pct == null ? "—" : Math.round(p) + "%"}</div>
    </div><div class="muted" style="font-size:12px;margin-top:6px">${label}</div></div>`;
}

views.sysstatus = async (v) => {
  clearInterval(sysTimer);
  const draw = async () => {
    let s;
    try { s = await api("/system-status"); } catch { return; }
    if (!s.available) {
      v.innerHTML = `<div class="card"><h3>📈 System Status</h3>
        <p class="muted">psutil is not installed on the server — run <code>pip install psutil</code> and restart.</p></div>`;
      return;
    }
    const h = s.host, p = s.process, n = s.network;
    const cpuSeries = s.series.map(x => x.cpu);
    const ramSeries = s.series.map(x => x.ram);
    const procCpuSeries = s.series.map(x => x.proc_cpu);
    const upSeries = s.series.map(x => x.up);
    const downSeries = s.series.map(x => x.down);
    const netMax = Math.max(...upSeries, ...downSeries, 1);
    const worstDisk = Math.max(0, ...h.disks.map(d => d.percent));
    const health = (h.cpu_total > 92 || h.ram_percent > 92 || worstDisk > 92) ? "crit"
                 : (h.cpu_total > 75 || h.ram_percent > 80 || worstDisk > 85) ? "warn" : "ok";
    const healthTxt = { ok: "ALL SYSTEMS NOMINAL", warn: "ELEVATED LOAD", crit: "CRITICAL" }[health];
    const healthCol = { ok: "#22c55e", warn: "#eab308", crit: "#ef4444" }[health];
    const led = (pct) => pct == null ? "off" : pct > 90 ? "crit" : pct > 70 ? "warn" : "ok";
    const panel = (icon, title, right, body, ledCls = "ok") => `
      <div class="noc-panel"><div class="noc-head"><span class="noc-led ${ledCls}"></span>
        <b>${icon} ${title}</b><span class="spacer"></span><small>${right}</small></div>
        <div class="noc-body">${body}</div></div>`;

    v.innerHTML = `
    <div class="noc-topbar">
      <div class="noc-kpi"><span class="k">System health</span>
        <span class="v" style="color:${healthCol}"><span class="noc-led ${health}"></span>${healthTxt}</span></div>
      <div class="noc-kpi"><span class="k">CPU</span><span class="v">${Math.round(h.cpu_total ?? 0)}% <small>${h.cpu_count} cores</small></span></div>
      <div class="noc-kpi"><span class="k">Memory</span><span class="v">${Math.round(h.ram_percent ?? 0)}% <small>${fmtBytes((h.ram_used_mb || 0) * 1048576)}</small></span></div>
      <div class="noc-kpi"><span class="k">Net ⬆ / ⬇</span><span class="v" style="font-size:15px">${fmtBps(n.host_up_bps)} <small>/</small> ${fmtBps(n.host_down_bps)}</span></div>
      <div class="noc-kpi"><span class="k">Requests served</span><span class="v">${n.app_requests.toLocaleString()}</span></div>
      <div class="noc-kpi"><span class="k">Agent processes</span><span class="v">${p.children ?? 0}</span></div>
      <span class="spacer"></span>
      <span class="muted" style="font-size:11px;font-family:Consolas,monospace">LIVE · 2s REFRESH · 5min HISTORY</span>
    </div>
    <div class="noc-grid">
      ${panel("🖥", "Host compute", `${h.cpu_count} CORES${h.load_avg ? " · LOAD " + h.load_avg.map(x => x.toFixed(2)).join(" ") : ""}`, `
        <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:space-around;margin:6px 0 10px">
          ${gauge(h.cpu_total, "CPU utilization")}
          ${gauge(h.ram_percent, `RAM — ${fmtBytes((h.ram_used_mb || 0) * 1048576)} / ${fmtBytes((h.ram_total_mb || 0) * 1048576)}`)}
          ${gauge(h.swap_percent, "Swap")}
        </div>
        <div class="noc-lbl">CPU utilization — 2 min</div>${sparkline(cpuSeries, { max: 100 })}
        <div class="noc-lbl">Memory pressure — 2 min</div>${sparkline(ramSeries, { max: 100, color: "#a78bfa" })}
        <div class="noc-lbl">Per-core load</div>
        <div style="display:flex;gap:4px;flex-wrap:wrap">
          ${(h.cpu_per_core || []).map((c, i) => `<div title="Core ${i}: ${c}%" style="flex:1;min-width:16px">
            <div style="height:34px;background:var(--bg);border-radius:3px;display:flex;align-items:flex-end;border:1px solid var(--border)">
              <div style="width:100%;height:${c}%;background:${c > 90 ? "#ef4444" : c > 70 ? "#eab308" : "#4f8ef7"};border-radius:2px"></div>
            </div><div class="muted" style="font-size:8px;text-align:center;font-family:Consolas,monospace">${i}</div></div>`).join("")}
        </div>`, led(Math.max(h.cpu_total ?? 0, h.ram_percent ?? 0)))}

      ${panel("🏢", "Platform process tree", "INCL. AGENT CLIS", `
        <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:space-around;margin:6px 0 10px">
          ${gauge(p.cpu_percent, "Process CPU")}
          ${gauge(h.ram_total_mb ? (p.rss_mb / h.ram_total_mb) * 100 : null, `Memory — ${fmtBytes((p.rss_mb || 0) * 1048576)}`, "#4f8ef7")}
        </div>
        <div class="noc-lbl">Process CPU — 2 min</div>${sparkline(procCpuSeries, { max: 100, color: "#22c55e" })}
        <table class="noc-table" style="margin-top:10px">
          <tr><td>Threads</td><td class="num">${p.threads ?? "—"}</td><td>Child processes (agents)</td><td class="num">${p.children ?? 0}</td></tr>
          <tr><td>Open files / handles</td><td class="num">${p.open_files ?? "—"}</td><td>HTTP requests served</td><td class="num">${n.app_requests.toLocaleString()}</td></tr>
        </table>`, led(p.cpu_percent))}

      ${panel("🌐", "Network throughput", `LIFETIME ⬆ ${fmtBytes(n.app_bytes_out)} · ⬇ ${fmtBytes(n.app_bytes_in)}`, `
        <table class="noc-table">
          <tr><th></th><th>⬆ Upload</th><th>⬇ Download</th></tr>
          <tr><td><b>This platform</b></td><td class="num" style="color:#22c55e"><b>${fmtBps(n.app_up_bps)}</b></td><td class="num" style="color:#4f8ef7"><b>${fmtBps(n.app_down_bps)}</b></td></tr>
          <tr><td>Host total</td><td class="num">${fmtBps(n.host_up_bps)}</td><td class="num">${fmtBps(n.host_down_bps)}</td></tr>
        </table>
        <div class="noc-lbl">Host ⬆ upload — 2 min</div>${sparkline(upSeries, { max: netMax, color: "#22c55e", h: 44 })}
        <div class="noc-lbl">Host ⬇ download — 2 min</div>${sparkline(downSeries, { max: netMax, color: "#4f8ef7", h: 44 })}`)}

      ${panel("🎮", "GPU & storage", `${s.gpus.length} GPU · ${h.disks.length} VOLUME(S)`, `
        ${s.gpus.length ? s.gpus.map(g => `<div style="margin-bottom:10px">
          <b>${esc(g.name)}</b> <span class="pill">${esc(g.vendor)}</span>${g.cuda ? ' <span class="pill" style="background:#22c55e33">CUDA</span>' : ""}
          ${g.utilization_pct != null || g.memory_total_mb || g.temperature_c != null ? `
          <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:space-around;margin-top:8px">
            ${g.utilization_pct != null ? gauge(g.utilization_pct, "GPU load") : ""}
            ${g.memory_total_mb ? gauge((g.memory_used_mb / g.memory_total_mb) * 100, `VRAM — ${fmtBytes(g.memory_used_mb * 1048576)} / ${fmtBytes(g.memory_total_mb * 1048576)}`, "#a78bfa") : ""}
            ${g.temperature_c != null ? gauge(g.temperature_c, "Temp °C", g.temperature_c > 85 ? "#ef4444" : "#4f8ef7") : ""}
          </div>` : `<p class="muted" style="font-size:11.5px;margin:6px 0 0">Detected — live metrics need nvidia-smi (NVIDIA only). GPU processing is forced for agent workloads.</p>`}
        </div>`).join("") : `<p class="muted" style="font-size:12px">No GPU detected — running on CPU.</p>`}
        <div class="noc-lbl" style="margin-top:12px">Storage volumes</div>
        ${h.disks.map(d => `<div style="margin:7px 0">
          <div style="display:flex;justify-content:space-between;font-size:12px;font-family:Consolas,monospace">
            <span><span class="noc-led ${led(d.percent)}"></span>${esc(d.mount)}</span>
            <span class="muted">${d.used_gb} / ${d.total_gb} GB · ${d.percent}%</span></div>
          <div class="pbar"><div class="pbar-fill" style="width:${d.percent}%;background:${d.percent > 90 ? "#ef4444" : d.percent > 75 ? "#eab308" : "#4f8ef7"}"></div></div>
        </div>`).join("")}`, led(worstDisk))}

      <div class="noc-panel" id="bt-status-card">
        <div class="noc-head"><span class="noc-led off"></span><b>📶 Bluetooth subsystem</b></div>
        <div class="noc-body">${window._btStatusHtml || '<p class="muted">⏳ Querying Bluetooth adapter…</p>'}</div>
      </div>
    </div>
    <p class="muted" style="font-size:10.5px;margin-top:10px;font-family:Consolas,monospace">📈 LIVE TELEMETRY · 2s REFRESH · 1Hz SAMPLER · 5min ROLLING HISTORY · PROCESS METRICS INCLUDE ALL AGENT SUBPROCESS TREES</p>`;
  };
  await draw();
  /* Bluetooth availability — checked once per visit (adapter query is slow) */
  api("/bluetooth/status").then(bt => {
    window._btStatusHtml = bt.available
      ? `<p style="font-size:13px">${bt.enabled
          ? '<b style="color:#22c55e">✅ Bluetooth available &amp; enabled</b>'
          : '<b style="color:#eab308">⚠️ Bluetooth adapter present but turned OFF</b>'}</p>
        <p class="muted" style="font-size:12px">Adapter: ${esc(bt.adapter || "unknown")} · OS: ${esc(bt.os)}</p>
        <p class="muted" style="font-size:12px">${bt.rfcomm ? "✅" : "❌"} RFCOMM file-transfer support — ${bt.rfcomm ? "calendar sync to smartphones is supported on this computer" : "calendar push not supported by this OS/Python build"}</p>
        <p class="muted" style="font-size:12px">📅 Used by Calendar → Bluetooth sync to smartphone.</p>`
      : '<p style="font-size:13px"><b style="color:#ef4444">❌ No Bluetooth adapter found on this computer</b></p><p class="muted" style="font-size:12px">Calendar → Bluetooth smartphone sync is unavailable here. Plug in a USB Bluetooth dongle to enable it.</p>';
    const c = $("#bt-status-card");
    if (c) c.innerHTML = `<div class="noc-head"><span class="noc-led ${bt.available && bt.enabled ? "ok" : bt.available ? "warn" : "off"}"></span><b>📶 Bluetooth subsystem</b></div><div class="noc-body">${window._btStatusHtml}</div>`;
  }).catch(() => {});
  sysTimer = setInterval(() => { if (state.view === "sysstatus") draw(); else clearInterval(sysTimer); }, 2000);
};

/* ---------------- user management (administrator) ---------------- */
views.users = async (v) => {
  let users;
  try { users = await api("/users"); }
  catch (e) {
    v.innerHTML = `<div class="card"><h3>👤 User Management</h3>
      <p class="muted">❌ ${esc(e.message)} — administrator privileges are required.</p></div>`;
    return;
  }
  // Companies deployed on this server — a user bound to one sees ONLY that
  // company's operations menu; administrators can operate every company.
  let companies = [];
  try { companies = await api("/business/companies"); } catch { /* none configured yet */ }
  const coName = (oid) => (companies.find(c => c.owner_id === oid) || {}).company_name || "";
  const admins = users.filter(u => u.is_admin).length;
  const initials = (u) => esc(((u.display_name || u.username).trim()[0] || "?").toUpperCase());
  const hue = (s) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };

  v.innerHTML = `
  <div class="kpis" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:14px">
    <div class="card" style="padding:14px 18px"><div class="muted" style="font-size:12px">TOTAL ACCOUNTS</div>
      <div style="font-size:26px;font-weight:700">👥 ${users.length}</div></div>
    <div class="card" style="padding:14px 18px"><div class="muted" style="font-size:12px">ADMINISTRATORS</div>
      <div style="font-size:26px;font-weight:700">🛡️ ${admins}</div></div>
    <div class="card" style="padding:14px 18px"><div class="muted" style="font-size:12px">STANDARD USERS</div>
      <div style="font-size:26px;font-weight:700">👤 ${users.length - admins}</div></div>
  </div>
  <div class="toolbar" style="margin-bottom:10px">
    <input id="user-q" placeholder="🔍 Filter by name or username…" style="width:260px">
    <span class="spacer"></span>
    <button class="btn primary" id="new-user">➕ New user</button>
  </div>
  <div class="card" style="padding:0;overflow:hidden">
    <table class="table" id="user-table"><thead><tr>
      <th>User</th><th>Role &amp; access</th><th>Created</th><th style="text-align:right">Actions</th>
    </tr></thead><tbody>
    ${users.map(u => `<tr data-row="${esc((u.username + " " + (u.display_name || "")).toLowerCase())}">
      <td><div style="display:flex;align-items:center;gap:10px">
        <span style="width:36px;height:36px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:700;color:#fff;background:hsl(${hue(u.username)},55%,45%)">${initials(u)}</span>
        <div><b>${esc(u.display_name || u.username)}</b>${u.id === state.user.id ? ' <span class="pill" style="background:#3b82f633">you</span>' : ""}
          <div class="muted" style="font-size:12px">@${esc(u.username)}</div></div>
      </div></td>
      <td>${u.is_admin
        ? '<span class="pill" style="background:#a78bfa33">🛡️ Administrator</span><div class="muted" style="font-size:11.5px;margin-top:3px">Full access — users, clients, cluster, audit, setup, settings · all company operations</div>'
        : '<span class="pill">👤 User</span><div class="muted" style="font-size:11.5px;margin-top:3px">Own companies, chats, projects, tasks &amp; approvals only</div>'}
        ${u.company_owner_id && coName(u.company_owner_id)
          ? `<div style="margin-top:4px"><span class="pill" style="background:#0ea5e933">🏢 ${esc(coName(u.company_owner_id))}</span><span class="muted" style="font-size:11px"> — operations menu</span></div>` : ""}</td>
      <td class="muted" style="font-size:12px">${new Date(u.created_at).toLocaleDateString()}</td>
      <td style="text-align:right"><div class="toolbar" style="justify-content:flex-end">
        <button class="btn" data-edit="${u.id}">✏ Edit</button>
        <button class="btn" data-pass="${u.id}">🔑 Password</button>
        ${u.id !== state.user.id ? `<button class="btn danger" data-del="${u.id}">🗑 Delete</button>` : ""}
      </div></td></tr>`).join("")}
    </tbody></table>
  </div>
  <p class="muted" style="font-size:12px;margin-top:10px">🔒 Every user is fully isolated — they see only their own companies, employees, chats and tasks.
    Admin-only areas (Cluster, Clients, Audit Log, Setup, Settings) are hidden from standard users and enforced by the server. Every user has his own private Skills and Backup.
    All account changes are recorded in the hash-chained Audit Log.</p>`;

  $("#user-q").oninput = () => {
    const q = $("#user-q").value.trim().toLowerCase();
    $$("#user-table tbody tr").forEach(r => r.style.display = !q || r.dataset.row.includes(q) ? "" : "none");
  };

  const userModal = (u = null, passOnly = false) => modal(
    passOnly ? `Change password — ${esc(u.username)}` : u ? `Edit user — ${esc(u.username)}` : "New user", `
    ${passOnly ? "" : `<label>Username *<input name="username" required value="${u ? esc(u.username) : ""}"></label>
    <label>Display name<input name="display_name" value="${u ? esc(u.display_name || "") : ""}"></label>`}
    ${passOnly || !u ? `<label>${u ? "New password *" : "Password * (min 8 characters)"}
      <input name="password" type="password" required minlength="8" autocomplete="new-password"></label>` :
      `<label>New password (leave empty to keep current)
      <input name="password" type="password" minlength="8" autocomplete="new-password"></label>`}
    ${passOnly ? "" : `<label style="display:flex;gap:8px;align-items:center">
      <input type="checkbox" name="is_admin" ${u && u.is_admin ? "checked" : ""} ${u && u.id === state.user.id ? "disabled" : ""}>
      🛡️ Administrator (full platform access incl. settings, licenses and audit log)</label>
    <label>🏢 Company (operations workspace)
      <select name="company_owner_id">
        <option value="">— none · own workspace —</option>
        ${companies.map(c => `<option value="${esc(c.owner_id)}" ${u && u.company_owner_id === c.owner_id ? "selected" : ""}>${esc(c.company_name)}${c.licensed ? "" : " (unlicensed)"}</option>`).join("")}
      </select>
      <small class="muted">The user's Operations menu shows ONLY this company's registers. Administrators can switch between all companies deployed on this server.</small></label>`}`,
    async (fd) => {
      const body = Object.fromEntries(fd.entries());
      if (!passOnly) body.is_admin = fd.get("is_admin") === "on";
      if (!body.password) delete body.password;
      if (u) await api(`/users/${u.id}`, { method: "PUT", body });
      else await api("/users", { method: "POST", body });
      toast("User saved ✓", "ok"); render();
    }, "Save");
  $("#new-user").onclick = () => userModal();
  $$("[data-edit]", v).forEach(b => b.onclick = () => userModal(users.find(x => x.id === b.dataset.edit)));
  $$("[data-pass]", v).forEach(b => b.onclick = () => userModal(users.find(x => x.id === b.dataset.pass), true));
  $$("[data-del]", v).forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === b.dataset.del);
    if (!confirm(`Delete user “${u.username}”? Their companies stay in the database but become inaccessible.`)) return;
    await api(`/users/${u.id}`, { method: "DELETE" }); toast("User deleted", "ok"); render();
  });
};

/* ---------------- chat search results dialog ---------------- */
function highlightSnippet(snippet, term) {
  const safe = esc(snippet);
  try {
    const rx = new RegExp("(" + term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
    return safe.replace(rx, "<mark>$1</mark>");
  } catch { return safe; }
}

function showSearchResultsDialog(term, results) {
  const root = $("#modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-label="Search results">
    <h3>🔍 ${results.length} matches for “${esc(term)}”</h3>
    <p class="muted" style="font-size:12px;margin-top:0">Click a result to jump straight to that message.</p>
    <div class="search-results">
      ${results.map((r, i) => `
        <button class="search-result" data-idx="${i}">
          <div class="sr-title">💬 ${esc(r.title)}
            <span class="pill" style="margin-left:6px">${r.match_kind === "title" ? "title match" : "message match"}</span></div>
          <div class="sr-snippet">${highlightSnippet(r.match_snippet || "", term)}</div>
          <div class="sr-date muted">${new Date(r.match_time || r.updated_at || r.created_at).toLocaleString()}</div>
        </button>`).join("")}
    </div>
    <div class="actions"><button type="button" class="btn" id="modal-cancel">Close</button></div>
  </div></div>`;
  $("#modal-cancel").onclick = () => (root.innerHTML = "");
  // close only on a genuine backdrop click (mousedown + click both outside)
  let _srDown = false;
  root.firstChild.addEventListener("mousedown", e => { _srDown = e.target === root.firstChild; });
  root.firstChild.addEventListener("click", e => { if (e.target === root.firstChild && _srDown) root.innerHTML = ""; _srDown = false; });
  $$("[data-idx]", root).forEach(b => b.onclick = () => {
    const r = results[Number(b.dataset.idx)];
    root.innerHTML = "";
    state.chatQuery = "";
    state.chatId = r.id;
    state.searchHit = { term, messageId: r.match_message_id || null };
    render();
  });
}

/* ---------------- chat context menu ---------------- */
function closeContextMenu() { $("#ctx-menu")?.remove(); }
document.addEventListener("click", closeContextMenu);
document.addEventListener("contextmenu", (e) => { if (!e.target.closest("[data-chat]")) closeContextMenu(); });

function showChatContextMenu(x, y, chat) {
  closeContextMenu();
  const menu = document.createElement("div");
  menu.id = "ctx-menu";
  menu.className = "ctx-menu";
  menu.innerHTML = `
    <button data-act="rename">✎ Rename</button>
    <button data-act="project">📁 Add to project…</button>
    <hr>
    <button data-act="delete" class="danger">🗑 Delete conversation</button>`;
  document.body.appendChild(menu);
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
  menu.style.top = Math.min(y, innerHeight - r.height - 8) + "px";

  const patch = (body) => api(`/chats/${chat.id}`, { method: "PUT", body: {
    title: chat.title, company_id: chat.company_id,
    project_id: chat.project_id, active_employee_id: chat.active_employee_id, ...body } });

  menu.onclick = async (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    closeContextMenu();
    if (!act) return;
    if (act === "rename") {
      modal("Rename conversation", `
        <label>Conversation name *<input name="title" required value="${esc(chat.title)}"></label>`,
        async (fd) => {
          await patch({ title: fd.get("title") });
          toast("Conversation renamed", "ok"); render();
        }, "Rename");
    } else if (act === "project") {
      const cid = chat.company_id || state.companyId;
      if (!cid) { toast("This chat has no company — cannot pick a project", "err"); return; }
      const projects = await api(`/companies/${cid}/projects`);
      if (!projects.length) { toast("No projects in this company yet — create one first", "err"); return; }
      modal("Add conversation to project", `
        <label>Project<select name="project_id">
          <option value="">— no project —</option>
          ${projects.map(p => `<option value="${p.id}" ${chat.project_id === p.id ? "selected" : ""}>📁 ${esc(p.name)}</option>`).join("")}
        </select></label>`,
        async (fd) => {
          await patch({ project_id: fd.get("project_id") || null });
          toast(fd.get("project_id") ? "Conversation added to project" : "Conversation removed from project", "ok");
          render();
        }, "Save");
    } else if (act === "delete") {
      if (!confirm(`Delete conversation “${chat.title}”? This cannot be undone.`)) return;
      await api(`/chats/${chat.id}`, { method: "DELETE" });
      if (state.chatId === chat.id) state.chatId = null;
      toast("Conversation deleted", "ok"); render();
    }
  };
}

/* ---------------- live pipeline monitor ---------------- */
function openRunMonitor(runId) {
  const w = window.open("", "_blank", "width=980,height=760");
  if (!w) { toast("Popup blocked — allow popups for this site", "err"); return; }
  w.document.write(`<!DOCTYPE html><html><head><title>Pipeline Monitor — live</title>
  <style>
    body{margin:0;background:#0f1420;color:#e6ecf7;font-family:Segoe UI,sans-serif}
    header{position:sticky;top:0;background:#161d2e;border-bottom:1px solid #2a3550;padding:12px 20px;display:flex;gap:14px;align-items:center}
    h1{font-size:16px;margin:0}
    .pill{padding:2px 12px;border-radius:999px;font-size:12px;border:1px solid #2a3550;background:#1d2639}
    .pill.running{color:#eab308}.pill.done{color:#22c55e}.pill.error{color:#ef4444}
    .wrap{padding:18px 20px}
    .stage{background:#161d2e;border:1px solid #2a3550;border-radius:10px;margin-bottom:14px;overflow:hidden}
    .stage-head{padding:10px 16px;display:flex;gap:12px;align-items:center;background:#1d2639;font-size:14px;font-weight:600}
    .stage-body{padding:12px 16px;font-size:12px}
    .lbl{color:#8b95a7;margin:8px 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
    pre{white-space:pre-wrap;word-wrap:break-word;background:#0f1420;border:1px solid #2a3550;border-radius:8px;padding:10px;margin:0;max-height:260px;overflow:auto;font-size:12px}
    .spin{display:inline-block;animation:s 1.4s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
    .muted{color:#8b95a7}.time{margin-left:auto;font-size:11px;color:#8b95a7}
    .progress-wrap{padding:10px 20px 0;background:#161d2e;border-bottom:1px solid #2a3550}
    .progress-info{display:flex;justify-content:space-between;font-size:12px;color:#8b95a7;margin-bottom:6px}
    .progress-info b{color:#e6ecf7}
    .pbar{height:10px;background:#0f1420;border:1px solid #2a3550;border-radius:999px;overflow:hidden;margin-bottom:12px}
    .pbar-fill{height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,#3b82f6,#22c55e);transition:width .8s ease}
    .pbar-fill.anim{background-size:28px 28px;background-image:linear-gradient(135deg,rgba(255,255,255,.18) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.18) 50%,rgba(255,255,255,.18) 75%,transparent 75%,transparent);animation:pb 1s linear infinite}
    @keyframes pb{to{background-position:28px 0}}
  </style></head><body>
  <header><h1>🔎 Pipeline Monitor</h1><span id="rstat" class="pill">loading…</span>
  <span class="muted" style="font-size:12px" id="remp"></span>
  <span class="time" id="rtime">updates every 1.5s</span></header>
  <div class="progress-wrap">
    <div class="progress-info"><span>Progress: <b id="ppct">0%</b> <span id="pstage"></span></span><span>Elapsed: <b id="pelapsed">0s</b> · ETA: <b id="peta">estimating…</b></span></div>
    <div class="pbar"><div class="pbar-fill anim" id="pfill"></div></div>
  </div>
  <div class="wrap">
    <div class="lbl">User request</div><pre id="rprompt">…</pre>
    <div id="stages" style="margin-top:16px"></div>
    <div id="final"></div>
  </div>
  <script>
    const runId=${JSON.stringify(runId)};
    const esc=s=>String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
    const icon=s=>s==="done"?"✅":s==="error"?"❌":'<span class="spin">🔄</span>';
    const EXPECTED={"codex.plan":3,"codex.index":3,"codex.image":1,"codex.file":1,"codex.analyze":1};
    const t0=Date.now();let startAt=null;
    const fmt=s=>s>=60?Math.floor(s/60)+"m "+Math.round(s%60)+"s":Math.round(s)+"s";
    const PATHRE=/[A-Za-z]:\\\\[^"'\`|<>*?\\r\\n]+?\\.[A-Za-z0-9]{1,6}(?![A-Za-z0-9.])/g;
    const linkify=h=>h.replace(PATHRE,p=>'<a href="#" class="file-link" data-path="'+p.trim()+'" style="color:#60a5fa">\ud83d\udcce '+p+'</a>');
    document.addEventListener("click",async e=>{
      const a=e.target.closest(".file-link");if(!a)return;e.preventDefault();
      const p=a.dataset.path;
      const local=["localhost","127.0.0.1","::1"].includes(location.hostname);
      if(!local){const dl=document.createElement("a");dl.href="/api/download?path="+encodeURIComponent(p);dl.download=p.split(/[\\\\/]/).pop();document.body.appendChild(dl);dl.click();dl.remove();return;}
      try{await fetch("/api/open-file",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:p})});}catch(_){}
    });
    function updateProgress(d){
      const stages=d.stages||[];
      const total=Math.max(stages.length?(EXPECTED[stages[0].tool]||stages.length):1,stages.length);
      const done=stages.filter(s=>s.status==="done").length;
      const running=stages.some(s=>s.status==="running")?1:0;
      let ratio=d.status==="done"?1:d.status==="error"?(done/total):(done+running*0.5)/total;
      ratio=Math.min(ratio,d.status==="done"?1:0.97);
      if(!startAt&&stages.length&&stages[0].started_at)startAt=new Date(stages[0].started_at+"Z").getTime();
      const elapsed=((Date.now()-(startAt||t0))/1000);
      document.getElementById("ppct").textContent=Math.round(ratio*100)+"%";
      document.getElementById("pelapsed").textContent=fmt(elapsed);
      const cur=stages.find(s=>s.status==="running");
      document.getElementById("pstage").textContent=cur?("— stage "+(done+1)+"/"+total+": "+cur.label):(d.status==="done"?"— all stages complete":"");
      const eta=document.getElementById("peta");
      if(d.status==="done"){eta.textContent="done ✓";}
      else if(d.status==="error"){eta.textContent="failed";}
      else if(ratio>0.03){eta.textContent="~"+fmt(Math.max(elapsed/ratio-elapsed,2))+" left";}
      else{eta.textContent="estimating…";}
      const fill=document.getElementById("pfill");
      fill.style.width=(ratio*100)+"%";
      if(d.status==="done"||d.status==="error")fill.classList.remove("anim");
      if(d.status==="error")fill.style.background="#ef4444";
    }
    async function tick(){
      try{
        const r=await fetch("/api/runs/"+runId+"/detail",{credentials:"same-origin"});
        if(!r.ok)return;
        const d=await r.json();
        document.getElementById("rstat").textContent=d.status;
        document.getElementById("rstat").className="pill "+d.status;
        document.getElementById("remp").textContent=d.employee?("acting employee: "+d.employee):"";
        document.getElementById("rprompt").textContent=d.prompt;
        updateProgress(d);
        document.getElementById("stages").innerHTML=d.stages.map(s=>
          '<div class="stage"><div class="stage-head">'+icon(s.status)+' '+esc(s.label)+
          '<span class="time">'+(s.started_at?new Date(s.started_at+"Z").toLocaleTimeString():"")+' → '+esc(s.status)+'</span></div>'+
          '<div class="stage-body">'+
          (s.arguments&&s.arguments!=="{}"?'<div class="lbl">Input</div><pre>'+esc(s.arguments)+'</pre>':'')+
          '<div class="lbl">Output</div><pre>'+(s.result?linkify(esc(s.result)):(s.status==="running"?"⏳ working — output will appear when this stage finishes…":"—"))+'</pre>'+
          '</div></div>').join("")
          ||'<div class="muted">No pipeline stages for this run (direct answer) — waiting…</div>';
        document.getElementById("final")["innerHTML"]=
          d.status==="done"&&d.result?'<div class="lbl">Final result</div><pre>'+linkify(esc(d.result))+'</pre>':
          d.status==="error"&&d.error?'<div class="lbl">Error</div><pre style="border-color:#ef4444">'+esc(d.error)+'</pre>':"";
        if(d.status==="done"||d.status==="error")document.getElementById("rtime").textContent="finished";
      }catch(e){}
    }
    tick();
    const t=setInterval(async()=>{await tick();},1500);
  <\/script></body></html>`);
  w.document.close();
}

/* ---------------- image viewer & reference ---------------- */
function openImageViewer(path) {
  const url = "/api/image?path=" + encodeURIComponent(path);
  const w = window.open("", "_blank", "width=1000,height=800");
  if (!w) { toast("Popup blocked — allow popups for this site", "err"); return; }
  w.document.write(`<!DOCTYPE html><html><head><title>Image Viewer — ${path.split(/[\\/]/).pop()}</title>
  <style>
    body{margin:0;background:#0f1420;color:#e6ecf7;font-family:Segoe UI,sans-serif;display:flex;flex-direction:column;height:100vh}
    .bar{padding:8px 14px;background:#161d2e;border-bottom:1px solid #2a3550;display:flex;gap:10px;align-items:center;font-size:13px}
    .bar button{background:#1d2639;color:#e6ecf7;border:1px solid #2a3550;border-radius:6px;padding:5px 12px;cursor:pointer}
    .bar button:hover{border-color:#3b82f6}
    .stage{flex:1;overflow:auto;display:flex;align-items:center;justify-content:center}
    img{transform-origin:center;transition:transform .1s;max-width:none}
    .hint{color:#8b95a7;font-size:12px;margin-left:auto}
  </style></head><body>
  <div class="bar">
    <button id="zin">➕ Zoom in</button><button id="zout">➖ Zoom out</button>
    <button id="zfit">◲ Fit</button><button id="z100">1:1</button>
    <button id="edit">✎ Edit this image</button>
    <span class="hint">Scroll wheel to zoom · Right-click the image to Copy / Save As</span>
  </div>
  <div class="stage"><img id="im" src="${url}" alt="image"></div>
  <script>
    let z=1; const im=document.getElementById('im');
    const apply=()=>im.style.transform='scale('+z+')';
    document.getElementById('zin').onclick=()=>{z=Math.min(z*1.25,20);apply()};
    document.getElementById('zout').onclick=()=>{z=Math.max(z/1.25,0.05);apply()};
    document.getElementById('z100').onclick=()=>{z=1;apply()};
    document.getElementById('zfit').onclick=()=>{z=Math.min((innerWidth-40)/im.naturalWidth,(innerHeight-90)/im.naturalHeight,1);apply()};
    addEventListener('wheel',e=>{if(e.ctrlKey||true){e.preventDefault();z=e.deltaY<0?Math.min(z*1.15,20):Math.max(z/1.15,0.05);apply();}},{passive:false});
    document.getElementById('edit').onclick=()=>{ window.opener.postMessage({type:'edit-image',path:${JSON.stringify(path)}},'*'); window.close(); };
  <\/script></body></html>`);
  w.document.close();
}

window.addEventListener("message", (e) => {
  if (e.data && e.data.type === "edit-image") setImageRef(e.data.path);
});

function setImageRef(path) {
  state.imageRef = path;
  if (state.view !== "chats") nav("chats");
  updateImgRefBar();
  const ta = $("#chat-text");
  if (ta) { ta.focus(); ta.placeholder = "Describe the corrections for the referenced image…"; }
  toast("Image attached as reference — type your correction prompt", "ok");
}

function updateImgRefBar() {
  const bar = $("#img-ref-bar");
  if (!bar) return;
  if (!state.imageRef) { bar.classList.add("hidden"); bar.innerHTML = ""; return; }
  bar.classList.remove("hidden");
  bar.innerHTML = `<img src="/api/image?path=${encodeURIComponent(state.imageRef)}" alt="reference">
    <span>🖼 Referencing: <b>${esc(state.imageRef.split(/[\\\/]/).pop())}</b> — your prompt will be applied to this image</span>
    <button class="mini-btn" id="img-ref-remove">✕ Remove</button>`;
  $("#img-ref-remove").onclick = () => { state.imageRef = null; updateImgRefBar(); };
}

/* ---------------- client install gate ----------------
   The platform may only be used from computers that have the client
   program installed. Detection: the client program always listens on
   127.0.0.1:8600 of the visitor's own machine — the browser probes it.
   When the page itself is opened from localhost, the program is by
   definition installed (it is serving the page). */
let _booted = false;
let _retryTimer = null;

/* Outdated clients are updated silently in the background: the client program
   checks the server version on every heartbeat (30 s) and self-updates via
   Python. The web page additionally nudges the client's local beacon so the
   update starts immediately — no file is ever downloaded by the browser. */
function checkClientOutdated() {
  const cl = window.clientInfo;
  if (!cl || !cl.version || !window.serverVersion) return;
  const vt = (s) => String(s || "0").split(".").map(n => parseInt(n) || 0);
  const x = vt(cl.version), y = vt(window.serverVersion);
  let older = false;
  for (let i = 0; i < 3; i++) { if ((x[i]||0) !== (y[i]||0)) { older = (x[i]||0) < (y[i]||0); break; } }
  if (!older) return;
  if (document.getElementById("upd-banner")) return;
  const div = document.createElement("div");
  div.id = "upd-banner";
  div.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:9999;background:#1e3a8a;color:#dbeafe;" +
    "padding:10px 16px;font-size:13.5px;display:flex;gap:12px;align-items:center;box-shadow:0 2px 8px #0008";
  div.innerHTML = `<b>⬆️ Client update</b>
    <span id="upd-msg">This computer runs client v${cl.version}, server is v${window.serverVersion}.
    The client is updating itself automatically in the background — it will restart when done.
    Your data and settings are kept.</span>
    <button onclick="this.parentElement.remove()" style="margin-left:auto;background:none;border:none;color:#dbeafe;cursor:pointer;font-size:16px">✕</button>`;
  document.body.appendChild(div);
  // nudge the client's local beacon to start the background update NOW
  // (otherwise it starts by itself within 30 s on the next heartbeat)
  fetch("http://127.0.0.1:8600/api/update", { cache: "no-store" })
    .then(r => r.json())
    .then(() => {
      const m = document.getElementById("upd-msg");
      if (m) m.innerHTML = `Background update started (v${cl.version} → v${window.serverVersion}) —
        the client program restarts itself when finished. Nothing to download or run manually.`;
    })
    .catch(() => { /* beacon busy/old — heartbeat self-update still handles it */ });
}

async function detectClientProgram() {
  const h = location.hostname;
  if (h === "localhost" || h === "127.0.0.1" || h === "[::1]") return true;
  // Station/kiosk terminals (?station=…) and mobile devices (ChromeOS,
  // Android, iPhone, iPad) cannot install the Python client — the web page
  // itself is the kiosk client, so no local program is required.
  if (new URLSearchParams(location.search).get("station")) return true;
  if (typeof isMobileKiosk === "function" && isMobileKiosk()) return true;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    // the client beacon sends CORS headers, so we can read its JSON —
    // including this computer's license key and client version.
    const r = await fetch("http://127.0.0.1:8600/api/health", { cache: "no-store", signal: ctrl.signal });
    clearTimeout(t);
    try { window.clientInfo = await r.json(); } catch { window.clientInfo = null; }
    return true;
  } catch { /* fall through to opaque probe (older clients without CORS) */ }
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    await fetch("http://127.0.0.1:8600/api/health", { mode: "no-cors", cache: "no-store", signal: ctrl.signal });
    clearTimeout(t);
    return true;
  } catch { return false; }
}

async function boot() {
  if (_booted) return;
  clearTimeout(_retryTimer);
  const st = $("#install-status");
  if (st) st.textContent = "Checking for a local installation…";
  if (await detectClientProgram()) {
    _booted = true;
    $("#install-screen").classList.add("hidden");
    fillVersions().then(checkClientOutdated);
    initAuth();
    return;
  }
  $("#install-screen").classList.remove("hidden");
  $("#auth-screen").classList.add("hidden");
  if (st) st.textContent = "❌ No client program detected on this computer (127.0.0.1:8600 not responding). Re-checking automatically…";
  $("#install-retry").onclick = boot;
  initLicenseUI();
  _retryTimer = setTimeout(boot, 5000);
}

function initLicenseUI() {
  const btn = $("#license-verify"), inp = $("#license-key"), out = $("#license-status");
  if (!btn || btn._wired) return;
  btn._wired = true;
  inp.addEventListener("input", () => {
    // auto-format XXXXX-XXXXX-XXXXX-XXXXX
    const raw = inp.value.toUpperCase().replace(/[^A-F0-9]/g, "").slice(0, 20);
    inp.value = (raw.match(/.{1,5}/g) || []).join("-");
  });
  btn.onclick = async () => {
    const key = inp.value.trim();
    if (key.replace(/-/g, "").length !== 20) { out.textContent = "❌ Enter the full 20-character license key."; return; }
    btn.disabled = true; out.textContent = "⏳ Verifying license key with the server…";
    try {
      const r = await fetch("/api/license/claim", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, hostname: "" }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "verification failed");
      out.innerHTML = `✅ License key accepted — bound to your IP <b>${data.bound_ip}</b>. Download and run the installer below.`;
      // if the client program is already running here, hand it the key directly
      // so its config is updated without any manual editing or restart
      try {
        const lr = await fetch("http://127.0.0.1:8600/api/license?key=" + encodeURIComponent(key), { signal: AbortSignal.timeout(3000) });
        const ld = await lr.json();
        if (ld.saved) out.innerHTML += " <br>🔑 The key was also applied to the client program on this computer automatically.";
      } catch { /* client program not installed yet — installer will set the key */ }
      $("#dl-installer").href = "/api/installer?key=" + encodeURIComponent(key);
      const shBtn = $("#dl-installer-sh");
      if (shBtn) shBtn.href = "/api/installer-sh?key=" + encodeURIComponent(key);
      const pkgBtn = $("#dl-package");
      pkgBtn.href = "/api/client-package?key=" + encodeURIComponent(key);
      // packaging progress bar: the zip is built on the server when the
      // download starts — poll the build counters and fill the bar live
      pkgBtn.onclick = () => {
        const box = $("#pkg-progress"), fill = $("#pkg-progress-fill"), txt = $("#pkg-progress-txt");
        if (!box) return;   // navigation continues — the browser downloads the file
        box.classList.remove("hidden");
        fill.style.width = "2%";
        txt.textContent = "⏳ Packaging the program on the server…";
        let stopped = false;
        const timer = setInterval(async () => {
          if (stopped) return;
          try {
            const r = await fetch("/api/client-package-progress", { cache: "no-store" });
            const p = await r.json();
            if (p.state === "building" && p.total) {
              fill.style.width = Math.max(2, Math.round(p.done / p.total * 100)) + "%";
              txt.textContent = `📦 Packaging… ${p.done} / ${p.total} files (${Math.round(p.done / p.total * 100)}%)`;
            } else if (p.state === "verifying") {
              fill.style.width = "98%";
              txt.textContent = "🔎 Verifying the archive…";
            } else if (p.state === "ready") {
              fill.style.width = "100%";
              txt.textContent = "✅ Package ready — the download is starting / has started.";
              stopped = true; clearInterval(timer);
              setTimeout(() => box.classList.add("hidden"), 8000);
            } else if (p.state === "error") {
              txt.textContent = "❌ Packaging failed on the server — try again.";
              stopped = true; clearInterval(timer);
            }
          } catch { /* server busy zipping — keep polling */ }
        }, 400);
        setTimeout(() => { stopped = true; clearInterval(timer); }, 180000);
      };
      $("#install-actions").classList.remove("hidden");
    } catch (e) { out.textContent = "❌ " + e.message; }
    btn.disabled = false;
  };
}

window.addEventListener("error", (e) => {
  // surface unexpected errors instead of leaving a silent blank page
  try { toast("⚠ " + (e.message || "Unexpected error"), "err"); } catch { /* toast not ready */ }
});

boot();
