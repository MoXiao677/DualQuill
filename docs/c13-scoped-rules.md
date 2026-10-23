# C13 分级作用域规则｜2026-10-20

2026-10-21 第二阶段隔离增量见 [真正的模型语义规则审阅与独立规划任务作用域](c13-semantic-rule-review.md)。以下保留历史交付范围。

2026-10-21 隔离增量：[C13-C 单任务规则与待核实语义意见](c13-task-rules.md) 补充显式任务绑定、冻结守卫、V36 建议格式及严格引文意见预览。下文保留原四级规则/V22 已验收历史，不将历史数字冒充本批结果。

写作规则已从单一书级文本扩展为 global/book/volume/chapter 四级规则集；解析时按 chapter > volume > book > global 归集，并把旧书级 `writing_rules` 作为 legacy book 指引继续注入。C13-B 补上批量导入和 append-only 规则历史，规则与历史一起升级到工作区/完整备份 V22。

## 规则字段

规则包含作用域、实体、类型、原文、启用/归档、来源与版本：

- 作用域：`global`（无实体）、`book`（当前书）、`volume`（卷号）、`chapter`（章节 id）。
- 类型：`required` 必写、`forbidden` 禁写、`guidance` 风格指引。
- 来源：`manual` 或 `legacy`（旧 writing_rules 合成只读规则）。
- 每条规则保存版本号；修改、启停、归档递增版本。归档规则不参与解析，但保留记录。删除仅删除当前规则记录。

## 批量导入

- 入口：规则页“批量导入”；HTTP 为 `POST /api/projects/{id}/rules/import-preview` 与 `POST /api/projects/{id}/rules/import`。
- 输入支持 JSON 数组或只含 `rules` 的对象，也支持 CSV；字段固定为 `scope,scope_id,kind,text,enabled`。CSV 表头必须完全一致，`enabled` 仅接受 `true/false`。
- 上限：512 KiB、500 条、单条原文 1–2000 字。只用 `json`/`csv` 解析器，不执行脚本或任意代码。
- 预览逐行返回 `row/status/errors/rule`，非法行显示行号和字段；任何一行非法时 `can_confirm=false`，确认入口整体拒绝，不写入任何一行。
- 预览把拟导入规则与现有启用规则一起按 chapter > volume > book > global 解析；同文本 required/forbidden 冲突会列出导入行、现有规则 id 和作用域，并阻止确认。已有冲突也会阻止本次导入。
- 确认请求携带 `operation_id`、`format`、`content`、`preview_sha256`；预览后状态/revision 变化会要求重新预览。写入在现有 `repository.atomic` 单事务内完成，任一步失败整体回滚。
- 同一 `operation_id` 重放仅在本次创建的规则仍全部存在、且条数/内容一致时返回 `idempotent=true, created=0`；同一编号的条数或内容不一致会拒绝；确定性历史已存在但规则已删除或部分删除时明确拒绝重放，绝不重新插入。导入只写规则与历史，不自动启用任务、不调用模型。

## 规则历史

- V22 新增 `scoped_rule_history` 集合；新建、修改、启停、归档/恢复归档、删除、批量导入都追加一条记录：`operation`、`before`、`after`、`created_at`、`source`（`manual`/`import`）。
- 历史 append-only：加载时校验已有前缀不得改写、删除或重排；修改规则当前记录不会改写历史。
- 删除只移除 `scoped_rules` 当前记录，历史仍按 `rule_id` 保留；规则页为现有规则和已删除规则都提供“查看历史”，只读显示操作前后版本/作用域/类型/启停/原文与时间。
- HTTP 读取：`GET /rules/history`（全部）和 `GET /rules/history/{rule_id}`（单条）。桌面安全层拒绝查询串，UI 使用路径参数。
- 不提供“回滚执行”：历史不能恢复为当前规则、不会改变解析结果或任务许可。

## 解析与冲突

- 只纳入启用且未归档的规则；全局、本书、目标章所属卷、目标章规则按 chapter > volume > book > global 排序。
- 完全相同的 `(kind,text)` 只保留最高作用域的一条；文字相近但不同不合并、不做模糊判断。
- 同一 text 同时出现 required 与 forbidden 时返回冲突，列出所有 rule id 与作用域。存在冲突时 C04-A/B1/B2 的准备入口都拒绝，不静默选择其中一条。
- 解决入口：在规则页停用/归档冲突规则，重新解析；冲突消失后可准备任务。

## 注入与字面检查

- 旧 `writing_rules` 是 legacy book guidance，仍出现在规则解析、上下文和结果中，不丢历史。
- `context_preview` 将每条生效规则以 `rule` 来源写入冻结上下文，保留 id/scope/kind/source/version；任务依赖记录 rule 来源，规则变化会使旧候选失效。
- C04-A 初稿/续写的 `required_literals`/`forbidden_literals` 合并解析后的必写/禁写文本，候选指标使用解析结果而非仅作者本次输入。
- C04-B1 构思/细纲与 C04-B2 场景/选区上下文都包含解析后的规则列表；准备前统一检查冲突。

## V22 持久化

工作区与完整备份格式升级到 V22，新增 `scoped_rule_history`；`scoped_rules` 继续使用 V21 结构。完整备份/恢复/复制保留规则、历史、来源与版本，复制映射规则/历史 id 和书/卷/章作用域，不继承执行许可。V1–V21 读取/恢复/复制继续可用；V21 规则复制后仍为 V21 且不凭空补造历史。旧 V1–V21 原行保留。能力端点 `/api/backups/capabilities` 的 `backup_format_versions` 与 `workspace_versions` 返回 1–22；`/api/migrations/capabilities` 的 `formats` 在 `backup_v21` 后包含 `backup_v22`，由 HTTP 测试守护。

## UI

“文风规则”页新增分级规则编辑：作用域/类型/目标/原文/启用、规则列表（启停/归档/删除）、选择某章查看实际生效规则与冲突。冲突时显示冲突文本；停用/归档后可重新解析，并提供“按生效规则准备初稿（不发送）”按钮用于验证 pending 任务。C13-B 增加粘贴/文件选择、格式选择、预览逐行结果、确认导入按钮，以及现有/已删除规则的只读历史面板。

## 证据

本批证据根：`%LOCALAPPDATA%\AI-Novel-Writer-review\c13b-20261020\`

- `green-unit-20261020T030940-baseline.log`：开始前基线 5 项。
- `green-unit-20261020T033209-rules-v22-contract.log`：规则、导入、历史与 HTTP 共 18 项通过（现有 5 + 新增业务 11 + HTTP 2），含“导入→删除全部→同编号重放拒绝”与 V22 能力契约断言。
- `green-regression-20261020T032703-engines.log`：C04-A/B1/B2 与控制台 39 项通过。
- `green-regression-20261020T033220-backup-migration-v22-contract.log`：备份、上传、迁移及 HTTP 66 项通过。
- `green-unit-20261020T031544-v21-copy.log`：V21 完整备份恢复/复制兼容 1 项。
- `green-electron-20261020T032926.log` 与 `electron-20261020T032926-report.json`：隐藏 Electron 6 项通过（规则页、预览启用确认、确认写入、单条历史、非法行阻止、冲突阻止），`status=passed`、`errors=[]`、`external=[]`；截图 `electron-20261020T032926.png`。
- 本轮仅重跑规则/HTTP 18 项与备份/迁移 66 项；39 项创作链与隐藏 Electron 6 项沿用既有通过证据，未重跑；UI 资产未改动。
- 领导独立复核（最终源码）：重跑规则/HTTP 18 项、备份/迁移 66 项、隐藏 Electron 6 项、交接核心 29 项均通过，证据为 `green-lead-unit-rules-v22-20261020T033410.log`、`green-lead-regression-backup-migration-v22-20261020T033502.log`、`green-lead-electron-20261020T0342.log`、`electron-lead-20261020T0342-report.json`、`green-lead-core-29-after-v22-20261020T0346.log`。另复跑 `test_backup_validation`+`test_server` 复现 4 项既有失败（`red-19-lead-backup-validation-server-20261020T033528.log`），与本批规则/V22 改动无调用关系。
- 当前保留的失败文件：`red-01-existing-version-20261020T031130.log`、`red-02-version-expectation-20261020T031136.log`、`red-03-business-20261020T031213.log`、`red-04-business-20261020T031230.log`、`red-05-business-20261020T031237.log`、`red-07-regression-storage-20261020T031330.log`、`red-13-electron-20261020T031811.log`、`red-14-electron-20261020T031847.log`、`red-15-electron-20261020T031948.log`、`red-16-electron-20261020T032019.log`、`red-17-electron-20261020T032110.log`、`red-18-electron-history-20261020T032206.log`；编号不连续是实际保留结果，不补造缺失编号。早期 green 误命名已原样改为 red-13..18，未把通过输出标成 red。
- `electron-20261020T032353-report-duplicate.json` 与 `electron-20261020T032353.png`：无时间戳旧产物；报告 `status=passed`，JSON 与 `green-electron-20261020T032353-report.json` 哈希相同。作为重复文件保留，不列为最终证据，也不标成失败。

上一批 C13 证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C13-scoped-rules-20261020/`

- `green-unit-20261020T023241Z.log`：5 业务 + 1 HTTP 通过（优先级、章级优先、冲突阻止、停用解决、legacy 生效、上下文来源、启停归档、未知作用域、V21 备份复制）。
- `green-ui-20261020T023224Z.log` + `ui-20261020T023224Z/scoped-rules-ui.json`：隐藏 Electron 新增 book required + chapter forbidden→显示冲突→停用一条→解析无冲突→规则页准备 pending 初稿，零外发。
- `green-affected-c04-20261020T023443Z.log`：C04-A/B1/B2 40 项；`green-affected-console-lifecycle-20261020T023248Z.log`：控制台/C16/C17 21 项；`green-assets-*`、`green-affected-desktop-*`：桌面/UI 资产 12 项与 profile 2 项。

失败日志保留：`red-01-rules-missing.log`、`red-02..15` 的实现/卡片/导航/准备调试失败。没有把通过日志另存成 red 名。

## 未验与边界

- 真实模型对规则的遵从率、语义冲突和长篇规则规模未验；文字相近但不同按设计不算冲突。
- 真实模型对导入后规则的遵从率、长篇规则规模与语义冲突仍未验；导入冲突只做精确同文本判断。
- V21 之前的规则没有历史回填；历史从 V22 启用后的操作开始记录，不提供回滚执行。
- 本批未重新打包/签名/发布；`red-07` 宽回归 118 项中有 4 项既有失败（2 errors + 2 failures）：`test_backup_validation` 的两条 `content_blobs` 表/列假定，以及 `test_server` 的导出与指南断言。均未修改相关代码，和本批导入/历史改动无关。
- 未操作作者预览 profile/stage/正式 data/8765/窗口/全局设置；未提交推送发布。
