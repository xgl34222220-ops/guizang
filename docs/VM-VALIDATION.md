# 下一阶段：一次性 Android VM 验证路线

## 许可闸门

本次临时AVD、调试Root、唯一自建测试App冻结/解冻与中断恢复已得到明确许可，测试脚本提交和CI执行也已获批。边界如下，不能沿用别的项目许可：

1. 仅一次性、无个人数据的 AOSP x86_64 AVD：`adb root` 临时调试提权，安装 `org.guizang.fixture` 测试 APK，运行自写只读探针。
2. 只有探测满足条件，才使用 AMS 对唯一测试进程 `org.guizang.fixture` 做冻结/解冻，并测试协调器中断后的独立清理；不处理系统应用/其他应用/实体手机。
3. 测试结束销毁临时 AVD。不新增长期 Root 授权，不持久化任何真实设备权限。
4. 若需要 Magisk/APatch/KernelSU 安装、修补或替换临时 boot、给测试 UID 授权 Root，须另列具体版本和动作单独批准。当前路线不自动升级到这一层。

仅有参数 `--ack-disposable-vm`、环境变量或CI开关不等同授权；它们只能防误触。

## 只读探针实际实现

`native/probe.cpp` 可用 Android NDK 编译 arm64-v8a 与 x86_64，输出 schema 2 JSON。只读系统属性、uname、自己的或指定夹具进程的 `/proc` 身份、cgroup2 mountinfo映射、freezer请求值/完成状态、pidfd是否可打开、Binder设备是否存在。

不执行 shell、不发送信号、不写 sysfs/cgroup、不操作 Binder ioctl、属性或进程调度。无路径覆写参数，拒绝任意命令；指定 PID 也必须匹配唯一夹具进程名和普通应用 UID。`/proc/PID` 目录FD锚定读取得到的进程身份，读前读后核对；不把这些读取当成后续外部命令的原子身份锁。

KernelSU Root bridge 仅允许固定命令 `/data/adb/modules/guizang/bin/guizang-probe --json`。默认构建关闭，重复请求合并、超时清理回调、输出限长与严格类型验证，不接受“已验证可冻结”的乐观声明。已Root的WebView中任意代码本来就有高权限；限制本bridge不是抵御恶意WebView脚本的安全边界，因此代码/安装来源仍必须可信。

Magisk原生管理器没有在本项目中验证WebUI桥接；不冒充支持。APatch只在实测其兼容接口后加入支持名单。

## AMS 冻结实验的硬条件

- AVD必须具备实际 `am help` 的 freeze/unfreeze命令。AOSP Android14已有按进程名命令；Android15/16支持PID或名称；Android13没有这一路径。以运行镜像为准。
- 固定字面进程名 `org.guizang.fixture`，单用户、单进程、无共享UID、无音频/VPN/无障碍等服务和跨进程依赖。
- 不使用 `--sticky`、SIGSTOP、force-stop、直接cgroup写入，缺能力就停止。
- app后台heartbeat先能稳定推进。只读外部私有文件观测，不对冻结中的夹具进行Binder调用。
- 冻结由AMS自己的ProcessRecord、CachedAppOptimizer与Binder协调，外部脚本不复制其顺序。当前AOSP是“Binder先冻结，再冻结进程”；解冻也是“Binder先解冻，再解冻进程”，不是简单反向顺序。
- `am freeze`输出成功只表示排入异步任务，不是冻结完成。
- `pidfd_open`可以绑定进程生命期，但AMS shell不接受pidfd/expected starttime。前后PID/starttime检查不能消除TOCTOU；因此此路线仅是清洁VM夹具验证，不扩展为任意应用生产控制。

## 通过证据

1. 记录AVD标识、API/fingerprint/kernel、夹具APK哈希、UID/PID/starttime、boot ID、进程nonce、cgroup2实际映射。
2. 冻结前：连续heartbeat推进，夹具处于后台且无受保护依赖。
3. 冻结后：同一PID/starttime/nonce；AMS状态与该夹具cgroup.events的`frozen 1`相符；固定短观察窗内heartbeat停滞。Android16的AMS状态来自`dumpsys activity cao`，旧镜像可检查`settings`，任何无法识别的格式都停止。
4. 解冻后：cgroup.events `frozen 0`、AMS移出冻结集合、相同进程nonce的heartbeat继续。进程重启/崩溃不能冒充解冻成功。
5. 收集仅该测试范围logcat和退出信息。Binder/freezer错误、自动重启、瞬间自解冻、证据缺失或超时均判失败/不确定。
6. 先布置独立超时清理，只请求同一夹具unfreeze。协调器中断时仍有清理路径；解冻未确认则停止实验并使用已批准的AVD销毁/重建。

cgroup.freeze只是请求值，cgroup.events frozen才是完成状态。freezer为cgroup2核心接口，不能根据cgroup.controllers里没有freezer就误判不支持。

## 后续启动恢复

先在VM专用状态目录验证原生恢复账本、相同boot幂等、连续未健康启动、只停用本模块、不会自动重新启用。然后另行获批管理器集成，才验证实际service/disable/uninstall生命周期。host BootGuard通过不代表Android开机保护已完成。

## 一手来源

- [AOSP Android16 CachedAppOptimizer](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/services/core/java/com/android/server/am/CachedAppOptimizer.java)
- [AOSP Android14 shell](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android-14.0.0_r1/services/core/java/com/android/server/am/ActivityManagerShellCommand.java)
- [AOSP Android16 shell](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android-16.0.0_r1/services/core/java/com/android/server/am/ActivityManagerShellCommand.java)
- [Linux cgroup2 semantics](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [KernelSU WebUI ABI](https://kernelsu.org/guide/module-webui.html)，核对官方npm kernelsu 3.0.2公开exec签名，Apache-2.0；未复制其实现。

脚本支持专用 `--fault-coordinator-exit`：在已经观察到夹具冻结后，让测试协调器进程以73退出，独立18秒watchdog只请求该夹具解冻。单独的Disposable Android fixture experiment工作流执行已批准实验；原android-compile任务仍只编译。runner同时核对kernel/AMS/heartbeat、同一实例、退出记录及框架freeze/thaw正向日志，再形成机器判定；仍须复核原始产物，任何一项缺失都不记为通过。


## 一次性 runner

`tools/vm_runner.py`创建官方API35 google_apis x86_64全新AVD，先核对无其他ADB设备、镜像身份、AVD名称，才执行一次调试Root。仅在预存sudo可用且普通runner无KVM访问时，用sudo监督官方emulator进程，不修改设备权限、组、udev或SELinux。

先只读探测，再进行常规冻结/唤醒，最后进行协调器退出和独立watchdog恢复。第二轮只复用本次安装回执与完全相同APK哈希，禁止覆盖预存App。结束时TERM/wait/KILL/wait仅针对自有直接子进程，验证回收、删除带独占标记的临时AVD目录，并比较KVM前后元数据。没有Magisk、真实手机或系统应用动作。

对应新增host回归覆盖调试Root closed重连与拒绝、安装回执/哈希、正向日志、退出记录、清理所有权和KVM不变；host通过不等于真实实验通过。

AVD身份闸门同时核对只读 `ro.boot.qemu.avd_name`，必须精确等于本次创建的名称。`adb emu avd name` 成功但stdout为空时，保留原始命令证据并使用该boot属性；不再对空行列表取首项。非空console响应必须为相同名称（可带末行 `OK`），任何冲突、拒绝、超时或缺失boot属性均在Root/安装前停止。此修正不改变镜像/架构/调试身份、独占端口和全新AVD的其他闸门。

2026-10-02 VM迭代：API35只读探测已实测完成；首次夹具冻结时onStop尚未完成，kernel/AMS短暂冻结后heartbeat继续，严格判失败，清理同实例解冻和AVD销毁均完成，不能记作冻结通过。后续runner在onStop后要求同生命周期至少两次heartbeat递增，才允许开始冻结；冻结观察只用已验证debug Root读取唯一夹具固定私有文件，不运行run-as进入夹具UID/cgroup。失败也保存冻结窗前后heartbeat、限定logcat与退出记录，原有1.2秒平台期、kernel与AMS双证据要求不变。

## 协调器死亡触发（待本轮真实VM验收）

独立watchdog先加载固定VM/夹具身份并通过READY握手，协调器才可提交冻结。协调器独占一个close-on-exec管道写端，watchdog只继承读端；协调器退出73或被杀后，EOF立即触发清理。18秒是从布置开始的最迟触发期限，不是保证解冻完成的期限；触发后的ADB I/O共用另一个20秒绝对预算，超时仍判未证实并由外层销毁AVD。

冻结提交、正常解冻和watchdog清理共享宿主锁；watchdog取得锁后设置终止标记，迟到协调器不能在已开始清理后再提交冻结。完成标记包含随机token、boot ID、PID/UID/starttime/nonce，仅在核对同实例解冻后写入。异常收尾由watchdog单独执行，记录命令尝试后才调用unfreeze，即使命令异常也保留attempt证据。

中断恢复通过必须同时有接手时kernel/AMS冻结、相同进程身份、解冻后heartbeat推进，以及本次watchdog命令时间窗内唯一新增的框架`sync unfroze … for 0`日志。API35 shell路径使用reason 0，不能误写为新版reason23；自然解冻、重复/缺失/过期或窗口外转换一律不作为watchdog因果证据。原1.2秒冻结平台期不缩短，不使用sticky或关闭系统保护。

锁只能阻止尚未提交的冻结，不能撤销已发出的ADB/AMS请求。协调器若在冻结提交中途死亡或请求超时，仍按失败/不完整处理并销毁AVD，不宣称原子回滚；本轮退出73专门发生在完整冻结平台期证据之后。损坏或过期完成标记不能取消清理，也不能获得通过判定；身份仍匹配时watchdog会尝试安全解冻，否则依赖外层销毁AVD。
