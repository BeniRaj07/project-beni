# Awaaz Notch

A small floating pill that lives at the top of your screen (positioned around your Mac's notch,
Coucou-style) showing your live Awaaz tasks and reminders, with native macOS notifications for
anything that comes due — even when no Awaaz browser tab is open.

## How it works

This is a separate Electron app from the main Awaaz Gradio app. It does **not** call Awaaz over
the network — it reads `data/tasks.json` and `data/reminders.json` directly off disk (the exact
files `database/json_store.py` already writes, validated against the same schema in
`database/models.py`). That means:

- It works whether or not `python app.py` is currently running.
- Zero changes were needed to the Python app.
- It can never slow down or crash the main Awaaz app — it's a read-only, independent process.

It re-reads those two files every 8 seconds, and separately checks every 20 seconds whether any
active reminder's `next_due_at` has passed, firing a real macOS notification for each one (deduped
per occurrence, so a recurring reminder notifies again once it's advanced to its next due time).

## Setup

```bash
cd notch-app
npm install
```

## Run it (development)

```bash
npm start
```

A small pill should appear at the top-center of your screen. Click it to expand into the full
Tasks/Reminders panel; click again to collapse.

By default it looks for Awaaz's data in `../data` (i.e. `project-beni/data/`, right next to this
folder) — the same place `python app.py` already writes to. If your Awaaz data lives somewhere
else, set the environment variable before starting:

```bash
AWAAZ_DATA_DIR=/path/to/your/data npm start
```

## Build a standalone app (so you don't need to run `npm start` every time)

```bash
npm run build:mac
```

This produces a `.dmg` installer under `dist/`. Open it and drag **Awaaz Notch.app** into
Applications, same as any other Mac app. Since it isn't signed with an Apple Developer ID, macOS
will block it the first time — right-click the app → **Open** → confirm, or go to
**System Settings → Privacy & Security** and click **Open Anyway**.

## Adjusting it to your exact notch

This was built and tested in a Linux sandbox without a physical MacBook notch to calibrate
against, so the pill's width/position are a reasonable default, not pixel-measured against your
specific MacBook Air M2 screen. If it looks slightly too narrow/wide once you see it on your
actual display, open `main.js` and adjust these two constants near the top:

```js
const COLLAPSED = { width: 280, height: 36 };
const EXPANDED = { width: 340, height: 460 };
```

The pill is deliberately wider than the physical notch cutout (so it visually "wraps" the notch
rather than needing to fit exactly inside it) — that's the same trick most notch-bar apps use,
since the notch's exact pixel dimensions vary slightly by display scaling setting.

## Quitting it

It has a normal Dock icon — quit it like any other Mac app (right-click the Dock icon → Quit, or
Cmd+Q while it's focused).

## Known limitations

- **Notifications are untested on real hardware** — the due-reminder detection logic itself was
  verified (it correctly identifies overdue reminders from the JSON data with no crashes over
  repeated polling cycles), but actually seeing a native macOS notification banner appear can only
  be confirmed on your Mac, not from this sandbox. If notifications don't appear, check
  **System Settings → Notifications → Awaaz Notch** is allowed to notify.
- **Read-only** — this widget can't check off a task or dismiss a reminder; use the main Awaaz
  app (browser tab) for that. It's a glanceable status display, not a second way to edit your data.
- **No tray icon / menu** — just the pill itself and the Dock icon for now.
