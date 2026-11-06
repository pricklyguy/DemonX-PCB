import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PythonBridge } from './electron/python-bridge.mjs';

const archivePath = process.argv[2];
if (!archivePath) throw new Error('Usage: node real-board-check.mjs <Gerber ZIP>');
const desktop = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(desktop, '..');
const enginePath = path.join(desktop, 'build', 'engine', 'pcbprep-engine.exe');
const child = spawn(enginePath, [], {
  cwd: root,
  env: {
    SystemRoot: process.env.SystemRoot,
    TEMP: process.env.TEMP,
    TMP: process.env.TMP,
    USERPROFILE: process.env.USERPROFILE,
    PYTHONNOUSERSITE: '1',
    PYTHONDONTWRITEBYTECODE: '1',
    DEMONX_PCBPREP_WORK_ROOT: path.join(process.env.TEMP || process.cwd(), 'DemonX-PCB-Prep', 'work', 'real-board')
  },
  stdio: ['pipe', 'pipe', 'pipe'],
  windowsHide: true
});
const bridge = new PythonBridge(child);
await new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('Engine readiness timed out')), 30_000);
  bridge.onReady = message => {
    clearTimeout(timer);
    if (message.engine !== 'pcbprep-python' || message.readOnly !== true) reject(new Error('Unexpected engine identity'));
    else resolve();
  };
  child.once('error', error => { clearTimeout(timer); reject(error); });
});
try {
  const board = await bridge.request('open', { archivePath });
  const single = await bridge.request('simulate', { options: { mode: 'single', angleDeg: 30, tipDiameterMm: 0.1, depthMm: 0.1 } });
  const twoPass = await bridge.request('simulate', { options: { mode: 'two-pass', angleDeg: 30, tipDiameterMm: 0.1, depthMm: 0.1, additionalOffsetMm: 0.2 } });
  const selective = await bridge.request('simulate', { options: { mode: 'selective-clearing', angleDeg: 30, tipDiameterMm: 0.1, depthMm: 0.1, selectedIds: [] } });
  assert.equal(board.validation.machiningEligibility, 'BLOCKED');
  assert.ok(board.layers.some(layer => layer.name === 'top-copper' && layer.path.length > 1000));
  assert.ok(board.layers.some(layer => layer.name === 'bottom-copper' && layer.path.length > 1000));
  assert.ok(board.drills.length > 0);
  assert.ok(board.sourceFeatures.length > 0);
  assert.ok(twoPass.rejections.length > 0);
  assert.ok(selective.candidates.length > 0);
  console.log(JSON.stringify({
    boardId: board.boardId,
    archiveSha256: board.archiveSha256,
    boundsMm: board.boundsMm,
    layers: board.layers.map(layer => ({ name: layer.name, pathBytes: Buffer.byteLength(layer.path) })),
    drills: board.drills.length,
    sourceFindings: board.findings.length,
    sourceFeatures: board.limits.sourceFeatureCount,
    machiningEligibility: board.validation.machiningEligibility,
    geometryStatus: board.geometryStatus,
    singlePass: { contours: single.singlePass.contours, lengthMm: single.singlePass.lengthMm, effectiveWidthMm: single.effectiveWidthMm },
    twoPass: { rejectedLengthMm: twoPass.rejectedLengthMm, collisionFindings: twoPass.rejections.length },
    selectiveClearing: { candidates: selective.candidates.length, rejected: selective.rejections.length },
    parity: 'UNVERIFIED: available ZIP archive SHA differs from the pinned Phase 2O archive SHA'
  }, null, 2));
} finally {
  await bridge.shutdown();
}
