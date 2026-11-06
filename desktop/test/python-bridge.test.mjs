import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { PythonBridge, PROTOCOL } from '../electron/python-bridge.mjs';

class FakeChild extends EventEmitter {
  constructor() {
    super();
    this.stdin = new PassThrough();
    this.stdout = new PassThrough();
    this.stderr = new PassThrough();
    this.writes = '';
    this.stdin.on('data', chunk => { this.writes += chunk.toString(); });
  }
  reply(value) { this.stdout.write(`${JSON.stringify({ protocol: PROTOCOL, ...value })}\n`); }
  kill() { this.emit('exit', 0, null); }
}

test('routes a versioned request and reports progress before the result', async () => {
  const child = new FakeChild();
  const bridge = new PythonBridge(child);
  child.reply({ event: 'ready', engine: 'pcbprep-python', readOnly: true });
  assert.equal(bridge.ready, true);
  const progress = [];
  const resultPromise = bridge.request('open', { archivePath: 'sample.zip' }, msg => progress.push(msg));
  const request = JSON.parse(child.writes.trim());
  child.reply({ event: 'progress', requestId: request.requestId, message: 'Parsing copper' });
  child.reply({ event: 'result', requestId: request.requestId, result: { boardId: 'sample', findings: [] } });
  assert.deepEqual(progress, ['Parsing copper']);
  assert.deepEqual(await resultPromise, { boardId: 'sample', findings: [] });
});

test('returns structured engine errors and issues cancellation for the active request', async () => {
  const child = new FakeChild();
  const bridge = new PythonBridge(child);
  child.reply({ event: 'ready', engine: 'pcbprep-python', readOnly: true });
  const pending = bridge.request('simulate', { options: { mode: 'single' } });
  const active = JSON.parse(child.writes.trim());
  bridge.cancel(active.requestId);
  const lines = child.writes.trim().split('\n').map(JSON.parse);
  assert.equal(lines[1].command, 'cancel');
  assert.equal(lines[1].targetRequestId, active.requestId);
  child.reply({ event: 'error', requestId: active.requestId, error: { code: 'NO_BOARD_LOADED', message: 'No board loaded' } });
  await assert.rejects(pending, error => error.code === 'NO_BOARD_LOADED' && error.message === 'No board loaded');
});

test('rejects oversized outgoing requests and fails pending work on process exit', async () => {
  const child = new FakeChild();
  const bridge = new PythonBridge(child);
  child.reply({ event: 'ready', engine: 'pcbprep-python', readOnly: true });
  await assert.rejects(bridge.request('open', { archivePath: 'x'.repeat(140_000) }), /Request too large/);
  const pending = bridge.request('simulate', {});
  child.emit('exit', 2, null);
  await assert.rejects(pending, /PCB engine exited/);
});
