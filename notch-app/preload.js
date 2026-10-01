"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("awaazNotch", {
  onData: (callback) => ipcRenderer.on("awaaz-data", (_event, payload) => callback(payload)),
  onExpandedChange: (callback) => ipcRenderer.on("awaaz-expanded", (_event, isExpanded) => callback(isExpanded)),
  toggleExpand: () => ipcRenderer.send("awaaz-toggle-expand"),
});
