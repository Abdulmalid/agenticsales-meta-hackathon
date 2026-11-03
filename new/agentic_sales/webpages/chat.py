"""The public web chat page: one self-contained HTML file per business (no external scripts or fonts).

It talks to POST /public/<business>/chat. Customers can type, attach a photo (downscaled in the browser) or record a voice note
(MediaRecorder; the server converts any format with ffmpeg). Every string that comes from the business is escaped or passed as JSON, and
replies are written with textContent, so nothing a customer or the model says can become markup. The page says plainly that it is a virtual (automated) assistant and that a person can step in.
"""
from __future__ import annotations

import html
import json

STYLE = """
:root{color-scheme:light dark;--bg:#f4f6f3;--card:#fff;--fg:#14201a;--muted:#5b6a61;--line:#e2e8e3;--brand:#0b6e4f;--brand-fg:#fff;--me:#0b6e4f;--me-fg:#fff;--bot:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#0e1511;--card:#16201a;--fg:#e8efe9;--muted:#98a89e;--line:#28362d;--brand:#35b585;--brand-fg:#06261a;--me:#1c6f52;--me-fg:#fff;--bot:#1b2720}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;display:flex;justify-content:center}
.app{width:100%;max-width:640px;height:100dvh;display:flex;flex-direction:column;background:var(--card);border-left:1px solid var(--line);border-right:1px solid var(--line)}
header{padding:.8rem 1rem;border-bottom:1px solid var(--line)}header h1{margin:0;font-size:1.1rem}
.sub{font-size:.82rem;color:var(--muted)}
#log{flex:1;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:.6rem}
.msg{max-width:85%;padding:.55rem .8rem;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}
.msg.me{align-self:flex-end;background:var(--me);color:var(--me-fg);border-bottom-right-radius:4px}
.msg.bot{align-self:flex-start;background:var(--bot);border:1px solid var(--line);border-bottom-left-radius:4px}
.msg img{display:block;max-width:220px;width:100%;border-radius:10px;margin-bottom:.3rem}
.hint{align-self:center;color:var(--muted);font-size:.85rem;text-align:center;max-width:90%}
form{display:flex;gap:.4rem;padding:.6rem;border-top:1px solid var(--line);align-items:flex-end}
textarea{flex:1;resize:none;min-height:44px;max-height:120px;padding:.6rem .7rem;border:1px solid var(--line);border-radius:12px;background:var(--bg);color:var(--fg);font:inherit}
button,label.btn{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:12px;min-width:44px;height:44px;padding:0 .7rem;font:inherit;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}
button.primary{background:var(--brand);color:var(--brand-fg);border-color:var(--brand);font-weight:600}
button.rec{background:#b3261e;color:#fff;border-color:#b3261e}
#mic .i-stop{display:none}#mic.rec .i-stop{display:inline}#mic.rec .i-mic{display:none}
.btn svg,#mic svg{vertical-align:middle}
button:disabled{opacity:.5;cursor:default}
#preview{display:none;padding:.4rem .8rem;border-top:1px solid var(--line);align-items:center;gap:.6rem}
#preview img{height:52px;border-radius:8px;border:1px solid var(--line)}
footer{padding:.4rem 1rem .7rem;color:var(--muted);font-size:.75rem;text-align:center}
"""

SCRIPT = r"""
const TENANT = __TENANT__;
const API = "/public/" + encodeURIComponent(TENANT) + "/chat";
const log = document.getElementById("log"), box = document.getElementById("box"), send = document.getElementById("send");
const preview = document.getElementById("preview"), pimg = document.getElementById("pimg"), mic = document.getElementById("mic");
let sid = "";
let src = "";
try { src = (new URLSearchParams(location.search).get("src") || "").toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 24); } catch (e) {}
try { sid = localStorage.getItem("ac_sid") || ""; } catch (e) {}
if (!/^[A-Za-z0-9_-]{8,40}$/.test(sid)) {
  sid = "w" + Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => (b % 36).toString(36)).join("");
  try { localStorage.setItem("ac_sid", sid); } catch (e) {}
}
let photo = null, recorder = null, chunks = [], busy = false, stopTimer = null;

function add(role, text, img) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  if (img) { const i = document.createElement("img"); i.src = img; i.alt = "Photo you sent"; d.appendChild(i); }
  if (text) d.appendChild(document.createTextNode(text));
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}
function setBusy(b) { busy = b; send.disabled = b; mic.disabled = b && !recorder; }

async function post(body) {
  const typing = add("bot", "…");
  setBusy(true);
  try {
    const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session: sid, ...(src ? { src } : {}), ...body }) });
    if (r.status === 429) throw new Error("You're sending messages quickly. Please wait a moment and try again.");
    if (!r.ok) throw new Error("Sorry, that didn't go through. Please try again.");
    const data = await r.json();
    typing.textContent = data.reply || "(no reply)";
    for (const u of (data.images || [])) { const i = document.createElement("img"); i.src = u; i.alt = "Product photo"; i.style.cssText = "display:block;max-width:220px;width:100%;border-radius:10px;margin-top:6px"; typing.appendChild(i); }
  } catch (e) {
    typing.textContent = e.message || "Sorry, that didn't go through. Please try again.";
  } finally { setBusy(false); log.scrollTop = log.scrollHeight; }
}

async function toJpeg(file) {
  const bmp = await createImageBitmap(file);
  const s = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}
document.getElementById("file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; e.target.value = "";
  if (!f) return;
  try { const url = await toJpeg(f); photo = url.split(",")[1]; pimg.src = url; preview.style.display = "flex"; }
  catch (err) { add("bot", "I couldn't read that image. Please try a JPEG or PNG photo."); }
});
document.getElementById("rm").addEventListener("click", () => { photo = null; preview.style.display = "none"; });

document.getElementById("f").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = box.value.trim();
  if ((!text && !photo) || busy) return;
  const shown = photo ? "data:image/jpeg;base64," + photo : null;
  add("me", text, shown);
  const body = { text }; if (photo) body.image = photo;
  box.value = ""; photo = null; preview.style.display = "none";
  post(body);
});
box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("f").requestSubmit(); } });

function blobToB64(blob) {
  return new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1] || ""); r.onerror = () => no(r.error); r.readAsDataURL(blob); });
}
mic.addEventListener("click", async () => {
  if (recorder) { recorder.stop(); return; }
  if (!navigator.mediaDevices || !window.MediaRecorder) { add("bot", "Voice notes aren't supported in this browser. Please type your message."); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    const type = types.find((t) => MediaRecorder.isTypeSupported(t)) || "";
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    recorder.ondataavailable = (ev) => { if (ev.data.size) chunks.push(ev.data); };
    recorder.onstop = async () => {
      clearTimeout(stopTimer);
      stream.getTracks().forEach((t) => t.stop());
      const mime = (recorder.mimeType || type || "audio/webm").split(";")[0];
      const blob = new Blob(chunks, { type: mime });
      recorder = null; mic.classList.remove("rec"); mic.setAttribute("aria-label", "Record a voice note");
      if (blob.size < 800) { add("bot", "That voice note was too short. Hold on a little longer."); return; }
      if (blob.size > 1800000) { add("bot", "That voice note is too long. Please keep it under a minute."); return; }
      add("me", "Voice note");
      post({ audio: await blobToB64(blob), audio_mime: mime });
    };
    recorder.start();
    mic.classList.add("rec"); mic.setAttribute("aria-label", "Stop recording");
    stopTimer = setTimeout(() => { if (recorder) recorder.stop(); }, 60000);
  } catch (err) { recorder = null; add("bot", "I couldn't use the microphone. Please allow access, or type your message."); }
});
"""


def page(tenant_id: str, business_name: str, agent_name: str = "") -> str:
    name = html.escape(business_name)
    who = html.escape(agent_name.strip() or "our assistant")
    script = SCRIPT.replace("__TENANT__", json.dumps(tenant_id).replace("</", "<\\/"))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<link rel="icon" href="data:,"><title>Chat with {name}</title><style>{STYLE}</style></head><body><div class="app">'
            f'<header><h1>{name}</h1><div class="sub">You are chatting with {who}, a virtual sales assistant</div></header>'
            '<div id="log" role="log" aria-live="polite"><div class="hint">Ask about products, prices or delivery. You can send a photo of what you want, or a voice note. '
            "A team member can step in at any time.</div></div>"
            '<div id="preview"><img id="pimg" alt="Photo ready to send"><button type="button" id="rm">Remove photo</button></div>'
            '<form id="f"><label class="btn" title="Send a photo"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg><input id="file" type="file" accept="image/*" hidden aria-label="Attach a photo"></label>'
            '<button type="button" id="mic" aria-label="Record a voice note"><svg class="i-mic" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0014 0M12 18v3"/></svg><svg class="i-stop" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/></svg></button>'
            '<textarea id="box" rows="1" maxlength="1000" placeholder="Type your message…" aria-label="Your message"></textarea>'
            '<button class="primary" id="send" type="submit">Send</button></form>'
            "<footer>Virtual assistant: it can make mistakes, a team member can step in, and a payment is only confirmed by the payment provider.</footer>"
            f"</div><script>{script}</script></body></html>")


CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; "
       "media-src blob:; base-uri 'none'; form-action 'none'")
