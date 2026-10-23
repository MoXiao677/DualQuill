# C13 第二阶段：模型规则语义意见与独立规划任务作用域

主仓整合为V46。单任务规则绑定只属于一个请求；该绑定用于章节构思或场景扩写时，多候选入口须选1个候选，2–6个候选会在任何准备请求前明确拒绝，避免部分创建或把一个任务的规则复制给其他任务。多个候选需要分别准备各自的任务规则。

## 来源身份摘要修复（独立 followup-source-identity）

父级 parent-contract-05 发现阶段二的 source_digest 误用了去身份的 memory.fingerprint：归档规则后新建同文、同类型、同作用域、同版本的新规则ID，在排序位置不变时可能仍被认为来源有效。此项是产品缺陷；parent-contract-04 的过度 fixture 假设不是本次产品RED。

修复只改本功能的 source_digest：对书/章/目标任务身份及按规则ID排序的完整适用规则快照作规范化 JSON + SHA-256，不删除任何规则字段，明确绑定ID、version、source、时间戳及作用域。通用memory.fingerprint不改，没有接受旧去身份摘要的宽松回退。旧V36的读取仍零写且不升级；带旧错误摘要的阶段二V46实验记录会严格校验失败，本修复不自动迁移或重签该实验历史，不能将旧结果冒充来源已验证。

原始wire_source、request_body、request_sha256及模型引用保持原样；复制仍只映射当前规则身份、重算当前source_sha256，copy_mappings保留每次原wire到当前身份链，禁止继承发送许可。新增实际准备后归档+同文新ID重建的发送零loopback拒绝、成功意见替换后的inspect拒绝，以及摘要逐字段/排序回归。恢复、双次复制、重开及旧V36只读回归用本修复目录虚构库验证。

父级另报 asset-gate-04：app.js导入的rule_reviews.js尚未登记 desktop/security.cjs ASSETS；按本次边界由唯一主整合者处理。本修复不改该共享登记、不写主仓，也不声称已通过desktop asset gate。

本阶段是在任务级规则第一阶段副本之上的增量，工作区/完整备份格式 **V46 为整合建议号**，需主整合统一分配。真实供应商请求和付费调用均为 0；以下模型响应均来自本任务目录中的虚构随机 loopback 夹具。传输与严格引文校验可运行，不代表真实模型语义质量已验收。

## 作者流程

规则页保留手工导入、确定性精确冲突硬阻止及外部 JSON 意见校验，另新增真正的「模型语义规则审阅」。选择已保存章节及可选单任务身份，预览**全部适用的已启用规则**（包括同文同类型的不同规则记录），选择具体自建连接/默认模型、输出上限、时限、本书累计调用/预留 Token 上限及单次美元风险预算，并明确接受费用未知。预览及冻结不发起请求。

冻结记录显示完整规则、书/章/目标任务身份、精确请求正文、去向、协议/JSON或SSE、SHA-256及预算。每张请求卡必须重新勾选本次外发确认，点击后只执行一次。默认模型会话关闭；没有自动启动、重试、恢复重发或后台审阅。风险预算不是实际账单硬封顶；累计调用数/输出预留上限在开始执行的事务中检查，已开始后取消/失败也计入。

输出只作为 `needs_verification` 模型意见保留。每条意见必须是 `model_opinion`，类别只能是 `possible_conflict|unclear`，必须恰好引用**两条不同规则**的当前冻结版本，使用 Unicode 码点起止位置和逐字非空引文。重复 JSON 键、未知字段、伪造/跨规则引文、错误版本、同侧两次引用和事实类别全部拒绝。空 findings 仅表示没有意见，不证明规则无冲突。

合法终止且校验成功才保存结构化意见；失败响应保留并明确无合法意见。流式预览仅存在共享任务引擎内存中，界面转义显示，不作为中间意见入库。取消、超时和截断不产生可使用意见，不自动再发。

发送前（含 worker 即将调用传输时）和只读复核意见前，重新解析完整当前适用规则及章节/任务归属。新增、修改、启停、归档、删除或 legacy 文风变化使旧来源失效。历史仍可查看，过期意见不可通过 inspect 使用。规则/任务在其他作用域变化但不适用于本任务时，不误判过期。

本功能没有采纳/豁免/停用/删除接口；**意见不会改变强制/禁写规则、正文、IDEA、正式细纲、记忆、审核豁免或正式修改许可**。作者如需改变规则，仍须在规则编辑/历史流程中另行明确操作；原精确冲突未解决时依然硬阻止。

## HTTP 契约

所有写操作沿用本地服务 token/来源保护，严格未知字段校验。以下路径以 `/api/projects/{project_id}/rule-reviews` 为前缀：

- `GET /`：只读任务/持久事件/响应/意见列表，另有 enabled、source_fresh、can_inspect。
- `GET /{id}`：只读单项，跨书或不存在的请求为404，不返回500或其他书的内容。
- `POST /preview`：仅 `{chapter_id,target_task_id}`，target_task_id可为null。
- `POST /prepare`：仅 `{request_id,chapter_id,target_task_id,source_sha256,model_options,max_output_chars,timeout_ms,budget_max_calls,budget_max_output_tokens}`。必须明确 configured-http-v2；专用提示 `rule-conflicts-json-1`。审阅请求 request_id 与被审阅 task binding 分离。
- `POST /{id}/execute`：仅 `{confirm_external:true,request_sha256}`；必须当前进程准备、当前连接未变、来源未变、未执行且共享串行槽/预算允许。
- `POST /{id}/cancel`：仅 `{}`；终止状态不恢复为可执行。
- `POST /recover`：仅 `{}`；显式将无活跃 worker 的 running 标记为 interrupted，不重发。
- `POST /{id}/inspect`：仅 `{result_id,request_sha256,expected_revision}`；复核当前书/章/任务及完整规则，返回只读待核实意见；不写工作区。

精确输出结构：

```json
{"overview":"待核实意见","findings":[{"assessment":"model_opinion","category":"possible_conflict","statement":"请作者核实","evidence":[{"rule_id":"第一条规则完整ID","version":1,"start":0,"end":2,"quote":"原文"},{"rule_id":"第二条不同规则完整ID","version":1,"start":0,"end":2,"quote":"原文"}]}]}
```

## 章节构思/细纲与场景/选区扩写

本阶段已实现，不再只列契约缺口。`rules/bind-task` 新增 `brainstorm_chapter|outline_chapter|expand_scene_selection`；分别对应 chapter_planning 的 brainstorm/outline 与 scene_expansion 的场景/选区。规则页可以创建以上任务身份；相应准备页按本章/能力筛选身份。

两个独立引擎的 source_options 都可选带 `rule_task_id`。带该键时必须是有效 UUID，预览需同书/同章/同能力；prepare 的 `operation_id` 必须等于该身份；已预留身份不能省略绑定后继续准备，也不能在冻结后补绑。可选键省略时保持旧编码，不插入null。

绑定任务的 source_guard 新增可选 `rule_sources`，冻结全部适用规则；旧无绑定 guard 省略该键，保留旧V1–V36数据、摘要和请求编码。发送、worker与候选复核/人工采用沿用各自的 source_fresh 守卫，规则新增/修改/启停等会阻止旧请求及旧候选。任务规则不会进入其他任务。

## 持久化、恢复与复制

V46 在既有 V36 的 `rule_task_bindings` 外新增 `rule_review_tasks|rule_review_events|rule_review_results`，三集合追加历史。存储历史验证核对新冻结的 source_revision 与前一完整快照规则集合，拒绝重新签一个缺失规则的自洽请求；也核对独立规划/扩写的规则冻结集合。请求正文必须可由专用提示与冻结 rules 逐字重建，结果必须可由保存的真实响应及原 wire 规则再校验。

完整备份支持V1–V46，精确恢复保留状态。复制映射当前书/章/任务/规则、owner与请求身份，保持原始 request_body/SHA、模型实际引用ID与输出原文，通过逐次 `copy_mappings` 记录原wire→当前实体身份链；不能把复制后的ID冒充实际发送过的ID。legacy合成规则ID按新书ID重新派生。已复制/重开待执行与运行中请求不继承当前进程权限，显示中断；必须新建准备请求并再次确认。

规划/扩写复制将 request_id、source_options.rule_task_id 和 binding.id 统一映射到 task_request 命名空间；映射 rule_sources 并重算 source_guard SHA。旧无绑定任务继续使用原规划/扩写命名空间。

## 实际验证与限制

测试覆盖三协议 JSON/SSE 真正 loopback wire、确认/预算、配置变更、Unicode双侧引文、未知/重复字段、取消/超时/截断、worker来源复核、准备原子回滚、历史篡改、当前规则新增（含同文不同ID）、跨书HTTP、只读复核、恢复与两次复制，以及 IDEA/outline/scene/selection 的绑定、隔离、发送/采用过期和旧编码。

UI 使用 Node 事件/DOM 夹具检查真实处理函数的 preview→prepare→逐请求execute、只读inspect、取消/恢复、转义及规划/扩写可选绑定。没有本轮实际浏览器/Electron布局验收；完整全量、固定包/安装器、真实供应商质量/费用与干净VM验收留给主整合。详细命令、实际组数和保留的失败日志见本阶段 workspace 外 verification.json 与 HANDOFF.md，不能把夹具通过当成真实模型效果或全部产品能力验收。
