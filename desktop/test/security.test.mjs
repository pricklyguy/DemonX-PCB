import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const main = await readFile(new URL('../electron/main.mjs', import.meta.url), 'utf8');
const preload = await readFile(new URL('../electron/preload.cjs', import.meta.url), 'utf8');
const packageJson = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));

test('Electron window uses isolation, disabled Node integration and sandboxing', () => {
  assert.match(main, /contextIsolation:\s*true/);
  assert.match(main, /nodeIntegration:\s*false/);
  assert.match(main, /sandbox:\s*true/);
  assert.match(main, /webSecurity:\s*true/);
  assert.match(main, /setWindowOpenHandler\(\(\)\s*=>\s*\(\{\s*action:\s*'deny'/);
  assert.match(main, /will-navigate/);
});

test('preload exposes only the narrow PCB Prep bridge and the main process checks senders', () => {
  for (const channel of ['pcb:open', 'pcb:simulate', 'pcb:cancel', 'pcb:open-diagnostics'])
    assert.ok(preload.includes(channel), `missing allowlisted channel ${channel}`);
  assert.match(preload, /contextBridge\.exposeInMainWorld/);
  assert.match(main, /function assertTrusted/);
  assert.match(main, /event\.senderFrame !== window\.webContents\.mainFrame/);
  assert.doesNotMatch(preload, /child_process|shell\.openExternal|send\s*:/);
});

test('second instance activation and packaged resources have explicit product paths', () => {
  assert.match(main, /requestSingleInstanceLock/);
  assert.match(main, /second-instance/);
  assert.match(main, /window\.restore\(\)/);
  assert.match(main, /process\.resourcesPath, 'engine'/);
  assert.match(main, /process\.resourcesPath, 'branding'/);
  assert.equal(packageJson.build.productName, 'DemonX PCB Prep');
  assert.equal(packageJson.build.appId, 'com.demonx.pcbprep');
  assert.ok(packageJson.build.extraResources.some(row => row.to === 'engine'));
});

test('startup and second-instance file-open requests wait for the renderer load', () => {
  assert.match(main, /let pendingOpenPath = null/);
  assert.match(main, /window\.webContents\.isLoadingMainFrame\(\)/);
  assert.match(main, /window\.webContents\.once\('did-finish-load'/);
  assert.match(main, /pendingOpenPath = openedAtLaunch/);
});
