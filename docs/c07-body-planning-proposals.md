# C07 / C04 正文驱动规划待审提案

阶段二补充：原生模型建议链现见 [C07 原生正文驱动模型建议](c07-native-model-planning.md)。下文保留为阶段一范围说明；其中“没有新增模型传输”和原生 unavailable 仅描述阶段一，不能当作阶段二现状。

2026-10-21 隔离开发增量。复用 V26 `FullBookPlanning` 命令和 F1 `planning_proposals` / `planning_receipts`，没有另建正文写入器或重写 F1。本文不改变旧版交付记录的实际测试结论。

## 作者流程

在全书大纲的“正文驱动规划 / 偏离提案 / AI 补全”中选择本书已保存且启用的章节，粘贴精确引文。引文不唯一时填写 Unicode 字符起点（不是 JavaScript UTF-16 码元）。

1. 手动提出计划位置调整、实际发生、新事件、放弃缺席阶段/事件、停用受阻依赖，或对主题/前提/主线/结局提出单字段 F1 反馈。
2. “按正文标题匹配提出建议”仅在引文精确包含计划阶段/事件标题时生成待审发生建议，不声称识别了语义或真正发生。
3. 查看逐实体新旧差异、late / early / unplanned / missing / blocked 计数变化、后续章节及人工伏笔链接。
4. 显式接受后，既有正式规划命令和收据在一个 SQLite 事务中提交；拒绝只追加决定。两者都不改写正文。

可以先“准备 AI 补全上下文”，查看来源版本、精确引文、偏离与允许动作，再导入 `actions` JSON 数组保存为 `ai_import` 待审提案。这个入口能运行上下文准备、格式校验、引文校验和人工采纳，**本增量没有新增模型传输/自动调用**，没有真实供应商质量验证。旧 `ai_completion` 顶层字段仍表示 V26 原生模型补全不可用，新增 `body_planning.ai_completion` 表示上下文/导入入口可用。外发请求、预算确认仍应复用现有受控模型入口；本增量不继承或伪造许可。

## 守卫和历史

- 来源冻结为本书已保存正文的稳定 ID、实体版本、工作区 revision、内容指纹及精确引文范围；草稿不进入提案。
- 提案接受前重新核对正文、计划、人物/章节生命周期、记忆/人工知识和两套既有 F1 锁。正式内容或引用变化须重新准备提案；只有其他待审记录变化也会使旧预览 token 失效，可重新预览。
- 预览 token 只存在当前业务服务内存，带随机 nonce，绑定完整正式基线及保存 revision。重开、恢复后的新服务及新项目复制没有旧预览许可；不能仅提供历史 hash 即接受。
- C07 的弧光、阶段、事件和依赖均可显式锁定/解锁。锁覆盖直接命令、关联阶段/事件和直接仓储保存；提案动作不能解除锁。F1 继续复用已有字段锁与创作方案的结局锁。
- 新发生提案必须使用同一来源章节及引文，正式 `body_reference` 保留该引文，提案永久保留原版本来源；正文后来变更不删除历史证据。旧 V26 描述型人工引用原样保留，不回写成虚构精确证据。
- 启用 V43 后，既有阶段/事件人工发生入口也要求引文存在于当时已保存正文；操作的 expected_revision 与不可变工作区快照保留实际来源版本。旧 V26–V35 兼容入口和旧历史不被静默重解释。
- F1 包装提案在准备阶段保存原生 `planning_proposals`，在后续决定阶段写原生收据，保持“决定只能引用此前已保存提案”的旧契约。关联的 F1 提案不能绕过包装提案直接接受。每个包装提案最多一个 F1 字段，多个字段分别提出与决定；同一包装可附带多项 C07 变更。
- `operation_id` 同请求重放返回原收据，不重复正式变更；同身份异请求、跨书使用与过期 revision 拒绝。任一步失败整体回滚，原提案/正文保留。

## 人物和结构化设定生命周期

人物及人工知识节点（包括 setting/location/organization/prop 等）有显式引用预览、归档和恢复。保留稳定 ID、人物关系、章/场景引用、弧光、事件、图谱边、记忆和历史，不删除实体或级联删除引用。

归档人物不再可作为新弧光/事件引用，章节构思输入排除该人物；手动编辑归档人物、向新章计划/场景/人物关系写入归档人物引用会拒绝。已有引用仍显示，须由作者显式恢复后继续编辑。归档知识节点默认不进入知识视图或新边/编辑/合并；“包含停用”可查看，恢复后原边重新显示。这个生命周期增量不是对所有历史模型冻结、检索排序、图谱语义和人物自动事实维护的全面重写。

## HTTP

沿用本地会话令牌/来源检查。`GET /api/projects/<id>/full-book-planning` 在原输出上增加 `body_planning`（提案、收据、锁、生命周期、可管理实体），旧字段保留。

`POST /api/projects/<id>/body-planning/<operation>`：

| operation | 输入/行为 |
| --- | --- |
| prepare | operation_id、expected_revision、chapter_id、start、end、quote、actions、reason；origin 可为 author/body_excerpt/ai_import |
| infer | operation_id、expected_revision 与相同引文字段；精确标题匹配，仅生成待审 |
| preview | proposal_id；只读，返回内存发行的 preview_sha256 |
| decide | operation_id、expected_revision、proposal_id、decision=accepted/rejected；接受须提交当前 preview_sha256 |
| completion | chapter_id、start、end、quote；只读准备上下文，不发送模型请求 |
| set-lock | operation_id、expected_revision、target_kind=arc/stage/event/dependency、target_id、locked、reason |
| references | kind=character/knowledge_node、entity_id；只读引用影响 |
| lifecycle | operation_id、expected_revision、kind、entity_id、archived、confirm=true |

每个 action 是 `{action, values}`，复用 C07 原动作或 F1 `prepare_plan`；不允许客户端指定内部 `operation_id` / `expected_revision`。未知提案/项目404，未授权403，过期版本/预览409，参数/锁定/状态错误422。

## 持久化、备份与整合

本地建议工作区版本 **V43**（最终由整合者统一分配）。首次新提案/锁/生命周期写入才升级，旧 V1–V35 只读不落盘升级。新增四个 append-only JSON 集合，不增加 SQL 表或修改 SQLite user_version：

- `body_planning_proposals`：精确来源、动作、正式基线指纹、原生 F1 提案链接；
- `body_planning_receipts`：接受/拒绝、当次预览摘要、保存 revision；
- `body_planning_locks`：目标锁定/解锁历史；
- `planning_entity_lifecycle`：人物/知识节点归档恢复历史。

备份校验、工作区历史校验、能力列表和复制映射同步支持四集合。复制映射项目、来源版本、章节、人物、弧光/阶段/事件/依赖、动作引用、F1 链接和操作身份；历史请求摘要与引文保持。复制后的待审基线故意过期，需重新提出；预览许可不保存、不复制。完整恢复精确保留新集合和历史，服务重开后仍须新预览。

## 验证边界

任务目录外层 `HANDOFF.md` 和 `verification.json` 记录实际命令、结果与原失败日志。业务/随机 loopback HTTP/Node 交互处理/定向原规划和备份回归分别计数；Node 处理测试不是实际 Electron 桌面验收。未做全量、桌面打包、安装器或真实模型调用；未接触正式库/8765/作者窗口/凭据。
