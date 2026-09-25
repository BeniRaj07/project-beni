"""A dark HUD console look — cyan-on-navy, Orbitron/Inter/JetBrains Mono — plus the small amount
of client-side JavaScript the UI genuinely needs. Most notably a continuous voice-session state
machine (LISTENING/USER_SPEAKING/PROCESSING/ASSISTANT_SPEAKING) driven by a persistent, always-on
VAD loop, so talking over Awaaz while it's speaking interrupts it instantly with no button press —
plus a live clock, a live uptime ticker, a dark/light toggle, and an off-canvas conversation
drawer. Sending, replying, playing audio and the conversation list are plain Gradio, driven from
Python in app.py; this module only builds the look and the dashboard cards (system stats,
weather, tasks, reminders, uptime) from data app.py hands it.
"""
from __future__ import annotations

import html
import math

import gradio as gr

# ── theme ────────────────────────────────────────────────────────────────────

BG = "#060b16"
SURFACE = "#0c1729"
SIDEBAR = "#080f1e"
BORDER = "rgba(94,195,255,.16)"
TEXT = "#e9f1fb"
MUTED = "#7f92ab"
ACCENT = "#4fd1ff"
ACCENT2 = "#4b8bff"
WARN = "#f5c451"


def _both(**values: str) -> dict[str, str]:
    import inspect
    accepted = set(inspect.signature(gr.themes.Base.set).parameters)
    out = dict(values)
    out.update({f"{k}_dark": v for k, v in values.items() if f"{k}_dark" in accepted})
    return out


THEME = gr.themes.Base(
    primary_hue="blue", neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
).set(**_both(
    body_background_fill=BG, body_text_color=TEXT, body_text_color_subdued=MUTED,
    background_fill_primary=SURFACE, background_fill_secondary=SIDEBAR,
    block_background_fill=SURFACE, block_border_color=BORDER, block_border_width="1px",
    block_radius="10px", block_label_text_color=MUTED, block_title_text_color=ACCENT,
    panel_background_fill=SIDEBAR, panel_border_color=BORDER,
    border_color_primary=BORDER, border_color_accent=ACCENT, color_accent=ACCENT,
    input_background_fill="rgba(255,255,255,.03)", input_border_color=BORDER, input_border_color_focus=ACCENT,
    input_placeholder_color=MUTED,
    button_primary_background_fill=f"linear-gradient(140deg,{ACCENT2},{ACCENT})",
    button_primary_background_fill_hover=ACCENT,
    button_primary_text_color="#06131f", button_primary_border_color=ACCENT,
    button_secondary_background_fill="rgba(255,255,255,.03)",
    button_secondary_background_fill_hover="rgba(79,209,255,.14)",
    button_secondary_text_color=TEXT, button_secondary_border_color=BORDER,
    button_cancel_background_fill="rgba(239,68,68,.12)", button_cancel_text_color="#fca5a5",
    link_text_color=ACCENT, code_background_fill="rgba(255,255,255,.03)",
))


# ── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
:root[data-theme="light"] {
  --bg:#eef3fb; --panel:#ffffff; --panel-2:#f4f8ff; --border:rgba(30,80,160,.14);
  --border-strong:rgba(30,80,160,.28); --text:#0b1830; --muted:#5c6b85; --faint:#8a97ad;
  --accent:#0d7fc4; --accent-2:#2f6fed; --accent-soft:rgba(13,127,196,.08);
  --good:#0ea968; --good-soft:rgba(14,169,104,.10); --warn:#c07a12; --warn-soft:rgba(192,122,18,.12);
}
:root, :root[data-theme="dark"] {
  --bg:#060b16; --panel:#0c1729; --panel-2:#0f1d33; --border:rgba(94,195,255,.14);
  --border-strong:rgba(94,195,255,.28); --text:#e9f1fb; --muted:#7f92ab; --faint:#566378;
  --accent:#4fd1ff; --accent-2:#4b8bff; --accent-soft:rgba(79,209,255,.10);
  --good:#34d399; --good-soft:rgba(52,211,153,.12); --warn:#f5c451; --warn-soft:rgba(245,196,81,.12);
}
body, gradio-app { background: var(--bg) !important; }
/* Gradio's own theme bakes a fixed text color onto inline leaf elements (span/strong/svg/small)
   inside the .prose wrapper it puts around every gr.HTML component's content, which silently
   breaks normal CSS color inheritance from the parent this file styles per-theme (a dark-mode
   value baked once at launch, invisible against a light background after the toggle). Forcing
   inheritance here restores the cascade so these elements pick up whatever color their actual
   parent has - which the rules below still control precisely via their own !important colors. */
.prose span, .prose strong, .prose small, .prose svg,
.prose svg path, .prose svg rect, .prose svg circle, .prose svg line { color: inherit !important; }
.gradio-container { max-width: 100% !important; padding: 0 !important; margin: 0 !important;
  font-family: 'Inter', ui-sans-serif, sans-serif !important; height: 100vh; position: relative; }
footer { display: none !important; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: rgba(94,195,255,.18); border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: rgba(94,195,255,.32); }
::-webkit-scrollbar-track { background: transparent; }

.mono { font-family: 'JetBrains Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.display { font-family: 'Orbitron', 'Inter', sans-serif; }

#app-root { height: 100vh; display: flex; flex-direction: column; position: relative; overflow: hidden; }
#app-root::before {
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background:
    radial-gradient(1100px 480px at 18% -10%, rgba(75,139,255,.10), transparent 60%),
    radial-gradient(900px 460px at 85% 0%, rgba(79,209,255,.08), transparent 55%),
    repeating-linear-gradient(0deg, rgba(94,195,255,.025) 0 1px, transparent 1px 42px),
    repeating-linear-gradient(90deg, rgba(94,195,255,.025) 0 1px, transparent 1px 42px);
}
h1, h2, h3, h4 { font-family: 'Inter', sans-serif !important; }

/* ── top bar ──────────────────────────────────────────── */
#topbar { position: relative; z-index: 3; display: flex; align-items: center; gap: 14px;
  padding: 10px 18px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, var(--panel-2), var(--panel)) !important; flex-wrap: wrap; }
#menu-btn { background: rgba(79,139,255,.08) !important; border: 1px solid var(--border) !important;
  color: var(--accent) !important; min-width: 38px; height: 38px; border-radius: 10px !important; }
#menu-btn svg { width: 18px !important; height: 18px !important; flex: none; }
#topbar .brand-wrap { display: flex; align-items: center; gap: 10px; }
#topbar .brand { font-weight: 800; font-size: 1.05rem; letter-spacing: .28em;
  background-image: linear-gradient(120deg, var(--accent), var(--accent-2)) !important;
  -webkit-background-clip: text !important; background-clip: text !important;
  -webkit-text-fill-color: transparent !important; color: transparent !important; }
#topbar .status-tag { display: flex; align-items: center; gap: 6px; font-size: .72rem; font-weight: 600;
  color: var(--good) !important; background: var(--good-soft); border: 1px solid rgba(52,211,153,.28);
  padding: 3px 9px 3px 7px; border-radius: 999px; white-space: nowrap; }
#topbar .status-tag .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  animation: pulse-dot 2s ease-out infinite; }
@keyframes pulse-dot { 0% { box-shadow: 0 0 0 0 rgba(52,211,153,.55) } 70% { box-shadow: 0 0 0 6px rgba(52,211,153,0) }
  100% { box-shadow: 0 0 0 0 rgba(52,211,153,0) } }
#topbar .spacer { flex: 1; }
#topbar-clock { display: flex; align-items: center; gap: 9px; font-size: .86rem; color: var(--muted) !important; }
#topbar-clock svg { width: 16px !important; height: 16px !important; flex: none; }
#topbar-clock .time { font-size: .92rem; color: var(--text) !important; }
#topbar-clock .divider { width: 1px; height: 14px; background: var(--border-strong); }
.weather-chip { display: flex; align-items: center; gap: 7px; font-size: .82rem; color: var(--muted) !important;
  padding: 5px 11px; border-radius: 999px; background: rgba(79,139,255,.06); border: 1px solid var(--border); }
.weather-chip strong { color: var(--text) !important; font-weight: 600; }
.weather-chip .city { color: var(--accent) !important; }
.hud-icon { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center;
  background: rgba(79,139,255,.07); border: 1px solid var(--border); flex: none; color: var(--muted) !important;
  cursor: pointer; transition: .15s ease; }
.hud-icon:hover { color: var(--accent) !important; border-color: var(--border-strong) !important; background: var(--accent-soft); }
.hud-icon svg { width: 17px; height: 17px; }

/* ── dashboard grid: left cards | center orb | right conversation ───────── */
#dashboard { position: relative; z-index: 1; flex: 1 1 auto; min-height: 0; display: grid;
  grid-template-columns: 288px minmax(360px, 1fr) 372px; gap: 16px; padding: 16px 18px;
  grid-auto-rows: 100%; }
/* CSS Grid's auto-row sizing doesn't reliably measure a flex-wrap child's true content height
   (the #left-rail column of cards), so narrow screens drop the grid entirely for a plain
   vertical flex stack instead - simpler and predictable rather than fighting that sizing quirk.
   flex:none on the three sections is required here too: Gradio's own Column CSS defaults every
   gr.Column to flex:1 1 0%, which - once #dashboard itself becomes a flex container - divides
   its height evenly across all three regardless of their actual content, instead of sizing each
   to fit; the overflow then spills silently onto the next section instead of pushing it down. */
@media (max-width: 1180px) { #dashboard { display: flex; flex-direction: column; flex-wrap: nowrap;
  overflow-y: auto; height: 100%; }
  #left-rail, #center-screen, #right-rail { flex: none; } }

/* Grid rows default to auto-sizing around their tallest item's natural content height, which
   would let the cards stack here grow the whole row (and leak past #app-root's clip) instead of
   scrolling internally - grid-auto-rows:100% above plus height:100% here keeps this column
   clipped to the row it was actually given, so overflow-y:auto has a real overflow to scroll. */
/* flex-wrap:nowrap is explicit, not the default, because Gradio's own Column CSS sets
   flex-wrap:wrap on every gr.Column by default - without this override the 5th card wraps into
   a second, horizontally-offset column instead of stacking, invisibly overlapping center-screen. */
#left-rail { display: flex; flex-direction: column; flex-wrap: nowrap; gap: 14px; height: 100%;
  min-height: 0; overflow-y: auto; padding-right: 2px; }
@media (max-width: 1180px) { #left-rail { flex-direction: column; flex-wrap: nowrap; height: auto; overflow: visible; } }
@media (max-width: 1180px) { #center-screen, #right-rail { height: auto; min-height: 480px; } }

.card { background: linear-gradient(180deg, var(--panel-2), var(--panel)); border: 1px solid var(--border);
  border-radius: 14px; padding: 14px 15px 14px; box-shadow: 0 14px 34px -20px rgba(0,0,0,.6); flex: none; }
.card.clickable { cursor: pointer; transition: border-color .15s ease, transform .15s ease; }
.card.clickable:hover { border-color: var(--border-strong); transform: translateY(-1px); }
.card.clickable:active { transform: translateY(0); }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 11px; }
.card-title { display: flex; align-items: center; gap: 8px; font-size: .82rem; font-weight: 700;
  color: var(--text) !important; letter-spacing: .02em; }
.card-title svg { width: 15px; height: 15px; color: var(--accent) !important; flex: none; }
.count-pill { font-size: .68rem; font-weight: 600; color: var(--muted) !important; background: rgba(255,255,255,.03);
  border: 1px solid var(--border); padding: 2px 8px; border-radius: 999px; white-space: nowrap;
  font-family: 'JetBrains Mono', monospace; }

.stat-row { margin-bottom: 10px; }
.stat-row-top { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 5px; }
.stat-label { font-size: .74rem; color: var(--muted) !important; }
.stat-value { font-size: .76rem; color: var(--text) !important; font-weight: 600; font-family: 'JetBrains Mono', monospace; }
.bar-track { height: 6px; border-radius: 999px; background: rgba(255,255,255,.05); overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent-2), var(--accent)); }
.bar-fill.warn { background: linear-gradient(90deg, #c98f2b, var(--warn)); }
.tile-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: 4px; }
.tile { background: rgba(255,255,255,.02); border: 1px solid var(--border); border-radius: 9px;
  padding: 7px 5px; text-align: center; }
.tile-label { font-size: .62rem; color: var(--faint) !important; margin-bottom: 3px; }
.tile-value { font-size: .78rem; font-weight: 700; color: var(--text) !important; font-family: 'JetBrains Mono', monospace; }

.weather-hero { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.weather-temp { font-size: 1.7rem; font-weight: 700; line-height: 1; font-family: 'JetBrains Mono', monospace; }
.weather-place { font-size: .8rem; color: var(--text) !important; font-weight: 600; margin-top: 7px; }
.weather-cond { font-size: .72rem; color: var(--faint) !important; margin-top: 2px; text-transform: capitalize; }
.weather-icon { width: 32px; height: 32px; color: var(--accent) !important; opacity: .9; flex: none; }
.weather-icon svg { width: 100%; height: 100%; }

.list { display: flex; flex-direction: column; gap: 7px; }
.list-empty { font-size: .78rem; color: var(--faint) !important; font-style: italic; padding: 6px 2px; }

.task-item { display: flex; align-items: center; gap: 9px; padding: 7px 8px; border-radius: 9px;
  background: rgba(255,255,255,.02); border: 1px solid transparent; }
.task-check { width: 16px; height: 16px; border-radius: 5px; flex: none; border: 1.5px solid var(--faint);
  display: flex; align-items: center; justify-content: center; color: transparent; }
.task-check svg { width: 10px; height: 10px; }
.task-item.done .task-check { background: var(--good); border-color: var(--good) !important; color: #06251a !important; }
.task-text { flex: 1; font-size: .78rem; color: var(--text) !important; font-weight: 500; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-item.done .task-text { color: var(--faint) !important; text-decoration: line-through; }
.task-tag { font-size: .62rem; font-weight: 600; padding: 2px 7px; border-radius: 999px; white-space: nowrap; flex: none; }
.task-tag.due-today, .task-tag.overdue { color: var(--warn) !important; background: var(--warn-soft); }
.task-tag.due-later { color: var(--muted) !important; background: rgba(255,255,255,.04); }
.task-tag.done-tag { color: var(--good) !important; background: var(--good-soft); }
.progress-line { display: flex; align-items: center; gap: 9px; margin-top: 11px; }
.progress-line .bar-track { flex: 1; }
.progress-line span { font-size: .68rem; color: var(--faint) !important; white-space: nowrap; font-family: 'JetBrains Mono', monospace; }

.reminder-item { display: flex; align-items: center; gap: 10px; padding: 7px 8px; border-radius: 9px;
  background: rgba(255,255,255,.02); }
.reminder-time { flex: none; text-align: center; min-width: 50px; font-size: .66rem; font-weight: 700;
  color: var(--accent) !important; background: var(--accent-soft); border: 1px solid var(--border); border-radius: 8px;
  padding: 4px 5px; line-height: 1.2; font-family: 'JetBrains Mono', monospace; }
.reminder-time .day { display: block; font-size: .58rem; color: var(--muted) !important; font-weight: 600; margin-top: 1px;
  font-family: 'Inter', sans-serif; }
.reminder-body { flex: 1; min-width: 0; }
.reminder-title { font-size: .78rem; color: var(--text) !important; font-weight: 500; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.reminder-meta { font-size: .64rem; color: var(--faint) !important; margin-top: 1px; }
.reminder-item.due .reminder-time { color: var(--warn) !important; background: var(--warn-soft); }

.uptime-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0 10px;
  border-bottom: 1px solid var(--border); margin-bottom: 10px; }
.uptime-row .stat-label { margin: 0; }
.uptime-value { font-size: .78rem; color: var(--text) !important; font-family: 'JetBrains Mono', monospace; }

/* ── center: voice orb ───────────────────────────────────── */
#center-screen { position: relative; z-index: 1; display: flex; flex-direction: column; flex-wrap: nowrap;
  align-items: center; justify-content: center; gap: 22px; height: 100%; min-height: 0; padding: 10px; }
.orb-wrap { position: relative; width: 240px; height: 240px; display: flex; align-items: center; justify-content: center; }
.orb-ring { position: absolute; border-radius: 50%; border: 1px solid var(--border-strong); }
.ring-1 { inset: 0; animation: orb-spin 26s linear infinite; border-style: dashed; opacity: .5; }
.ring-2 { inset: 22px; animation: orb-spin 18s linear infinite reverse; opacity: .38; }
@keyframes orb-spin { to { transform: rotate(360deg); } }
.orb-core { width: 138px; height: 138px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at 35% 30%, rgba(79,209,255,.30), rgba(11,20,38,.92) 68%);
  border: 1px solid var(--border-strong); box-shadow: 0 0 50px -6px rgba(79,209,255,.3), inset 0 0 34px rgba(79,209,255,.1);
  transition: box-shadow .3s ease; }
.orb-wrap.st-listening .orb-core, .orb-wrap.st-processing .orb-core, .orb-wrap.st-assistant_speaking .orb-core {
  animation: orb-breathe 3.4s ease-in-out infinite; }
@keyframes orb-breathe { 0%,100% { box-shadow: 0 0 50px -6px rgba(79,209,255,.3), inset 0 0 34px rgba(79,209,255,.1); }
  50% { box-shadow: 0 0 66px -4px rgba(79,209,255,.48), inset 0 0 42px rgba(79,209,255,.18); } }
.orb-wrap.st-user_speaking .orb-core { border-color: rgba(239,68,68,.5);
  box-shadow: 0 0 54px -4px rgba(239,68,68,.4), inset 0 0 34px rgba(239,68,68,.14); }
.wave-bars { display: flex; align-items: center; gap: 4px; height: 26px; }
.wave-bars i { width: 3px; border-radius: 3px; background: var(--accent); display: block; height: 6px;
  transition: height .09s ease; }
.orb-wrap.st-user_speaking .wave-bars i { background: #f2596b; }
.orb-wrap.st-listening .wave-bars i, .orb-wrap.st-processing .wave-bars i, .orb-wrap.st-assistant_speaking .wave-bars i {
  animation: wave-idle 1.15s ease-in-out infinite; }
.wave-bars i:nth-child(1) { animation-delay: -.9s; } .wave-bars i:nth-child(2) { animation-delay: -.6s; }
.wave-bars i:nth-child(3) { animation-delay: -.3s; } .wave-bars i:nth-child(4) { animation-delay: -.75s; }
.wave-bars i:nth-child(5) { animation-delay: -.15s; }
@keyframes wave-idle { 0%,100% { height: 6px; opacity: .5; } 50% { height: 22px; opacity: 1; } }

.brand-title { font-family: 'Orbitron', sans-serif; font-weight: 800; font-size: 1.5rem; letter-spacing: .4em;
  margin: 0; padding-left: .4em; color: var(--text) !important; }
.status-pill { display: flex; align-items: center; gap: 8px; font-size: .8rem; font-weight: 600;
  color: var(--muted) !important; background: rgba(255,255,255,.03); border: 1px solid var(--border);
  padding: 6px 15px; border-radius: 999px; transition: .2s ease; }
.status-pill .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); flex: none; }
.status-pill.live { color: var(--good) !important; background: var(--good-soft); border-color: rgba(52,211,153,.28); }
.status-pill.live .dot { background: var(--good); animation: pulse-dot 2s ease-out infinite; }
.status-pill.hearing { color: #f2596b !important; background: rgba(242,89,107,.12); border-color: rgba(242,89,107,.3); }
.status-pill.hearing .dot { background: #f2596b; }

.dock { display: flex; align-items: center; gap: 16px; }
.dock-btn { width: 50px; height: 50px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(180deg, var(--panel-2), var(--panel)); border: 1px solid var(--border);
  color: var(--muted) !important; cursor: pointer; transition: .18s ease; }
.dock-btn:hover { color: var(--accent) !important; border-color: var(--border-strong) !important; transform: translateY(-2px); }
.dock-btn svg { width: 20px; height: 20px; }
.dock-btn--mic { width: 62px; height: 62px; background: linear-gradient(140deg, var(--accent-2), var(--accent));
  color: #06131f !important; border: none; box-shadow: 0 10px 26px -8px rgba(79,209,255,.55); position: relative; }
.dock-btn--mic:hover { color: #06131f !important; transform: translateY(-2px) scale(1.03); }
.dock-btn--mic.conv-on { box-shadow: 0 0 0 4px rgba(79,209,255,.22), 0 10px 26px -8px rgba(79,209,255,.6); }
.dock-btn--mic.recording { background: linear-gradient(140deg, #f2596b, #ff8a5c);
  box-shadow: 0 0 0 4px rgba(242,89,107,.22), 0 10px 26px -8px rgba(242,89,107,.6); }
.dock-btn--mic.speaking { animation: mic-speak-pulse 1.8s ease-in-out infinite; }
@keyframes mic-speak-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(79,209,255,.4) } 50% { box-shadow: 0 0 0 8px rgba(79,209,255,0) } }
#end-conv-btn { min-width: 68px; height: 26px; border-radius: 13px; white-space: nowrap;
  background: rgba(242,89,107,.1); border: 1px solid rgba(242,89,107,.4); color: #f2596b !important; font-size: .7rem;
  padding: 0 10px; cursor: pointer; font-family: 'JetBrains Mono', monospace; display: none; }
#end-conv-btn:hover { background: rgba(242,89,107,.2); }

#mic-upload { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important;
  overflow: hidden !important; }
#audio-row { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important;
  overflow: hidden !important; }

/* ── right: conversation panel ───────────────────────────── */
#right-rail { display: flex; flex-direction: column; flex-wrap: nowrap; height: 100%; min-height: 0;
  background: linear-gradient(180deg, var(--panel-2), var(--panel));
  border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
#convo-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 13px 15px;
  border-bottom: 1px solid var(--border); flex-wrap: wrap; }
#convo-head h2 { margin: 0; font-size: .92rem; font-weight: 700; color: var(--text) !important; }
#convo-actions { display: flex; gap: 7px; flex: none; }
.chip-btn { display: flex !important; align-items: center; gap: 5px !important; font-size: .72rem !important;
  font-weight: 600 !important; color: var(--muted) !important; background: rgba(255,255,255,.03) !important;
  border: 1px solid var(--border) !important; padding: 5px 10px !important; border-radius: 8px !important;
  min-width: 0 !important; height: auto !important; box-shadow: none !important; }
.chip-btn:hover { border-color: var(--border-strong) !important; color: var(--text) !important; }
#extract-btn { color: var(--accent) !important; border-color: rgba(79,209,255,.3) !important;
  background: var(--accent-soft) !important; }

#chatbot { flex: 1 1 auto; min-height: 0; border: none !important; background: transparent !important; }
#chatbot .message-wrap { padding: 4px 15px !important; }
#chatbot .message.user { background: linear-gradient(140deg, var(--accent-2), var(--accent)) !important;
  border: none !important; border-radius: 13px 13px 3px 13px !important; color: #06131f !important;
  font-weight: 500 !important; }
#chatbot .message.bot { background: rgba(79,139,255,.07) !important; border: 1px solid var(--border) !important;
  border-radius: 13px 13px 13px 3px !important; color: var(--text) !important; }
#chatbot table { display: block; overflow-x: auto; white-space: nowrap; max-width: 100%; }
#chatbot table td, #chatbot table th { white-space: nowrap; border-color: var(--border) !important; }

#status-line { padding: 0 15px; min-height: 16px; font-size: .74rem; color: var(--accent) !important;
  font-family: 'JetBrains Mono', monospace; flex: none; }
#status-line:not(:empty) { animation: pulse-text 1.3s ease-in-out infinite; }
/* While a voice session is running, the orb's own status pill is the single status readout for
   that turn - suppress this text line so the two never show duplicate or conflicting text. Typed
   (non-voice) turns have no voice session active, so this line still carries their status. */
#app-root.voice-session-on #status-line { display: none; }
@keyframes pulse-text { 0%,100% { opacity: .45 } 50% { opacity: 1 } }

#composer-wrap { flex: none; padding: 10px 14px 14px; border-top: 1px solid var(--border); }
#composer { display: flex; align-items: center; gap: 9px; }
#composer-input textarea, #composer-input input { border: 1px solid var(--border) !important;
  background: rgba(255,255,255,.03) !important; border-radius: 10px !important; box-shadow: none !important;
  font-size: .86rem !important; padding: 9px 12px !important; color: var(--text) !important; }
#composer-input textarea:focus, #composer-input input:focus { border-color: var(--border-strong) !important; }
#send-btn { min-width: 38px !important; width: 38px; height: 38px; border-radius: 10px !important;
  padding: 0 !important; font-size: 1rem !important; flex: none;
  background: linear-gradient(140deg, var(--accent-2), var(--accent)) !important; border: none !important;
  color: #06131f !important; box-shadow: 0 8px 20px -8px rgba(79,209,255,.55); }

/* ── sidebar drawer (off-canvas conversation history) ────── */
#sidebar { position: fixed; z-index: 50; left: 0; top: 0; bottom: 0; width: 300px; max-width: 82vw;
  background: var(--panel) !important; border-right: 1px solid var(--border);
  display: flex; flex-direction: column; flex-wrap: nowrap; padding: 10px !important; gap: 8px;
  transform: translateX(-100%); transition: transform .22s ease; box-shadow: 10px 0 30px rgba(0,0,0,.5); }
#app-root.sidebar-open #sidebar { transform: translateX(0); }
#app-root.sidebar-open #scrim { opacity: 1; pointer-events: auto; }
#scrim { position: fixed; inset: 0; z-index: 45; background: rgba(3,7,15,.6); opacity: 0; pointer-events: none;
  transition: opacity .2s ease; }
#sidebar-header { display: flex; align-items: center; gap: 8px; padding: 6px 6px 2px; }
#sidebar-header .logo { font-size: 1.1rem; }
#sidebar-header .name { font-weight: 800; font-size: .92rem; color: var(--accent) !important; letter-spacing: .16em; }
#sidebar-header .spacer { flex: 1; }
#sidebar-close { background: transparent !important; border: 1px solid var(--border) !important;
  color: var(--muted) !important; width: 26px; height: 26px; border-radius: 6px !important; cursor: pointer; font-size: .8rem; }
#sidebar-close:hover { color: var(--text) !important; background: var(--accent-soft) !important; }
#new-chat-btn { border: 1px solid var(--border) !important; background: rgba(79,139,255,.06) !important;
  color: var(--text) !important; justify-content: flex-start !important; font-weight: 600 !important;
  border-radius: 8px !important; }
#new-chat-btn:hover { background: var(--accent-soft) !important; }
#search-box textarea, #search-box input { border-radius: 8px !important; font-size: .86rem !important; }
#sidebar-scroll { flex: 1 1 auto; overflow-y: auto; min-height: 0; padding-right: 2px; }
.conv-group-label { font-size: .64rem; font-weight: 700; letter-spacing: .1em; color: var(--faint) !important;
  text-transform: uppercase; margin: 12px 8px 4px; }
.conv-row { display: flex; align-items: center; gap: 2px; border-radius: 6px; }
.conv-row:hover, .conv-row.active { background: var(--accent-soft); }
.conv-title-btn { flex: 1; text-align: left !important; background: transparent !important; border: none !important;
  color: var(--text) !important; font-size: .84rem !important; font-weight: 400 !important; padding: 8px 6px !important;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; min-width: 0; box-shadow: none !important; }
.conv-row.active .conv-title-btn { color: var(--accent) !important; font-weight: 600 !important; }
.conv-icon-btn { min-width: 26px !important; width: 26px !important; height: 26px !important; padding: 0 !important;
  background: transparent !important; border: none !important; color: var(--faint) !important; font-size: .8rem !important;
  border-radius: 6px !important; opacity: 0; transition: opacity .12s; }
.conv-row:hover .conv-icon-btn { opacity: 1; }
.conv-icon-btn:hover { background: var(--accent-soft) !important; color: var(--text) !important; }
#rename-bar { padding: 4px 2px 8px; }
#sidebar-footer { border-top: 1px solid var(--border); padding-top: 8px; display: flex; align-items: center;
  justify-content: space-between; gap: 6px; flex-wrap: wrap; }
#sidebar-footer label { font-size: .78rem !important; color: var(--muted) !important; }
#theme-toggle { min-width: 32px !important; width: 32px; height: 32px; border-radius: 50% !important;
  padding: 0 !important; background: transparent !important; border: 1px solid var(--border) !important; }

/* ── card detail modals (Weather / Tasks / Reminders) ────── */
#modal-backdrop { position: fixed; inset: 0; z-index: 90; background: rgba(3,7,15,.65);
  opacity: 0; pointer-events: none; transition: opacity .18s ease; backdrop-filter: blur(2px); }
#app-root.modal-open #modal-backdrop { opacity: 1; pointer-events: auto; }
#modal-panel { position: fixed; z-index: 91; top: 50%; left: 50%; width: min(560px, 92vw); max-height: 82vh;
  background: linear-gradient(180deg, var(--panel-2), var(--panel)) !important;
  border: 1px solid var(--border-strong) !important; border-radius: 16px !important;
  box-shadow: 0 30px 70px -20px rgba(0,0,0,.6); display: flex !important; flex-direction: column !important;
  flex-wrap: nowrap !important; opacity: 0; pointer-events: none; overflow: hidden;
  transform: translate(-50%, -46%); transition: opacity .18s ease, transform .18s ease; }
#app-root.modal-open #modal-panel { opacity: 1; pointer-events: auto; transform: translate(-50%, -50%); }
.modal-close { position: absolute; top: 14px; right: 14px; z-index: 2; width: 30px; height: 30px;
  border-radius: 8px; border: 1px solid var(--border); background: rgba(255,255,255,.04); color: var(--muted);
  cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: .85rem; }
.modal-close:hover { color: var(--text); border-color: var(--border-strong); background: var(--accent-soft); }
/* #modal-body is itself a flex item of #modal-panel, and each .modal-section (when shown) is in
   turn a flex item of #modal-body - both need flex:none/flex:1 1 auto set explicitly, because
   Gradio's own Column/HTML component CSS defaults every one of these to flex:1 1 0%, which
   collapses an item with no explicit height to zero and hides its content behind the resulting
   empty box (the same failure mode already fixed for #left-rail and friends, recurring here). */
#modal-body { display: flex !important; flex-direction: column !important; flex-wrap: nowrap !important;
  flex: 1 1 auto !important; min-height: 0; overflow-y: auto; padding: 20px; }
/* Gradio applies elem_classes to BOTH the outer .block wrapper and the inner .prose div it
   renders gr.HTML content into, but elem_id only to the outer one - so the "show" rule has to
   match the inner .prose.modal-section div too (by descendant selector off the outer id), or
   the actual content stays display:none forever regardless of which modal is toggled open. */
.modal-section { display: none; }
#app-root.modal-weather #modal-weather-content,
#app-root.modal-weather #modal-weather-content .modal-section,
#app-root.modal-tasks #modal-tasks-content,
#app-root.modal-tasks #modal-tasks-content .modal-section,
#app-root.modal-reminders #modal-reminders-content,
#app-root.modal-reminders #modal-reminders-content .modal-section { display: block !important; flex: none !important; }
.modal-section h3 { margin: 0 0 14px; font-size: 1rem; font-weight: 700; color: var(--text) !important;
  display: flex; align-items: center; gap: 9px; padding-right: 34px; }
.modal-section h3 svg { width: 17px; height: 17px; color: var(--accent) !important; flex: none; }
.modal-section .card-head, .modal-section .weather-hero { margin-bottom: 14px; }

.forecast-list { margin-top: 16px; border-top: 1px solid var(--border); }
.forecast-row { display: flex; align-items: center; gap: 12px; padding: 10px 2px; border-bottom: 1px solid var(--border); }
.forecast-day { width: 78px; flex: none; font-size: .82rem; font-weight: 600; color: var(--text) !important; }
.forecast-icon { width: 20px; height: 20px; color: var(--accent) !important; flex: none; }
.forecast-icon svg { width: 100%; height: 100%; }
.forecast-cond { flex: 1; min-width: 0; font-size: .76rem; color: var(--muted) !important; text-transform: capitalize; }
.forecast-temps { flex: none; font-size: .82rem; font-family: 'JetBrains Mono', monospace; }
.forecast-temps .hi { color: var(--text) !important; font-weight: 700; }
.forecast-temps .lo { color: var(--faint) !important; margin-left: 5px; }
.forecast-rain { flex: none; width: 46px; text-align: right; font-size: .7rem; color: var(--accent) !important;
  font-family: 'JetBrains Mono', monospace; }

@media (max-width: 640px) {
  #dashboard { padding: 10px; gap: 10px; }
  #topbar .brand small { display: none; }
  .brand-title { font-size: 1.1rem; letter-spacing: .2em; }
  .orb-wrap { width: 180px; height: 180px; }
  .orb-core { width: 104px; height: 104px; }
  #modal-panel { width: 94vw; max-height: 88vh; }
  .forecast-cond { display: none; }
}
"""


# ── head: fonts + the small amount of client JS ─────────────────────────────

def head(initial_theme: str) -> str:
    theme = "light" if initial_theme == "light" else "dark"
    return f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;800;900&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
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
    const opener = e.target.closest("#menu-btn, #history-btn");
    if (sidebar && !sidebar.contains(e.target) && !opener) root.classList.remove("sidebar-open");
  });

  // ── keyboard dock button: jump focus to the text composer, no voice session involved ──
  window.awaazFocusComposer = function () {
    const el = document.querySelector("#composer-input textarea, #composer-input input");
    if (el) el.focus();
  };

  // ── card detail modals (Weather / Tasks / Reminders) ──
  // Content for all three is always kept live in the DOM (see dashboard_panels in app.py) so
  // opening one never shows stale data; only which one is visible is toggled here, via a class
  // on #app-root that the CSS uses to show the matching #modal-*-content block.
  const MODAL_NAMES = ["weather", "tasks", "reminders"];
  window.awaazOpenModal = function (name) {
    const root = document.getElementById("app-root");
    if (!root) return;
    MODAL_NAMES.forEach(function (n) { root.classList.remove("modal-" + n); });
    root.classList.add("modal-open", "modal-" + name);
  };
  window.awaazCloseModal = function () {
    const root = document.getElementById("app-root");
    if (!root) return;
    root.classList.remove("modal-open");
    MODAL_NAMES.forEach(function (n) { root.classList.remove("modal-" + n); });
  };
  document.addEventListener("click", function (e) {
    const root = document.getElementById("app-root");
    if (!root || !root.classList.contains("modal-open")) return;
    const panel = document.getElementById("modal-panel");
    const opener = e.target.closest(".card.clickable");
    if (panel && !panel.contains(e.target) && !opener) awaazCloseModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") awaazCloseModal();
  });

  // ── live clock ──
  function tickClock() {
    const t = document.getElementById("topbar-time"), d = document.getElementById("topbar-date");
    if (!t && !d) return;
    const now = new Date();
    if (t) t.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true });
    if (d) d.textContent = now.toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" });
  }
  setInterval(tickClock, 1000);
  document.addEventListener("DOMContentLoaded", tickClock);

  // ── live uptime ticker: purely cosmetic per-second smoothing between the ~30s server polls ──
  // Reads data-start (ms since epoch, when the app process started) fresh every tick, so it keeps
  // working correctly across Gradio re-rendering the card's HTML on every dashboard refresh.
  function tickUptime() {
    document.querySelectorAll("[data-uptime-start]").forEach(function (el) {
      const start = Number(el.dataset.uptimeStart);
      if (!start) return;
      const s = Math.max(0, Math.floor((Date.now() - start) / 1000));
      const h = String(Math.floor(s / 3600)).padStart(2, "0");
      const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
      const sec = String(s % 60).padStart(2, "0");
      el.textContent = h + ":" + m + ":" + sec;
    });
  }
  setInterval(tickUptime, 1000);
  document.addEventListener("DOMContentLoaded", tickUptime);

  // ── mirror the Weather card's live figures into the top bar's compact chip ──
  // A plain poll (not a MutationObserver) since a couple of seconds' staleness on a weather
  // readout is irrelevant, and this avoids wiring a 4th Gradio output just for the top bar.
  function syncWeatherChip() {
    const t = document.querySelector("#weather-card .weather-temp");
    const p = document.querySelector("#weather-card .weather-place");
    const ct = document.getElementById("topbar-weather-temp");
    const cp = document.getElementById("topbar-weather-place");
    if (t && ct) ct.textContent = t.textContent;
    if (p && cp) cp.textContent = p.textContent.split(",")[0];
  }
  setInterval(syncWeatherChip, 2000);
  document.addEventListener("DOMContentLoaded", syncWeatherChip);

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
  const STATUS_TEXT = { idle: "Tap the mic to start", listening: "Listening…", user_speaking: "Hearing you…",
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
    document.querySelectorAll(".wave-bars i").forEach(function (bar, i) {
      bar.style.height = (5 + Math.min(20, level * (160 + i * 30))) + "px";
    });
  }
  function setStatus(text) { const el = document.getElementById("mic-status"); if (el) el.textContent = text || ""; }
  function refreshUI() {
    document.querySelectorAll(".dock-btn--mic").forEach(function (b) {
      b.classList.toggle("conv-on", SESSION.active);
      b.classList.toggle("recording", SESSION.state === STATE.USER_SPEAKING);
      b.classList.toggle("speaking", SESSION.state === STATE.ASSISTANT_SPEAKING);
    });
    const end = document.getElementById("end-conv-btn"); if (end) end.style.display = SESSION.active ? "" : "none";
    const orb = document.getElementById("voice-orb");
    if (orb) {
      orb.className = "orb-wrap st-" + SESSION.state;
    }
    const pill = document.getElementById("status-pill");
    if (pill) {
      pill.classList.toggle("live", SESSION.active && SESSION.state !== STATE.USER_SPEAKING);
      pill.classList.toggle("hearing", SESSION.state === STATE.USER_SPEAKING);
    }
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


GEAR_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
           '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18.4 5.6l-1.5 1.5'
           'M7.1 16.9l-1.5 1.5M18.4 18.4l-1.5-1.5M7.1 7.1 5.6 5.6"/></svg>')
MENU_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">'
           '<path d="M4 7h16M4 12h16M4 17h16"/></svg>')
CPU_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
          '<rect x="6" y="6" width="12" height="12" rx="2"/><path stroke-linecap="round" '
          'd="M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2"/></svg>')
CLOUD_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
            '<path d="M7 18h10a4 4 0 0 0 .4-8 5.5 5.5 0 0 0-10.6 1.7A3.5 3.5 0 0 0 7 18Z"/></svg>')
RAIN_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
           '<path d="M7 15h10a4 4 0 0 0 .4-8 5.5 5.5 0 0 0-10.6 1.7A3.5 3.5 0 0 0 7 15Z"/>'
           '<path stroke-linecap="round" d="M8 18v2M12 18v2M16 18v2"/></svg>')
CHECKLIST_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
                 '<path stroke-linecap="round" stroke-linejoin="round" d="M9 11l2.5 2.5L16 9"/>'
                 '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/></svg>')
BELL_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
           '<path stroke-linejoin="round" d="M6 8a6 6 0 1 1 12 0c0 4 1.5 5.5 1.5 5.5h-15S6 12 6 8Z"/>'
           '<path stroke-linecap="round" d="M10 18a2 2 0 0 0 4 0"/></svg>')
CLOCK_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
            '<circle cx="12" cy="12" r="9"/><path stroke-linecap="round" d="M12 8v4l2.5 1.5"/></svg>')
MIC_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">'
          '<rect x="9" y="3" width="6" height="11" rx="3"/>'
          '<path stroke-linecap="round" d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>')
KEYBOARD_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
               '<rect x="2.5" y="6" width="19" height="12" rx="2.4"/>'
               '<path stroke-linecap="round" d="M6 10h.01M9.5 10h.01M13 10h.01M16.5 10h.01M6 14h12"/></svg>')

def topbar_html() -> str:
    return f"""
<div id="topbar">
  <button id="menu-btn" onclick="awaazToggleSidebar()" title="Conversations">{MENU_SVG}</button>
  <div class="brand-wrap">
    <span class="brand">AWAAZ</span>
    <span class="status-tag"><span class="dot"></span>Online</span>
  </div>
  <div class="spacer"></div>
  <div id="topbar-clock" class="mono">
    {CLOCK_SVG}
    <span class="time" id="topbar-time">--:--:-- --</span>
    <span class="divider"></span>
    <span id="topbar-date">···</span>
  </div>
  <div class="weather-chip" id="topbar-weather">{CLOUD_SVG}
    <strong class="mono" id="topbar-weather-temp">--°C</strong>
    <span class="city" id="topbar-weather-place">···</span>
  </div>
  <div class="hud-icon" onclick="awaazToggleSidebar()" title="Settings &amp; conversations">{GEAR_SVG}</div>
</div>"""


def conversation_welcome_html(language: str = "en") -> str:
    if language == "ne":
        title, sub = "आवाज सहायक", "नमस्ते! रिमाइन्डर, काम, मौसम वा फुटबल बारे सोध्नुहोस्।"
    else:
        title, sub = "Awaaz", "Hi! Ask about reminders, tasks, weather or football."
    return (f"<div style='text-align:center;opacity:.75;padding-top:8vh'>"
           f"<div style='font-size:1.8rem'>🗣️</div><div style='font-size:1.05rem;font-weight:700;margin-top:6px;"
           f"color:var(--accent)'>{html.escape(title)}</div>"
           f"<div style='font-size:.82rem;margin-top:4px;max-width:280px;margin-inline:auto;color:var(--muted)'>"
           f"{html.escape(sub)}</div></div>")


def voice_orb_html() -> str:
    """The center hero: a purely client-driven voice-session visual. No Python data — the JS
    state machine (see JS above) drives every dynamic bit of it (orb glow, wave bars, status
    pill, mic button state) by id/class, so this only needs to render once."""
    bars = "".join("<i></i>" for _ in range(5))
    return f"""
<div class="orb-wrap st-idle" id="voice-orb">
  <div class="orb-ring ring-1"></div>
  <div class="orb-ring ring-2"></div>
  <div class="orb-core"><div class="wave-bars">{bars}</div></div>
</div>
<h1 class="brand-title">AWAAZ</h1>
<div class="status-pill" id="status-pill"><span class="dot"></span><span id="mic-status">Tap the mic to start</span></div>
<div class="dock">
  <button class="dock-btn" onclick="awaazFocusComposer()" title="Type instead">{KEYBOARD_SVG}</button>
  <div class="mic-btn-group" style="display:flex;flex-direction:column;align-items:center;gap:8px;">
    <button class="dock-btn dock-btn--mic" onclick="awaazMicTap()" title="Tap to talk hands-free">{MIC_SVG}</button>
    <button id="end-conv-btn" onclick="awaazEndConversation()" title="End the conversation">✕ End</button>
  </div>
  <button class="dock-btn" onclick="awaazToggleSidebar()" title="Conversation history">{CLOCK_SVG}</button>
</div>"""


# ── dashboard widgets (pure HTML builders — app.py supplies the data) ───────

def panel(title: str, body_html: str, count: int | str | None = None, icon_svg: str = "",
         onclick: str = "") -> str:
    n = f'<span class="count-pill">{html.escape(str(count))}</span>' if count is not None else ""
    cls = "card clickable" if onclick else "card"
    click_attr = f' onclick="{html.escape(onclick, quote=True)}"' if onclick else ""
    return (f'<div class="{cls}"{click_attr}><div class="card-head"><div class="card-title">{icon_svg}'
           f'<span>{html.escape(title)}</span></div>{n}</div>{body_html}</div>')


def modal_section(title: str, icon_svg: str, body_html: str) -> str:
    """Wraps a card detail modal's content with its heading; the close button is fixed chrome
    that lives in the modal shell itself, not per-section, so its reserved space (padding-right
    on h3) is baked into .modal-section h3 rather than repeated here."""
    return f'<h3>{icon_svg}<span>{html.escape(title)}</span></h3>{body_html}'


def forecast_row(day_label: str, icon_svg: str, condition: str, temp_max: str, temp_min: str,
                 rain_pct: str) -> str:
    return (f'<div class="forecast-row"><span class="forecast-day">{html.escape(day_label)}</span>'
           f'<span class="forecast-icon">{icon_svg}</span>'
           f'<span class="forecast-cond">{html.escape(condition)}</span>'
           f'<span class="forecast-temps"><span class="hi">{html.escape(temp_max)}°</span>'
           f'<span class="lo">{html.escape(temp_min)}°</span></span>'
           f'<span class="forecast-rain">{html.escape(rain_pct)}</span></div>')


def modal_shell_html() -> str:
    return '<div id="modal-backdrop" onclick="awaazCloseModal()"></div>'


def system_stats_body(cpu_pct: float, mem_pct: float, mem_used_gb: float, mem_total_gb: float,
                      disk_used_gb: float, disk_total_gb: float) -> str:
    cpu_pct, mem_pct = max(0.0, min(100.0, cpu_pct)), max(0.0, min(100.0, mem_pct))
    return f"""
<div class="stat-row">
  <div class="stat-row-top"><span class="stat-label">CPU Usage</span><span class="stat-value">{cpu_pct:.0f}%</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:{cpu_pct:.0f}%"></div></div>
</div>
<div class="stat-row">
  <div class="stat-row-top"><span class="stat-label">RAM Usage</span><span class="stat-value">{mem_used_gb:.1f} GB</span></div>
  <div class="bar-track"><div class="bar-fill" style="width:{mem_pct:.0f}%"></div></div>
</div>
<div class="tile-row">
  <div class="tile"><div class="tile-label">CPU</div><div class="tile-value">{cpu_pct:.0f}%</div></div>
  <div class="tile"><div class="tile-label">Memory</div><div class="tile-value">{mem_pct:.0f}%</div></div>
  <div class="tile"><div class="tile-label">Disk</div><div class="tile-value">{disk_used_gb:.0f}/{disk_total_gb:.0f} GB</div></div>
</div>"""


def weather_body(temp: str, condition: str, place: str, icon_svg: str,
                 humidity: str = "--", wind: str = "--", feels_like: str = "--") -> str:
    return f"""
<div class="weather-hero">
  <div>
    <div class="weather-temp">{html.escape(temp)}°C</div>
    <div class="weather-place">{html.escape(place)}</div>
    <div class="weather-cond">{html.escape(condition)}</div>
  </div>
  <div class="weather-icon">{icon_svg}</div>
</div>
<div class="tile-row">
  <div class="tile"><div class="tile-label">Humidity</div><div class="tile-value">{html.escape(humidity)}</div></div>
  <div class="tile"><div class="tile-label">Wind</div><div class="tile-value">{html.escape(wind)}</div></div>
  <div class="tile"><div class="tile-label">Feels Like</div><div class="tile-value">{html.escape(feels_like)}</div></div>
</div>"""


def task_list(rows: list[tuple[str, str, str, bool]], empty: str) -> str:
    """rows = [(title, tag_text, tag_class, done)]; tag_class is 'due-today'|'overdue'|'due-later'."""
    if not rows:
        return f'<div class="list-empty">{html.escape(empty)}</div>'
    items = []
    for title, tag_text, tag_class, done in rows:
        cls = "task-item done" if done else "task-item"
        tag = "done-tag" if done else tag_class
        tag_text = "Done" if done else tag_text
        check = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">'
                '<path stroke-linecap="round" stroke-linejoin="round" d="M4 12l5 5L20 6"/></svg>') if done else ""
        items.append(f'<div class="{cls}"><span class="task-check">{check}</span>'
                    f'<span class="task-text">{html.escape(title)}</span>'
                    f'<span class="task-tag {tag}">{html.escape(tag_text)}</span></div>')
    return f'<div class="list">{"".join(items)}</div>'


def progress_bar(percent: int, label: str) -> str:
    percent = max(0, min(100, percent))
    return (f'<div class="progress-line"><div class="bar-track">'
           f'<div class="bar-fill" style="width:{percent}%"></div></div>'
           f'<span>{html.escape(label)}</span></div>')


def reminder_list(rows: list[tuple[str, str, str, str, bool]], empty: str) -> str:
    """rows = [(time_main, time_day, title, meta, due_soon)]."""
    if not rows:
        return f'<div class="list-empty">{html.escape(empty)}</div>'
    items = []
    for time_main, time_day, title, meta, due_soon in rows:
        cls = "reminder-item due" if due_soon else "reminder-item"
        items.append(f'<div class="{cls}"><div class="reminder-time">{html.escape(time_main)}'
                    f'<span class="day">{html.escape(time_day)}</span></div>'
                    f'<div class="reminder-body"><div class="reminder-title">{html.escape(title)}</div>'
                    f'<div class="reminder-meta">{html.escape(meta)}</div></div></div>')
    return f'<div class="list">{"".join(items)}</div>'


def uptime_body(uptime_start_ms: int, uptime_str: str, session_count: int, command_count: int,
               load_pct: float, load_label: str) -> str:
    load_pct = max(0.0, min(100.0, load_pct))
    warn = ' warn' if load_pct >= 60 else ''
    return f"""
<div class="uptime-row">
  <span class="stat-label">System Running For:</span>
  <span class="uptime-value mono" data-uptime-start="{uptime_start_ms}">{html.escape(uptime_str)}</span>
</div>
<div class="tile-row" style="margin-bottom:11px;">
  <div class="tile"><div class="tile-label">Session</div><div class="tile-value">{session_count}</div></div>
  <div class="tile"><div class="tile-label">Commands</div><div class="tile-value">{command_count}</div></div>
  <div class="tile"><div class="tile-label"{' style="color:var(--warn)"' if warn else ''}>Load</div>
    <div class="tile-value"{' style="color:var(--warn)"' if warn else ''}>{load_pct:.0f}%</div></div>
</div>
<div class="stat-row" style="margin-bottom:0;">
  <div class="stat-row-top"><span class="stat-label">System Load</span>
    <span class="stat-value"{' style="color:var(--warn)"' if warn else ''}>{html.escape(load_label)} · {load_pct:.0f}%</span></div>
  <div class="bar-track"><div class="bar-fill{warn}" style="width:{load_pct:.0f}%"></div></div>
</div>"""
