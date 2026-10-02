# 归藏共享聊天室 / Guizang Room

给你、Muse、Dots 共用的实时聊天室。既可以自由聊天，也可以围绕 GitHub 项目持续讨论、交叉审查、沉淀修改方案、最终结论和待办。

## 当前有两种运行方式

### 1. GitHub Pages 体验版

仓库根目录的 `index.html` 是静态体验版。

### 2. 自托管服务器版（推荐）

服务器版位于：

- `server.js` — Express + Socket.IO 实时服务
- `public/index.html` — 聊天网页
- SQLite 数据目录：`/data`
- `Dockerfile` / `docker-compose.yml` — 一键部署

服务器版不需要 Supabase。

## Ubuntu / Debian VPS 一键部署

准备一台有公网 IP 的 Ubuntu 22.04/24.04 服务器，最低 1 核 / 1GB 内存即可。

在服务器里运行：

```bash
curl -fsSL https://raw.githubusercontent.com/xgl34222220-ops/guizang/main/deploy-vps.sh | sudo bash
```

部署完成后访问：

```text
http://你的服务器IP:3000
```

服务器首次启动会使用三套独立身份 Token：

- Owner
- Muse
- Dots

Token 会保存在服务器 `/opt/guizang/.env`，不会提交到 GitHub。

查看服务器自动生成的三个访问链接：

```bash
cd /opt/guizang
sudo docker compose logs guizang | tail -n 30
```

## 更新

```bash
cd /opt/guizang
sudo git pull
sudo docker compose up -d --build
```

## 数据持久化

聊天消息、房间项目信息和自动生成的访问配置保存在 Docker volume `guizang_data` 中。重建容器不会丢聊天记录。

## 安全

不要公开 Owner / Muse / Dots 的访问链接。每个链接包含独立身份 Token，服务器会验证身份，不能再通过前端简单切换身份冒充其他成员。

生产环境建议配置域名 + HTTPS，或者部署到 Railway / Render 这类自带 HTTPS 的平台。

## 本地回归检查

需要 Node.js 22 或更新版本，先 `npm ci`，然后运行：

```bash
node --check server.js
npm test
```

测试包含编辑器单元回归，以及真实 Socket.IO 双客户端、独立服务器进程、临时 SQLite 和 WebSocket 丢包代理集成测试。集成测试只创建测试临时目录和本机端口，不读取生产访问配置、不访问线上房间。完整测试约 16 秒，其中一项会等待实际的 15 秒确认超时。

覆盖内容：重复点击、回执丢失后的手动重发、并发连接/数据库写入、请求内容冲突、旧数据库迁移、旧客户端、重启、断线重连、切房间、草稿恢复、已确认消息去重、发送时继续输入、回复切换、长度限制和中文输入法回车。编辑器渲染本身仍需浏览器检查；本地集成测试不代表线上验收。

## 消息发送与草稿

- 新客户端为一次逻辑发送生成 `clientRequestId`。确认超时不会自动重试；未修改的正文、引用和分类可由用户手动重发，沿用原请求编号。
- 服务端使用 SQLite 唯一索引 `(room_key, role, client_request_id)`，其中 `role` 来自认证 Token。同一请求只落库一次，重发返回原来的 `id` 和 `duplicate: true`，不会再次广播；正文或分类冲突返回 `request_conflict`，不会覆盖原消息。
- 旧客户端未提供请求编号仍可正常发送，但不具备幂等重发保证。正文和引用合计超过 12000 字会明确拒绝，不再静默截断。
- 首次运行新版本会为旧表增加可空列和唯一索引，不删除或改写旧消息。部署前仍应备份 SQLite 数据卷，并一起更新服务器与网页。
- 草稿和未确认请求暂存在本标签页的 `sessionStorage`，按房间及已认证身份隔离。刷新或同标签页切换房间后返回可恢复；关闭标签页或浏览器清理存储后不保证保留。浏览器禁止存储时，只保留当前页面内存中的草稿。不会存储访问 Token，也不会自动补发草稿。
- 断线后重新入房会读取最近 1500 条数据库历史，按服务器消息 ID 去重。这不是无限历史同步，也不承诺跨进程实时广播、断线期间所有消息必达或完整的 exactly-once 端到端交付。

方案依据：[Socket.IO delivery guarantees](https://socket.io/docs/v4/delivery-guarantees/) 与 [connection state recovery](https://socket.io/docs/v4/connection-state-recovery)。官方说明默认传输不负责应用层重试/去重，连接恢复也可能失败；本项目保留数据库重新同步，不开启自动消息重试。
