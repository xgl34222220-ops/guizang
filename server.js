'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const http = require('http');
const express = require('express');
const helmet = require('helmet');
const compression = require('compression');
const Database = require('better-sqlite3');
const { Server } = require('socket.io');

const PORT = Number(process.env.PORT || 3000);
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const PUBLIC_DIR = path.join(__dirname, 'public');
const BASE_URL = (process.env.BASE_URL || '').replace(/\/$/, '');

fs.mkdirSync(DATA_DIR, { recursive: true });

const secretPath = path.join(DATA_DIR, 'access.json');
const randomToken = () => crypto.randomBytes(32).toString('hex');

let saved = {};
if (fs.existsSync(secretPath)) {
  try { saved = JSON.parse(fs.readFileSync(secretPath, 'utf8')); } catch {}
}

const access = {
  owner: process.env.OWNER_TOKEN || saved.owner || randomToken(),
  muse: process.env.MUSE_TOKEN || saved.muse || randomToken(),
  dots: process.env.DOTS_TOKEN || saved.dots || randomToken()
};

fs.writeFileSync(secretPath, JSON.stringify(access, null, 2), { mode: 0o600 });

function safeEqual(a, b) {
  if (!a || !b) return false;
  const aa = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return aa.length === bb.length && crypto.timingSafeEqual(aa, bb);
}

function roleFromToken(token) {
  if (safeEqual(token, access.owner)) return 'owner';
  if (safeEqual(token, access.muse)) return 'muse';
  if (safeEqual(token, access.dots)) return 'dots';
  return null;
}

function cleanRoom(input) {
  const value = String(input || 'main').trim();
  return /^[a-zA-Z0-9_-]{1,64}$/.test(value) ? value : 'main';
}

function cleanText(input, max) {
  return String(input ?? '').trim().slice(0, max);
}

const db = new Database(path.join(DATA_DIR, 'guizang.sqlite'));
db.pragma('journal_mode = WAL');
db.pragma('synchronous = NORMAL');
db.exec(`
  CREATE TABLE IF NOT EXISTS rooms (
    room_key TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '归藏共享聊天室',
    repo_url TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_key TEXT NOT NULL,
    author TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
  );

  CREATE INDEX IF NOT EXISTS idx_messages_room_id
  ON messages(room_key, id);
`);

const roomGet = db.prepare('SELECT * FROM rooms WHERE room_key = ?');
const roomInsert = db.prepare(`
  INSERT OR IGNORE INTO rooms(room_key, title, repo_url, objective, updated_at)
  VALUES (?, '归藏共享聊天室', '', '', ?)
`);
const roomUpdate = db.prepare(`
  INSERT INTO rooms(room_key, title, repo_url, objective, updated_at)
  VALUES (@room_key, @title, @repo_url, @objective, @updated_at)
  ON CONFLICT(room_key) DO UPDATE SET
    title = excluded.title,
    repo_url = excluded.repo_url,
    objective = excluded.objective,
    updated_at = excluded.updated_at
`);
const historyGet = db.prepare(`
  SELECT id, room_key, author, role, kind, body, created_at
  FROM messages WHERE room_key = ? ORDER BY id DESC LIMIT ?
`);
const messageInsert = db.prepare(`
  INSERT INTO messages(room_key, author, role, kind, body, created_at)
  VALUES (@room_key, @author, @role, @kind, @body, @created_at)
`);
const messageById = db.prepare(`
  SELECT id, room_key, author, role, kind, body, created_at
  FROM messages WHERE id = ?
`);

function ensureRoom(roomKey) {
  roomInsert.run(roomKey, new Date().toISOString());
  return roomGet.get(roomKey);
}

const app = express();
app.set('trust proxy', 1);
app.use(helmet({
  contentSecurityPolicy: false,
  crossOriginEmbedderPolicy: false
}));
app.use(compression());
app.use(express.json({ limit: '64kb' }));

function tokenFromReq(req) {
  const auth = req.headers.authorization || '';
  if (auth.startsWith('Bearer ')) return auth.slice(7);
  return String(req.query.token || '');
}

function apiAuth(req, res, next) {
  const token = tokenFromReq(req);
  const role = roleFromToken(token);
  if (!role) return res.status(401).json({ error: 'invalid_token' });
  req.role = role;
  req.token = token;
  next();
}

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, service: 'guizang-room', time: new Date().toISOString() });
});

app.get('/api/me', apiAuth, (req, res) => {
  res.json({ ok: true, role: req.role });
});

app.get('/api/invites', apiAuth, (req, res) => {
  if (req.role !== 'owner') return res.status(403).json({ error: 'owner_only' });
  const room = cleanRoom(req.query.room);
  const origin = BASE_URL || `${req.protocol}://${req.get('host')}`;
  const make = (token) => `${origin}/?room=${encodeURIComponent(room)}&token=${encodeURIComponent(token)}`;
  res.json({
    room,
    owner: make(access.owner),
    muse: make(access.muse),
    dots: make(access.dots)
  });
});

app.use(express.static(PUBLIC_DIR, {
  extensions: ['html'],
  maxAge: process.env.NODE_ENV === 'production' ? '1h' : 0
}));

const server = http.createServer(app);
const io = new Server(server, {
  serveClient: true,
  transports: ['websocket', 'polling'],
  maxHttpBufferSize: 128 * 1024,
  pingInterval: 25000,
  pingTimeout: 20000
});

io.use((socket, next) => {
  const token = socket.handshake.auth?.token || socket.handshake.query?.token;
  const role = roleFromToken(token);
  if (!role) return next(new Error('unauthorized'));
  socket.data.role = role;
  next();
});

const presence = new Map();

function roomPresence(room) {
  if (!presence.has(room)) presence.set(room, new Map());
  return presence.get(room);
}

function emitPresence(room) {
  const p = roomPresence(room);
  const counts = { owner: 0, muse: 0, dots: 0 };
  for (const role of p.values()) if (role in counts) counts[role] += 1;
  io.to(room).emit('presence', counts);
}

function leaveCurrentRoom(socket) {
  const room = socket.data.room;
  if (!room) return;
  const p = roomPresence(room);
  p.delete(socket.id);
  if (!p.size) presence.delete(room);
  socket.leave(room);
  emitPresence(room);
  socket.data.room = null;
}

io.on('connection', (socket) => {
  socket.emit('session', { role: socket.data.role });

  socket.on('room:join', (payload = {}, ack = () => {}) => {
    try {
      leaveCurrentRoom(socket);
      const room = cleanRoom(payload.room);
      socket.join(room);
      socket.data.room = room;
      roomPresence(room).set(socket.id, socket.data.role);

      const meta = ensureRoom(room);
      const history = historyGet.all(room, 1500).reverse();
      socket.emit('room:state', { room, meta, messages: history });
      emitPresence(room);
      ack({ ok: true, room });
    } catch (error) {
      ack({ ok: false, error: 'join_failed' });
    }
  });

  socket.on('message:send', (payload = {}, ack = () => {}) => {
    try {
      const room = socket.data.room;
      if (!room) return ack({ ok: false, error: 'not_in_room' });

      const kind = ['chat', 'project', 'proposal', 'decision', 'todo'].includes(payload.kind)
        ? payload.kind : 'chat';
      const body = cleanText(payload.body, 12000);
      if (!body) return ack({ ok: false, error: 'empty_message' });

      const role = socket.data.role;
      const author = role === 'owner' ? '我' : role === 'muse' ? 'Muse' : 'Dots';
      const row = {
        room_key: room,
        author,
        role,
        kind,
        body,
        created_at: new Date().toISOString()
      };

      const result = messageInsert.run(row);
      const message = messageById.get(result.lastInsertRowid);
      io.to(room).emit('message:new', message);
      ack({ ok: true, id: message.id });
    } catch (error) {
      ack({ ok: false, error: 'send_failed' });
    }
  });

  socket.on('room:update', (payload = {}, ack = () => {}) => {
    try {
      if (socket.data.role !== 'owner') return ack({ ok: false, error: 'owner_only' });
      const room = socket.data.room;
      if (!room) return ack({ ok: false, error: 'not_in_room' });
      const row = {
        room_key: room,
        title: cleanText(payload.title || '归藏共享聊天室', 120) || '归藏共享聊天室',
        repo_url: cleanText(payload.repo_url || '', 500),
        objective: cleanText(payload.objective || '', 4000),
        updated_at: new Date().toISOString()
      };
      roomUpdate.run(row);
      const meta = roomGet.get(room);
      io.to(room).emit('room:meta', meta);
      ack({ ok: true, meta });
    } catch (error) {
      ack({ ok: false, error: 'update_failed' });
    }
  });

  socket.on('typing', (payload = {}) => {
    const room = socket.data.room;
    if (!room) return;
    socket.to(room).emit('typing', {
      role: socket.data.role,
      active: Boolean(payload.active),
      at: Date.now()
    });
  });

  socket.on('disconnect', () => leaveCurrentRoom(socket));
});

server.listen(PORT, '0.0.0.0', () => {
  const base = BASE_URL || `http://localhost:${PORT}`;
  console.log('');
  console.log('Guizang Room is running');
  console.log(`Data: ${DATA_DIR}`);
  console.log(`Owner: ${base}/?room=main&token=${access.owner}`);
  console.log(`Muse:  ${base}/?room=main&token=${access.muse}`);
  console.log(`Dots:  ${base}/?room=main&token=${access.dots}`);
  console.log('');
});
