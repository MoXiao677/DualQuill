# C07 全书规划：人物弧光、关键事件、章节依赖与进度偏离

2026-10-21 隔离增量：正文驱动待审提案、影响预览、接受/拒绝、锁定、人物/知识节点生命周期及建议 V43 集合见 [新提案契约](c07-body-planning-proposals.md)。下文保留 V26 原交付的历史范围与实测结果；AI 新增入口仅提供上下文准备和建议导入，不新增模型传输。

截至 2026-10-20。本批补齐 PRD §10.7 中可离线、确定性的 V26 范围：人物弧光及阶段、关键事件、章节依赖、计划与实际发生的分开记录、进度/偏离只读报告，以及 V26 完整备份/恢复/复制。大纲/分卷/场景、F1 手动规划、书级 AI 候选与既有字段提案链路继续沿用原实现。

## 数据模型（V26）

新增集合：

- `character_arcs`：`character_id`、标题、说明、归档、revision、创建/更新时间。
- `character_arc_stages`：`arc_id`、按弧光内唯一且递增的 `ordinal`、计划章节、`status=planned|occurred|dropped`、发生章节、正文引用、revision。
- `key_events`：标题、说明、人物/弧光绑定（可空）、计划章节、`planned_order`、发生状态/章节/正文引用、revision。
- `chapter_dependencies`：前驱/后继章节、`kind=setup|payoff|continuity|causal|knowledge`、说明、启用、归档、revision。
- `full_book_planning_operations`：append-only 操作记录，保存 `operation_id`、动作、目标类型/ID、请求 revision 与请求 SHA-256。

状态约束：

- `occurred` 必须同时有发生章节和非空正文引用；`planned`/`dropped` 必须没有发生章节，正文引用为空。
- 弧光阶段不能跨书、不能引用不存在或已归档的章节作为新计划/发生位置；归档弧光拒绝新增或修改阶段。
- 依赖不能自环；未归档依赖的（前驱、后继、类型）组合不能重复；跨书章节与不存在章节被拒绝。
- 归档/恢复、计划/发生/放弃/回到计划都递增对应实体的 revision，并写入一条操作记录；旧记录只追加不删除。

## 计划与已发生分离

章节正文的 `status=confirmed` 只表示正文已确认，不会自动把任何弧光阶段或关键事件改成 `occurred`。作者必须显式提交发生章节和正文引用，例如“第三章第 2 节末段 / 第一次交出旧钥匙”。回到计划会清除发生章节和正文引用，不会删除历史操作记录。

`GET /api/projects/<id>/full-book-planning` 返回：

- 弧光及按序阶段、关键事件、依赖、可选章节/人物列表；
- `deviation`：已确认章节数、最新确认章号；阶段/事件/依赖计数；逐项计划位置与实际位置；偏差与引用警告；
- `ai_completion`：固定为 `{'status':'unavailable','reason':'AI 补全未实现；当前入口不接受模型请求'}`。

偏差原因：

- `late`：作者记录的实际发生章号晚于计划章号。
- `early`：实际发生早于计划。
- `unplanned`：已记录发生，但没有计划章节。
- `missing`：计划位置已进入已确认章节范围但尚未记录发生；或引用损坏/缺失。
- `blocked`：计划/发生章节已归档；或后继章节已确认而前驱尚未确认。

缺失/归档引用同时在 `deviation.references` 中按实体与字段列出，供作者修复；报告只读，不自动改写正文、计划或锁定项。

## 写入入口

`POST /api/projects/<id>/full-book-planning/actions`

请求必须含 `action`、`operation_id`、`expected_revision`，其余字段按动作传入。支持：

- 弧光：`create_arc`、`update_arc`、`archive_arc`、`restore_arc`
- 阶段：`create_stage`、`update_stage`、`occur_stage`、`drop_stage`、`reopen_stage`
- 事件：`create_event`、`update_event`、`occur_event`、`drop_event`、`reopen_event`
- 依赖：`create_dependency`、`update_dependency`、`set_dependency_enabled`、`archive_dependency`、`restore_dependency`

同一 `operation_id` 与同一语义请求重放返回原结果且不重复写入；同编号不同请求、跨书身份、过期 revision 均明确拒绝。HTTP 边界：未授权 403、revision/身份冲突 409、未知项目/实体/动作 404、参数或状态非法 422。

## 界面

“全书大纲”页在原大纲下方增加“全书规划”面板：

- 进度卡与偏差原因列表；
- 每个阶段/事件分列“计划位置”和“实际发生（作者记录）”；
- 弧光/阶段/事件/依赖的新增、编辑、发生、放弃、回到计划、启停、归档、恢复；
- 发生记录强制选择启用章节并填写正文引用；
- 缺失/归档引用与受阻项集中显示；
- 危险动作（归档、放弃、回到计划）要求浏览器确认；
- AI 补全明确显示不可用，不伪造执行或候选。

静态资产 `/full_book_planning.js` 已加入 Python 静态白名单与 Electron `desktop/security.cjs` 资产表；`app.js` 仅在打开大纲页时读取该接口。

## 备份与迁移

- 工作区版本 26；完整备份 manifest 的 `backup_format_version` 与 `database.workspace_version` 随实际工作区为 26。
- 备份能力返回 1–26，迁移能力含 `backup_v26`；V1–V25 读取/恢复/复制路径保持原样。
- 复制映射弧光/阶段/事件/依赖/操作记录 ID，`target_id` 按目标类型映射；保留 `request_sha256`，操作幂等 token 重新映射，避免跨书身份冲突。
- V25 状态仅在首次 V26 写入时落盘升级；只读列表不会伪造已保存版本。升级不会改动既有资料、记忆、任务等集合。

## 验证

证据根：`C:/Users/Administrator/AppData/Local/AI-Novel-Writer-review/c07-20261020/`。

- C07 业务 7 项通过（`green-c07-unit.log`），HTTP 3 项通过（`green-c07-http.log`）。
- C08 资料回归 13 项通过（`green-c07-materials.log`）；迁移/备份回归 74 项通过（`green-c07-migration-backup.log`）。
- `app.js`、`full_book_planning.js`、`desktop/security.cjs` 的 `node --check` 均通过（`green-node.log`）。
- 隐藏 Electron/CDP 8 项通过，`status=passed`、`providerCalls=0`、`errors=[]`、`external=[]`（`green-electron-c07.log`、`green-electron-c07-report.json`、`green-electron-c07-20261020d.png`）；覆盖新增弧光/阶段/事件/依赖、确认章节不自动发生、缺失偏差、显式发生后的迟到偏差及确认后归档依赖。
- 全量 `unittest discover` 共 723 项，结果为 4 failures、4 errors（`red-full-unittest-4f-4e.log`），不标为全绿。既有失败为：`test_backup_validation.test_all_fifteen_sql_columns_have_pre_read_byte_limits` 的 `content_blobs.sha256`/`content_blobs.data_base64` 两个子测试错误；`test_s3_planning.test_budget_truncation_sources_and_versions_are_explainable` 错误及 `test_default_preview_is_readonly_saved_past_only_and_no_unlocated_spoilers` 失败；`test_s3b_retrieval.test_confirmed_memory_filter_freshness_archive_position_and_budget` 错误；`test_s6b_http.test_template_preflight_export_and_token_no_execution`、`test_server.test_export_contains_all_saved_data`、`test_server.test_in_app_guide_is_accessible_without_a_novel` 失败。

## 明确边界

- 本批不实现 AI 补全、语义质量评估、自动规划提案、偏离提案的接受/拒绝/影响预览或自动改写正文；界面与 API 均不发起模型请求。
- 依赖类型与偏差是确定性的作者记录与位置比较，不代表语义因果、动机、知识状态或伏笔是否真正成立。
- 真实长篇规模（数千章/大量依赖）的交互性能、可读性与存储规模未验。
- 隐藏 Electron/CDP 已在本批开发入口通过上述 8 项；打包安装器、干净 Windows 环境、真实模型效果与费用未验。
- 未提交、推送、签名或发布；未操作正式 `data/`、端口 8765、作者预览 profile/stage 或全局凭据设置。
