# 研究与许可证记录

核对日期：2026-10-02。链接是设计依据，不是兼容性测试证据。没有复制第三方实现或二进制。

- [AOSP Cached apps freezer](https://source.android.com/docs/core/perf/cached-apps-freezer)：由 ActivityManager / CachedAppOptimizer 管生命周期，需 cgroup/Binder 协作；同步 Binder 和异步缓存溢出有风险。不能把简单 cgroup 写入当成完整应用冻结。
- [Magisk 开发指南](https://topjohnwu.github.io/Magisk/guides.html) 与 [安全模式 FAQ](https://topjohnwu.github.io/Magisk/faq.html)：晚期 service、disable 标记；启动脚本不能承担万能救援。
- [KernelSU 模块指南](https://kernelsu.org/guide/module.html)：不同阶段和 late-load 行为需单独测试。
- [APatch 模块指南](https://apatch.dev/apm-guide.html) 与 [启动循环恢复](https://apatch.dev/rescue-bootloop.html)：管理器安全模式是独立恢复后路，不是数据恢复工具。
- [yc9559/uperf](https://github.com/yc9559/uperf)：研究场景识别、增量调参和退出场景后回落；仓库显示 Apache-2.0。没有导入脚本、预设、hook 或二进制，也不照搬关闭系统 boost/温控的策略。注意不要与同名网络基准项目 uperf/uperf 混淆。

项目当前仅自写原型，尚未选择发行许可证；复用第三方代码前须逐文件核对来源/许可证并保留通知，不能把公开 README 当成闭源二进制的复用授权。

## 两台目标设备

- [一加15官方产品页](https://www.oneplus.com/cn/15) 确认第五代骁龙8至尊版和 ColorOS16 产品信息。
- [小米集团2025中期报告](https://ir.mi.com/static-files/f032d2b5-8fa8-4cb7-b00e-a22ec00b954d) 确认 Redmi K80 至尊版采用天玑9400+。这是硬件产品信息，不是设备当前 ROM/内核版本。
- Qualcomm 与 MediaTek 的 CPU/GPU、功耗管理和厂商服务不同；不共享 sysfs 写入预设。每台手机必须单独采集当前内核、cgroup、Binder 能力、系统保护信号与原值，不能从型号推导运行时权限或兼容性。
- [Linux cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)：`cgroup.freeze` 是核心接口，不应因 `cgroup.controllers` 未列出 freezer 就判定不支持；读取节点存在也不能证明 Binder/框架协作可用。

## 未纳入内容

不导入第三方闭源二进制，不注入 SurfaceFlinger，不杀厂商温控/调度服务，不用随机网上调参集合。Android 11+ 的 AOSP 功能存在不等于任意 OEM ROM 可安全外部控制；目前没有宣布任何系统/Root管理器完成兼容。

## Android接口追踪补充

核对AOSP android16-release的CachedAppOptimizer：冻结与解冻都先处理Binder，再处理进程freeze状态，并包含事务失败/终止处理。因此不能自行反转顺序或仅写cgroup节点。Android14至16的ActivityManagerShellCommand提供AMS管理的夹具实验路线，但shell不接收pidfd/expected-starttime，前后身份检查并非原子保障。只在隔离VM唯一测试包范围研究，生产执行仍封闭。KernelSU官方WebUI文档与npm kernelsu 3.0.2(声明Apache-2.0)用于核对exec回调ABI；项目只写独立固定命令适配器，没有复制其实现。

界面重做参考 [Miuix组件体系](https://github.com/compose-miuix-ui/miuix) 的分组偏好行、层级与导航，仓库声明Apache-2.0。当前为自写WebUI，不声称使用原生Compose/Miuix组件；未复制其代码/字体/资源。本轮仅首页确认新方向，不把旧暖色营销布局当定稿。
