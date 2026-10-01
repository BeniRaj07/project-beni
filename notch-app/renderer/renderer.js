"use strict";

const pill = document.getElementById("pill");
const collapsedView = document.getElementById("collapsed-view");
const expandedView = document.getElementById("expanded-view");
const collapsedSummary = document.getElementById("collapsed-summary");
const tasksList = document.getElementById("tasks-list");
const remindersList = document.getElementById("reminders-list");
const tasksCount = document.getElementById("tasks-count");
const emptyState = document.getElementById("empty-state");

let latest = { tasks: { items: [], pendingCount: 0 }, reminders: { items: [] }, dataFound: true };

pill.addEventListener("click", () => window.awaazNotch.toggleExpand());

window.awaazNotch.onExpandedChange((isExpanded) => {
  collapsedView.hidden = isExpanded;
  expandedView.hidden = !isExpanded;
  if (isExpanded) render();
});

window.awaazNotch.onData((payload) => {
  latest = payload;
  renderCollapsedSummary();
  if (!expandedView.hidden) render();
});

function renderCollapsedSummary() {
  const { pendingCount } = latest.tasks;
  const nextReminder = latest.reminders.items[0];
  if (!latest.dataFound) {
    collapsedSummary.textContent = "Awaaz — no data yet";
    return;
  }
  const bits = [];
  if (pendingCount > 0) bits.push(`${pendingCount} task${pendingCount === 1 ? "" : "s"}`);
  if (nextReminder) bits.push(`next: ${reminderClock(nextReminder.nextDueAt)}`);
  collapsedSummary.textContent = bits.length ? bits.join(" · ") : "All clear";
}

function render() {
  emptyState.hidden = latest.dataFound;
  if (!latest.dataFound) {
    tasksList.innerHTML = "";
    remindersList.innerHTML = "";
    tasksCount.textContent = "";
    return;
  }

  tasksCount.textContent = `${latest.tasks.items.filter((t) => !t.done).length}/${latest.tasks.items.length}`;
  tasksList.innerHTML = latest.tasks.items.length
    ? latest.tasks.items.map(taskRow).join("")
    : '<div class="list-empty">No tasks this month</div>';

  remindersList.innerHTML = latest.reminders.items.length
    ? latest.reminders.items.map(reminderRow).join("")
    : '<div class="list-empty">No upcoming reminders</div>';
}

function taskRow(t) {
  const cls = t.done ? "task-item done" : "task-item";
  const tagText = t.done ? "done" : t.tag === "overdue" ? "overdue" : t.tag === "today" ? "today" : t.dueDate || "";
  return (
    `<div class="${cls}">` +
    `<span class="dot-check"></span>` +
    `<span class="task-title">${escapeHtml(t.title)}</span>` +
    (tagText ? `<span class="task-tag ${t.tag}">${escapeHtml(tagText)}</span>` : "") +
    `</div>`
  );
}

function reminderRow(r) {
  const due = new Date(r.nextDueAt);
  const isDue = due <= new Date();
  return (
    `<div class="reminder-item${isDue ? " due" : ""}">` +
    `<span class="reminder-time">${reminderClock(r.nextDueAt)}</span>` +
    `<span class="reminder-title">${escapeHtml(r.title)}</span>` +
    `</div>`
  );
}

function reminderClock(isoString) {
  const d = new Date(isoString);
  let hour = d.getHours() % 12;
  if (hour === 0) hour = 12;
  const minute = String(d.getMinutes()).padStart(2, "0");
  const ampm = d.getHours() < 12 ? "AM" : "PM";
  return `${hour}:${minute} ${ampm}`;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
