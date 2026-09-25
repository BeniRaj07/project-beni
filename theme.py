"""A sci-fi "circuit-board" HUD look: dark teal-on-black theme, CSS, and the small amount of
client-side JavaScript the UI genuinely needs — most notably a continuous voice-session state
machine (LISTENING/USER_SPEAKING/PROCESSING/ASSISTANT_SPEAKING) driven by a persistent, always-on
VAD loop, so talking over Awaaz while it's speaking interrupts it instantly with no button press —
plus a live clock, a dark/light toggle, and an off-canvas conversation drawer. Sending, replying,
playing audio and the conversation list are plain Gradio, driven from Python in app.py; this
module only builds the look and a handful of pure-HTML dashboard widgets (reminders/tasks/weather
cards) from data app.py hands it.
"""
from __future__ import annotations

import html
import math

import gradio as gr

# ── theme ────────────────────────────────────────────────────────────────────

BG = "#040b0a"
SURFACE = "rgba(7,26,24,.72)"
SIDEBAR = "#03100e"
BORDER = "rgba(52,230,200,.28)"
TEXT = "#d8fff5"
MUTED = "#6f9a92"
ACCENT = "#2fe6c8"      # the reference image's glowing teal
WARN = "#ff9f43"        # its warm orange accent, used sparingly (due/overdue, live status)


def _both(**values: str) -> dict[str, str]:
    import inspect
    accepted = set(inspect.signature(gr.themes.Base.set).parameters)
    out = dict(values)
    out.update({f"{k}_dark": v for k, v in values.items() if f"{k}_dark" in accepted})
    return out


THEME = gr.themes.Base(
    primary_hue="teal", neutral_hue="slate",
    font=[gr.themes.GoogleFont("Rajdhani"), "ui-sans-serif", "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("Share Tech Mono"), "ui-monospace", "monospace"],
).set(**_both(
    body_background_fill=BG, body_text_color=TEXT, body_text_color_subdued=MUTED,
    background_fill_primary=SURFACE, background_fill_secondary=SIDEBAR,
    block_background_fill=SURFACE, block_border_color=BORDER, block_border_width="1px",
    block_radius="4px", block_label_text_color=MUTED, block_title_text_color=ACCENT,
    panel_background_fill=SIDEBAR, panel_border_color=BORDER,
    border_color_primary=BORDER, border_color_accent=ACCENT, color_accent=ACCENT,
    input_background_fill="rgba(0,20,18,.6)", input_border_color=BORDER, input_border_color_focus=ACCENT,
    input_placeholder_color=MUTED,
    button_primary_background_fill=ACCENT, button_primary_background_fill_hover="#5cf2da",
    button_primary_text_color="#022420", button_primary_border_color=ACCENT,
    button_secondary_background_fill="rgba(47,230,200,.08)",
    button_secondary_background_fill_hover="rgba(47,230,200,.18)",
    button_secondary_text_color=TEXT, button_secondary_border_color=BORDER,
    button_cancel_background_fill="rgba(239,68,68,.12)", button_cancel_text_color="#fca5a5",
    link_text_color=ACCENT, code_background_fill="rgba(0,20,18,.6)",
))


# ── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
:root[data-theme="light"] {
  --bg:#eafbf7; --surface:#ffffff; --sidebar:#f0fbf8; --border:rgba(13,120,105,.25);
  --text:#04231e; --muted:#4c766e; --accent:#0c9c85; --warn:#e07b1f;
}
:root, :root[data-theme="dark"] {
  --bg:#040b0a; --surface:rgba(7,26,24,.72); --sidebar:#03100e; --border:rgba(52,230,200,.28);
  --text:#d8fff5; --muted:#6f9a92; --accent:#2fe6c8; --warn:#ff9f43;
}
body, gradio-app { background: var(--bg) !important; }
.gradio-container { max-width: 100% !important; padding: 0 !important; margin: 0 !important;
  font-family: 'Rajdhani', ui-sans-serif, sans-serif !important; height: 100vh; position: relative; }
footer { display: none !important; }

/* circuit-board backdrop: fine grid + faint diagonal hatch corners + vignette glow */
#app-root { height: 100vh; display: flex; flex-direction: column; position: relative; overflow: hidden; }
#app-root::before {
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(1100px 650px at 15% -10%, rgba(47,230,200,.10), transparent 60%),
    radial-gradient(900px 600px at 105% 60%, rgba(47,230,200,.08), transparent 60%),
    repeating-linear-gradient(135deg, rgba(52,230,200,.05) 0 2px, transparent 2px 14px),
    linear-gradient(rgba(52,230,200,.05) 1px, transparent 1px) 0 0/34px 34px,
    linear-gradient(90deg, rgba(52,230,200,.05) 1px, transparent 1px) 0 0/34px 34px;
  -webkit-mask-image: radial-gradient(1200px 900px at 50% 20%, #000 55%, transparent 95%);
          mask-image: radial-gradient(1200px 900px at 50% 20%, #000 55%, transparent 95%);
}
h1, h2, h3, h4 { font-family: 'Rajdhani', sans-serif !important; }
code, .mono { font-family: 'Share Tech Mono', monospace !important; }

/* ── top bar ──────────────────────────────────────────── */
#topbar { position: relative; z-index: 2; display: flex; align-items: center; gap: 14px;
  padding: 10px 18px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, rgba(3,16,14,.9), rgba(3,16,14,.6)); }
#menu-btn { background: rgba(47,230,200,.08) !important; border: 1px solid var(--border) !important;
  color: var(--accent) !important; min-width: 38px; height: 38px; border-radius: 8px !important;
  clip-path: polygon(6px 0,100% 0,100% calc(100% - 6px),calc(100% - 6px) 100%,0 100%,0 6px); }
#topbar .brand { font-family: 'Rajdhani', sans-serif; font-weight: 700; font-size: 1.15rem;
  letter-spacing: .18em; color: var(--accent); text-shadow: 0 0 10px rgba(47,230,200,.55); }
#topbar .brand small { display: block; font-family: 'Share Tech Mono', monospace; font-size: .6rem;
  letter-spacing: .12em; color: var(--muted); font-weight: 400; }
#topbar .spacer { flex: 1; }
#topbar-clock { font-family: 'Share Tech Mono', monospace; font-size: 1.05rem; color: var(--text);
  letter-spacing: .06em; text-align: right; }
#topbar-clock .date { font-size: .68rem; color: var(--muted); letter-spacing: .1em; }
.hud-icon { width: 38px; height: 38px; border-radius: 8px; display: grid; place-items: center;
  background: rgba(47,230,200,.08); border: 1px solid var(--border); flex: none; }
.hud-icon.status { color: var(--warn); } .hud-icon.status svg { filter: drop-shadow(0 0 4px var(--warn)); }
.hud-icon.gear { color: var(--accent); cursor: pointer; }

/* ── dashboard grid ───────────────────────────────────── */
#dashboard { position: relative; z-index: 1; flex: 1 1 auto; min-height: 0; display: grid;
  grid-template-columns: 240px 1fr 260px; gap: 14px; padding: 14px 16px 10px; }
@media (max-width: 1100px) { #dashboard { grid-template-columns: 1fr; grid-template-rows: auto auto auto 1fr; } }
#right-rail { display: flex; flex-direction: column; gap: 14px; min-height: 0; min-width: 0; }
#right-rail > div:first-child { flex: 1 1 auto; min-height: 0; }
#right-rail > div:last-child { flex: none; }

.hud-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px 13px; display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow: hidden;
  clip-path: polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,16px 100%,0 calc(100% - 16px));
  box-shadow: 0 0 26px rgba(47,230,200,.06) inset; backdrop-filter: blur(6px); }
.hud-panel .hp-title { font-size: .72rem; font-weight: 700; letter-spacing: .16em; color: var(--accent);
  text-transform: uppercase; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; }
.hud-panel .hp-title .n { font-family: 'Share Tech Mono', monospace; color: var(--muted); font-weight: 400; }
.hud-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1 1 auto; }
.hud-list li { padding: 7px 2px 7px 10px; border-left: 2px solid var(--border); margin-bottom: 6px;
  font-size: .86rem; color: var(--text); }
.hud-list li.due { border-left-color: var(--warn); }
.hud-list li.done { opacity: .55; text-decoration: line-through; }
.hud-list li small { display: block; font-family: 'Share Tech Mono', monospace; font-size: .68rem;
  color: var(--muted); margin-top: 1px; text-decoration: none; }
.hud-list li.empty { border-color: transparent; color: var(--muted); font-style: italic; }
.hud-ring-row { display: flex; align-items: center; gap: 12px; margin-top: 10px; padding-top: 10px;
  border-top: 1px solid var(--border); }
.hud-ring { flex: none; filter: drop-shadow(0 0 5px rgba(47,230,200,.35)); }
.hud-ring-text { font-family: 'Share Tech Mono', monospace; font-size: 13px; fill: var(--accent); }
.hud-ring-label { font-size: .78rem; color: var(--muted); }

.hud-table-wrap { flex: 1 1 auto; overflow: hidden auto; min-height: 0; max-width: 100%; }
.hud-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: .82rem; }
.hud-table th { text-align: left; font-family: 'Share Tech Mono', monospace; font-size: .62rem;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted); font-weight: 400;
  padding: 0 4px 6px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--surface); }
.hud-table th:first-child, .hud-table td:first-child { width: 62%; }
.hud-table th:last-child, .hud-table td:last-child { width: 38%; }
.hud-table td { padding: 6px 4px; border-bottom: 1px solid rgba(47,230,200,.08); color: var(--text);
  vertical-align: top; overflow-wrap: break-word; }
.hud-table td:last-child { font-family: 'Share Tech Mono', monospace; font-size: .74rem; color: var(--muted);
  text-align: right; }
.hud-table tr.due td:last-child { color: var(--warn); font-weight: 600; }
.hud-table tr.done td:first-child { opacity: .55; text-decoration: line-through; }
.hud-table-empty { color: var(--muted); font-style: italic; font-size: .84rem; padding: 4px 2px; margin: 0; }

.weather-gauge { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 4px 0 2px; }
.wg-ring-wrap { position: relative; width: 104px; height: 104px; }
.wg-ring { width: 100%; height: 100%; filter: drop-shadow(0 0 6px rgba(47,230,200,.35)); }
.wg-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.wg-icon { font-size: 1.3rem; line-height: 1; margin-bottom: 3px; }
.wg-temp { font-family: 'Share Tech Mono', monospace; font-size: 1.5rem; color: var(--accent);
  text-shadow: 0 0 10px rgba(47,230,200,.5); line-height: 1; }
.wg-temp small { font-size: .8rem; }
.wg-place { font-size: .82rem; color: var(--text); margin-top: 10px; font-weight: 600; }
.wg-cond { font-size: .72rem; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-top: 2px; }

/* ── center screen ────────────────────────────────────── */
#center-screen { position: relative; background: radial-gradient(120% 100% at 50% 0%, rgba(47,230,200,.07), transparent 60%), var(--surface);
  border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; min-height: 0;
  box-shadow: 0 0 40px rgba(47,230,200,.08) inset, 0 0 0 1px rgba(47,230,200,.05); overflow: hidden; }
#center-screen::before { content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background: repeating-linear-gradient(0deg, rgba(47,230,200,.025) 0 1px, transparent 1px 3px); }
#chatbot { flex: 1 1 auto; border: none !important; background: transparent !important; }
#chatbot .message-wrap { max-width: 720px; margin: 0 auto; }
#chatbot .message.user { background: rgba(47,230,200,.08) !important; border: 1px solid var(--border) !important;
  border-radius: 12px !important; color: var(--text) !important; }
#chatbot .message.bot { background: transparent !important; border: none !important; color: var(--text) !important; }
#chatbot table { display: block; overflow-x: auto; white-space: nowrap; max-width: 100%; }
#chatbot table td, #chatbot table th { white-space: nowrap; border-color: var(--border) !important; }
#status-line { max-width: 720px; margin: -4px auto 0; padding: 0 20px; min-height: 18px;
  font-size: .82rem; color: var(--accent); font-family: 'Share Tech Mono', monospace; }
#status-line:not(:empty) { animation: pulse-text 1.3s ease-in-out infinite; }
@keyframes pulse-text { 0%,100% { opacity: .45 } 50% { opacity: 1 } }

#composer-wrap { position: relative; max-width: 760px; width: 100%; margin: 0 auto; padding: 6px 20px 16px; z-index: 1; }
#composer { display: flex; align-items: center; gap: 10px; background: rgba(0,18,16,.7);
  border: 1px solid var(--border); border-radius: 30px; padding: 5px 6px 5px 16px;
  box-shadow: 0 0 18px rgba(47,230,200,.10) inset; }
#composer-input textarea, #composer-input input { border: none !important; background: transparent !important;
  box-shadow: none !important; font-size: 1rem !important; padding: 8px 4px !important; color: var(--text) !important; }
#send-btn, .mic-btn { min-width: 42px !important; width: 42px; height: 42px; border-radius: 50% !important;
  padding: 0 !important; font-size: 1.05rem !important; flex: none; position: relative; }
#send-btn { background: radial-gradient(circle at 35% 30%, #6dffe6, var(--accent) 60%) !important;
  border: 1px solid var(--accent) !important; color: #02201c !important;
  box-shadow: 0 0 16px rgba(47,230,200,.65); }
.mic-btn { background: rgba(47,230,200,.06) !important; border: 1px solid var(--border) !important;
  color: var(--accent) !important; cursor: pointer; }
.mic-btn::after { content: ""; position: absolute; inset: -5px; border-radius: 50%; border: 1px solid var(--border);
  opacity: .6; }
.mic-btn:hover { background: rgba(47,230,200,.14) !important; }
.mic-btn.conv-on { background: rgba(47,230,200,.16) !important; border-color: var(--accent) !important;
  box-shadow: 0 0 12px rgba(47,230,200,.5); }
.mic-btn.recording { background: rgba(239,68,68,.15) !important; border-color: #ef4444 !important;
  color: #ef4444 !important; animation: mic-pulse 1.1s ease-in-out infinite; }
.mic-btn.recording::after { border-color: rgba(239,68,68,.5); }
@keyframes mic-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(239,68,68,.45) } 50% { box-shadow: 0 0 0 9px rgba(239,68,68,0) } }
/* Mic is still live (listening for barge-in) while Awaaz talks - a slower, calmer pulse than
   .recording so it reads as "still on" without looking like an error/alert state. */
.mic-btn.speaking { animation: mic-speaking-pulse 1.8s ease-in-out infinite; }
@keyframes mic-speaking-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(47,230,200,.4) } 50% { box-shadow: 0 0 0 7px rgba(47,230,200,0) } }
/* While a voice session is running, the JS-driven #mic-status line (below) is the single status
   readout - suppress the Python-driven #status-line so the two never show conflicting text. */
#app-root.voice-session-on #status-line { display: none; }
/* Positioned absolutely (not inline) so it never fights Gradio's own flex-basis math for the
   composer row's other children — it just floats above the mic button when shown. */
.mic-btn-group { position: relative; flex: none; }
#end-conv-btn { position: absolute; left: 50%; bottom: 54px; transform: translateX(-50%);
  min-width: 68px; height: 28px; border-radius: 14px; white-space: nowrap;
  background: rgba(10,26,24,.92); border: 1px solid rgba(239,68,68,.4);
  color: #fca5a5; font-size: .74rem; padding: 0 10px; cursor: pointer;
  font-family: 'Share Tech Mono', monospace; box-shadow: 0 4px 14px rgba(0,0,0,.4); }
#end-conv-btn:hover { background: rgba(239,68,68,.18); }
#rec-indicator { display: none; align-items: center; gap: 8px; max-width: 720px; margin: 0 auto 6px;
  padding: 0 20px; font-size: .82rem; color: #ef4444; font-weight: 600; font-family: 'Share Tech Mono', monospace; }
#rec-indicator.on { display: flex; }
#rec-indicator .dot { width: 7px; height: 7px; border-radius: 50%; background: #ef4444; animation: mic-pulse 1s infinite; }
#rec-indicator .bars { display: flex; align-items: center; gap: 2px; height: 14px; }
#rec-indicator .bars i { width: 3px; background: #ef4444; border-radius: 2px; transition: height .08s; height: 4px; }
#mic-status { font-size: .76rem; color: var(--muted); max-width: 720px; margin: 0 auto; padding: 0 20px;
  min-height: 15px; font-family: 'Share Tech Mono', monospace; }

/* decorative reticle, echoing the reference image's radar/targeting motif */
.reticle { position: absolute; right: 14px; bottom: 8px; width: 64px; height: 64px; pointer-events: none;
  opacity: .5; z-index: 0; }
.reticle svg { width: 100%; height: 100%; }
.reticle .spin { animation: reticle-spin 12s linear infinite; transform-origin: center; }
@keyframes reticle-spin { to { transform: rotate(360deg); } }

#mic-upload { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important;
  overflow: hidden !important; }
/* The reply is spoken, not watched: keep the <audio> element mounted (autoplay still fires) but hide
   its waveform/scrubber/Stop-button chrome entirely. Speaking into the mic (see JS) interrupts it. */
#audio-row { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important;
  overflow: hidden !important; }

/* ── sidebar drawer (off-canvas on every screen size) ──── */
#sidebar { position: fixed; z-index: 50; left: 0; top: 0; bottom: 0; width: 300px; max-width: 82vw;
  background: var(--sidebar) !important; border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 10px !important; gap: 8px;
  transform: translateX(-100%); transition: transform .22s ease; box-shadow: 10px 0 30px rgba(0,0,0,.5); }
#app-root.sidebar-open #sidebar { transform: translateX(0); }
#app-root.sidebar-open #scrim { opacity: 1; pointer-events: auto; }
#scrim { position: fixed; inset: 0; z-index: 45; background: rgba(0,8,7,.6); opacity: 0; pointer-events: none;
  transition: opacity .2s ease; }
#sidebar-header { display: flex; align-items: center; gap: 8px; padding: 6px 6px 2px; }
#sidebar-header .logo { font-size: 1.2rem; }
#sidebar-header .name { font-weight: 700; font-size: 1rem; color: var(--accent); letter-spacing: .08em; }
#sidebar-header .spacer { flex: 1; }
#sidebar-close { background: transparent !important; border: 1px solid var(--border) !important;
  color: var(--muted) !important; width: 26px; height: 26px; border-radius: 6px !important;
  cursor: pointer; font-size: .8rem; }
#sidebar-close:hover { color: var(--text) !important; background: rgba(47,230,200,.12) !important; }
#new-chat-btn { border: 1px solid var(--border) !important; background: rgba(47,230,200,.06) !important;
  color: var(--text) !important; justify-content: flex-start !important; font-weight: 600 !important;
  border-radius: 8px !important; }
#new-chat-btn:hover { background: rgba(47,230,200,.14) !important; }
#search-box textarea, #search-box input { border-radius: 8px !important; font-size: .9rem !important; }
#sidebar-scroll { flex: 1 1 auto; overflow-y: auto; min-height: 0; padding-right: 2px; }
.conv-group-label { font-size: .68rem; font-weight: 700; letter-spacing: .1em; color: var(--muted);
  text-transform: uppercase; margin: 12px 8px 4px; }
.conv-row { display: flex; align-items: center; gap: 2px; border-radius: 6px; }
.conv-row:hover, .conv-row.active { background: rgba(47,230,200,.10); }
.conv-title-btn { flex: 1; text-align: left !important; background: transparent !important;
  border: none !important; color: var(--text) !important; font-size: .88rem !important;
  font-weight: 400 !important; padding: 8px 6px !important; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; display: block; min-width: 0; box-shadow: none !important; }
.conv-row.active .conv-title-btn { color: var(--accent) !important; font-weight: 600 !important; }
.conv-icon-btn { min-width: 26px !important; width: 26px !important; height: 26px !important;
  padding: 0 !important; background: transparent !important; border: none !important;
  color: var(--muted) !important; font-size: .85rem !important; border-radius: 6px !important;
  opacity: 0; transition: opacity .12s; }
.conv-row:hover .conv-icon-btn { opacity: 1; }
.conv-icon-btn:hover { background: rgba(47,230,200,.18) !important; color: var(--text) !important; }
#rename-bar { padding: 4px 2px 8px; }
#sidebar-footer { border-top: 1px solid var(--border); padding-top: 8px; display: flex;
  align-items: center; justify-content: space-between; gap: 6px; }
#sidebar-footer label { font-size: .8rem !important; color: var(--muted) !important; }
#theme-toggle { min-width: 34px !important; width: 34px; height: 34px; border-radius: 50% !important;
  padding: 0 !important; background: transparent !important; border: 1px solid var(--border) !important; }

@media (max-width: 640px) {
  #dashboard { padding: 10px 10px 6px; gap: 10px; }
  #topbar .brand small { display: none; }
  #topbar-clock { font-size: .85rem; }
  .reticle { display: none; }
}
"""


# ── head: fonts + the small amount of client JS ─────────────────────────────

def head(initial_theme: str) -> str:
    theme = "light" if initial_theme == "light" else "dark"
    return f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<script>document.documentElement.dataset.theme = localStorage.getItem("awaaz-theme") || "{theme}";</script>
<script>{JS}</script>
"""


JS = r"""
(function () {
  // ── dark / light toggle (instant, client-only; the Python side just mirrors it into settings.json) ──
  window.awaazToggleTheme = function () {
    const html = document.documentElement;
    const next = html.dataset.theme === "light" ? "dark" : "light";
    html.dataset.theme = next;
    try { localStorage.setItem("awaaz-theme", next); } catch (e) {}
  };

  // ── off-canvas conversation drawer ──
  window.awaazToggleSidebar = function () {
    const root = document.getElementById("app-root");
    if (root) root.classList.toggle("sidebar-open");
  };
  document.addEventListener("click", function (e) {
    const root = document.getElementById("app-root");
    if (!root || !root.classList.contains("sidebar-open")) return;
    const sidebar = document.getElementById("sidebar");
    const opener = e.target.closest("#menu-btn");
    if (sidebar && !sidebar.contains(e.target) && !opener) root.classList.remove("sidebar-open");
  });

  // ── live clock ──
  function tickClock() {
    const el = document.getElementById("topbar-clock");
    if (!el) return;
    const now = new Date();
    const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    const date = now.toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short" });
    el.innerHTML = time + '<div class="date">' + date + "</div>";
  }
  setInterval(tickClock, 1000);
  document.addEventListener("DOMContentLoaded", tickClock);

  // ── continuous voice session with real barge-in (VAD-driven, not tap-driven) ──
  // Tap once: ONE microphone grant for the whole session. The mic stays live and is continuously
  // analysed for voice activity in every state, including while Awaaz is talking — so starting to
  // talk over it interrupts immediately, with no button press. State machine:
  //   LISTENING -> USER_SPEAKING -> PROCESSING -> ASSISTANT_SPEAKING -> LISTENING
  // with a direct ASSISTANT_SPEAKING -> USER_SPEAKING edge (and PROCESSING -> USER_SPEAKING) for
  // barge-in. Tap "End" (or the mic again) to release the microphone and stop everything.
  //
  // Tunable without a settings page — e.g. from the browser console:
  //   localStorage.setItem('awaaz_silence_ms', '900'); location.reload();
  function vadTunable(key, fallback) {
    try { const v = localStorage.getItem("awaaz_" + key); return v !== null && v !== "" ? Number(v) : fallback; }
    catch (e) { return fallback; }
  }
  const VAD = {
    speechRms: vadTunable("speech_rms", 0.02),         // energy above this = "someone is talking"
    bargeInRms: vadTunable("bargein_rms", 0.035),       // higher bar to interrupt playback (echo/false-trigger margin)
    onsetMs: vadTunable("onset_ms", 120),               // sustained-above-threshold time before it commits (rejects clicks/pops)
    silenceMs: vadTunable("silence_ms", 700),           // end-of-speech pause (spec default)
    maxUtteranceMs: vadTunable("max_utterance_ms", 30000),
    turnTimeoutMs: vadTunable("turn_timeout_ms", 25000), // give up waiting for a reply and resume listening
  };

  const STATE = { IDLE: "idle", LISTENING: "listening", USER_SPEAKING: "user_speaking",
                 PROCESSING: "processing", ASSISTANT_SPEAKING: "assistant_speaking" };
  const STATUS_TEXT = { listening: "Listening…", user_speaking: "Hearing you…",
                        processing: "Thinking…", assistant_speaking: "Speaking…" };

  const SESSION = {
    active: false, state: STATE.IDLE, genId: 0,
    stream: null, ctx: null, analyser: null, buf: null, mime: "",
    rec: null, chunks: [],
    onsetStart: 0, silenceStart: 0, utterStartedAt: 0,
    rafId: null, replyObserver: null, turnTimer: null,
  };

  function pickMime() {
    if (!window.MediaRecorder) return "";
    for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"])
      if (MediaRecorder.isTypeSupported(m)) return m;
    return "";
  }
  function setBars(level) {
    document.querySelectorAll("#rec-indicator .bars i").forEach(function (bar, i) {
      bar.style.height = (4 + Math.min(16, level * (140 + i * 30))) + "px";
    });
  }
  function setStatus(text) { const el = document.getElementById("mic-status"); if (el) el.textContent = text || ""; }
  function refreshUI() {
    document.querySelectorAll(".mic-btn").forEach(function (b) {
      b.classList.toggle("conv-on", SESSION.active);
      b.classList.toggle("recording", SESSION.state === STATE.USER_SPEAKING);
      b.classList.toggle("speaking", SESSION.state === STATE.ASSISTANT_SPEAKING);
    });
    const end = document.getElementById("end-conv-btn"); if (end) end.style.display = SESSION.active ? "" : "none";
    const ind = document.getElementById("rec-indicator"); if (ind) ind.classList.toggle("on", SESSION.state === STATE.USER_SPEAKING);
    const root = document.getElementById("app-root"); if (root) root.classList.toggle("voice-session-on", SESSION.active);
  }
  function setState(next) { SESSION.state = next; setStatus(STATUS_TEXT[next] || ""); refreshUI(); }

  // Talking to Awaaz always interrupts whatever it's currently saying — instantly, client-side,
  // no server round-trip needed to stop audio that's already playing in the browser.
  //
  // Clearing .autoplay matters as much as .pause(): if a reply's <audio> element is still
  // loading (data URI/blob not yet decoded) when this runs, .pause() on a not-yet-playing
  // element doesn't stick - the browser can still auto-start it once the resource becomes
  // ready, moments later, unless the autoplay attribute itself is cleared first. .muted is a
  // last line of defence so a race here is silent rather than audible even in the worst case.
  function stopSpeaking() {
    document.querySelectorAll("#audio-row audio").forEach(function (a) {
      try { a.autoplay = false; a.muted = true; a.pause(); a.currentTime = 0; } catch (e) {}
    });
  }

  // ── session lifecycle: one mic grant, kept alive for the whole conversation ──
  async function startSession() {
    if (SESSION.active) return;
    try {
      SESSION.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      setStatus("Microphone blocked — allow microphone access for this site, then try again.");
      return;
    }
    SESSION.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (SESSION.ctx.state === "suspended") await SESSION.ctx.resume();
    SESSION.analyser = SESSION.ctx.createAnalyser(); SESSION.analyser.fftSize = 1024;
    SESSION.buf = new Float32Array(SESSION.analyser.fftSize);
    SESSION.ctx.createMediaStreamSource(SESSION.stream).connect(SESSION.analyser);
    SESSION.mime = pickMime();
    SESSION.active = true;
    setState(STATE.LISTENING);
    startReplyWatcher();          // idempotent - a no-op if already watching from a prior session
    vadLoop();
  }

  function endSession() {
    if (!SESSION.active) return;
    SESSION.active = false;
    SESSION.genId++;                                  // invalidate anything still in flight
    if (SESSION.rafId) cancelAnimationFrame(SESSION.rafId);
    clearTurnTimeout();
    // The reply watcher is deliberately NOT disconnected here: a request from the ended session
    // can still resolve late server-side, and its staleness check (SESSION.active is now false)
    // is exactly what keeps that late reply muted. Tearing the observer down would remove the
    // one thing still guarding against it, right when it's needed most.
    if (SESSION.rec && SESSION.rec.state !== "inactive") { try { SESSION.rec.stop(); } catch (e) {} }
    if (SESSION.stream) SESSION.stream.getTracks().forEach(function (t) { t.stop(); });
    SESSION.stream = null; SESSION.ctx = null; SESSION.analyser = null;
    stopSpeaking();
    setState(STATE.IDLE);
    setStatus("");
  }
  window.awaazEndConversation = endSession;

  // Onset must be sustained for VAD.onsetMs before it commits — rejects clicks, pops, brief echo spikes.
  function trackOnset(level, now, threshold, onCommit) {
    if (level > threshold) {
      if (!SESSION.onsetStart) SESSION.onsetStart = now;
      else if (now - SESSION.onsetStart > VAD.onsetMs) { SESSION.onsetStart = 0; onCommit(); }
    } else {
      SESSION.onsetStart = 0;
    }
  }

  // The continuous VAD loop: runs every animation frame for the ENTIRE session, in every state -
  // this is what makes barge-in during ASSISTANT_SPEAKING possible at all.
  function vadLoop() {
    if (!SESSION.active || !SESSION.analyser) return;
    SESSION.analyser.getFloatTimeDomainData(SESSION.buf);
    let sum = 0; for (let i = 0; i < SESSION.buf.length; i++) sum += SESSION.buf[i] * SESSION.buf[i];
    const level = Math.sqrt(sum / SESSION.buf.length);
    const now = Date.now();

    switch (SESSION.state) {
      case STATE.LISTENING:
        trackOnset(level, now, VAD.speechRms, beginUtterance);
        break;
      case STATE.USER_SPEAKING:
        setBars(level);
        if (level > VAD.speechRms) {
          SESSION.silenceStart = 0;
        } else {
          if (!SESSION.silenceStart) SESSION.silenceStart = now;
          else if (now - SESSION.silenceStart > VAD.silenceMs) { endUtterance(true); break; }
        }
        if (now - SESSION.utterStartedAt > VAD.maxUtteranceMs) { endUtterance(true); break; }
        break;
      case STATE.PROCESSING:
        // Barge in even before the reply arrives (Test 3): a higher threshold than plain
        // listening, since this state can follow the tail of your own last utterance.
        trackOnset(level, now, VAD.bargeInRms, beginUtterance);
        break;
      case STATE.ASSISTANT_SPEAKING:
        trackOnset(level, now, VAD.bargeInRms, function () { stopSpeaking(); beginUtterance(); });
        break;
    }
    SESSION.rafId = requestAnimationFrame(vadLoop);
  }

  function beginUtterance() {
    clearTurnTimeout();
    SESSION.genId++;                     // supersede whatever the previous turn was waiting on
    SESSION.chunks = [];
    try { SESSION.rec = new MediaRecorder(SESSION.stream, SESSION.mime ? { mimeType: SESSION.mime } : {}); }
    catch (e) { SESSION.rec = new MediaRecorder(SESSION.stream); }
    SESSION.rec.ondataavailable = function (e) { if (e.data && e.data.size) SESSION.chunks.push(e.data); };
    SESSION.rec.start();
    SESSION.utterStartedAt = Date.now();
    SESSION.silenceStart = 0; SESSION.onsetStart = 0;
    setState(STATE.USER_SPEAKING);
  }

  async function waitFor(fn, ms) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { const v = fn(); if (v) return v; await new Promise(function (r) { setTimeout(r, 80); }); }
    return null;
  }

  async function endUtterance(send) {
    const rec = SESSION.rec;
    if (!rec || rec.state === "inactive") { if (SESSION.active) setState(STATE.LISTENING); return; }
    setState(STATE.PROCESSING);          // synchronous, immediate - stops vadLoop re-entering this branch
    const myGen = SESSION.genId;
    await new Promise(function (resolve) { rec.onstop = resolve; rec.stop(); });
    if (!SESSION.active || myGen !== SESSION.genId) return;     // session ended or superseded mid-stop
    if (send === false) { setState(STATE.LISTENING); return; }
    const blob = new Blob(SESSION.chunks, { type: rec.mimeType || SESSION.mime });
    if (blob.size < 800) { setState(STATE.LISTENING); return; }  // too short to be real speech
    const ext = (blob.type || "").includes("mp4") ? "m4a" : (blob.type || "").includes("ogg") ? "ogg" : "webm";
    const file = new File([blob], "voice_" + Date.now() + "." + ext, { type: blob.type });
    const input = await waitFor(function () { return document.querySelector("#mic-upload input[type=file]"); }, 4000);
    if (!input || !SESSION.active || myGen !== SESSION.genId) return;
    const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    armTurnTimeout(myGen);
  }

  function clearTurnTimeout() {
    if (SESSION.turnTimer) { clearTimeout(SESSION.turnTimer); SESSION.turnTimer = null; }
  }
  // No reply arrived at all within this window (TTS failed, or nothing needed saying) - resume
  // listening anyway rather than waiting forever. Per-turn (myGen-gated) since a newer turn's
  // own timeout, or its reply arriving, should not be cancelled by an older turn's timer.
  function armTurnTimeout(myGen) {
    clearTurnTimeout();
    SESSION.turnTimer = setTimeout(function () {
      if (SESSION.active && myGen === SESSION.genId && SESSION.state === STATE.PROCESSING) setState(STATE.LISTENING);
    }, VAD.turnTimeoutMs);
  }

  // The LAST <audio> in the row, not the first: Gradio normally reuses a single element across
  // turns, but this stays correct even if more than one ever coexists in the DOM.
  function lastAudio(row) {
    const els = row ? row.querySelectorAll("audio") : [];
    return els.length ? els[els.length - 1] : null;
  }

  // ── watch for the reply: a fresh <audio> src means "an answer arrived" ──
  // Set up ONCE for the entire page lifetime (not per-utterance, and not even per-session) and
  // never torn down, so a reply that arrives late - after the user has already moved on to a new
  // utterance, a new turn, or has ended the conversation entirely - is still seen and still
  // judged. Whether it's allowed to speak depends only on the CURRENT state at the moment it
  // arrives: if we're still PROCESSING (still waiting on exactly this reply), it plays; in any
  // other state, it's stale and is suppressed immediately. This is what guarantees an interrupted
  // response can never resume even when its API calls finish late server-side (Gradio's
  // synchronous handler model doesn't give a clean way to abort the Groq/Gemini calls themselves
  // mid-flight, but their result is never shown or spoken once superseded) - anything short of a
  // permanent, never-disconnected watch leaves a window where a late reply plays unguarded.
  function startReplyWatcher() {
    if (SESSION.replyObserver) return;      // already watching - idempotent across sessions
    const row = document.getElementById("audio-row");
    if (!row) return;
    let lastSeenSrc = lastAudio(row) ? lastAudio(row).src : "";
    SESSION.replyObserver = new MutationObserver(function () {
      const a = lastAudio(row);
      // .src (not .currentSrc): .src resolves synchronously the instant it's assigned;
      // .currentSrc lags behind (resolved async by the browser's media pipeline), so comparing
      // it right when a mutation fires can still see the old value and miss the reply entirely.
      if (!a || !a.src || a.src === lastSeenSrc) return;
      lastSeenSrc = a.src;
      if (!SESSION.active || SESSION.state !== STATE.PROCESSING) {
        stopSpeaking();   // not currently expecting a reply - stale, never let it speak
        return;
      }
      clearTurnTimeout();
      // Undo any muted/autoplay-off left on this element by a PRIOR interruption - Gradio
      // reuses the same <audio> node across turns, so without this a genuinely new, valid
      // reply could inherit a previous turn's "never play" state and stay silent.
      a.muted = false; a.autoplay = true;
      a.play().catch(function () {});
      setState(STATE.ASSISTANT_SPEAKING);
      a.addEventListener("ended", function () {
        if (SESSION.active && SESSION.state === STATE.ASSISTANT_SPEAKING) setState(STATE.LISTENING);
      }, { once: true });
    });
    SESSION.replyObserver.observe(row, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
  }

  window.awaazMicTap = function () {
    if (SESSION.active) { endSession(); return; }
    startSession();
  };
})();
"""


# ── static chrome ────────────────────────────────────────────────────────────

def sidebar_header_html() -> str:
    return """
<div id="sidebar-header">
  <span class="logo">🗣️</span><span class="name">AWAAZ</span>
  <span class="spacer"></span>
  <button id="sidebar-close" onclick="awaazToggleSidebar()" title="Close">✕</button>
</div>"""


WIFI_SVG = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
           'stroke-width="2" stroke-linecap="round"><path d="M2 8.5a16 16 0 0 1 20 0"/>'
           '<path d="M5.5 12.5a11 11 0 0 1 13 0"/><path d="M9 16.5a6 6 0 0 1 6 0"/>'
           '<circle cx="12" cy="20" r="1.2" fill="currentColor" stroke="none"/></svg>')
GEAR_SVG = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
           'stroke-width="1.8"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.2M12 18.8V21M21 12h-2.2'
           'M5.2 12H3M18.4 5.6l-1.5 1.5M7.1 16.9l-1.5 1.5M18.4 18.4l-1.5-1.5M7.1 7.1 5.6 5.6"/></svg>')


def topbar_html() -> str:
    return f"""
<div id="topbar">
  <button id="menu-btn" onclick="awaazToggleSidebar()" title="Conversations">☰</button>
  <div class="brand">AWAAZ<small>BILINGUAL VOICE ASSISTANT · नेपाली / ENGLISH</small></div>
  <div class="spacer"></div>
  <div id="topbar-clock" class="mono">--:--:--<div class="date">···</div></div>
  <div class="hud-icon status" title="Online">{WIFI_SVG}</div>
  <div class="hud-icon gear" onclick="awaazToggleSidebar()" title="Settings &amp; conversations">{GEAR_SVG}</div>
</div>"""


def welcome_html(language: str = "en") -> str:
    if language == "ne":
        title, sub = "आवाज सहायक", "नमस्ते! रिमाइन्डर, काम, मौसम वा फुटबल बारे सोध्नुहोस् — बोलेर वा लेखेर।"
    else:
        title, sub = "Awaaz", "Hi! Ask about reminders, tasks, weather or football — by voice or by typing."
    return (f"<div style='text-align:center;opacity:.8;padding-top:6vh'>"
           f"<div style='font-size:2.2rem'>🗣️</div><div style='font-size:1.25rem;font-weight:700;margin-top:6px;"
           f"color:var(--accent);letter-spacing:.04em'>{html.escape(title)}</div>"
           f"<div style='font-size:.9rem;margin-top:4px;max-width:400px;margin-inline:auto;color:var(--muted)'>"
           f"{html.escape(sub)}</div></div>")


def rec_indicator_html() -> str:
    # Shown only while actively capturing an utterance (state USER_SPEAKING); the calmer
    # "Listening…"/"Speaking…" states are conveyed by #mic-status instead, not this pulse.
    bars = "".join("<i></i>" for _ in range(5))
    return f'<div id="rec-indicator"><span class="dot"></span><span>Hearing you…</span><span class="bars">{bars}</span></div>'


def reticle_html() -> str:
    """Decorative radar/targeting reticle, echoing the reference image — purely visual."""
    return """
<div class="reticle"><svg viewBox="0 0 100 100">
  <g class="spin">
    <circle cx="50" cy="50" r="44" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="2 6" opacity=".6"/>
  </g>
  <circle cx="50" cy="50" r="32" fill="none" stroke="currentColor" stroke-width="1" opacity=".4"/>
  <circle cx="50" cy="50" r="20" fill="none" stroke="currentColor" stroke-width="1" opacity=".5"/>
  <line x1="50" y1="4" x2="50" y2="20" stroke="currentColor" stroke-width="1" opacity=".5"/>
  <line x1="50" y1="80" x2="50" y2="96" stroke="currentColor" stroke-width="1" opacity=".5"/>
  <line x1="4" y1="50" x2="20" y2="50" stroke="currentColor" stroke-width="1" opacity=".5"/>
  <line x1="80" y1="50" x2="96" y2="50" stroke="currentColor" stroke-width="1" opacity=".5"/>
  <circle cx="50" cy="50" r="3" fill="currentColor"/>
</svg></div>"""


# ── dashboard widgets (pure HTML builders — app.py supplies the data) ───────

def panel(title: str, body_html: str, count: int | str | None = None) -> str:
    n = f'<span class="n">{count}</span>' if count is not None else ""
    return f'<div class="hud-panel"><div class="hp-title"><span>{html.escape(title)}</span>{n}</div>{body_html}</div>'


def list_items(rows: list[tuple[str, str, str]], empty: str) -> str:
    """rows = [(title, subtitle, css_class)]; css_class is '', 'due' or 'done'."""
    if not rows:
        return f'<ul class="hud-list"><li class="empty">{html.escape(empty)}</li></ul>'
    lis = "".join(f'<li class="{cls}">{html.escape(title)}<small>{html.escape(sub)}</small></li>'
                 for title, sub, cls in rows)
    return f'<ul class="hud-list">{lis}</ul>'


def task_table(rows: list[tuple[str, str, str]], empty: str) -> str:
    """rows = [(title, due_label, css_class)]; css_class is '', 'due' (today/overdue) or 'done'."""
    if not rows:
        return f'<div class="hud-table-wrap"><p class="hud-table-empty">{html.escape(empty)}</p></div>'
    body = "".join(f'<tr class="{cls}"><td>{html.escape(title)}</td><td>{html.escape(due)}</td></tr>'
                  for title, due, cls in rows)
    return (f'<div class="hud-table-wrap"><table class="hud-table">'
           f'<thead><tr><th>Task</th><th>Due</th></tr></thead><tbody>{body}</tbody></table></div>')


def _ring(percent: float, r: float) -> tuple[float, float]:
    """Shared math for an SVG ring gauge: (circumference, dash-offset) for `percent` (0-100) filled."""
    percent = max(0.0, min(100.0, percent))
    circumference = 2 * math.pi * r
    return circumference, circumference * (1 - percent / 100)


def progress_ring(label: str, percent: int) -> str:
    r = 26
    circumference, offset = _ring(percent, r)
    return f"""
<div class="hud-ring-row">
  <svg class="hud-ring" viewBox="0 0 64 64" width="52" height="52">
    <circle cx="32" cy="32" r="{r}" fill="none" stroke="var(--border)" stroke-width="5"/>
    <circle cx="32" cy="32" r="{r}" fill="none" stroke="var(--accent)" stroke-width="5" stroke-linecap="round"
            stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{offset:.1f}" transform="rotate(-90 32 32)"/>
    <text x="32" y="37" text-anchor="middle" class="hud-ring-text">{percent}%</text>
  </svg>
  <span class="hud-ring-label">{html.escape(label)}</span>
</div>"""


def weather_gauge(temp: str, condition: str, place: str, icon: str = "🌤️") -> str:
    """A circular dial mapping temp onto a -10..40°C range (clamped); '--'/non-numeric temp -> empty ring."""
    try:
        percent = (float(temp) + 10) / 50 * 100
    except ValueError:
        percent = 0.0
    r = 42
    circumference, offset = _ring(percent, r)
    return f"""
<div class="weather-gauge">
  <div class="wg-ring-wrap">
    <svg viewBox="0 0 100 100" class="wg-ring">
      <circle cx="50" cy="50" r="{r}" fill="none" stroke="var(--border)" stroke-width="6"/>
      <circle cx="50" cy="50" r="{r}" fill="none" stroke="var(--accent)" stroke-width="6" stroke-linecap="round"
              stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{offset:.1f}" transform="rotate(-90 50 50)"/>
    </svg>
    <div class="wg-center"><span class="wg-icon">{icon}</span><span class="wg-temp">{html.escape(temp)}<small>°C</small></span></div>
  </div>
  <div class="wg-place">{html.escape(place)}</div>
  <div class="wg-cond">{html.escape(condition)}</div>
</div>"""
