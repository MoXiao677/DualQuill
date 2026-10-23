# C05 增量记忆与自动选用（隔离实现，建议 V42）

本切片补充已存在的章语义摘要提案、章/卷/书确定性汇总和显式上下文入口。默认关闭；策略只能由作者明确保存。开启策略不准备、不执行、不重试模型请求，也不自动接受任何记忆。

## 本地策略与队列

`GET /api/projects/{pid}/memory-automation` 零写读取 `revision / policy / queue / external_execution_authorized:false`。

`POST` 同一路由，严格接受 `action / operation_id / expected_revision`，再按动作接受 `policy:{track_updates:bool,auto_select:bool}` 或 `job_id`。动作：`policy`、`cancel`、`reopen`、`resolve`。同编号同请求重放幂等，换输入拒绝，过期 revision 409。`resolve` 仅记录“作者已核对该队列项”，不确认记忆、不重建汇总、不授予模型执行权限。

策略开启后，正文保存/确认、标题和版本变化、归档/恢复/回收站变化、移动/重排/跨卷，以及已确认记忆增改/归档均在原保存事务追加确定性影响事件。事件给出精确 `chapter_ids / memory_ids / rollup_ids`；新记忆也会影响尚未收录它的对应汇总。正文未变但保存出新版本同样追踪，以保持既有版本新鲜度契约。未发生来源变化的普通任务状态写入不造假更新。影响沿人工来源及已接受模型提案的全部引文传播，不限于主来源章。事件只存身份、revision 与 SHA-256，不复制正文。

记忆页可保存策略、查看精确影响、取消/重开/标记人工核对，再进入对应章的既有摘要准备面板。队列不是后台执行计划；取消队列不会取消已单独准备的模型任务。付费摘要继续走原冻结请求和预算/逐请求 `confirm_external + request_sha256` 门。模型结果仅为待核实提案；显式接受才新增记忆，既有正文和 append-only 历史不被覆盖。

## 自动上下文

现有上下文预览/正文初稿续写/模型任务界面增加 `include_automatic_memories`；作者策略启用时界面默认勾选，仍可逐次取消。直接 API 调用须明确传 `true`。该字段默认 `false`，旧冻结编码省略它。

自动候选按有效位置倒序、记忆 ID 排序，只选本书启用、作者确认、正文来源新鲜且无既有确定性冲突的记忆。规划来源及未接受候选不参与；有效章位考虑所有已接受模型引文，归档/回收站来源、当前章（`previous` 模式）及未来章均排除。不会声称能够自然语言识别所有剧透或判断真实语义质量。人工作出的事实和位置声明仍由作者负责核实。

预览报告逐项给出 `automatic_memory / automatic_disabled / memory_planning_source / memory_hidden_chapter / memory_future / memory_current / memory_outdated / memory_conflict / automatic_budget` 等原因。预算按 Unicode 字符，含标题/换行，整条记忆不足则排除，不截断事实，也不是精确 token 计价。组合汇总与显式检索时重新执行同一排除门，不能绕回规划、未来或预算已拒绝的记忆。发送和采用前重新计算上下文及依赖，策略、来源或冲突变化使旧请求失效。

## 持久化和复制

建议新增工作区 V42（最终编号由主整合统一分配），新增唯一集合 `memory_automation_events`。四种人工操作与 `impact` 共用严格字段校验及 append-only 转换验证；SQLite 物理 schema/user_version 不变。旧 V1–V35 只读不升级，默认字段不写回旧冻结。

完整备份/恢复和复制支持新集合；映射事件、队列、章节、记忆和汇总 ID。策略的 `authorization_project_id` **刻意保留原项目身份**，所以独立复制后的有效策略恢复默认关闭，作者须在新书重新启用。原库完整恢复保留本地策略和队列历史，但不创建任何执行许可；执行许可仍是原任务运行时逐请求确认，没有新增许可存储或自动工作线程。

## 验证边界

定向 Python、随机 loopback 假供应商和 Node 资产测试的实际命令、退出码与原失败见本任务目录 `verification.json`。V1–V35 矩阵覆盖每版空集合合法工作区零写读取；既有 V23/V32/V34 历史丰富夹具、恢复复制和语义摘要定向回归另跑。它不是每版生产数据语料穷举，也不等于全量/桌面/打包或真实模型质量验收。真实供应商调用和付费均为 0。
