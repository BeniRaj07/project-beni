// Awaaz Notch — a floating pill at the top of the screen showing live tasks/reminders.
//
// Deliberately reads data/tasks.json and data/reminders.json directly off disk (the exact
// files Awaaz's own database/json_store.py already writes — see database/models.py for the
// schema this mirrors) instead of talking to the Python app over a network API. That keeps
// this widget fully decoupled: it works whether or not `python app.py` is currently running,
// needs zero changes to the Python side, and can never block/crash the main Awaaz app.
"use strict";

const { app, BrowserWindow, screen, Notification, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");

// ── where Awaaz's data/ folder lives ────────────────────────────────────────
// Defaults to the sibling "data" folder (this app is meant to live at
// project-beni/notch-app/, right next to project-beni/data/). Override with the
// AWAAZ_DATA_DIR env var if you run Awaaz from somewhere else.
const DATA_DIR = process.env.AWAAZ_DATA_DIR || path.join(__dirname, "..", "data");
const TASKS_FILE = path.join(DATA_DIR, "tasks.json");
const REMINDERS_FILE = path.join(DATA_DIR, "reminders.json");

const COLLAPSED = { width: 280, height: 36 };
const EXPANDED = { width: 340, height: 460 };
const POLL_MS = 8000; // re-read the JSON files this often (cheap: two small local file reads)
const NOTIFY_CHECK_MS = 20000; // how often to check for newly-due reminders

let win = null;
let expanded = false;
const notifiedOccurrences = new Set(); // "<reminderId>:<next_due_at>" already notified this run

function topCenterBounds(size) {
  const display = screen.getPrimaryDisplay();
  const x = Math.round(display.bounds.x + (display.bounds.width - size.width) / 2);
  return { x, y: display.bounds.y, width: size.width, height: size.height };
}

function createWindow() {
  win = new BrowserWindow({
    ...topCenterBounds(COLLAPSED),
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    hasShadow: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    fullscreenable: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setAlwaysOnTop(true, "screen-saver");
  // pushData() right after loadFile() would race the renderer — preload.js's ipcRenderer.on
  // listener isn't guaranteed to be attached yet, so an immediate send() can be silently
  // dropped, leaving the widget showing nothing until the next POLL_MS interval fires. Waiting
  // for did-finish-load guarantees the very first push always lands.
  win.webContents.once("did-finish-load", () => pushData());
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  return win;
}

// ── read + shape the JSON files into what the renderer actually displays ───

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    return null; // missing or still mid-write (atomic replace means this is rare and self-heals next poll)
  }
}

/** Mirrors app.py's _task_due_label/_task_tag_class: 'overdue' once past due_date, 'due-today'
 * for today, else plain date. Deleted tasks never surface here. */
function summarizeTasks(raw) {
  if (!raw || !raw.tasks) return { items: [], pendingCount: 0 };
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD, same lexicographic form as due_date
  const items = Object.values(raw.tasks)
    .filter((t) => t.status !== "deleted")
    .map((t) => ({
      id: t.id,
      title: t.title,
      done: t.status === "completed",
      dueDate: t.due_date || null,
      tag: !t.due_date ? "later" : t.due_date < today ? "overdue" : t.due_date === today ? "today" : "later",
    }))
    .sort((a, b) => (a.dueDate || "9999").localeCompare(b.dueDate || "9999"));
  return { items: items.slice(0, 8), pendingCount: items.filter((t) => !t.done).length };
}

/** Mirrors app.py's reminder ordering: soonest-due first, active only. */
function summarizeReminders(raw) {
  if (!raw || !raw.reminders) return { items: [], dueNow: [] };
  const now = new Date();
  const active = Object.values(raw.reminders).filter((r) => r.status === "active");
  const items = active
    .map((r) => ({ id: r.id, title: r.title, nextDueAt: r.next_due_at, recurrence: r.recurrence }))
    .sort((a, b) => new Date(a.nextDueAt) - new Date(b.nextDueAt));
  const dueNow = active.filter((r) => new Date(r.next_due_at) <= now);
  return { items: items.slice(0, 8), dueNow };
}

function pushData() {
  if (!win || win.isDestroyed()) return;
  const tasks = summarizeTasks(readJson(TASKS_FILE));
  const reminders = summarizeReminders(readJson(REMINDERS_FILE));
  win.webContents.send("awaaz-data", {
    tasks: { items: tasks.items, pendingCount: tasks.pendingCount },
    reminders: { items: reminders.items },
    dataFound: fs.existsSync(TASKS_FILE) || fs.existsSync(REMINDERS_FILE),
  });
}

/** Independent of the Gradio app's own in-browser reminder polling — this fires a real macOS
 * notification even when no Awaaz browser tab is open, which is the whole point of a notch
 * widget. Dedup is in-memory per reminder occurrence (reminder id + its exact next_due_at),
 * so a recurring reminder notifies again once json_store.py advances it to its next occurrence. */
function checkDueReminders() {
  const raw = readJson(REMINDERS_FILE);
  if (!raw || !raw.reminders) return;
  const now = new Date();
  for (const r of Object.values(raw.reminders)) {
    if (r.status !== "active") continue;
    const dueAt = new Date(r.next_due_at);
    if (dueAt > now) continue;
    const key = `${r.id}:${r.next_due_at}`;
    if (notifiedOccurrences.has(key)) continue;
    notifiedOccurrences.add(key);
    if (Notification.isSupported()) {
      new Notification({ title: "Awaaz reminder", body: r.title, silent: false }).show();
    }
  }
  // keep the dedup set from growing forever across a long-running session
  if (notifiedOccurrences.size > 500) notifiedOccurrences.clear();
}

// ── collapse / expand, driven by the renderer's click handler ──────────────

ipcMain.on("awaaz-toggle-expand", () => {
  if (!win || win.isDestroyed()) return;
  expanded = !expanded;
  win.setBounds(topCenterBounds(expanded ? EXPANDED : COLLAPSED));
  win.webContents.send("awaaz-expanded", expanded);
});

app.whenReady().then(() => {
  createWindow(); // pushes its own first data once the renderer signals did-finish-load
  setInterval(pushData, POLL_MS);
  setInterval(checkDueReminders, NOTIFY_CHECK_MS);
  checkDueReminders();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
