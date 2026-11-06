export const PROTOCOL = 'demonx.pcbprep.engine/1';
const MAX_LINE = 32 * 1024 * 1024;
export class PythonBridge {
  constructor(child) {
    this.child = child; this.pending = new Map(); this.buffer = ''; this.ready = false; this.closed = false;
    child.stdout.setEncoding('utf8'); child.stdout.on('data', chunk => this.#read(chunk));
    child.stderr.on('data', chunk => process.stderr.write(`[pcb-engine] ${chunk}`));
    child.on('error', error => this.#failAll(error));
    child.on('exit', (code, signal) => { this.closed = true; this.#failAll(new Error(`PCB engine exited (${code ?? signal})`)); });
  }
  #read(chunk) {
    this.buffer += chunk;
    if (Buffer.byteLength(this.buffer, 'utf8') > MAX_LINE && !this.buffer.includes('\n')) return this.#failAll(new Error('Engine response exceeded size limit'));
    let i;
    while ((i = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, i); this.buffer = this.buffer.slice(i + 1);
      if (!line || Buffer.byteLength(line, 'utf8') > MAX_LINE) { this.#failAll(new Error('Invalid engine response size')); continue; }
      let msg; try { msg = JSON.parse(line); } catch { this.#failAll(new Error('Invalid JSON from PCB engine')); continue; }
      if (msg.protocol !== PROTOCOL) { this.#failAll(new Error('Unsupported PCB engine protocol')); continue; }
      if (msg.event === 'ready') { this.ready = true; this.onReady?.(msg); continue; }
      const pending = this.pending.get(msg.requestId);
      if (!pending) continue;
      if (msg.event === 'progress') pending.onProgress?.(msg.message);
      else if (msg.event === 'result') { this.pending.delete(msg.requestId); pending.resolve(msg.result); }
      else if (msg.event === 'error') { this.pending.delete(msg.requestId); pending.reject(Object.assign(new Error(msg.error?.message || 'Engine error'), {code:msg.error?.code || 'ENGINE_ERROR'})); }
      else if (msg.event === 'cancelled') { this.pending.delete(msg.requestId); pending.reject(Object.assign(new Error(msg.message || 'Cancelled'), {code:'CANCELLED'})); }
    }
  }
  request(command, payload = {}, onProgress) {
    if (this.closed || !this.ready) return Promise.reject(new Error('PCB engine is not ready'));
    const requestId = crypto.randomUUID();
    return new Promise((resolve,reject) => {
      this.pending.set(requestId,{resolve,reject,onProgress});
      const body=JSON.stringify({protocol:PROTOCOL,requestId,command,...payload})+'\n';
      if (Buffer.byteLength(body,'utf8')>128*1024) { this.pending.delete(requestId); reject(new Error('Request too large')); return; }
      this.child.stdin.write(body,error => { if(error){this.pending.delete(requestId);reject(error);} });
    });
  }
  cancel(requestId = null) {
    const target=requestId || this.pending.keys().next().value;
    if(!target) return;
    const requestIdCancel=crypto.randomUUID();
    this.child.stdin.write(JSON.stringify({protocol:PROTOCOL,requestId:requestIdCancel,command:'cancel',targetRequestId:target})+'\n');
  }
  shutdown() {
    if(this.closed) return Promise.resolve();
    this.child.stdin.end(JSON.stringify({protocol:PROTOCOL,requestId:crypto.randomUUID(),command:'shutdown'})+'\n');
    return new Promise(resolve => { const t=setTimeout(()=>{this.child.kill();resolve();},5000); this.child.once('exit',()=>{clearTimeout(t);resolve();}); });
  }
  #failAll(error) { for(const p of this.pending.values()) p.reject(error); this.pending.clear(); }
}
