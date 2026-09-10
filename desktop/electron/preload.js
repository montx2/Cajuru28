/**
 * Preload script - expõe APIs seguras para o renderer
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('notasflow', {
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),
  getCredentials: () => ipcRenderer.invoke('get-credentials'),
  openDataFolder: () => ipcRenderer.invoke('open-data-folder'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  
  // Eventos de atualização
  onUpdateAvailable: (callback) => ipcRenderer.on('update-available', callback),
  onUpdateDownloaded: (callback) => ipcRenderer.on('update-downloaded', callback),
  onUpdateProgress: (callback) => ipcRenderer.on('update-progress', callback),
  
  // Versão
  version: process.env.npm_package_version || '1.0.0',
  platform: process.platform,
});

contextBridge.exposeInMainWorld('electron', {
  isDesktop: true,
});
