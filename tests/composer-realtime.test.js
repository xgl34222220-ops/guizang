'use strict';
// Only DOM/storage are stubbed. The production send() calls a real Socket.IO
// client, child server process, WebSocket network proxy and temporary SQLite DB.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { fixture, join, until, pause } = require('./helpers/realtime');

test('production composer keeps the same request through actual ack loss, reconnect and tab restore', { timeout: 25000 }, async t => {
  const f = await fixture(t), server = await f.start(), proxy = await f.proxy(server.url);
  const sender = await f.client(proxy.url, 'owner', { reconnection: true, reconnectionDelay: 100, randomizationFactor: 0 });
  const observer = await f.client(server.url, 'muse'); await join(sender); await join(observer);
  const received = []; observer.on('message:new', message => received.push(message));
  const html = fs.readFileSync('public/index.html', 'utf8');
  const source = html.slice(html.indexOf('function draftKey(){'), html.indexOf('\n$("#send").onclick=send;'));
  const nodes = { '#input': { value: '真实传输的手动重发' }, '#send': {}, '#reply': {} }, saved = new Map();
  const state = {
    room: 'main', role: 'owner', sending: false, observer: false, roomReady: true, replyTo: null, kind: 'chat', pendingSend: null,
    draftScope: 'guizang.draft.v1:main:owner', R: {}, K: { chat: 1 }, socket: sender, Uint8Array,
    crypto: require('node:crypto').webcrypto, $: selector => nodes[selector], toast: () => {}, setKind: () => {},
    sessionStorage: { getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) }
  };
  vm.createContext(state); vm.runInContext(source, state);
  proxy.dropNextAck = true; state.send(); state.send();
  await until(() => received.length === 1, 'first commit/broadcast');
  const requestId = state.pendingSend.clientRequestId;
  // Wait for the actual production 15-second ack timeout, not a fake callback.
  await pause(15200);
  assert.equal(state.sending, false); assert.equal(nodes['#input'].value, '真实传输的手动重发');
  assert.equal(f.rows().length, 1); assert.equal(proxy.dropped, 1);
  sender.io.engine.close(); state.roomReady = false;
  await until(() => sender.connected, 'transport reconnect');
  const history = await join(sender); state.roomReady = true;
  assert.equal(history.messages.length, 1);
  // Reload-equivalent composer restore uses only this tab's persisted draft.
  state.pendingSend = null; state.draftScope = null; nodes['#input'].value = ''; state.restoreDraft();
  assert.equal(state.pendingSend.clientRequestId, requestId); assert.equal(received.length, 1);
  state.send(); await until(() => !state.sending, 'manual retry acknowledgement');
  assert.equal(nodes['#input'].value, ''); assert.equal(state.pendingSend, null);
  assert.equal(f.rows().length, 1); assert.equal(received.length, 1);
  assert.equal(saved.size, 0, 'confirmed draft removed from tab storage');
});
