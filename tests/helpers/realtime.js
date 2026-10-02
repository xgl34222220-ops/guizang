'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { io } = require('socket.io-client');
const Database = require('better-sqlite3');
const { WebSocket, WebSocketServer } = require('ws');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(fn, label = 'condition') {
  const deadline = Date.now() + 5000;
  while (!fn()) { if (Date.now() > deadline) throw Error(`Timed out: ${label}`); await pause(10); }
}
async function fixture(t) {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), 'guizang-e2e-'));
  const clients = [], children = [], proxies = [];
  t.after(async () => {
    clients.forEach(client => client.disconnect());
    for (const proxy of proxies) { for (const socket of proxy.sockets) socket.terminate(); await new Promise(r => proxy.server.close(r)); }
    for (const child of children) if (child.exitCode === null && child.signalCode === null) { const exited = once(child, 'exit'); child.kill(); await exited; }
    fs.rmSync(data, { recursive: true, force: true });
  });
  const tokens = { owner: 'test-owner-only', muse: 'test-muse-only', dots: 'test-dots-only' };
  async function start() {
    const probe = http.createServer(); probe.listen(0, '127.0.0.1'); await once(probe, 'listening');
    const port = probe.address().port; await new Promise(r => probe.close(r));
    const child = spawn(process.execPath, [path.resolve('server.js')], {
      env: { ...process.env, PORT: String(port), DATA_DIR: data, OWNER_TOKEN: tokens.owner, MUSE_TOKEN: tokens.muse, DOTS_TOKEN: tokens.dots }, stdio: ['ignore', 'pipe', 'pipe']
    });
    children.push(child);
    let output = ''; child.stdout.on('data', b => { output += b; }); child.stderr.on('data', b => { output += b; });
    await until(() => child.exitCode !== null || output.includes('Guizang Room is running'), 'server startup');
    assert.equal(child.exitCode, null, output);
    return { url: `http://127.0.0.1:${port}`, child, async stop() { const exited = once(child, 'exit'); child.kill(); await exited; } };
  }
  async function client(url, role = 'owner', options = {}) {
    const socket = io(url, { auth: { token: tokens[role] }, transports: ['websocket'], forceNew: true, reconnection: false, ...options });
    clients.push(socket); await once(socket, 'connect'); return socket;
  }
  function rows() { const db = new Database(path.join(data, 'guizang.sqlite'), { readonly: true }); try { return db.prepare('SELECT * FROM messages ORDER BY id').all(); } finally { db.close(); } }
  async function proxy(url) {
    const server = http.createServer(), wss = new WebSocketServer({ server }), sockets = new Set();
    const state = { server, sockets, dropNextAck: false, dropped: 0 };
    proxies.push(state);
    wss.on('connection', (downstream, req) => {
      const upstream = new WebSocket(url.replace(/^http/, 'ws') + req.url);
      sockets.add(downstream); sockets.add(upstream);
      const queue = [];
      downstream.on('message', data => upstream.readyState === WebSocket.OPEN ? upstream.send(data.toString()) : queue.push(data.toString()));
      upstream.on('open', () => queue.splice(0).forEach(packet => upstream.send(packet)));
      upstream.on('message', data => {
        const packet = data.toString();
        if (state.dropNextAck && /^43\d+\[/.test(packet)) { state.dropNextAck = false; state.dropped++; return; }
        if (downstream.readyState === WebSocket.OPEN) downstream.send(packet);
      });
      upstream.on('error', () => downstream.terminate()); downstream.on('error', () => upstream.terminate());
      upstream.on('close', () => { sockets.delete(upstream); downstream.close(); });
      downstream.on('close', () => { sockets.delete(downstream); upstream.close(); });
    });
    server.listen(0, '127.0.0.1'); await once(server, 'listening'); state.url = `http://127.0.0.1:${server.address().port}`; return state;
  }
  return { data, start, client, rows, proxy };
}
function ack(socket, event, payload, timeout = 2000) { return socket.timeout(timeout).emitWithAck(event, payload); }
async function join(socket, room = 'main') {
  const state = once(socket, 'room:state'); const result = await ack(socket, 'room:join', { room }); assert.equal(result.ok, true); return (await state)[0];
}
module.exports = { fixture, ack, join, pause, until };
