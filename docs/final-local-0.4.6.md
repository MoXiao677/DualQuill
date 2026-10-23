# 0.4.6 固定包验收与已知 RED｜2026-10-21

本版新增作者明确启用的已保存汇总上下文消费。**固定包存在两个独立复现的上下文保护缺陷，不称全部完成。** 源码完整回归825项通过（506.656秒），但未覆盖的独验RED仍为缺陷。功能契约与操作见 [已保存汇总上下文](saved-rollup-context.md)。

## 固定产物

唯一构建 `run-88-build-0.4.6.log`，独立 `desktop/.cache/build-stage-a31dd68533b9`；后续修复进入0.4.7，不覆盖以下文件。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/s7/AI Novel Writer-0.4.6-win.zip` | 165428295 | `66fba27890ce3612137697bcf7b4e47bc94599b3f5b6427485b2f23d2fcf8cfa` |
| `dist/s7/AI Novel Writer Setup 0.4.6.exe` | 122048167 | `7e2dcf7e43a0a19faad9857775f790d4b06bfcca9fb2e6a2884dd3ff8faad55a` |

证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。`package-audit-final-0.4.6.json`：真解包 `extracted-final-0.4.6` 共264条目，141后端源码匹配 `source-manifest-final-0.4.6.json`，无禁带内容。`asar-audit-final-0.4.6.json`：5个CJS/版本匹配；notices另逐SHA核对一致。`signature-final-0.4.6.json` 为NotSigned，安装器未执行。父独立核对相同字节数、哈希、264条目/141源码与ASAR一致。

## 已通过的有限验证

- `run-87-0.4.6-full.log`：Python825项通过，506.656秒，退出码0。结束后再次核对141文件SHA，差异0；`full-source-binding-0.4.6.json`同时记录两个独验RED，不把全量绿称为零缺陷。
- `run-82-rollup-writing.log`：新增7项通过，含真实loopback请求、V32完整恢复复制、旧编码、冻结与重建保护。
- `run-84-context-regression.log`：85项通过，63.809秒；任务/初稿续写/迁移/备份。
- `run-85-node-0.4.6.log`：Node24项通过；静态JS29文件通过。
- `run-86-context-source-ui.log`：源码上下文桌面5组通过；`run-89-context-packaged.log`：最终解包同5组通过，0模型调用。
- `run-90-author-packaged.log`：最终解包原作者7组通过，0模型调用。
- `run-91-dialogue-packaged.log`：最终解包三协议严格原生对话5组通过，5次loopback。
- `run-92-writing-packaged.log`：最终解包长正文4组通过，实际31.456秒响应、取消218ms、1秒超时与重开不重发，3次loopback。桌面errors/external均空。

父独立证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/lead-independent-c05-context-20261021/`：最终包 `packaged-context-backend/report.json` 6组、`packaged-context-ui/report.json` 5组、`packaged-legacy/report.json` 5库（含2个旧正文FrozenInput逐字段/request_body/hash不变与零写）、原对话6组（首响应32.017秒）、原作者7组通过；源码capture-01同范围另外保留。有限范围通过不能抵消后述新增失败。

## 必须保留的产品 RED

父 `packaged-search-extra-01/report.json` / `red-11-packaged-search-extra.log`：`include_memory_rollups=true`、`scope=previous`、显式检索选入当前章记忆时，当前章原文通过 `search_result` 绕过原始记忆分支排除；同入口也可选入未解冲突的过去记忆。原始记忆已排除，但检索仍 `included=true / selected_search`。旧flag关闭行为亦记录，下一版只能加强新模式，不能改写旧冻结。

父 `packaged-new-context-guard-01/report.json` / `red-12-packaged-new-context-guard.log`：新flag开启但没有可选汇总依赖时，冻结的过去原始记忆之后新增同位置同标题冲突；新预览已经排除，真实TaskCoordinator.start却仍返回running。根因是发送/采用复核仅按已有rollup依赖触发，没有按新模式开关触发。使用本地协议、无外网，是真实产品失败。

下一版0.4.7优先统一新模式的原始记忆与显式检索资格，并在发送/采用时按opt-in复核，即使没有rollup依赖也不能漏。只复核，不替换冻结正文或请求体。两项GREEN前不扩SSE。

`run-83-context-source-ui.log` 为新增UI测试等待已自动导航离开的DOM导致null读取，改为等待真实持久任务后run-86通过；这是夹具问题，与上述两个产品RED分别保留。父旧库早期夹具RED为选中只有book_ai_tasks的库及把复合request_sha误当纯bodySHA，修夹具后旧冻结通过。

真实付费0；正式data/8765、作者窗口/profile/凭据、冻结stage、author-preview及全局配置未触碰；无子代理/新聊天、提交推送、签名发布或安装器执行。模型语义摘要、自动记忆更新、SSE、真实供应商/干净VM等仍未齐。
