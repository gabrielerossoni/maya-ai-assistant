const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('maya', {
    sendLayout: (layout) => ipcRenderer.send('layout', layout)
});
