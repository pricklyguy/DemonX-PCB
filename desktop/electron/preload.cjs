const { contextBridge, ipcRenderer } = require('electron');
if (process.isMainFrame) {
  contextBridge.exposeInMainWorld('demonxPCB', Object.freeze({
    openGerber: () => ipcRenderer.invoke('pcb:open'),
    simulate: options => ipcRenderer.invoke('pcb:simulate', options),
    cancel: () => ipcRenderer.invoke('pcb:cancel'),
    openDiagnostics: () => ipcRenderer.invoke('pcb:open-diagnostics'),
    onProgress: callback => { if (typeof callback !== 'function') return () => {}; const listener=(_e,message)=>callback(message); ipcRenderer.on('pcb:progress',listener); return () => ipcRenderer.removeListener('pcb:progress',listener); },
    onOpened: callback => { if (typeof callback !== 'function') return () => {}; const listener=(_e,result)=>callback(result); ipcRenderer.on('pcb:opened',listener); return () => ipcRenderer.removeListener('pcb:opened',listener); }
  }));
}
