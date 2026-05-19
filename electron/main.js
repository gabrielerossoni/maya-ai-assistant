const { app, BrowserWindow, globalShortcut, dialog, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

let mainWindow;
let pythonProcess;
const PORT = process.env.MAYA_PORT || 8000;
const HEALTH_URL = `http://127.0.0.1:${PORT}/health`;
const DASHBOARD_URL = `http://127.0.0.1:${PORT}`;

function startPython() {
    pythonProcess = spawn('python', ['main.py'], {
        cwd: path.join(__dirname, '..'),
        env: { ...process.env, MAYA_SKIP_BROWSER_OPEN: '1' }
    });

    pythonProcess.stdout.on('data', (data) => {
        process.stdout.write(data);
    });

    pythonProcess.stderr.on('data', (data) => {
        process.stderr.write(data);
    });

    pythonProcess.on('close', (code) => {
        if (code !== 0 && code !== null) {
            console.log(`\n[SYSTEM] Processo terminato con codice ${code}`);
        }
    });
}

async function checkServerReady() {
    const startTime = Date.now();
    const timeout = 30000; // 30s

    while (Date.now() - startTime < timeout) {
        try {
            const isReady = await new Promise((resolve) => {
                http.get(HEALTH_URL, (res) => {
                    resolve(res.statusCode === 200);
                }).on('error', () => {
                    resolve(false);
                });
            });
            if (isReady) return true;
        } catch (err) {
            // Error in check
        }
        await new Promise(resolve => setTimeout(resolve, 500));
    }
    return false;
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        fullscreen: true,
        frame: false,
        transparent: true,
        alwaysOnTop: false,
        icon: path.join(__dirname, '..', 'static', 'maya_logo_no_sfondo.png'),
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true
        }
    });

    // Toggle alwaysOnTop con F12
    globalShortcut.register('F12', () => {
        const isAlwaysOnTop = mainWindow.isAlwaysOnTop();
        mainWindow.setAlwaysOnTop(!isAlwaysOnTop);
        console.log(`AlwaysOnTop: ${!isAlwaysOnTop}`);
    });

    // Escape per layout:orb
    globalShortcut.register('Escape', () => {
        mainWindow.webContents.send('layout-reset');
        // Notifichiamo anche via IPC se necessario per logica interna
        mainWindow.webContents.executeJavaScript('if(typeof setLayout === "function") setLayout("orb")');
    });

    mainWindow.loadURL(DASHBOARD_URL);

    // Gestione link esterni nel browser predefinito
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        if (url.startsWith('http')) {
            require('electron').shell.openExternal(url);
        }
        return { action: 'deny' };
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

app.whenReady().then(async () => {
    startPython();
    
    const isReady = await checkServerReady();
    if (isReady) {
        createWindow();
    } else {
        dialog.showErrorBox('Errore di Avvio', 'Il server Python non è partito entro 30 secondi. L\'applicazione verrà chiusa.');
        app.quit();
    }

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('will-quit', () => {
    if (pythonProcess) {
        console.log('Chiusura processo Python...');
        pythonProcess.kill();
    }
    globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});

ipcMain.on('layout', (event, layout) => {
    console.log(`Layout change requested: ${layout}`);
});
