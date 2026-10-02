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

运行 `npm test` 可执行无需服务器或访问 Token 的消息编辑器回归测试，覆盖重复点击、回执超时、断线/入房未完成、发送期间继续输入、回复切换、长度限制和中文输入法回车。服务器语法检查：`node --check server.js`。

服务器版发送超时会保留正文，不自动重发；先核对房间消息，避免不确定回执造成重复发送。
