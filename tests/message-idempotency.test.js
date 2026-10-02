'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { fixture, ack, join, pause, until } = require('./helpers/realtime');

test('lost ack after commit: manual resend does not insert or broadcast twice', async t => {
  const f = await fixture(t), server = await f.start(), proxy = await f.proxy(server.url);
  const sender = await f.client(proxy.url), observer = await f.client(server.url, 'muse');
  await join(sender); await join(observer);
  const received = []; observer.on('message:new', m => received.push(m));
  const payload = { room: 'main', clientRequestId: 'e2e-lost-ack-request', kind: 'chat', body: '网络确认丢失后手动重发' };
  proxy.dropNextAck = true;
  await assert.rejects(ack(sender, 'message:send', payload, 150));
  await until(() => received.length === 1, 'observer received committed message');
  assert.equal(proxy.dropped, 1); assert.equal(f.rows().length, 1);
  const result = await ack(sender, 'message:send', payload);
  await pause(30);
  t.diagnostic(JSON.stringify({ droppedAcks: proxy.dropped, firstId: received[0].id, retryId: result.id, rows: f.rows().length, broadcasts: received.length }));
  assert.equal(result.id, received[0].id, 'retry must acknowledge the existing message id');
  assert.equal(f.rows().length, 1, 'one durable row after manual retry');
  assert.equal(received.length, 1, 'one broadcast after manual retry');
});

test('concurrent identical requests across two server processes share one database row', async t => {
  const f = await fixture(t), first = await f.start(), second = await f.start();
  const a = await f.client(first.url), b = await f.client(second.url);
  await join(a); await join(b);
  const payload = { clientRequestId: 'concurrent-same-request', kind: 'chat', body: 'one logical send' };
  const results = await Promise.all(Array.from({ length: 24 }, (_, index) => ack(index % 2 ? a : b, 'message:send', payload)));
  assert.equal(new Set(results.map(r => r.id)).size, 1);
  assert.equal(results.filter(r => r.duplicate === false).length, 1);
  assert.equal(f.rows().length, 1);
});

test('conflicting body/kind never overwrites; requests are scoped to room and authenticated role', async t => {
  const f = await fixture(t), server = await f.start(), owner = await f.client(server.url), muse = await f.client(server.url, 'muse');
  await join(owner, 'alpha'); await join(muse, 'alpha');
  const payload = { clientRequestId: 'scope-and-conflict-request', kind: 'chat', body: 'original' };
  const original = await ack(owner, 'message:send', payload);
  assert.equal((await ack(owner, 'message:send', { ...payload, body: 'changed' })).error, 'request_conflict');
  assert.equal((await ack(owner, 'message:send', { ...payload, kind: 'todo' })).error, 'request_conflict');
  const otherRole = await ack(muse, 'message:send', { ...payload, role: 'owner', author: '我' });
  await join(owner, 'beta'); const otherRoom = await ack(owner, 'message:send', payload);
  assert.equal(new Set([original.id, otherRole.id, otherRoom.id]).size, 3);
  assert.equal(f.rows()[0].body, 'original'); assert.equal(f.rows()[1].role, 'muse');
  assert.equal((await ack(owner, 'message:send', { ...payload, room: 'alpha' })).error, 'room_changed');
  assert.equal(f.rows().length, 3);
});

test('invalid IDs and overlength content are rejected; old clients without IDs remain compatible', async t => {
  const f = await fixture(t), server = await f.start(), client = await f.client(server.url); await join(client);
  for (const clientRequestId of ['', 123, 'short', 'x'.repeat(129), 'bad request id with spaces']) {
    assert.equal((await ack(client, 'message:send', { clientRequestId, body: 'test' })).error, 'invalid_request_id');
  }
  assert.equal((await ack(client, 'message:send', { clientRequestId: 'valid-but-long-request', body: 'x'.repeat(12001) })).error, 'message_too_long');
  assert.equal(f.rows().length, 0);
  const first = await ack(client, 'message:send', { body: 'legacy' });
  const second = await ack(client, 'message:send', { body: 'legacy' });
  assert.equal(first.ok, true); assert.equal(second.ok, true); assert.notEqual(first.id, second.id);
});

test('database migration preserves legacy rows and request IDs survive server restart', async t => {
  const f = await fixture(t), Database = require('better-sqlite3'), path = require('node:path');
  const db = new Database(path.join(f.data, 'guizang.sqlite'));
  db.exec("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, room_key TEXT NOT NULL, author TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL); INSERT INTO messages VALUES(1,'main','我','owner','chat','legacy row','2026-01-01T00:00:00Z')"); db.close();
  const firstServer = await f.start(), first = await f.client(firstServer.url);
  assert.equal((await join(first)).messages[0].body, 'legacy row');
  const payload = { clientRequestId: 'durable-restart-request', body: 'durable' }, sent = await ack(first, 'message:send', payload);
  first.disconnect(); await firstServer.stop();
  const secondServer = await f.start(), second = await f.client(secondServer.url); await join(second);
  const retried = await ack(second, 'message:send', payload);
  assert.equal(retried.id, sent.id); assert.equal(retried.duplicate, true); assert.equal(f.rows().length, 2);
});

test('transport reconnect rejoins from durable history; switching rooms prevents stale-room sends', async t => {
  const f = await fixture(t), server = await f.start(), receiver = await f.client(server.url, 'owner', { reconnection: true, reconnectionDelay: 100, randomizationFactor: 0 }), sender = await f.client(server.url, 'muse');
  await join(receiver); await join(sender);
  await ack(sender, 'message:send', { body: 'before outage', clientRequestId: 'reconnect-before-request' });
  receiver.io.engine.close(); await until(() => !receiver.connected, 'receiver disconnected');
  const missed = await ack(sender, 'message:send', { body: 'during outage', clientRequestId: 'reconnect-during-request' });
  await until(() => receiver.connected, 'receiver reconnected');
  const history = await join(receiver); assert.equal(history.messages.filter(m => m.id === missed.id).length, 1);
  await join(receiver, 'other');
  assert.equal((await ack(receiver, 'message:send', { room: 'main', body: 'stale', clientRequestId: 'reconnect-stale-request' })).error, 'room_changed');
  assert.equal(f.rows().length, 2);
});
