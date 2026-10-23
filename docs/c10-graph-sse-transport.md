# C10 阶段二：专用图谱 SSE 契约

本阶段在 `followup-transport/workspace` 开发，基线为阶段一440文件白名单快照；阶段一源码、三件套和证据保持冻结。工作区格式仍为暂用 V45，不新增集合、迁移或 SQL 表。完整版本号仍由主整合分配。

## 实际范围

图谱使用自己的 `graph-extract-json-1` 提示、明确选择的保存章节、精确冻结请求和目的地/预算确认。SSE 只是同一请求的传输方式：未完整结束前只提供当前进程内的转义预览；只有合法完成且通过 typed 图谱与逐实体/边精确引文校验，才保存待核实提案。作者另行勾选核实推断并接受后，才新增正式图谱。

三种协议均有图谱专用真实 loopback HTTP 及浏览器链路：OpenAI Chat、Anthropic Messages、Gemini Content。供应商替身将 UTF-8 文本和 SSE 边界逐字节写入，正文含首 LF、CRLF、中文和 emoji，且通过门闩确保预览与完整输出可分开观察。没有使用摘要或普通候选的 SSE 结果替代图谱证据。

失败覆盖错误帧、HTTP 响应中途断开、缺少 SSE 完成、错误引文、错误实体类型、空边引文、取消和超时。取消/超时先在本地结束，再让供应商尝试发送完整迟到尾部，不能生成提案或正式图谱；终态不能以旧许可重跑。预览不进入数据库、备份或重开结果。

完成后的数据库实盘重开不自动发送；完整恢复及连续两次复制保留精确冻结请求和来源身份映射，但 pending 任务仍须新的执行确认。新响应即使合法，也须新的独立作者采纳，不能继承已有提案的接受许可。

## 尾帧根因修复

原 Gemini 解码器在读到 STOP 后仍要求后续事件必须含一个候选，因而拒绝 `candidates: []` 或省略 candidates 的 usage-only 元数据尾帧，导致已经完整返回的图谱任务失败。本阶段先保存图谱真实 HTTP 的失败日志，再修正共用 `application/sse_protocols.py`：只有 STOP 之后且含合法 usageMetadata 的空候选/无候选帧才允许作为用量尾帧；不追加正文，不放宽 STOP、工具、负数 usage、缺少完成或迟到续文守卫。计数来自响应，未伪造为零。

OpenAI usage 在 finish_reason 后、DONE 前；Messages usage 在 content_block_stop 后的 message_delta；Gemini usage-only 在 STOP 后。成功时持久响应分别保留实际 17/23/40 的虚构计数。以上为受控虚构协议证据，不能等同全部真实供应商兼容性或实际账单验收。

## PRD 资料范围核对

当前 `PRODUCT_REQUIREMENTS.md` §10.10 明确要求「点击节点/关系回到正文或资料」，并要求纠正提取及来源版本，但没有明确要求从导入资料自动抽取。§10.5 的自动提取来源明确是「作者选择的章节或已采纳正文」；§10.8 管理导入资料、版本/范围、引用与检索。

因此本阶段保持选中已保存章节的抽取范围，不新增导入资料抽取。导入资料的版本/range/hash/归档到模型提案全链路仍未实现或验收；不能将当前章节来源证据称作资料导入来源证据，也不宣称 PRD 所有资料出处能力已完成。

## 主整合必须处理的共享白名单

阶段一新增的 `/graph_view.js` 已在 Python HTTP server 静态映射中，但本副本 `desktop/security.cjs` 的精确 `ASSETS` 缺少它。`desktop/build.cjs::sourceFiles()` 从该 Map 派生静态打包白名单，实际只读审计得到：文件存在、ASSETS false、packaged false。

根据主协调分工，这两项由主整合集中修复，本阶段不抢改。主整合应增加精确 `/graph_view.js` → `graph_view.js` 映射，并验证自定义协议分类、静态依赖闭包及包内 sourceFiles 包含该文件；保持未知路径拒绝，不能用通配路径绕过安全边界。本轮没有执行 build/prepare/下载、全量或打包桌面，HTTP 浏览器通过不等同 Electron 自定义协议或最终包验收。

## 验证入口

- `python -m unittest test_graph_sse_transport -v`：图谱专用实际 HTTP、错误/中断/迟到、重开/恢复/双次复制/新许可。
- `python -m unittest test_sse_protocols test_sse_tasks -v`：共用解码器和原请求回归，不作为图谱专用证据的替代品。
- `node tests/e2e-graph-sse.cjs`：三个协议各成功/取消两个场景，显示临时预览、人工采纳及重载不重发；需显式 G盘 `NOVEL_WRITER_ARTIFACTS`、预装 Playwright/Edge。

精确命令、退出码、原失败/修后结果、源 SHA 与阶段一冻结校验以本阶段 workspace 外三件套为准。真实模型/真实付费调用为零；实体消歧、别名和关系语义质量仍待真实模型与作者验收。
