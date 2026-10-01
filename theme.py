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
import json
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
/* z-index:55 (above #sidebar's 50 and #scrim's 45, below the modals' 90+): the sidebar spans
   top:0 to bottom:0, so without this it would cover the topbar's own Home/Chat icons whenever
   open - including the Chat icon that's supposed to close it again. */
#topbar { position: relative; z-index: 55; display: flex; align-items: center; gap: 14px;
  padding: 10px 18px; border-bottom: 1px solid var(--border);
  background: linear-gradient(180deg, var(--panel-2), var(--panel)) !important; flex-wrap: wrap; }
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

/* ── notch-pill icon clusters (Home / Chat / + on the left, Gear / Speaker on the right) ──
   A rounder, fully-circular take on .hud-icon for the two button groups bookending the top
   bar — purely a shape/shell treatment, each icon still fires a real existing action (see
   topbar_html()), never a decorative no-op. */
.pill-cluster { display: flex; align-items: center; gap: 6px; padding: 5px; border-radius: 999px;
  background: rgba(255,255,255,.025); border: 1px solid var(--border); flex: none; }
.pill-icon { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center;
  background: transparent; border: none; color: var(--muted) !important; cursor: pointer;
  transition: color .15s ease, background .15s ease, transform .1s ease; }
.pill-icon:hover { color: var(--accent) !important; background: var(--accent-soft); }
.pill-icon:active { transform: scale(.92); }
/* Home/Chat act as a 2-way tab indicator (see awaazSyncTopbarActive in theme.JS): whichever one
   names what's currently showing (the chat view, or the conversation-history drawer) gets this
   highlight, the same way a segmented control marks its selected tab. */
.pill-icon.active { background: rgba(255,255,255,.1); color: var(--text) !important; }
.pill-icon svg { width: 16px; height: 16px; }
.pill-icon--plus { background: linear-gradient(140deg, var(--accent-2), var(--accent)); color: #06131f !important; }
.pill-icon--plus:hover { background: linear-gradient(140deg, var(--accent-2), var(--accent)); color: #06131f !important; filter: brightness(1.08); }

/* ── Coucou-style 3-state notch: collapsed (small pill) -> panel (quick view) -> full (the
   mascot + live conversation + voice + text chat view - the only "opened" interface now; the
   old stats/orb/sidebar dashboard grid was removed, its functionality folded in here, in
   modals, and in the always-present sidebar - see app.py's build_ui()). Switching states never
   rebuilds or refetches anything, it only shows/hides what's already there. Defaults to
   collapsed (see head()'s html[data-notch] init script), so a first-time visitor sees the small
   pill first. The pill/panel/chat-view subtree is deliberately theme-independent (hardcoded dark
   colors, not var(--bg)/var(--text)) so it reads like a fixed black notch island regardless of
   the app's own light/dark toggle underneath it. */
/* Topbar only shows alongside the full chat view, not the quick panel - the panel is meant to
   float on its own (see the reference: mascot card + tiles, nothing above it). */
html[data-notch="collapsed"] #topbar,
html[data-notch="panel"] #topbar { display: none !important; }
/* !important on both show-overrides below: Gradio auto-prefixes plain class rules with its own
   `.gradio-container... .contain` scope, which inflates the base `display: none` rules' real
   specificity past these html[data-notch]-qualified overrides (whose own auto-prefixed copies
   can never match, since `html` can never be a descendant of `.contain`) — so without
   !important here the base rules would win and neither layer would ever show. */
.notch-launcher, .notch-panel, #chat-view { display: none; }
html[data-notch="collapsed"] .notch-launcher { display: flex !important; }
html[data-notch="panel"] .notch-panel { display: flex !important; }
html[data-notch="full"] #chat-view { display: flex !important; }

/* ── mascot: a small white blob with two dot eyes that track the cursor (see
   awaazTrackMascotEyes in theme.JS). Used at both sizes below. ── */
.mascot { position: relative; flex: none; background: linear-gradient(165deg, #ffffff, #e6e9f0);
  border-radius: 46% 46% 50% 50% / 60% 60% 40% 40%;
  box-shadow: inset 0 -3px 5px rgba(0,0,0,.1), 0 2px 8px rgba(0,0,0,.3);
  animation: mascot-bob 3.4s ease-in-out infinite; }
@keyframes mascot-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
.mascot-sm { width: 30px; height: 26px; }
.mascot-md { width: 42px; height: 36px; }
.mascot-lg { width: 60px; height: 52px; }
.mascot-eye { position: absolute; top: 48%; border-radius: 50%; background: #1b1d24;
  transform: translate(-50%, -50%); transition: transform .06s ease-out; }
.mascot-sm .mascot-eye { width: 4px; height: 4px; }
.mascot-md .mascot-eye { width: 5px; height: 5px; }
.mascot-lg .mascot-eye { width: 7px; height: 7px; }
.mascot .mascot-eye:nth-child(1) { left: 38%; }
.mascot .mascot-eye:nth-child(2) { left: 62%; }

/* ── collapsed: mascot + a 2x2 grid of dot-capsules (purely a decorative "stuff is connected"
   indicator, like the reference — identity/labels only appear once the panel is open). Draggable
   anywhere on screen (see awaazInitNotchDrag in theme.JS); fully rounded since it's no longer
   pinned to the top edge, and its position is restored from localStorage on load. ── */
.notch-launcher { position: fixed; z-index: 40; top: 0; left: 50%; transform: translateX(-50%);
  align-items: center; justify-content: center; gap: 14px; height: 52px; padding: 0 20px;
  min-width: 190px; border-radius: 999px; cursor: grab;
  background: #0a0a0d; border: 1px solid rgba(94,195,255,.16);
  box-shadow: 0 14px 34px -16px rgba(0,0,0,.7);
  transition: border-color .15s ease; touch-action: none; }
.notch-launcher:hover { border-color: rgba(94,195,255,.32); }
.notch-launcher.dragging { cursor: grabbing; transition: none; }
.notch-pips { display: grid; grid-template-columns: repeat(2, 1fr); gap: 5px; }
.notch-pip { width: 26px; height: 15px; border-radius: 999px; display: flex; align-items: center;
  justify-content: center; gap: 4px; flex: none; }
.notch-pip-dot { width: 4px; height: 4px; border-radius: 50%; background: rgba(0,0,0,.55); flex: none; }

/* ── panel: the compact quick view shown after tapping the pill — a status/launch card next to
   a grid of the live feature cards, reached one tap earlier than the full dashboard. Positioned
   in JS (awaazOpenNotchPanel) next to wherever the pill currently is, since the pill is now
   draggable; top/left here are just the pre-first-open fallback. ── */
.notch-panel { position: fixed; z-index: 35; top: 54px; left: 50%; transform: translateX(-50%);
  width: min(560px, calc(100vw - 32px)); gap: 12px; padding: 14px;
  background: #0a0a0d; border: 1px solid rgba(94,195,255,.16); border-radius: 22px;
  box-shadow: 0 24px 60px -20px rgba(0,0,0,.65); animation: notch-panel-in .18s ease-out; }
@keyframes notch-panel-in { from { opacity: 0; } to { opacity: 1; } }

.notch-hero { flex: 1; display: flex; align-items: center; gap: 12px; padding: 14px;
  border-radius: 16px; background: #14161d; border: 1px solid rgba(94,195,255,.14);
  cursor: pointer; text-align: left; font: inherit; color: inherit;
  transition: border-color .15s ease, transform .1s ease; }
.notch-hero:hover { border-color: rgba(94,195,255,.32); transform: translateY(-1px); }
.notch-hero-body { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.notch-hero-title { font-weight: 700; font-size: .92rem; color: #e9f1fb; }
.notch-hero-status { display: flex; align-items: center; gap: 6px; font-size: .72rem; color: #8a97ad; }
.notch-hero-status .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--good); flex: none;
  animation: pulse-dot 2.2s ease-out infinite; }
.notch-hero-cta { margin-top: 2px; font-size: .72rem; font-weight: 600; color: #4fd1ff; }

.notch-grid { flex: 1; display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.notch-tile { display: flex; align-items: center; gap: 8px; padding: 9px 11px; border-radius: 14px;
  background: #14161d; border: 1px solid rgba(94,195,255,.14); cursor: pointer; font: inherit;
  color: #e9f1fb; transition: border-color .15s ease, transform .1s ease; }
.notch-tile:hover { border-color: rgba(94,195,255,.32); transform: translateY(-1px); }
.notch-tile .badge { width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; flex: none; }
.notch-tile .badge svg { width: 12px; height: 12px; color: #06131f !important; }
.notch-tile-label { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; min-width: 0; }
.notch-tile-label span { font-size: .78rem; font-weight: 600; }
.notch-tile-label small { font-size: .62rem; font-weight: 600; color: #6f7c92; font-family: 'JetBrains Mono', monospace; }

@media (max-width: 560px) {
  .notch-panel { flex-direction: column; }
}

/* ── full: the only "opened" interface now — a floating rounded card below #topbar (unchanged)
   holding the mascot, the live conversation (the real gr.Chatbot, relocated here - see app.py),
   voice controls (the real voice orb + dock, just compact-sized below) and the real text
   composer. Nothing here is a second copy of anything - these are the exact same components the
   old dashboard used, just rendered in this container instead. Its own CSS custom properties are
   redeclared with fixed dark values (not inherited from :root) so every theme-aware component
   embedded in it (chatbot bubbles, orb, status pill, dock, composer) stays legible against this
   always-dark card regardless of the app's own light/dark toggle. ── */
#chat-view {
  --bg: #0a0a0d; --panel: #14161d; --panel-2: #14161d; --border: rgba(94,195,255,.16);
  --border-strong: rgba(94,195,255,.32); --text: #e9f1fb; --muted: #8a97ad; --faint: #566378;
  --accent: #4fd1ff; --accent-2: #4b8bff; --accent-soft: rgba(79,209,255,.10);
  --good: #34d399; --good-soft: rgba(52,211,153,.12); --warn: #f5c451; --warn-soft: rgba(245,196,81,.12);
  position: fixed; z-index: 30; top: 70px; left: 50%; transform: translateX(-50%);
  width: min(720px, calc(100vw - 32px)); height: auto; max-height: min(340px, calc(100vh - 110px));
  flex-direction: column; gap: 4px;
  background: var(--bg); border: 1px solid var(--border); border-radius: 26px;
  box-shadow: 0 30px 70px -24px rgba(0,0,0,.65); overflow: hidden;
  animation: notch-panel-in .18s ease-out; }
#chat-view-header { position: relative; flex: none; display: flex !important; align-items: center;
  gap: 10px; padding: 10px 16px; }
.chat-view-glow { position: absolute; top: -60%; left: 10%; width: 40%; aspect-ratio: 1;
  border-radius: 50%; pointer-events: none;
  background: radial-gradient(circle, rgba(79,139,255,.22), rgba(79,139,255,0) 70%); }
/* mascot + title in their own row - see chat_view_header_html()'s docstring for why this can't
   just rely on the outer #chat-view-header row to lay them out side by side. */
.chat-view-brand { position: relative; z-index: 1; display: flex; align-items: center; gap: 8px; flex: 1; }
.chat-view-title { font-weight: 700; font-size: .88rem; color: var(--text) !important; }
#chat-view .chip-btn { position: relative; z-index: 1; }

/* height:auto on #chat-view above means this no longer stretches to fill a tall fixed-height
   card while empty (conversation_welcome_html() is blank on purpose, see app.py) - min-height
   keeps a little breathing room for the first reply, max-height plus its own scroll is what
   kicks in once a conversation actually grows past that. */
#chat-view #chatbot { flex: 0 1 auto; min-height: 60px; max-height: 180px; padding: 0 6px; }
/* Gradio's own inner wrapper divs for Chatbot carry their own min-height (independent of the
   #chatbot rule above, which only bounds the outer element) - without zeroing those too, an
   empty conversation still reserves Gradio's default empty-state height regardless. */
#chat-view #chatbot > div { min-height: 0 !important; }
#chat-view #status-line { padding: 0 21px; }

/* ── the mic sits right beside the composer, in the same row, instead of its own section above
   it. It's still the exact same tap-to-talk voice session (orb/wake-word/barge-in all unchanged
   JS) - only the big ring/core/wave-bars visualisation and the now-redundant keyboard/history
   dock buttons (the composer is always visible right here; conversation history already has its
   own topbar icon) are hidden. The mic button's own state styling (.recording/.speaking/.conv-on,
   all pre-existing) is what shows session state now, instead of the separate status pill. ── */
#chat-input-row { display: flex !important; align-items: center; gap: 8px; padding: 8px 16px 16px; }
/* width:auto !important is required: Gradio's own .block wrapper class (applied to every
   gr.HTML component, including this one) sets width:100% by default, which would otherwise
   stretch this to fill the row and push the composer onto its own line below instead of
   beside it. */
#voice-orb-wrap { flex: none; width: auto !important; display: flex !important; align-items: center;
  gap: 6px; padding: 0; }
#voice-orb-wrap .orb-wrap, #voice-orb-wrap .brand-title, #voice-orb-wrap .status-pill,
#voice-orb-wrap .dock-btn:not(.dock-btn--wake):not(.dock-btn--mic) { display: none; }
#voice-orb-wrap .dock { gap: 6px; }
#voice-orb-wrap .dock-btn { width: 36px; height: 36px; }
#voice-orb-wrap .dock-btn svg { width: 15px; height: 15px; flex: none; }
#voice-orb-wrap .dock-btn--mic { width: 42px; height: 42px; }
#voice-orb-wrap #end-conv-btn { height: 22px; min-width: 56px; font-size: .62rem; }

#chat-view #composer-wrap { flex: 1; min-width: 0; padding: 0; border-top: none; }
#chat-view #composer-input textarea, #chat-view #composer-input input {
  background: rgba(255,255,255,.05) !important; border-radius: 999px !important; padding: 10px 16px !important; }
#chat-view #send-btn { border-radius: 50% !important; background: var(--text) !important;
  color: var(--bg) !important; }

@media (max-width: 480px) {
  #chat-view { width: calc(100vw - 24px); }
}

/* #hidden-cards: the compact Tasks/Reminders/Weather/System card HTML used to render visibly in
   the old dashboard grid (now removed) - it's kept rendered (off-screen, not display:none) only
   because syncNotchCounts() and syncWeatherChip() in theme.JS still read live numbers off of it
   (#tasks-card/#reminders-card/#weather-card), same off-screen technique as #mic-upload below. */
#hidden-cards { position: absolute !important; left: -9999px !important; width: 1px !important;
  height: 1px !important; overflow: hidden !important; }

.card { background: linear-gradient(180deg, var(--panel-2), var(--panel)); border: 1px solid var(--border);
  border-radius: 20px; padding: 14px 15px 14px; box-shadow: 0 14px 34px -20px rgba(0,0,0,.6); flex: none; }
.card.clickable { cursor: pointer; transition: border-color .15s ease, transform .15s ease; }
.card.clickable:hover { border-color: var(--border-strong); transform: translateY(-1px); }
.card.clickable:active { transform: translateY(0); }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 11px; }
.card-title { display: flex; align-items: center; gap: 8px; font-size: .82rem; font-weight: 700;
  color: var(--text) !important; letter-spacing: .02em; }
.card-title svg { width: 15px; height: 15px; color: var(--accent) !important; flex: none; }

/* ── per-card colored icon badge (Coucou-style integration dots: each card gets its own hue
   instead of sharing one global accent colour, so the left rail reads as a set of distinct
   cards at a glance) — wraps the existing icon_svg, doesn't replace it. */
.card-title .badge { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; flex: none; }
.card-title .badge svg { width: 13px; height: 13px; color: #06131f !important; }
.badge-blue { background: linear-gradient(140deg, #6fd8ff, #4b8bff); }
.badge-sky { background: linear-gradient(140deg, #8fe8ff, #4fd1ff); }
.badge-green { background: linear-gradient(140deg, #6ee7b7, #34d399); }
.badge-amber { background: linear-gradient(140deg, #fde68a, #f5c451); }
.badge-purple { background: linear-gradient(140deg, #c4b5fd, #a78bfa); }
.badge-pink { background: linear-gradient(140deg, #fda4af, #fb7185); }
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
  display: flex; align-items: center; justify-content: center; color: transparent; cursor: pointer;
  transition: border-color .12s ease, background .12s ease; }
.task-check:hover { border-color: var(--accent) !important; }
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

/* ── voice orb (now lives inside #chat-view, compact-sized there - see that section's CSS) ── */
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
.orb-wrap.st-wake_listening .orb-core { opacity: .78; animation: orb-breathe 4.6s ease-in-out infinite; }
.orb-wrap.st-awake .orb-core { border-color: rgba(52,211,153,.6);
  box-shadow: 0 0 70px -2px rgba(52,211,153,.55), inset 0 0 40px rgba(52,211,153,.2); }
.orb-wrap.st-stopped .orb-core, .orb-wrap.st-error .orb-core { border-color: rgba(242,89,107,.55);
  box-shadow: 0 0 54px -4px rgba(242,89,107,.4), inset 0 0 34px rgba(242,89,107,.14); }
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
.dock-btn--wake.wake-on { color: var(--good) !important; border-color: rgba(52,211,153,.5) !important;
  box-shadow: 0 0 0 3px rgba(52,211,153,.18); animation: wake-pulse 2.4s ease-in-out infinite; }
@keyframes wake-pulse { 0%,100% { box-shadow: 0 0 0 3px rgba(52,211,153,.18) } 50% { box-shadow: 0 0 0 6px rgba(52,211,153,.05) } }
#end-conv-btn { min-width: 68px; height: 26px; border-radius: 13px; white-space: nowrap;
  background: rgba(242,89,107,.1); border: 1px solid rgba(242,89,107,.4); color: #f2596b !important; font-size: .7rem;
  padding: 0 10px; cursor: pointer; font-family: 'JetBrains Mono', monospace; display: none; }
#end-conv-btn:hover { background: rgba(242,89,107,.2); }

#mic-upload { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important;
  overflow: hidden !important; }
#audio-row { position: absolute !important; left: -9999px !important; width: 1px !important; height: 1px !important;
  overflow: hidden !important; }
#task-toggle-trigger, #task-toggle-btn { position: absolute !important; left: -9999px !important;
  width: 1px !important; height: 1px !important; overflow: hidden !important; }

/* ── conversation actions (Clear / Extract), now a small row inside #chat-view's header ── */
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
  border: 1px solid var(--border-strong) !important; border-radius: 22px !important;
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
#app-root.modal-reminders #modal-reminders-content .modal-section,
#app-root.modal-system #modal-system-content,
#app-root.modal-system #modal-system-content .modal-section { display: block !important; flex: none !important; }
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
  #topbar .brand small { display: none; }
  #modal-panel { width: 94vw; max-height: 88vh; }
  .forecast-cond { display: none; }
}
"""


# ── head: fonts + the small amount of client JS ─────────────────────────────

def head(initial_theme: str, wake_phrases: tuple[str, ...] = ("Hey Aawaz", "Aawaz")) -> str:
    theme = "light" if initial_theme == "light" else "dark"
    # A plain global, set before the main script runs, is the whole "configuration point" for wake
    # phrases: adding one is a .env edit (WAKE_PHRASES), never a code change — see config.py and
    # README's "how to configure wake phrases".
    phrases_json = json.dumps([p.lower() for p in wake_phrases if p.strip()])
    return f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;800;900&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<script>document.documentElement.dataset.theme = localStorage.getItem("awaaz-theme") || "{theme}";</script>
<script>document.documentElement.dataset.notch = localStorage.getItem("awaaz-notch") || "collapsed";</script>
<script>window.AWAAZ_WAKE_PHRASES = {phrases_json};</script>
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

  // ── Coucou-style 3-state notch: collapsed (small pill) -> panel (quick view) -> full (the
  // chat view). Switching states never rebuilds or refetches anything, it only toggles which
  // layer is visible (see CSS: html[data-notch]). ──
  window.awaazSetNotch = function (state) {
    document.documentElement.dataset.notch = state;
    try { localStorage.setItem("awaaz-notch", state); } catch (e) {}
    awaazSyncTopbarActive();
  };
  // Home/Chat act as a 2-way tab indicator: Home highlights while the chat view is open, Chat
  // highlights while the conversation-history drawer is open (see .pill-icon.active in CSS).
  window.awaazSyncTopbarActive = function () {
    const home = document.querySelector('.pill-icon[title="Home"]');
    const chat = document.querySelector('.pill-icon[title="Conversations"]');
    const sidebarOpen = !!document.getElementById("app-root")?.classList.contains("sidebar-open");
    const isFull = document.documentElement.dataset.notch === "full";
    if (home) home.classList.toggle("active", isFull && !sidebarOpen);
    if (chat) chat.classList.toggle("active", sidebarOpen);
  };
  // The notch state is restored directly onto html[data-notch] by head()'s init script, not
  // through awaazSetNotch, so the initial sync needs its own call once the topbar actually
  // exists (same reasoning as the other DOMContentLoaded/setInterval syncs in this file).
  document.addEventListener("DOMContentLoaded", awaazSyncTopbarActive);
  // Tapping outside the open quick-view panel collapses it back to the pill, same pattern as
  // the sidebar's own outside-click-to-close below.
  document.addEventListener("click", function (e) {
    if (document.documentElement.dataset.notch !== "panel") return;
    const panel = document.querySelector(".notch-panel");
    // #topbar is excluded because it's visible during "panel" too and manages notch state
    // itself (e.g. the minimize button) - without this, any topbar click would immediately
    // re-collapse the panel it had just switched to, on the very same bubbling click event.
    const opener = e.target.closest(".notch-launcher, #topbar");
    if (panel && !panel.contains(e.target) && !opener) awaazSetNotch("collapsed");
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" || document.documentElement.dataset.notch !== "panel") return;
    // Defer to an open modal's own Escape handler first (closing the modal should never also
    // collapse the panel underneath it) - a second Escape press then collapses the panel.
    if (document.getElementById("app-root")?.classList.contains("modal-open")) return;
    awaazSetNotch("collapsed");
  });

  // ── mascot eyes track the cursor, Coucou-style ──
  // Cheap: on each mousemove, point every .mascot's eyes toward the cursor, clamped to a tiny
  // radius so it reads as a glance. Works for every mascot instance (pill + panel hero) at once.
  (function () {
    const RADIUS = 2.4;
    document.addEventListener("mousemove", function (e) {
      document.querySelectorAll(".mascot").forEach(function (m) {
        const r = m.getBoundingClientRect();
        if (!r.width) return;
        const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2);
        const dist = Math.hypot(dx, dy) || 1;
        const ex = (dx / dist) * RADIUS, ey = (dy / dist) * RADIUS;
        m.querySelectorAll(".mascot-eye").forEach(function (eye) {
          eye.style.transform = "translate(calc(-50% + " + ex + "px), calc(-50% + " + ey + "px))";
        });
      });
    });
  })();

  // ── draggable pill: drag it anywhere on screen; a plain click (no real movement) still opens
  // the quick panel, anchored next to wherever the pill currently sits. Position persists across
  // reloads via localStorage. Listeners are delegated on document (not attached directly to the
  // pill) because this script runs before Gradio has necessarily rendered .notch-launcher into
  // the DOM yet - same reasoning as the setInterval-based syncs elsewhere in this file, just via
  // delegation instead of polling, since mousedown/mousemove/mouseup all need document-wide reach
  // anyway (a drag's pointer routinely leaves the pill's own bounds mid-gesture). ──
  // This always runs one animation frame after the state switch that reveals the panel - by
  // which point CSS has already hidden .notch-launcher (display: none), so getBoundingClientRect
  // on it would read all zeros. Its inline left/top (set by the drag/restore code below) stay
  // readable regardless of visibility, so those are the source of truth here instead.
  // window.-qualified (not a plain function declaration): this whole JS blob is wrapped in one
  // top-level IIFE (see the very first line of this file), so a plain declaration would only be
  // visible inside that closure - invisible to the inline onclick="...requestAnimationFrame(
  // awaazPositionNotchPanel)" on the minimize button below, which runs in global scope.
  function awaazPillAnchor() {
    const pill = document.querySelector(".notch-launcher");
    if (!pill) return null;
    const w = pill.offsetWidth || 220, h = pill.offsetHeight || 52;
    if (pill.style.left && pill.style.top) {
      return { left: parseFloat(pill.style.left), top: parseFloat(pill.style.top), width: w, height: h };
    }
    // Never dragged yet: mirror the CSS default (top: 0, horizontally centered).
    return { left: window.innerWidth / 2 - w / 2, top: 0, width: w, height: h };
  }
  window.awaazPositionNotchPanel = function () {
    const panel = document.querySelector(".notch-panel");
    const anchor = awaazPillAnchor();
    if (!panel || !anchor) return;
    const pw = panel.offsetWidth, ph = panel.offsetHeight;
    let x = Math.min(Math.max(anchor.left, 8), window.innerWidth - pw - 8);
    let y = anchor.top + anchor.height + 10;
    if (y + ph > window.innerHeight - 8) y = Math.max(anchor.top - ph - 10, 8);
    panel.style.left = x + "px";
    panel.style.top = y + "px";
    panel.style.transform = "none";
  };
  (function () {
    const POS_KEY = "awaaz-notch-pos";
    function clamp(pill, x, y) {
      return {
        x: Math.min(Math.max(x, 4), window.innerWidth - pill.offsetWidth - 4),
        y: Math.min(Math.max(y, 0), window.innerHeight - pill.offsetHeight - 4),
      };
    }
    function place(pill, x, y) {
      pill.style.left = x + "px";
      pill.style.top = y + "px";
      pill.style.transform = "none";
    }
    // Restore a saved position the first time the pill exists in the DOM.
    let restored = false;
    const restoreTimer = setInterval(function () {
      const pill = document.querySelector(".notch-launcher");
      if (!pill) return;
      clearInterval(restoreTimer);
      restored = true;
      let saved = null;
      try { saved = JSON.parse(localStorage.getItem(POS_KEY) || "null"); } catch (e) {}
      if (saved) { const p = clamp(pill, saved.x, saved.y); place(pill, p.x, p.y); }
    }, 150);

    let dragging = false, moved = false, startX = 0, startY = 0, originX = 0, originY = 0;
    document.addEventListener("mousedown", function (e) {
      const pill = e.target.closest(".notch-launcher");
      if (!pill) return;
      dragging = true; moved = false;
      startX = e.clientX; startY = e.clientY;
      const r = pill.getBoundingClientRect();
      originX = r.left; originY = r.top;
      pill.classList.add("dragging");
      e.preventDefault();
    });
    document.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      const pill = document.querySelector(".notch-launcher");
      if (!pill) return;
      const dx = e.clientX - startX, dy = e.clientY - startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      const p = clamp(pill, originX + dx, originY + dy);
      place(pill, p.x, p.y);
    });
    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      const pill = document.querySelector(".notch-launcher");
      if (pill) pill.classList.remove("dragging");
      if (moved) {
        if (pill) {
          const r = pill.getBoundingClientRect();
          try { localStorage.setItem(POS_KEY, JSON.stringify({ x: r.left, y: r.top })); } catch (e) {}
        }
      } else {
        awaazSetNotch("panel");
        requestAnimationFrame(awaazPositionNotchPanel);
      }
    });
  })();

  // ── off-canvas conversation drawer ──
  window.awaazToggleSidebar = function () {
    const root = document.getElementById("app-root");
    if (root) root.classList.toggle("sidebar-open");
    awaazSyncTopbarActive();
  };
  document.addEventListener("click", function (e) {
    const root = document.getElementById("app-root");
    if (!root || !root.classList.contains("sidebar-open")) return;
    const sidebar = document.getElementById("sidebar");
    const opener = e.target.closest("#menu-btn, #history-btn, .sidebar-opener");
    if (sidebar && !sidebar.contains(e.target) && !opener) root.classList.remove("sidebar-open");
  });

  // ── keyboard dock button: jump focus to the text composer, no voice session involved ──
  window.awaazFocusComposer = function () {
    const el = document.querySelector("#composer-input textarea, #composer-input input");
    if (el) el.focus();
  };

  // ── card detail modals (Weather / Tasks / Reminders / System) ──
  // Content for all four is always kept live in the DOM (see dashboard_panels in app.py) so
  // opening one never shows stale data; only which one is visible is toggled here, via a class
  // on #app-root that the CSS uses to show the matching #modal-*-content block.
  const MODAL_NAMES = ["weather", "tasks", "reminders", "system"];
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
    // #task-toggle-btn is excluded because awaazToggleTask's own btn.click() call synthesizes a
    // brand new click event that bubbles from that hidden button - which lives outside
    // #modal-panel - not a continuation of the checkbox's original (already-stopped) event, so
    // without this it reads as an outside click and closes the modal the instant a task inside
    // it is checked off.
    // .notch-tile is excluded for the same reason: it's the quick-view panel's own opener
    // button for this exact modal, not an outside click.
    const opener = e.target.closest(".card.clickable, #task-toggle-btn, .notch-tile");
    if (panel && !panel.contains(e.target) && !opener) awaazCloseModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") awaazCloseModal();
  });

  // ── task checkbox: mark done/pending directly from the dashboard ──
  // A hidden Gradio Textbox holds the task id, and a hidden Button's real .click() call fires
  // the actual server round-trip (services.tasks.set_task_status - the same function voice/text
  // completion already uses), which hands back fresh dashboard HTML. Deliberately NOT done by
  // setting the textbox's value and dispatching a synthetic "input" event on it: Gradio's own
  // reactive tracking for text-type components only updates from a real, browser-generated input
  // event, so a JS-dispatched one is silently ignored (confirmed against this app's own
  // already-working search box, not just this new component - a synthetic input event on it
  // does not filter the list either). A Button's own js= hook has no such restriction: it reads
  // the textbox's live DOM value directly at click time, bypassing Gradio's tracked value
  // entirely, so this needs no event on the textbox at all - see task-toggle-btn's wiring in
  // app.py. A ":"-suffixed timestamp guarantees a fresh value even when toggling the same task
  // repeatedly in a row.
  window.awaazToggleTask = function (event, taskId) {
    if (event) event.stopPropagation();
    const input = document.querySelector("#task-toggle-trigger textarea, #task-toggle-trigger input");
    const btn = document.getElementById("task-toggle-btn");
    if (!input || !btn) return;
    input.value = taskId + ":" + Date.now();
    btn.click();
  };

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

  // ── mirror live task/reminder counts into the quick-view panel's tiles ──
  // Same plain-poll approach as syncWeatherChip above: these counts are purely cosmetic
  // (the real numbers live in the dashboard cards), so a couple of seconds' staleness is
  // irrelevant and this avoids wiring new Gradio outputs just for a second display of them.
  function syncNotchCounts() {
    const t = document.querySelector("#tasks-card .count-pill");
    const r = document.querySelector("#reminders-card .count-pill");
    const tEl = document.getElementById("notch-tile-tasks-count");
    const rEl = document.getElementById("notch-tile-reminders-count");
    if (t && tEl) tEl.textContent = t.textContent.trim();
    if (r && rEl) rEl.textContent = r.textContent.trim();
  }
  setInterval(syncNotchCounts, 2000);
  document.addEventListener("DOMContentLoaded", syncNotchCounts);

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

  const STATE = { IDLE: "idle", WAKE_LISTENING: "wake_listening", AWAKE: "awake",
                 LISTENING: "listening", USER_SPEAKING: "user_speaking",
                 PROCESSING: "processing", ASSISTANT_SPEAKING: "assistant_speaking",
                 STOPPED: "stopped", ERROR: "error" };
  const STATUS_TEXT = { idle: "Tap the mic to start", wake_listening: "Listening for Aawaz…",
                        awake: "Yes?", listening: "Listening…", user_speaking: "Hearing you…",
                        processing: "Thinking…", assistant_speaking: "Speaking…",
                        stopped: "Stopped", error: "Something went wrong" };

  const SESSION = {
    active: false, state: STATE.IDLE, genId: 0,
    stream: null, ctx: null, analyser: null, buf: null, mime: "",
    rec: null, chunks: [],
    onsetStart: 0, silenceStart: 0, utterStartedAt: 0,
    rafId: null, replyObserver: null, turnTimer: null,
    // Wake-word listening (separate lifecycle from the VAD command session above; see
    // startWakeListening()/onWakeWordDetected() further down). wakeMode marks a command session
    // that was entered via a detected wake word, so it knows to return to wake-listening
    // afterwards instead of staying hands-free open (see the reply-ended and timeout handlers).
    wakeActive: false, wakeMode: false, wakeRecognizer: null, wakeErrorCount: 0, wakeRestartTimer: null,
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
    document.querySelectorAll(".dock-btn--wake").forEach(function (b) {
      b.classList.toggle("wake-on", SESSION.wakeActive);
    });
    const end = document.getElementById("end-conv-btn");
    if (end) end.style.display = (SESSION.active || SESSION.wakeActive) ? "" : "none";
    const orb = document.getElementById("voice-orb");
    if (orb) {
      orb.className = "orb-wrap st-" + SESSION.state;
    }
    const pill = document.getElementById("status-pill");
    if (pill) {
      pill.classList.toggle("live", (SESSION.active || SESSION.wakeActive) && SESSION.state !== STATE.USER_SPEAKING);
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
    SESSION.wakeMode = false;    // reset here; onWakeWordDetected() sets it back true right after, if that's how we got here
    try {
      SESSION.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      setState(STATE.ERROR);
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
    SESSION.wakeMode = false;
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

  // The "✕ End" button / re-tapping the mic while ANY session (full command session or passive
  // wake-word listening) is running: a full stop of everything, never a return to wake-listening -
  // that return only happens automatically after a wake-triggered turn finishes (see the reply
  // "ended" handler and the turn-timeout handler further down).
  function endEverything() {
    stopWakeListening();
    endSession();
  }
  window.awaazEndConversation = endEverything;

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
  // The shared "a turn just finished" transition: a wake-triggered session (SESSION.wakeMode)
  // goes back to passive wake-word listening - "Idle/listening -> wake word -> ... -> return to
  // wake-word listening mode", per spec - while a manually tap-started session stays hands-free
  // open exactly as before (README's documented always-on barge-in behaviour is unchanged for it).
  function returnToListening() {
    if (SESSION.wakeMode) { endSession(); startWakeListening(); return; }
    setState(STATE.LISTENING);
  }
  // No reply arrived at all within this window (TTS failed, or nothing needed saying) - resume
  // listening anyway rather than waiting forever. Per-turn (myGen-gated) since a newer turn's
  // own timeout, or its reply arriving, should not be cancelled by an older turn's timer.
  function armTurnTimeout(myGen) {
    clearTurnTimeout();
    SESSION.turnTimer = setTimeout(function () {
      if (SESSION.active && myGen === SESSION.genId && SESSION.state === STATE.PROCESSING) returnToListening();
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
        if (!SESSION.active || SESSION.state !== STATE.ASSISTANT_SPEAKING) return;
        returnToListening();
      }, { once: true });
    });
    SESSION.replyObserver.observe(row, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
  }

  window.awaazMicTap = function () {
    if (SESSION.active) { endEverything(); return; }
    stopWakeListening();   // manually taking over from passive wake-word listening, if it was on
    startSession();
  };

  // The explicit "⏹ Stop" button: unlike barge-in (which means "I'm about to talk, so stop and
  // start listening to ME"), pressing Stop just means "stop talking" - it must not start a new
  // utterance recording. Same instant client-side stopSpeaking() as barge-in uses, so the user
  // never waits on a server round-trip for audio that's already playing locally to actually stop.
  // Passes through STATE.STOPPED briefly (per spec) so the UI can show "Stopped" for a beat before
  // the normal return-to-listening transition (wake-mode aware, same as a completed turn).
  window.awaazStopSpeaking = function () {
    stopSpeaking();
    if (!SESSION.active || SESSION.state !== STATE.ASSISTANT_SPEAKING) return;
    setState(STATE.STOPPED);
    setTimeout(function () { if (SESSION.active && SESSION.state === STATE.STOPPED) returnToListening(); }, 450);
  };

  // ── persistent wake-word listening ──────────────────────────────────────────
  // A second, deliberately lightweight listening mode, separate from the VAD command session
  // above: instead of continuously recording and sending audio to Groq Whisper (expensive, and
  // exactly what the spec says to avoid while idle), it uses the browser's own built-in speech
  // recognizer (SpeechRecognition) purely to watch for a wake phrase locally. Only once one is
  // heard does it hand off to the real, full-fidelity command session (startSession()).
  // Wake phrases come from window.AWAAZ_WAKE_PHRASES (set server-side from .env's WAKE_PHRASES —
  // see config.py) so adding one is a config change, never a code change.
  function normalizeForMatch(s) {
    return (s || "").toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();
  }
  function matchesWakePhrase(transcript) {
    const norm = normalizeForMatch(transcript);
    const phrases = (window.AWAAZ_WAKE_PHRASES && window.AWAAZ_WAKE_PHRASES.length)
      ? window.AWAAZ_WAKE_PHRASES : ["hey aawaz", "aawaz"];
    return phrases.some(function (p) { return norm.indexOf(normalizeForMatch(p)) !== -1; });
  }
  function getRecognitionCtor() { return window.SpeechRecognition || window.webkitSpeechRecognition || null; }

  function startWakeListening() {
    if (SESSION.active || SESSION.wakeActive) return;      // a real session already owns the mic
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      setState(STATE.ERROR);
      setStatus("Wake-word listening isn't supported in this browser — tap the mic instead.");
      return;
    }
    SESSION.wakeActive = true;
    SESSION.wakeErrorCount = 0;
    setState(STATE.WAKE_LISTENING);
    _runWakeRecognizer();
  }

  function _runWakeRecognizer() {
    if (!SESSION.wakeActive) return;
    const Ctor = getRecognitionCtor();
    const rec = new Ctor();
    SESSION.wakeRecognizer = rec;
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";
    rec.onresult = function (e) {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const alt = e.results[i] && e.results[i][0];
        if (alt && alt.transcript && matchesWakePhrase(alt.transcript)) { onWakeWordDetected(); return; }
      }
    };
    rec.onerror = function (e) {
      // "no-speech" fires routinely on every silent gap - not a real error, never counted.
      if (e.error === "no-speech" || e.error === "aborted") return;
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        SESSION.wakeActive = false;
        setState(STATE.ERROR);
        setStatus("Microphone blocked — allow microphone access to use wake-word listening.");
        return;
      }
      SESSION.wakeErrorCount++;
    };
    rec.onend = function () {
      if (!SESSION.wakeActive) return;      // stopped deliberately (toggled off, or wake word matched)
      if (SESSION.wakeErrorCount > 6) {     // stop retrying forever after repeated real failures
        SESSION.wakeActive = false;
        setState(STATE.ERROR);
        setStatus("Wake-word listening kept failing — tap the mic to talk instead.");
        return;
      }
      // Browsers silently end "continuous" recognition after a while (commonly ~60s of quiet) -
      // restarting here is what makes wake-word listening actually persistent, not one-shot.
      const delay = Math.min(4000, 300 * Math.pow(2, SESSION.wakeErrorCount));
      SESSION.wakeRestartTimer = setTimeout(function () { if (SESSION.wakeActive) _runWakeRecognizer(); }, delay);
    };
    try { rec.start(); } catch (e) { SESSION.wakeErrorCount++; rec.onend(); }
  }

  function stopWakeListening() {
    if (!SESSION.wakeActive && !SESSION.wakeRecognizer) return;
    SESSION.wakeActive = false;
    if (SESSION.wakeRestartTimer) { clearTimeout(SESSION.wakeRestartTimer); SESSION.wakeRestartTimer = null; }
    if (SESSION.wakeRecognizer) { try { SESSION.wakeRecognizer.stop(); } catch (e) {} SESSION.wakeRecognizer = null; }
    if (!SESSION.active) setState(STATE.IDLE);
    refreshUI();
  }

  // A short two-tone chime — the "activation sound/acknowledgement" — synthesised locally with
  // the Web Audio API rather than round-tripping a file from the server, so it plays the instant
  // the wake word is recognised (mirrors services/text_to_speech.py's notification_sound(), which
  // uses the same two notes for the due-reminder chime, just generated client-side here for speed).
  function playChime() {
    try {
      const ctx = SESSION.ctx || new (window.AudioContext || window.webkitAudioContext)();
      [[880, 0], [1320, 0.12]].forEach(function (nf) {
        const osc = ctx.createOscillator(); const gain = ctx.createGain();
        osc.frequency.value = nf[0]; osc.type = "sine";
        osc.connect(gain); gain.connect(ctx.destination);
        const t0 = ctx.currentTime + nf[1];
        gain.gain.setValueAtTime(0, t0);
        gain.gain.linearRampToValueAtTime(0.18, t0 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, t0 + 0.22);
        osc.start(t0); osc.stop(t0 + 0.24);
      });
    } catch (e) {}
  }

  async function onWakeWordDetected() {
    if (!SESSION.wakeActive) return;
    stopWakeListening();           // release the lightweight recognizer before opening the full mic session
    setState(STATE.AWAKE);
    playChime();
    await new Promise(function (r) { setTimeout(r, 260); });   // let the chime finish before recording starts
    await startSession();
    SESSION.wakeMode = true;       // marks this session as wake-triggered (see returnToListening())
  }

  window.awaazToggleWakeWord = function () {
    if (SESSION.wakeActive) { stopWakeListening(); return; }
    if (SESSION.active) return;    // a full session already has the mic; nothing to toggle
    startWakeListening();
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
EAR_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">'
          '<path stroke-linecap="round" stroke-linejoin="round" d="M8 13a5 5 0 1 1 5 5c-1.5 0-2-1-2-2v-2a2 2 0 0 0-2-2'
          'M14.5 5.5a7 7 0 0 0-9 9.5c.6 1.4 1 2 1 3.5"/></svg>')
HOME_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
           '<path d="M4 11.5 12 4l8 7.5"/><path d="M6 10v9a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-9"/></svg>')
CHAT_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
           '<path d="M4 5.5h16v10H9l-4 3.5v-3.5H4z"/></svg>')
PLUS_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round">'
           '<path d="M12 5v14M5 12h14"/></svg>')
SPEAKER_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
              '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 9a4 4 0 0 1 0 6M19 6.5a7.5 7.5 0 0 1 0 11"/></svg>')
MINIMIZE_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">'
                '<path d="M6 12h12"/></svg>')

def topbar_html() -> str:
    """Bookended by two rounded-pill icon clusters — Home / Chat / + on the left, Gear / Speaker
    on the right — each firing a real existing action (never decorative chrome):
    Home focuses the composer, Chat opens the conversation drawer, + starts a new conversation
    (forwarded to the real, already-wired #new-chat-btn), Gear opens the same drawer to its
    settings footer, Speaker stops whatever Awaaz is currently speaking."""
    return f"""
<div id="topbar">
  <div class="pill-cluster">
    <button class="pill-icon" onclick="awaazFocusComposer()" title="Home">{HOME_SVG}</button>
    <button class="pill-icon sidebar-opener" onclick="awaazToggleSidebar()" title="Conversations">{CHAT_SVG}</button>
    <button class="pill-icon pill-icon--plus" onclick="document.getElementById('new-chat-btn')?.click()" title="New chat">{PLUS_SVG}</button>
    <button class="pill-icon" onclick="awaazSetNotch('panel'); requestAnimationFrame(awaazPositionNotchPanel)" title="Minimize">{MINIMIZE_SVG}</button>
  </div>
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
  <div class="pill-cluster">
    <button class="pill-icon sidebar-opener" onclick="awaazToggleSidebar()" title="Settings &amp; conversations">{GEAR_SVG}</button>
    <button class="pill-icon" onclick="awaazStopSpeaking()" title="Stop speaking">{SPEAKER_SVG}</button>
  </div>
</div>"""


def mascot_html(size: str = "sm") -> str:
    """A small white blob with two dot eyes that track the cursor (see awaazTrackMascotEyes in
    theme.JS). size: 'sm' for the collapsed pill, 'lg' for the panel's hero card."""
    return f'<div class="mascot mascot-{size}"><span class="mascot-eye"></span><span class="mascot-eye"></span></div>'


def notch_launcher_html() -> str:
    """The Coucou-style collapsed state: a small pill, draggable anywhere on screen (see
    awaazInitNotchDrag in theme.JS), with the mascot plus a purely decorative 2x2 grid of
    dot-capsules (no icons/labels - those only appear once the panel below is open). A plain
    click (no real movement) opens notch_panel_html()'s quick view; nothing here is ever rebuilt
    or refetched, state switches only toggle visibility (see CSS: html[data-notch]). No onclick
    here - open-vs-drag is decided in JS so a drag never also fires a click."""
    pips = "".join(
        f'<span class="notch-pip badge-{color}"><span class="notch-pip-dot"></span><span class="notch-pip-dot"></span></span>'
        for color in ("green", "amber", "purple", "pink")
    )
    return f"""
<div class="notch-launcher">
  {mascot_html("sm")}
  <div class="notch-pips">{pips}</div>
</div>"""


def notch_panel_html() -> str:
    """The Coucou-style quick view shown right after tapping the pill: a status/launch card next
    to a grid of Tasks/Reminders/Weather/System, each opening its own modal directly (see
    awaazOpenModal, already wired elsewhere) without needing to open the chat view at all. The
    hero card opens the chat view itself (see chat_view_header_html() below) - the single
    "opened" interface, holding the live conversation and voice controls. Live task/reminder
    counts are kept in sync with the real (off-screen) data cards by syncNotchCounts() in
    theme.JS."""
    tiles = "".join(f"""
  <button class="notch-tile" onclick="awaazOpenModal('{name}')">
    <span class="badge badge-{color}">{icon}</span>
    <span class="notch-tile-label"><span>{label}</span>{f'<small id="notch-tile-{name}-count"></small>' if count_id else ''}</span>
  </button>""" for name, color, icon, label, count_id in (
        ("tasks", "green", CHECKLIST_SVG, "Tasks", True),
        ("reminders", "amber", BELL_SVG, "Reminders", True),
        ("weather", "sky", CLOUD_SVG, "Weather", False),
        ("system", "blue", CPU_SVG, "System", False),
    ))
    return f"""
<div class="notch-panel">
  <button class="notch-hero" onclick="awaazSetNotch('full')">
    {mascot_html("lg")}
    <div class="notch-hero-body">
      <div class="notch-hero-title">Awaaz</div>
      <div class="notch-hero-status"><span class="dot"></span>Online</div>
      <div class="notch-hero-cta">Open Awaaz →</div>
    </div>
  </button>
  <div class="notch-grid">{tiles}</div>
</div>"""


def chat_view_header_html() -> str:
    """Static header shell for #chat-view (see app.py's build_ui): mascot + an ambient glow +
    title. Placed in the same gr.Row as the real Clear/Extract gr.Button components, which need
    real click wiring so they're not part of this raw HTML string. Mascot+title are wrapped in
    their own inline flex row here (not left to the outer Row) because Gradio renders this whole
    gr.HTML block as a single flex child of that Row - without their own row, they'd stack
    vertically as plain block content instead of sitting side by side, inflating the header."""
    return f"""
<div class="chat-view-glow"></div>
<div class="chat-view-brand">{mascot_html("md")}<span class="chat-view-title">Awaaz</span></div>"""


def conversation_welcome_html() -> str:
    """Empty on purpose: the chat view's own mascot header already carries the "Awaaz" branding,
    so an empty conversation just leaves this area blank rather than repeating a welcome message
    - keeps the card short instead of reserving a tall block of space for it."""
    return ""


def voice_orb_html() -> str:
    """The center hero: a purely client-driven voice-session visual. No Python data — the JS
    state machine (see JS above) drives every dynamic bit of it (orb glow, wave bars, status
    pill, mic/wake button state) by id/class, so this only needs to render once."""
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
  <button class="dock-btn dock-btn--wake" onclick="awaazToggleWakeWord()"
         title="Toggle passive wake-word listening (say &quot;Hey Aawaz&quot;)">{EAR_SVG}</button>
  <div class="mic-btn-group" style="display:flex;flex-direction:column;align-items:center;gap:8px;">
    <button class="dock-btn dock-btn--mic" onclick="awaazMicTap()" title="Tap to talk hands-free">{MIC_SVG}</button>
    <button id="end-conv-btn" onclick="awaazEndConversation()" title="End the conversation">✕ End</button>
  </div>
  <button class="dock-btn" onclick="awaazFocusComposer()" title="Type instead">{KEYBOARD_SVG}</button>
  <button class="dock-btn" onclick="awaazToggleSidebar()" title="Conversation history">{CLOCK_SVG}</button>
</div>"""


# ── dashboard widgets (pure HTML builders — app.py supplies the data) ───────

def panel(title: str, body_html: str, count: int | str | None = None, icon_svg: str = "",
         onclick: str = "", badge: str = "blue") -> str:
    """badge: 'blue' | 'sky' | 'green' | 'amber' | 'purple' — one of the badge-* classes in CSS,
    so each dashboard card reads as a distinct colour at a glance (see app.py call sites)."""
    n = f'<span class="count-pill">{html.escape(str(count))}</span>' if count is not None else ""
    cls = "card clickable" if onclick else "card"
    click_attr = f' onclick="{html.escape(onclick, quote=True)}"' if onclick else ""
    icon = f'<span class="badge badge-{html.escape(badge, quote=True)}">{icon_svg}</span>' if icon_svg else ""
    return (f'<div class="{cls}"{click_attr}><div class="card-head"><div class="card-title">{icon}'
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


def task_list(rows: list[tuple[int, str, str, str, bool]], empty: str) -> str:
    """rows = [(task_id, title, tag_text, tag_class, done)]; tag_class is 'due-today'|'overdue'|'due-later'.
    The checkbox is clickable (awaazToggleTask, wired in app.py to the real tasks.set_task_status
    backend) - event.stopPropagation() on it is what keeps a click inside the compact card from
    also triggering the card's own onclick that opens the detail modal."""
    if not rows:
        return f'<div class="list-empty">{html.escape(empty)}</div>'
    items = []
    for task_id, title, tag_text, tag_class, done in rows:
        cls = "task-item done" if done else "task-item"
        tag = "done-tag" if done else tag_class
        tag_text = "Done" if done else tag_text
        next_state = "pending" if done else "done"
        check = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">'
                '<path stroke-linecap="round" stroke-linejoin="round" d="M4 12l5 5L20 6"/></svg>') if done else ""
        items.append(f'<div class="{cls}">'
                    f'<span class="task-check" onclick="awaazToggleTask(event, {task_id})" '
                    f'title="Mark {next_state}">{check}</span>'
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
