# C13-C 单任务规则与待核实语义意见（隔离开发交付）

**阶段记录说明：** 本页以下内容是第一阶段冻结交付的范围。第二阶段已在独立 followup-semantic 副本实现真正的模型语义审阅请求/三协议JSON与SSE/持久待核实意见，并补上章节构思、细纲与场景/选区扩写的单任务作用域及UI。最新功能与V46建议格式见 [第二阶段准确契约](c13-semantic-rule-review.md)；第一阶段原副本及交付文件没有改动。

本页描述 2026-10-21 隔离副本中的实际增量，不表示主仓已整合、完整全量已通过或桌面安装包已发布。既有四级规则、批量导入、历史说明见 [C13 原契约](c13-scoped-rules.md)。

## 单任务身份与优先级

- 新增 `task` 作用域，优先级为 `task > chapter > volume > book > global`。优先级只用于排序及相同 `(kind,text)` 去重；required/forbidden 同文本硬冲突始终阻止受影响任务，不因 task 更具体而覆盖强制规则。
- `scope_id` 是明确预约的 **准备请求 request_id**，不是现有 generation task 的随机 `id`。先绑定 `request_id + 当前书章节 + task_type`，再写任务规则，最后以相同 request_id 冻结。绑定本身不生成候选、不发送、不产生费用授权。
- 绑定不可改写或删除；已冻结但此前没有绑定的任务不得补绑。相同绑定请求只读幂等，变更章节或能力拒绝。只接受当前书的既有目标章节。其他书、其他章节、未绑定 ID 或另一 request_id 均拒绝。
- 当前复用共享 `TaskCoordinator` 的 `rewrite_chapter / audit_chapter / draft_chapter / continue_chapter`。UI 提供初稿任务身份；改写、续写及普通审核可使用同一 HTTP 契约。单章语义摘要只允许原有唯一已保存正文，明确拒绝任务规则绑定。独立 chapter-planning / scene-expansion 引擎仍按原四级规则运行，本增量不声称为其提供 task 规则。
- 一条绑定只对应一次准备及其唯一执行尝试。重试需要新 request_id 与新绑定；不会自动复制旧任务规则或继承发送许可。

## 作者操作

1. 在“文风规则”页选择目标章节，点“为所选章节创建初稿任务身份（不发送）”。
2. 编辑规则时选择“单任务”和相应完整任务 ID；选择 required、forbidden 或 guidance 后保存。JSON/CSV 导入也接受已绑定的 task 目标。
3. 在“本次任务”选择此任务，然后点“查看生效规则”，检查实际规则、版本与精确冲突。
4. 点“按生效规则准备初稿（不发送）”。仍要求已有实际模型配置或用途预设；本页不会自动发送。活动/任务详情保留原有逐请求确认与预算流程。
5. 冻结后变更本任务规则，会使发送和正式采用失效；需要新建任务再准备。修改其他任务专属规则不会使本任务过期。

## HTTP 契约

所有新增操作沿用本机会话令牌、来源保护与严格字段白名单；无查询串依赖。

- `POST /api/projects/{project}/rules/bind-task`：字段恰为 `request_id,chapter_id,task_type`。
- `POST /api/projects/{project}/rules/resolve-task`：字段恰为 `chapter_id,task_id`，此处 task_id 指绑定的 request_id。
- 既有 `/rules/save` 与 JSON/CSV 导入接受 `scope="task",scope_id="绑定的 request_id"`；其他字段、导入预览摘要及确认契约保持。
- `POST /context-preview` 的 options 可增加 `rule_task_id`；共享 `/tasks/prepare` 及 `/chapter-writing/prepare` 必须使用同一个 request_id。已预约绑定不得通过省略 rule_task_id 绕过规则。
- `GET /tasks/{id}` 新增 `rule_task_id`、`rule_trace`（规则 ID、来源 SHA-256 与冻结 revision）、`rules_fresh`。冻结 context_text、依赖及实际 wire 请求继续不可变。

发送在开始事务和 worker 实际传输前均重新检查；正文采用和绑定任务的审核提案接受也检查当前完整生效规则集合。新增/删除/停用/归档/版本变化都会使旧冻结失效，包括原先没有任何 task 规则的绑定。不能只靠检查旧依赖来漏掉新规则。

## 待核实语义意见：准确边界

本增量接入的是**作者提交的模型或人工意见 JSON 的结构与引文校验**，不是已实现的自动语义检测器，也没有新增模型生成传输。三协议实际传输测试验证的是写作请求携带任务规则，不能将其当作“模型语义判断质量通过”。

`POST /rules/semantic-preview` 字段恰为 `chapter_id,task_id,observations`；不选择 task 时 task_id 为 null。observations 最多 100 项，每项恰含：

```json
{
  "rule_ids": ["当前生效规则A完整ID", "当前生效规则B完整ID"],
  "quotes": ["规则A的逐字引文", "规则B的逐字引文"],
  "reason": "可能存在语义冲突，但仍需作者核实"
}
```

- 必须引用当前解析中两条不同的规则；每段引文必须逐字属于对应规则。伪造、越界、反序不匹配、未知字段及非法类型全部拒绝。
- 结果一律为 `status=needs_verification, hard_conflict=false, can_apply=false`；`semantic_quality_verified=false, model_request_sent=false, automatic_rule_changes=false`。
- 精确文本硬冲突独立返回 `exact_conflicts`；语义意见不能降低其阻止等级。
- 预览只读且不持久化意见；不产生正式事实、豁免、停用或删除操作。若作者决定修改规则，必须另外走原有明确的规则编辑/停用/归档入口并追加历史。没有“模型自动撤销强制规则”功能。
- UI 可粘贴意见并查看只读结果；不执行输入中的 HTML、脚本、链接或工具指令。

## 原子性、历史与恢复复制

- JSON/CSV 所有行与历史仍在单一仓储事务中提交。task A 与 task B 的硬冲突彼此隔离；仅导入 task B 时，不因 task A 独有冲突阻止 B。导入书/卷/章/全局规则时，会检查其可能影响的 task 上下文。
- 导入的预览 revision/内容绑定、operation_id 幂等、已删除导入拒绝重放保持。新增手动创建也拒绝用旧 operation_id 在删除后复活规则，且幂等重放不得绑定不同内容。
- `scoped_rule_history` 保持 append-only，删除规则后仍可按原 rule_id 查询；新增 `rule_task_bindings` 也 append-only。
- 本地建议格式为 V36（最终编号由整合者统一分配）。首次绑定才升级：先补齐 V27 以来已有集合，再设置 V36 并新增绑定集合。普通四级规则写入继续走原版本链；旧 V1–V35 读取不补造新字段、不重写旧快照。
- 完整备份保留绑定、当前规则、删除历史及冻结任务。复制重映射绑定 ID（task_request）、章节/项目、task 规则及 before/after 历史作用域、冻结 ContextOptions；旧来源指纹沿用既有按映射后历史重算机制。复制的模型任务不继承当前进程 owner/发送许可。
- 旧 ContextOptions 省略 rule_task_id；只有实际任务绑定使用新字段。SQLite 物理 schema/user_version 不变；workspace/backup 能力上限扩展到建议 V36。

## 实际验证与未验

交付目录的 `verification.json` 与 `evidence/` 记录每条实际命令、退出码和原始日志；首次 UI 夹具失败日志另保留，未改名为通过。

已做：任务隔离/优先级/三种类型、精确冲突、冻结新增及启停变化、发送及采用守卫、严格 HTTP 与令牌、导入幂等和回滚、逐字引文/意见信任边界、真实磁盘重开、V36 完整恢复/复制、三协议 loopback 实际请求、旧规则/创作链及备份/迁移/SSE/V34/V35 定向回归、Node UI 事件和转义测试。

未做：全量测试、Electron 真窗口布局/交互、安装/打包、真实付费供应商、真实语义判断效果和长篇规模。没有新语义意见模型生成或意见持久化/接受撤销链；本批仅交付明确标注的只读校验入口。所有素材、模型密钥与 wire 都是本任务目录内虚构夹具，真实供应商调用为 0。
