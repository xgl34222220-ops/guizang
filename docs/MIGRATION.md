# 仓库迁移记录

- 迁移前 main：`8124f8d8235590cd59422169c6561647e67387ce`
- 已读回验证的归档分支：[`archive/pre-android-module-20261002-8124f8d`](https://github.com/xgl34222220-ops/guizang/tree/archive/pre-android-module-20261002-8124f8d)
- 迁移方式：以旧 main 为父提交，正常提交替换工作树；没有 force push、重写/删除历史、删除仓库。
- 保留旧聊天室测试分支和 `4e45188` 幂等重试工作，不带入 Android 模块。
- 不触碰已经部署的聊天室/网关服务、平台设置、secrets 或数据卷。若服务另设自动跟踪 main，维护者需要单独核对其部署规则；本次未调用任何部署操作。

## 找回旧源码

在新的本地目录 clone 本仓库并 checkout 上述 archive 分支，即可得到迁移前完整工作树。不要在现有生产服务目录盲目 pull 新 main。若决定恢复主分支用途，应通过新的正常 revert/恢复提交审核，不重置远端历史。
