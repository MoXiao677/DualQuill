# 0.4.5 本地最终验收｜2026-10-21

本版交付章节独立确定性记忆汇总、旧 V1 非 UUID 章节归档/回收站兼容，以及 localhost 多地址 TCP 建连兼容。操作与契约见 [章节汇总](chapter-memory-rollups.md)。不调用模型生成摘要，不自动消费汇总或更新记忆。

## 固定产物

唯一构建 `run-74-build-0.4.5.log`，独立 `desktop/.cache/build-stage-c46c44264c41`。以下产物固定，不用后续源码变化冒称属于本包。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/s7/AI Novel Writer-0.4.5-win.zip` | 165426519 | `f248cb2c7342ce8d7cbe5a89f3c5437273e1fd3158be542e9aa27cfee1b8adba` |
| `dist/s7/AI Novel Writer Setup 0.4.5.exe` | 122046379 | `e1088dab254142195d37c96032ddc8d5c0d579bef51f899e6164fb7aa864570f` |

证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。`package-audit-final-0.4.5.json`：真解包 `extracted-final-0.4.5` 共264条目，141后端源码逐字匹配，无禁带内容。`asar-audit-final-0.4.5.json` 核对5个CJS、版本与notices。`signature-final-0.4.5.json` 为NotSigned，安装器未执行。完整测试结束再次核对 `source-manifest-final-0.4.5.json` 的141文件，差异为空；完整回归期间产品源码没有改变。

## 最终验证

- `run-72-0.4.5-full.log`：Python **818项全部通过，499.838秒，退出码0**。
- `run-70-chapter-legacy-ready.log`：章节汇总、旧ID生命周期、localhost与既有相关回归31项通过，17.649秒。
- `run-75-node-0.4.5.log`：Node24项通过；29个静态JS语法通过。
- `run-73-chapter-source-ui.log`：源码隐藏桌面5组通过；最终解包 `run-76-chapter-packaged.log` / `chapter-final-0.4.5/report.json` 5组通过，含选择、预览保存、过期/重建、不可变历史、归档阻止与重开。
- `run-77-author-packaged.log` / `author-final-0.4.5/report.json`：原作者7组通过；0次模型调用。
- `run-78-dialogue-packaged.log` / `dialogue-final-0.4.5/dialogue-report.json`：三协议严格原生对话5组通过，5次虚构loopback。
- `run-79-writing-packaged.log` / `writing-final-0.4.5/report.json`：正文4组通过，真实31.461秒响应、取消217ms、1秒超时及重开不重发，3次虚构loopback。上述桌面errors/external均为空。

父独立证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/lead-independent-c05-chapter-20261020/`：`package-independent-audit.json` 核对同一ZIP/NSIS哈希、264条目、141文件、ASAR、NotSigned及与capture-02源码差异为空。`packaged-chapter-backend/report.json` 8组、`packaged-chapter-ui/report.json` 4组、`packaged-dialogue-ui/report.json` 6组（真实首响应32.072秒）、`packaged-tls-localhost/report.json` 6组及原作者7组全部通过，UI errors/external为空。父源码8组及实际原生确认框UI4组另保留，不与最终包证据混称。

## 保留的 RED 与边界

0.4.4 IPv6首地址拒绝后未尝试IPv4是实际产品缺陷，本版修复仅限发送前TCP建连；全部地址先过SSRF校验，共享截止时间，TLS证书验证保持，HTTP错误和发送后绝不重试。旧V1非UUID章归档亦为实际产品缺陷，本版修复实体引用校验，操作/事件ID继续UUID。

run-64/65/67/68是新增测试夹具错误：确认参数、独立SkillLibrary schema、跨项目快照排序假定、缺少保存版本/HTTP停止方法及原文假定；修正夹具后run-70通过，不冒称产品回归。run-71因原生确认框阻塞CDP evaluate超时；测试显式确认后run-73/76通过，父另验证真实原生确认框。旧0.4.3及0.4.4失败记录和固定产物继续保留。

真实付费0；正式data/8765、作者窗口/profile/凭据、冻结stage、author-preview及全局配置未触碰。无新聊天/子代理，无提交、推送、签名、发布或安装器执行。模型语义摘要、记忆自动更新、汇总自动上下文、SSE及真实供应商/干净VM仍未齐。下一版才实现作者明确启用的已保存确定性汇总上下文消费，默认关闭，必须保护旧冻结字节、排除当前/未来位置、去重、预算及来源版本冻结。
