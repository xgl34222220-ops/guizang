# 归藏 · Guizang

Android Root 应用休眠与性能管理实验项目。

> **研发骨架，默认 disabled / dry-run，尚不可刷入。** 这是 Android 上借鉴 iOS 体验的冻结/唤醒设计，不是 iOS 内核实现，也不承诺全机型、零掉消息或“万能救砖”。

## 三条主线

- **应用休眠**：仅显式允许的应用；先保护前台、音频、输入法、无障碍、VPN、系统关键进程；以框架/Binder 可验证解冻为前提。
- **场景调度**：先观察并解释决策；不盲写 sysfs、不关温控、不超频。未来写入必须有能力探测、原值快照及幂等恢复。
- **启动保护**：只处理本模块连续启动失败；自动停用自身、恢复自己记录的变更；不刷 boot、不清数据、不操作其他模块。

## 开发与验证

只需要 Python 3.10+ 和 Node.js 22；核心参考实现无第三方依赖。

```sh
python3 -m unittest discover -s tests -v
sh tools/check.sh
```

UI 默认是无网络、无持久化的四页交互原型；设备只读 bridge 已实现源码但默认关闭。启动 `python3 -m http.server 8768 --directory webroot` 后本地查看；它始终标注未连接设备，不会伪装真实冻结/性能数据。浏览器回归用 `npm ci && npx playwright install chromium && npm run test:browser`，产物只包含自有示例夹具。

`core/` 是 Python host 参考模型，不是 Android daemon。只有测试提供 mock 冻结与参数执行器；没有向手机部署 Python 的方案。已新增 Android NDK 可编译的只读 native 探针；设备端冻结协调器、持久化冻结账本和可靠保护信号采集尚未实现。VM脚本提供独立超时解冻清理，但尚不能代替生产设备 watchdog。`module/probe.sh` 与 `native/probe.cpp` 仅输出只读能力提示，不能据此启用冻结。

## 当前阶段

主分支保存新项目起点；第一版 host 安全模型、WebUI 与 CI 在 `test/android-module-foundation-20261002` 分支审阅。没有发布安装包，没有在用户设备安装或执行 Root 操作。设备端冻结/性能执行器尚未开放；host 测试不能证明实机兼容性。

- [设计与安全边界](docs/ARCHITECTURE.md)
- [迁移和旧项目恢复点](docs/MIGRATION.md)
- [研究与许可证记录](docs/RESEARCH.md)

## 仓库迁移

本仓库已按所有者要求整体更换用途，旧聊天室与 Gemini 网关不再位于当前工作树。Git 历史和归档分支保留。仓库替换本身不会关闭已经部署的服务，也未更改远端服务、密钥、其他分支或标签。

## Android只读联调阶段

- `native/probe.cpp`：实际cgroup2挂载解析、进程身份/boot identity、freezer请求/完成状态与能力提示；无写入和Binder ioctl。
- `webroot/bridge.js`：只允许固定探针命令，默认关闭；严格JSON协议、限长、超时和并发去重。不能启用真实冻结。
- `fixture/`：无权限、无服务的测试App，用私有原子heartbeat文件识别同一进程的暂停与恢复。
- `tools/vm_validate.py`：拒绝实体/远程设备序列号，不自动提权，只使用AMS针对 `org.guizang.fixture` 的名字命令；实际VM安全操作需要本次单独许可。
- [VM路线、许可与验收条件](docs/VM-VALIDATION.md)

```sh
sh tools/native-check.sh
ANDROID_NDK_HOME=/path/to/official/ndk sh tools/build-native-android.sh
sh tools/build-fixture.sh
```

交叉编译成功、mock测试和界面预览均不能代替Android运行验证。仍无可安装的归藏模块发行包。
