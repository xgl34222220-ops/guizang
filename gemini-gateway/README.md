# 归藏 · Gemini Gateway

轻量、多人可用、仅面向 Gemini 的私人 API 网关。单实例、少量用户场景不需要 MySQL / PostgreSQL / Redis；Key 与用量聚合保存在持久化数据文件中。

## 能力

- OpenAI 兼容入口：`/v1/*`
- Gemini 原生透传：`/gemini/*`
- 每个用户独立 `sk-gzg-*` Key
- 每 Key RPM / 日 Token / 月 Token 上限
- 创建、禁用、删除 Key
- 多 Gemini 上游 Key 轮转，429 / 5xx 自动尝试备用 Key
- SSE 流式透传
- 持久化 Key / 用量统计
- 模型别名
- 手机可用管理页 `/admin`
- 默认不保存 Prompt / Response 正文
- Go 标准库实现，无第三方运行依赖

## 环境变量

必须：

- `GEMINI_API_KEYS`：一个或多个 Gemini API Key，多个用逗号分隔。不要提交到 Git。
- `ADMIN_TOKEN`：管理页密码。建议 32 字节以上随机值。

可选：

- `PORT=8080`
- `STATE_PATH=/data/gateway.json`
- `MAX_BODY_MB=32`
- `REQUEST_TIMEOUT_SECONDS=600`
- `MODEL_ALIASES={"gemini":"gemini-3.1-pro-preview","gemini-fast":"gemini-3.8-flash"}`

## Docker

```bash
cp .env.example .env
# 修改 .env，不要提交它
docker build -t guizang-gemini-gateway .
docker run --rm -p 8080:8080 --env-file .env -v "$PWD/data:/data" guizang-gemini-gateway
```

访问 `http://127.0.0.1:8080/admin`，输入 `ADMIN_TOKEN`，创建第一个客户端 API Key。

## 客户端

OpenAI 兼容客户端：

```text
Base URL: https://YOUR_HOST/v1
API Key:  sk-gzg-xxxxxxxx
```

请求会转发到 Google 官方 Gemini OpenAI-compatible endpoint。

Gemini 原生协议：把 Google 原生路径前面加 `/gemini`：

```text
Google:  /v1beta/models/...:generateContent
Gateway: /gemini/v1beta/models/...:generateContent
```

客户端仍然用 `Authorization: Bearer sk-gzg-xxxx`，网关会替换为服务器保存的 Google 凭据。

## 安全

- 不要把 `GEMINI_API_KEYS` 或 `ADMIN_TOKEN` 写进仓库。
- 网关只持久化 Key 配置和 Token / 请求聚合数据，不保存 Prompt / Response 正文。
- 如果公开给多人使用，建议配合域名 HTTPS、Cloudflare/WAF 和上游项目消费上限。
- 多上游 Key 只用于灾备/不同项目。Google 的项目级配额不会因为同项目多建 Key 而倍增。

## Render

使用 Blueprint 时选择本文件：`gemini-gateway/render.yaml`。它会从 `gemini-gateway/` 构建 Docker 服务，并把 1GB 持久磁盘挂载到 `/data`。部署时只需要填写 `GEMINI_API_KEYS`。
