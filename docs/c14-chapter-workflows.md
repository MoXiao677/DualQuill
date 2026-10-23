# C14 专用章节工作流（隔离副本增量，待主仓整合）

本增量在0.4.13白名单图、候选审核及attempt预览归属修复上追加功能，不更改产品发布版本。首次保存专用节点或并行运行使用建议工作区/备份版本V40；最终编号由主整合统一分配。

## 可运行范围

工作流页可填入 `IDEA→细纲→初稿→候选模型意见→改写→人工采纳` 模板。后端新增 `model_idea / model_outline / model_draft`，均为writer角色，复用原逐请求确认、真实HTTP适配、不可变候选和预算管线；共享generation task的 `rewrite_chapter` 是传输信封，专用用途由冻结 `workflow-idea-json-1 / workflow-outline-json-1 / workflow-draft-1` 明确区分。不能把该信封当作“已保存正文改写”或允许采纳规划JSON的理由。

IDEA候选精确为 `{"idea":"非空文本"}`；细纲候选复用严格章节规划解析，包含 `core_idea / objective / character_ids / scenes / story_time`。本变体仅生成叙述场景，章纲和每场景的 `character_ids` 固定为空列表，不新增人物/地点实体关联；人物名称可写入叙述。本步骤不代替独立章节规划页的实体选择和人工保存。

细纲节点只接受声明父节点实际生产的完整IDEA候选，初稿只接受实际typed细纲候选且原保存正文必须为空。原文不能冒充typed结果；未知字段、乱序场景、未知实体ID或非法JSON导致模型任务失败，保存实际响应，不产生候选。运行GET的 `typed_result` 每次从实际持久候选按冻结用途重解析，不是示例或合成输出。

`model_candidate_audit` 仍只审核真实未采纳正文候选，严格Unicode引文和待核实意见语义不变。改写实际消费审核节点携带的同一候选和真实feedback。旧 `model_audit` 仍只接保存正文，未扩展成候选审核。正文仍只由独立human→apply绑定具体差异、经原原子采纳事务保存；IDEA/细纲候选禁止经正文人工门和任务采纳API写正文。IDEA/细纲不会自动变成保存规划，候选不能自动变成确认记忆。

## 身份与原保存目标

每个模型节点冻结 `upstream` 的candidate ID、producer task/attempt/node ID、via父attempt、文本SHA及原保存目标。后继通过声明的source消费真实父结果，不按名称挑选最新任意候选。`input_snapshot` 返回真实冻结输入，`input_manifest_sha256` 对父attempt/输出引用/快照做确定性摘要；审核或human另有request/diff SHA。原保存目标的版本、内容、状态、章号、标题及指纹独立保留，生成后不能换成“当前目标”绕过过期守卫。

新专用wire包含真实来源文本、input SHA、原保存目标SHA和用途提示；生产者的完整本地身份保存在冻结upstream。复制重映射本地身份，保留历史wire/body/hash。细纲不含需要隐式改写的实体ID，保证真实响应与历史候选逐字保留。复制/恢复后的本次执行或正式写入许可必须重新确认。

## 编辑与有界并行

页面提供已接通节点菜单、父连线/source、参数/分支条件、上下移动和无后继节点删除。修改只保留内存模板草稿，必须重新服务端预检并保存；可载入最新模板，追加同系列新版本。旧运行始终使用冻结旧图。普通边构成环、悬空source、删除被引用生产者、未注册能力均明确拒绝；循环仅使用原1–3次有界loop。移动改变同级准备顺序，依赖仍以连线为准；没有自由表达式或代码执行。

运行默认并发1，可声明2或3。候选任务各自写独立task/candidate ID；准备窗口不超过本次并发数，每个请求仍分别确认。TaskCoordinator按同运行group预留名额；不同group和普通任务不混跑，普通任务保持串行。每次外发原子增加次数和保留token；失败/取消/超时不退款式释放预算，重试必须新attempt/task并重新确认。

同一运行只支持一个章节正式目标。两个无依赖先后关系、同动作的apply视为共享正式写目标冲突，在创建并行运行前拒绝；正式写入继续走原业务事务和人工守卫。跨章节自动调度、任意文件写目标、自动预算许可、自动重发和未注册节点均不支持。

分支不采取或父结果不可用时，先记录skipped，不能先准备无效模型请求；显式failed分支可保留失败节点并执行人工/本地后备路径，不把失败伪装typed成功。合流必须指定source才能继续消费原文，不隐式选择某一分支。

## 定向验收入口

- `python -m unittest test_c14_workflows -v`：专用真实loopback链、typed失败重试、不退款预算、身份/目标守卫、分支/合流、有界并行及写目标冲突、V40真实磁盘备份恢复复制与许可失效。
- `python -m unittest test_s6b_workflows test_candidate_model_reviews test_candidate_review_http -v`：原分支/循环/暂停取消/失败重跑、旧model_audit、候选审核JSON/SSE及HTTP隔离回归。
- `node --test tests/workflow-editor.test.mjs`：连线、重排、删除、不可变编辑、循环/悬空/未接通能力拒绝。
- `node tests/e2e-c14-workflows.cjs`：需环境变量C14_EVIDENCE_DIR、NOVEL_WRITER_PYTHON、NOVEL_WRITER_BROWSER和可用Playwright。独立临时库、随机loopback端口，真实供应商调用0；验证可见编辑/预检/专用五请求/人工采纳及窄屏。

实际命令、原始RED、修后日志和结果见任务目录的 `verification.json` / `HANDOFF.md`。工程传输、解析、引用/权限验证不代表真实模型的小说质量或审核准确率；没有运行真实付费模型、作者桌面、安装器、完整全量或打包。
