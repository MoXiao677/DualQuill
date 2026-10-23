# S4-A：本地单步任务、候选与幂等采纳

2026-10-15（Asia/Shanghai）。本批本地技术交付通过，**本轮335 Python、Node6及示例均退出0**。默认真实模型继续关闭；本地协议夹具不是AI输出或真实token/费用，正式8765未加载、作者体验及真实供应商验收仍待安排。

## 实际入口

章节写作 → 选择章节 → “预览已保存上下文” → “生成只读预览” → 填整章改写要求 → “准备整章改写任务”。任务冻结服务器实际已保存原稿/目标版本、确切资料串、来源版本/字段指纹、章位、参数和请求UUID，不取编辑区未保存草稿。原稿/参数/来源可在任务详情审阅。

“任务与候选”可查看待执行/执行中/成功/失败/取消/中断、追加事件/attempt和完整候选；原稿与候选逐行差异可见。普通启动没有adapter，执行拒绝；仅显式启动参数`--local-protocol-demo`注册固定本地adapter（验收用虚构库/`--offline --no-browser --port 0`），界面明确标识本地协议。没有任意fixture_output/scenario/外部URL或凭据通道，演示/测试与未来adapter共用同一registry/coordinator、取消令牌、结果校验和采纳路径。

成功候选需“明确采纳候选为新草稿”；正式章仍需勾选作者授权。取消先与完成在仓储锁内裁决，已接受取消/超时后的迟到结果不变成功候选。失败/部分输出不当完成候选，不自动重试。重开可见任务/候选；失去本会话归属的running仅派生显示中断，读/恢复/导入不改库或执行，显式“明确将中断落盘”才追加中断事件。

## 原子采纳与来源

采纳同一个BEGIN IMMEDIATE先读最新状态，先核对同UUID既有收据的任务/候选/目标绑定，再校验expected_revision、目标正文版本/内容、相关依赖和正式章授权。正文实体版本、整书历史、采纳事件和收据同事务提交/回滚。响应丢失可按原UUID核对；重复/重启返回同一收据，不重复追加正文，换候选不能借同身份写第二次。

相关计划/IDEA亦有明确guard（未选计划文本不会作为模型输入）。依赖按具体实体版本、语义摘要和类型化引用逐项比较，不按全局revision让所有候选失效；无关后续章保存可继续采纳。记忆依赖要求启用/确认/来源新鲜且位置允许，采纳后正文新版本会让相关旧记忆过期，不自动重新确认。内存FrozenInput及其嵌套是冻结dataclass/tuple，直接构造、加载和registry边界均强校验，无validated布尔捷径；错误归属/能力/类型/编码/部分结果拒绝。

## V1/V2/V3持久与迁移

SQL三表/user_version1及document1不变；首次准备任务升级当前workspace3，显式`generation_tasks/task_events/generation_candidates/adoption_receipts`，保留记忆集合/全部编辑历史。旧V1/V2只按自身声明读取，不补存revision、改原字节/时间/历史。纯旧包保持原版本/profile/counts，含V3才正式声明包3；混合历史逐条校验，冻结任务/事件/候选/收据不可改写。

完整包恢复原SQL行，新项目复制两遍收集全历史映射：task/request/attempt/owner/candidate/event/adoption及目标/结果版本、memory与全局Skills依赖。原稿、冻结资料串、候选正文只作原文，不替换其中字符串ID；可影响摘要的结构身份与有序类型引用分开绑定，旧持久记忆出处指纹不改。全局Skills先锁内复查并规划复用/冲突映射，冻结Skill快照与选定来源同步映射；历史独有/被排除的全局来源单列映射，不虚构当前资料。恢复/导入不执行任务，缺完整来源历史的单工作区JSON明确拒绝，不补造依赖。

旧V1/V2真实库/完整包/原SQL行与JSON在修改前冻结为`tests/fixtures/s4a_legacy.json`，不由新序列化器伪造旧oracle。新任务+有效记忆+明确全局Skills的待执行组合已通过完整包/冲突复制，输入完整可加载、资料串/时间/顺序保留、类型引用正确且没有自动执行。旧“未来workspace=3”反例随正式支持3改为真正未来4，原拒绝/不改源断言保留；未知字段/非法类型未放宽。

## 本轮原始证据

根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S4A-tasks-20261015-60eac7/`。144项起点hash、before、旧格式原始库/包与plan保留，全部既有未提交内容继承。

| 检查 | 本轮实际结果 | 相对路径 |
|---|---|---|
| 新增协议/构造/coordinator/HTTP | 19项纳入最终335；此前专项19通过 | `green-s4a-specialized`、`green-final-boundary` |
| 记忆＋全局Skills任务复制 | 专项通过，旧ID文本保留/Skill冲突重映射/任务不执行 | `green-combined-copy` |
| 最终S4 headless | 三组通过，external/errors空，exit0；含已保存冻结、协议执行/差异、丢响应采纳恰一次与刷新重开 | `final-browser/s4a-browser-report.json` |
| 原workbench | exit0，草稿/冲突/历史/正式章授权等受影响路径保留 | `affected-workbench` |
| 一次完整core | **335 Python OK、Node6、示例各exit0**；源码期间无变化、diff0、credential_hints空 | `core/exit.json`、`core-evidence/20261015T113423Z-5100f4b45e1f/report.json`与`regression` |

原RED/失败不覆盖：`red-protocol`、`red-coordinator`、`red-http`、`red-browser`、`red-constructor`和`red-bypassed-call-identity`。最初coordinator切片10/11通过，V3预检尚未接入时的1个error保留于`green-coordinator-1`，接入后对应V3用例与19专项通过。构造校验、根调用绕过反例及一次联动补丁验证失败导致缺失一行未落盘的`green-final-protocol`失败均保留，实际补齐后`green-final-boundary`通过。没有删断言/skip、改名重开证据或额外模型审查；本轮修订检查点沿原记录，不因充值重算。

core仍经仓库外hidden_core.py仅隐藏控制台转发原入口，原/实际argv留痕，不声称无shim运行。完整335为本轮实跑，316/310均历史。core后仅三个当前顶部与本交付文档变化；最终hash/相对起点清单/差异见根下`final-files.json`、`final-delta.json`、`diffs/`。

## 实际边界与后续

没有真实供应商调用、流式验收、token/费用、对抗同账户任意代码执行或百万字规模承诺；未访问正式data/凭据/8765、作者窗口/输入/剪贴板，未扫删旧authority/暂存、装依赖/改全局环境、提交推送/发布。只改必要V3契约与任务入口，既有统一POST错误收尾、暂存/ACL/上传工程未重做。

按作者最新授权，领导核对此交付后直接派S5离线审核/记忆提案/出处/图谱规则，再串行S6工作流/比较/人工节点和S7桌面封装；Sol主执行、省钱、不常规Astra，只有确实无法解决并给出证据才由领导评估。真实AI/语义能力、S2性能/章节整理/磁盘草稿及整体S3余项仍诚实待办；S7若需新构建依赖先报告已有工具及最小项目内方案，不擅自安装/签名/正式发布。
