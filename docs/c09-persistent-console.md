# C09 持久创作控制台｜2026-10-20

2026-10-21增量：注册只读工具、本次许可连续推进、候选计划回链与实际usage见 [受控工具契约](c09-controlled-tools.md)。下文保留V20/V24历史范围与当时证据，不将旧边界或旧测试数字当作本次结果。

“创作对话”已从窗口内存需求升级为项目级持久会话：会话、消息和可编辑操作计划写入工作区 V20；V24 增补显式运行编排。控制台只能把步骤派发为既有协调器的**待确认任务**，不会自动外发、执行、采纳或创建实体。

## 会话与消息

- 每项目可新建、列举、改名、归档/恢复会话；归档会话保留文字，拒绝新增消息与派发。
- 消息角色为 `author`/`system`/`assistant`/`result`，作者输入与系统派发记录追加保存；结果引用类型限定 task/candidate/receipt/session/step，不解析文字、不执行工具。
- 重启、完整恢复或复制后会话文字与计划保留；复制不继承任务执行许可。

## 可编辑计划

每条计划为会话内一条结构化记录，步骤包含：

- 类型：IDEA 构思、章节细纲、正文初稿、正文续写、场景扩写、选区扩写；
- 目标章节、指令、状态（planned/prepared/failed）；
- 场景步骤可选有序号；选区步骤可选 Unicode 码点起止。

作者可增删、改名、调整顺序与内容；保存计划只写工作区数据，不调用模型、不创建任务。未知类型、未知字段、非法章节/场景/选区明确拒绝。

## 受控派发

点击某一步“派发准备”时：

1. 先保存当前计划；
2. 调用既有 C04-A/B1/B2 协调器的 preview/prepare，使用当前本书资料与已选正文/构思/细纲/场景构建冻结输入；
3. 只产生 `pending` 任务，不调用 `start`，供应商请求数为 0；
4. 控制台只显示任务链接、状态、候选/收据引用；实际执行、逐请求确认和采纳仍必须在原任务页完成。

派发需要对应步骤的 creation preset（IDEA→brainstorm，细纲→outline，正文/扩写→draft）或已配置的明确覆盖；缺配置直接失败，不自动启用模型。归档会话、归档章节、未知参数、步骤已被派发均拒绝重复准备。

## 结果回链

会话详情实时读取已链接任务的既有状态：待确认、运行、失败、取消、中断、候选完成或已采纳；同时显示 task/candidate/receipt id 与迟到响应标记。结果只是引用，不复制正文，不把候选当已采纳内容。

## V24 显式运行编排（2026-10-20 增补）

运行是计划之上的显式状态机，不是自动执行器：

- `start` 冻结当前计划版本与有序步骤，创建 `console_runs`、`console_run_steps` 和 append-only `console_run_actions`；开始本身不调用 `preview`/`prepare`，不创建任务。
- `advance` 每次最多准备一个 `queued` 步骤，复用既有 C04 preview/prepare；只产生一个 `pending` 任务，零供应商请求。不会自动 `start`、执行、采纳或跳过。
- 步骤状态：`queued`、`prepared`、`awaiting_confirmation`、`awaiting_adoption`、`completed`、`blocked`、`skipped`、`cancelled`、`failed`；运行状态：`running`、`paused`、`cancelled`、`completed`。
- 计划版本变化、会话归档、当前任务失败/取消/中断/不可读/无候选时，推进被明确阻止并显示原因；只有作者点击“明确跳过”或“取消运行”才跨过/结束。
- `pause`、`resume`、`cancel`、`skip` 均要求 `operation_id` 与当前 `expected_revision`，操作追加保存；重复 `operation_id` 幂等。UI 不轮询、不自动推进。
- V24 完整备份/恢复/复制保留运行、步骤、操作历史并映射章节/任务/派发 ID；不复制执行或采纳许可。

运行 API：

- `GET /api/projects/{id}/console/runs`（可选 `session_id` 查询）
- `GET /api/projects/{id}/console/runs/{run_id}`
- `POST /api/projects/{id}/console/runs`
- `POST /api/projects/{id}/console/runs/{run_id}/advance|pause|resume|cancel|skip`

## V20 会话与计划持久化

工作区 V20 新增 `console_sessions`、`console_messages`、`console_plans`、`console_dispatches`。消息与派发追加保存；会话/计划仅允许改属性与步骤，不允许删除会话或消息。完整备份/恢复/复制保持会话文字/计划/任务引用，映射章节与任务 ID，不复制任何执行许可。旧 V1–V19 原记录保留。

## 证据（V24 增补）

证据根：`C:/Users/Administrator/AppData/Local/AI-Novel-Writer-review/c09-orchestration-20261020/`

- `green-unit-20261020T061500.log`：8 运行业务 + 1 资产 + 1 HTTP 共 10 项通过，覆盖冻结计划、单步准备、幂等/过期保存号、明确跳过、计划变化阻止、归档/缺预设拒绝、V24 备份恢复复制与 UI 控件资产。
- `green-ui-20261020T061000.log` + `electron-c09-1792442703788-report.json`：隐藏 Electron/CDP 7 项检查通过，覆盖开始、推进、暂停/恢复、明确跳过、计划变化阻止、归档阻止；供应商请求 0，无运行时异常/外部请求。
- `green-regression-20261020T062000.log`：241 项 Python 回归通过（控制台、C04、C13-B、C05、C16/C17、备份/恢复/复制/迁移）。
- `green-assets-20261020T055000.log`：21 项 Node 桌面安全/后端/打包/UI 状态资产通过。
- `green-lead-focused-20261020T0655.log`：领导独立重跑 C09 运行/控制台/HTTP、C05 汇总、备份/迁移 HTTP 共 46 项通过。
- `green-lead-core-29-v24-20261020T0705.log`：领导独立重跑交接核心 29 项通过；`py_compile` 与 `node --check` 通过。
- `green-lead-ui-c09-20261020T0700.log` + `electron-c09-lead20261020T0700-report.json`：领导重跑隐藏 Electron/CDP 7 项，`status=passed`、`providerCalls=0`、`errors=[]`、`external=[]`。
- 失败日志保留：`red-ui-*`、`electron-c09-*-failed.*`，以及初始 `red-01-c09-run-tests-*`。

已知但未在本批修复的既有失败：`test_s3b_retrieval` 的上下文预览预算、`test_backup_validation` 默认 schema `content_blobs` 子测试；均未混入本批通过数字。

## 证据（V20 基线）

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C09-console-20261020/`

- `green-unit-20261020T022202Z.log`：5 业务 + 1 HTTP 通过 — 会话/消息/重开、计划编辑顺序、派发 pending/零请求、未知类型、助手文字不触发任务、V20 备份/复制不继承许可。
- `green-ui-20261020T022142Z.log` + `ui-20261020T022142Z/persistent-console-ui.json`：真实 Electron 新建会话→写需求→编辑计划→派发 pending→在既有细纲任务页确认运行/采纳→控制台候选+收据回链→重开恢复，未重发。
- `green-affected-lifecycle-drafts-20261020T022211Z.log`：C16/C17 15 项回归；`green-affected-c04-20261020T022211Z.log`：C04-A/B1/B2 40 项回归；`green-assets-20261020T022346Z.log`：桌面/UI 资产 12 项。

失败日志保留：`red-01/02-console-missing-*`（模块）、`red-03..06-console-*`（消息字段/项目参数/编辑）、`red-07..19-ui-*`（导航遮罩、UI 初始化、模型会话、输入值断言等）。通过输出只写 `green-*`。

## 未验与边界

- 真实供应商语义质量、费用/限流未验；本批仅 1 次虚构 loopback（显式确认后）。
- 控制台不提供自动执行、工具调用、自动采纳或“模型文本触发动作”；计划步骤的具体上下文/预算由既有协调器决定。
- V24 运行只做“显式推进 + 单步准备”，不是自动多工具编排；步骤完成/采纳仍由作者在原任务页操作后才被观察到。
- 草稿、章节删除/危险清理、作用域规则、最终安装包仍属后续。
- 未操作作者预览 profile/正式 data/8765/窗口/全局设置；未提交推送发布。
