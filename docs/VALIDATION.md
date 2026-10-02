# 验证账本（0.1.0-dev）

## 已在 host 执行

- 第一阶段 Python 37 个测试方法通过，含每个保护项的 true/unknown/非法真假值子测试。
- 第一阶段 WebUI 6 个模型测试通过。
- shell 语法、Python 编译、默认关闭配置、不可安装断言通过。
- 覆盖：白名单/保护拒绝、能力缺失、PID/starttime/UID/boot identity 失配、旧冻结不接管、前台保护自动解冻、部分冻结失败补偿、解冻失败保留责任并停止新冻结；写前日志、部分写失败、恢复冲突、幂等回滚、模拟进程重启；启动 ID 去重、连续失败阈值、陈旧健康回调、损坏状态与符号链接拒绝。

## 浏览器验证

`tools/ui-smoke.cjs` 是隔离的自有夹具测试，1440、393、320 像素三种宽度，覆盖四页、横向溢出、名单→休眠→唤醒、失败三次停用→手动重置、后退、刷新和 JS 错误。

本地执行环境不支持独立 Chromium 的进程 socket，未声称本地浏览器验收通过。GitHub Actions 的 host 与 WebUI job 已通过：提交 `0a56d362617ec24a94c6deeb21eb8f45d936f397`，push run [37055415869](https://github.com/xgl34222220-ops/guizang/actions/runs/37055415869) 与 PR run [37055478237](https://github.com/xgl34222220-ops/guizang/actions/runs/37055478237)。已下载并目视核对截图；报告三种宽度均无横向溢出、JS错误。后续修改以对应提交的最终 CI 结果为准。

## 尚未验证 / 禁止据此宣布

- 没有 Android native 冻结执行器、生产恢复事务后端或 Root WebUI bridge。
- 模块不可安装；未执行真正 cgroup/Binder 冻结、sysfs 写入、温控修改、开机故障或卸载恢复。
- 尚未在 Android VM 运行本模块；现有本地 ADB 清单没有附加设备。
- 一加15、Redmi K80至尊版当前 ROM/内核/Root管理器尚未采样；不能声称兼容、续航提升或全机型救砖。

## 下阶段闸门

1. 仅只读 Android 诊断：SDK/内核/管理器/cgroup 路径与保护信号支持情况，无个人内容采集。
2. Native 适配器：pidfd 或等效安全身份、持久化冻结账本、独立 watchdog、有界解冻、AMS/Binder 一致性。
3. 临时 VM 经过单独明确范围授权后测试生命周期；不修改用户手机。
4. 两台 OEM 实机单独验证前台切换、来电、音频/录音、通知、锁屏、重启、卸载与热限制。
5. 只在上述关卡通过后讨论小范围白名单启用；任何阶段失败都保持真实执行关闭。

## 第二阶段本地代码验证

- Python累计43项测试：新增VM序列号范围、固定夹具命令、无自动Root提权、身份/heartbeat/AMS解析fail-closed。
- Node累计14项测试：增加只读bridge默认关闭、固定命令、并发去重、超时清理、畸形与乐观报告拒绝。
- Native C++ 21项解析断言，host probe JSON协议与拒绝非法参数通过。
- 专用Android夹具本地构建通过，12项Java解析检查、零权限/组件边界、签名和对齐检查通过。两次同工具链无签名包字节一致；每次使用新的临时测试签名，密钥不保留或上传。
- 新增Android arm64-v8a/x86_64只读探针交叉编译CI；在该job实际通过前不宣称Android编译已验证。
- 尚未获得或执行本阶段VM Root/冻结许可；这不是Android运行结果。
