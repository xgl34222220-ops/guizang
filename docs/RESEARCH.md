# 研究与许可证记录

核对日期：2026-10-02。链接是设计依据，不是兼容性测试证据。没有复制第三方实现或二进制。

- [AOSP Cached apps freezer](https://source.android.com/docs/core/perf/cached-apps-freezer)：由 ActivityManager / CachedAppOptimizer 管生命周期，需 cgroup/Binder 协作；同步 Binder 和异步缓存溢出有风险。不能把简单 cgroup 写入当成完整应用冻结。
- [Magisk 开发指南](https://topjohnwu.github.io/Magisk/guides.html) 与 [安全模式 FAQ](https://topjohnwu.github.io/Magisk/faq.html)：晚期 service、disable 标记；启动脚本不能承担万能救援。
- [KernelSU 模块指南](https://kernelsu.org/guide/module.html)：不同阶段和 late-load 行为需单独测试。
- [APatch 模块指南](https://apatch.dev/apm-guide.html) 与 [启动循环恢复](https://apatch.dev/rescue-bootloop.html)：管理器安全模式是独立恢复后路，不是数据恢复工具。
- [yc9559/uperf](https://github.com/yc9559/uperf)：研究场景识别、增量调参和退出场景后回落；仓库显示 Apache-2.0。没有导入脚本、预设、hook 或二进制，也不照搬关闭系统 boost/温控的策略。注意不要与同名网络基准项目 uperf/uperf 混淆。

项目当前仅自写原型，尚未选择发行许可证；复用第三方代码前须逐文件核对来源/许可证并保留通知，不能把公开 README 当成闭源二进制的复用授权。
