import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PythonBridge } from './python-bridge.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESKTOP = path.resolve(HERE, '..');
const ROOT = path.resolve(DESKTOP, '..');
const PRODUCT_ID = 'com.demonx.pcbprep';
app.setName('DemonX PCB Prep');
if (process.platform === 'win32') app.setAppUserModelId(PRODUCT_ID);
const ownsLock = app.requestSingleInstanceLock();
let window = null;
let bridge = null;
let child = null;
let stopping = false;
let openedAtLaunch = null;
let pendingOpenPath = null;
let logStream = null;

function log(message) {
  const line = `${new Date().toISOString()} ${message}\n`;
  try { logStream?.write(line); } catch {}
  process.stderr.write(line);
}
log(`Main process started; Electron ${process.versions.electron}, Node ${process.versions.node}.`);
log(`Single-instance lock ${ownsLock ? 'acquired' : 'already held'}.`);
function archiveArg(args) {
  const candidate = args.find(x => typeof x === 'string' && x.toLowerCase().endsWith('.zip') && fs.existsSync(x));
  return candidate ? path.resolve(candidate) : null;
}
function pythonLaunch() {
  if (app.isPackaged) {
    const exe = process.platform === 'win32' ? 'pcbprep-engine.exe' : 'pcbprep-engine';
    return { command: path.join(process.resourcesPath, 'engine', exe), args: [] };
  }
  const python = process.platform === 'win32'
    ? path.join(DESKTOP, '.venv', 'Scripts', 'python.exe')
    : path.join(DESKTOP, '.venv', 'bin', 'python');
  return { command: python, args: ['-u', path.join(HERE, '..', 'engine', 'bridge.py')] };
}
function cleanEngineEnvironment() {
  const keys = ['SystemRoot','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','HOME','TMPDIR','LANG','LC_ALL','LC_CTYPE'];
  const env = Object.fromEntries(keys.filter(k => typeof process.env[k] === 'string').map(k => [k, process.env[k]]));
  env.PYTHONNOUSERSITE = '1'; env.PYTHONDONTWRITEBYTECODE = '1'; env.PYTHONUTF8 = '1';
  env.DEMONX_PCBPREP_WORK_ROOT = path.join(app.getPath('userData'), 'work');
  return env;
}
function assertTrusted(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame)
    throw new Error('Untrusted IPC sender');
  try {
    const url = fileURLToPath(event.senderFrame.url);
    if (path.resolve(url) !== path.resolve(path.join(DESKTOP, 'ui', 'index.html'))) throw new Error('Unexpected application frame');
  } catch { throw new Error('Unexpected application frame'); }
}
async function startEngine() {
  const launch = pythonLaunch();
  if (!fs.existsSync(launch.command)) throw new Error(`PCB engine runtime is missing: ${launch.command}`);
  child = spawn(launch.command, launch.args, { cwd: app.isPackaged ? app.getPath('userData') : ROOT, env: cleanEngineEnvironment(), stdio: ['pipe','pipe','pipe'], windowsHide: true, shell: false });
  child.stderr.on('data', b => log(`Engine stderr: ${b.toString('utf8').slice(0, 4000)}`));
  child.on('exit', (code, signal) => {
    if (!stopping) {
      log(`Engine exited unexpectedly: ${code ?? signal}`);
      const diagnostic = path.join(app.getPath('userData'), 'logs');
      dialog.showErrorBox('DemonX PCB Prep engine stopped', `The geometry engine exited unexpectedly. Diagnostics: ${diagnostic}`);
      app.quit();
    }
  });
  bridge = new PythonBridge(child);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Python engine readiness timed out')), 15000);
    bridge.onReady = msg => {
      if (msg.engine !== 'pcbprep-python' || msg.readOnly !== true) { clearTimeout(timer); reject(new Error('Python engine identity check failed')); return; }
      clearTimeout(timer); resolve();
    };
    child.once('error', e => { clearTimeout(timer); reject(e); });
    child.once('exit', code => { if (!stopping) reject(new Error(`Python engine exited during startup (${code})`)); });
  });
  log('Python geometry engine ready (stdio protocol v1).');
}
function createWindow() {
  const iconRoot = app.isPackaged ? path.join(process.resourcesPath, 'branding') : path.join(ROOT, 'assets', 'DemonX-PCB-Prep');
  const icon = process.platform === 'win32' ? path.join(iconRoot, 'Windows', 'DemonX-PCB-Prep.ico') : path.join(iconRoot, 'Linux', '512x512', 'apps', 'DemonX-PCB-Prep.png');
  window = new BrowserWindow({
    width: 1560, height: 980, minWidth: 1050, minHeight: 700, show: false,
    title: 'DemonX PCB Prep', icon: fs.existsSync(icon) ? icon : undefined,
    backgroundColor: '#0b1118', autoHideMenuBar: false,
    webPreferences: { preload: path.join(HERE, 'preload.cjs'), contextIsolation: true, nodeIntegration: false,
      sandbox: true, webSecurity: true, webviewTag: false, allowRunningInsecureContent: false }
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => {
    try { if (path.resolve(fileURLToPath(url)) !== path.resolve(path.join(DESKTOP, 'ui', 'index.html'))) event.preventDefault(); }
    catch { event.preventDefault(); }
  });
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.webContents.on('render-process-gone', (_event, details) => {
    log(`Renderer exited: ${details.reason}`);
    if (details.reason !== 'clean-exit') dialog.showErrorBox('DemonX PCB Prep', `The application window stopped unexpectedly. Diagnostics: ${app.getPath('userData')}`);
  });
  window.on('closed', () => { window = null; });
  window.webContents.once('did-finish-load', () => {
    window?.show();
    log('Application window ready.');
    if (pendingOpenPath) {
      const archivePath = pendingOpenPath;
      pendingOpenPath = null;
      void openPath(archivePath);
    }
  });
  window.loadFile(path.join(DESKTOP, 'ui', 'index.html')).catch(error => {
    log(`Window load failed: ${error.stack || error}`);
    dialog.showErrorBox('DemonX PCB Prep startup failed', String(error));
    app.quit();
  });
}
function registerIpc() {
  ipcMain.handle('pcb:open', async event => {
    assertTrusted(event);
    const picked = await dialog.showOpenDialog(window, { title: 'Open Gerber ZIP', properties: ['openFile'], filters: [{ name: 'Gerber archive', extensions: ['zip'] }] });
    if (picked.canceled || !picked.filePaths[0]) return { cancelled: true };
    const archivePath = picked.filePaths[0];
    if (fs.statSync(archivePath).size > 64 * 1024 * 1024) throw new Error('ZIP exceeds 64 MiB import limit.');
    return bridge.request('open', { archivePath }, message => window?.webContents.send('pcb:progress', message));
  });
  ipcMain.handle('pcb:simulate', async (event, options) => {
    assertTrusted(event);
    return bridge.request('simulate', { options }, message => window?.webContents.send('pcb:progress', message));
  });
  ipcMain.handle('pcb:cancel', event => { assertTrusted(event); bridge?.cancel(); return true; });
  ipcMain.handle('pcb:open-diagnostics', async event => {
    assertTrusted(event);
    return shell.openPath(path.join(app.getPath('userData'), 'logs'));
  });
}
async function openPath(archivePath) {
  if (!archivePath || !bridge) return;
  if (!window || window.webContents.isLoadingMainFrame()) { pendingOpenPath = archivePath; return; }
  try {
    if (fs.statSync(archivePath).size > 64 * 1024 * 1024) throw new Error('ZIP exceeds 64 MiB import limit.');
    const result = await bridge.request('open', { archivePath }, message => window?.webContents.send('pcb:progress', message));
    window?.webContents.send('pcb:opened', result);
  } catch (error) {
    log(`File-open request failed: ${error.stack || error}`);
    dialog.showErrorBox('Could not open Gerber ZIP', String(error.message || error));
  }
}
if (!ownsLock) {
  app.quit();
} else {
  openedAtLaunch = archiveArg(process.argv);
  app.on('second-instance', (_event, argv) => {
    const archivePath = archiveArg(argv);
    if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus(); }
    if (archivePath) void openPath(archivePath);
  });
  app.whenReady().then(async () => {
    log('Electron application is ready.');
    let dataDir = '';
    try {
      dataDir = app.getPath('userData');
      fs.mkdirSync(path.join(dataDir, 'logs'), { recursive: true });
      logStream = fs.createWriteStream(path.join(dataDir, 'logs', 'desktop.log'), { flags: 'a' });
      await startEngine(); createWindow(); registerIpc();
      if (openedAtLaunch) pendingOpenPath = openedAtLaunch;
    } catch (error) {
      log(`Startup failed: ${error.stack || error}`);
      dialog.showErrorBox('DemonX PCB Prep startup failed', `${error.message || error}\n\nDiagnostics: ${dataDir ? path.join(dataDir, 'logs', 'desktop.log') : 'The application data folder could not be opened.'}`);
      stopping = true; child?.kill(); app.exit(1);
    }
  });
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else { window?.show(); window?.focus(); }
  });
  let quitRequested = false;
  app.on('before-quit', event => {
    if (quitRequested) return;
    event.preventDefault(); quitRequested = true; stopping = true;
    void (bridge?.shutdown() || Promise.resolve()).finally(() => { logStream?.end(); app.exit(0); });
  });
  app.on('window-all-closed', () => app.quit());
  process.on('uncaughtException', error => {
    log(`Uncaught exception: ${error.stack || error}`);
    if (!stopping) dialog.showErrorBox('DemonX PCB Prep error', String(error));
    app.quit();
  });
}
