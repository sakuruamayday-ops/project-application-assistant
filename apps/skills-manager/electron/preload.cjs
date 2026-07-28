const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jiaotang", {
  overview: () => ipcRenderer.invoke("app:overview"),
  scanPlatforms: () => ipcRenderer.invoke("platforms:scan"),
  connectPortal: (payload) => ipcRenderer.invoke("portal:connect", payload),
  disconnectPortal: () => ipcRenderer.invoke("portal:disconnect"),
  chooseDirectory: () => ipcRenderer.invoke("directory:choose"),
  downloadAndVerify: (channelId) => ipcRenderer.invoke("artifact:download-verify", { channelId }),
  planGenericInstall: (payload) => ipcRenderer.invoke("install:plan-generic", payload),
  executeGenericInstall: (planId) => ipcRenderer.invoke("install:execute-generic", {
    planId,
    confirmation: "INSTALL",
  }),
  planDetectedInstall: () => ipcRenderer.invoke("install:plan-detected"),
  executeDetectedInstall: (batchId) => ipcRenderer.invoke("install:execute-detected", {
    batchId,
    confirmation: "INSTALL_ALL",
  }),
  rollback: (targetRoot) => ipcRenderer.invoke("install:rollback", {
    targetRoot,
    confirmation: "ROLLBACK",
  }),
  revealPath: (value) => ipcRenderer.invoke("path:reveal", value),
  showItem: (value) => ipcRenderer.invoke("path:show-item", value),
});
