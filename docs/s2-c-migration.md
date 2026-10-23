# S2-C 迁移、复制与旧JSON：技术回归收口交付

日期：2026-10-15（Asia/Shanghai）。**本次S2-C技术回归收口通过；作者体验验收、正式服务投用和整体S2仍未完成。** 独立Astra单候选后，4项定向、B headless8组/C7组、完整278 Python/6 Node/示例均退出0。Sol原3次修复、原277方法失败及所有原始日志保留，不改记为Sol第四轮。

当前领导为`01a13b4a-0b47-7100-93fa-0a13b8fa6752`，原领导`01a13aaf-a3ee-7bc2-9aab-fa9dbca086f1`已交权停派。Sol独立聊天统一执行被派任务，具体难题交领导派独立GPT-6 Astra，仅执行链仍处理不了的网络/安全测试才交DeepSeek（仅测试）；不用子代理、不重建或重复创建执行聊天，结果留执行聊天由领导主动读取。Astra已停止三个项目文件写入并交回领导；当前Sol只获指定文档同步授权，不改业务/测试/检查脚本、不重跑测试、不进入D/S3，`G:/AGI/领导交接.md`仍仅领导维护。

剩余优先级建议：快速核对S3依赖，已交付备份迁移冻结，S2性能/章节整理/磁盘草稿余项明确排期；作者决定优先S3时再调整原阶段门槛。当前未获门槛调整或S3启动授权，不以文档同步代替阶段决定。

## 当前收口修复与原始证据

Astra证据根目录：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S2C-Astra-20261015-179230fd45/`。`astra-result.md`记录停止写入及归属交回；`project-delta.json`确认相对Astra起点只有以下三个项目文件变更，无增删；`candidate.patch`保留完整差异，`commands-and-results.json`记录实际argv、退出码、白名单环境键/PATH与检查期间hash。

| 文件 | 修复与保护 | Astra最终SHA256 |
|---|---|---|
| `src/novel_writer/storage/backup_validation.py` | 恢复integrity_check专用读取错误分类；外层在错误已转换时仍优先重抛进度回调保存的原异常，避免一次性取消误报损坏库。原损坏样本/断言不变 | `4e0f5bd893b489fef08048808ec0517fcb1da3ed1669be30a55aa0cb5b8f7650` |
| `tests/test_migrations.py` | worker显式src导入且不继承PYTHONPATH；独立白名单环境和持久PID/操作编号/事务窗口/模块路径握手，杀前确认存活；成功与提前退出均收集真实双流/returncode并关闭PIPE。保留原强杀/状态/项目数/重试断言，增加全三表回滚、提交后重试不变、全字段历史逆映射、来源字节保护 | `44439d1224e993e8f3d95939184607de713dcb67d677aa46da764dac9344f136` |
| `tests/test_backup_validation.py` | 新增1项真实SQLite integrity_check指令执行中的一次性取消测试，要求同一异常对象和来源字节不变。该保护在修改前已通过，修改后及完整core继续通过，不冒称新增RED | `bd383207e11bf50ce2c7dde18a3f968d640e6099ccb1a26293e00b9ac447fb03` |

新仓库外runner仅为本轮子进程PATH补上已装Windows PowerShell目录；Sol旧runner/原日志保持原hash，未改全局PATH、白名单、执行策略或项目检查脚本。

| Astra实际检查 | 原始结果 | 证据根下相对路径 |
|---|---|---|
| 原失败3方法复现 | exit1，3条failure+1error；两个worker真实ModuleNotFoundError/exit1已捕获，不再仅凭静态推断 | `red-original-methods/stderr.log`、`captured-workers.json` |
| 修改前取消边界 | 1方法通过，exit0，保护既有正确行为 | `cancel-baseline` |
| 单候选定向 | 原失败3方法加取消边界共4方法通过，exit0 | `candidate-targeted` |
| B/C受影响headless | 分别8/7组通过，exit0，无外部请求/页面异常 | `candidate-b-browser/backup-browser-report.json`、`candidate-c-browser/migration-browser-report.json` |
| 唯一完整core | **278 Python（原277+取消1）、6 Node及示例全部通过，各exit0，无skip或ResourceWarning** | `core-evidence/20261014T165214Z-8342728a1c92/report.json`、`regression/regression-results.json`及各`run.log` |
| worker提前退出注入 | 外层exit0；内层两个子场景故意失败并由外层确认，原exit23和双流保存，PIPE均关闭；不是候选回归失败 | `candidate-early-exit-probe` |

完整core冻结129文件，前后无modified/removed/added，diffcheck=0、credential_hints=[]。`regression/python/migration-crash-probes.jsonl`保存两个实际到达事务窗口、杀前仍存活且随后强杀的握手、PID/returncode/双流/PIPE关闭证据；这证明进程强杀窗口，不等于物理断电。最初仓库外runner因`--legacy-path`位置错误发生准备阶段WinError2、没有测试进程启动，保留`red-original/launch-error.json`；纠正调用顺序后才得到真实原失败复现，未覆盖准备失败。

**core运行边界：** 本次由仓库外`hidden_core.py`通过runpy执行原`dev_workflow.py`入口，并给Popen加CREATE_NO_WINDOW。仅两级Python调度命令插入隐藏窗口转发，原/实际argv在`hidden-core-transit.jsonl`完整留痕，worker的`-c`代码不经此转发；测试发现、选择、断言、cwd和环境白名单不变。这里如实报告带shim的隐藏后台运行，不宣称无shim运行，也没有为了通过检查改变测试或项目检查脚本。

领导已核对原始core/定向/浏览器/握手与差异并授权文档同步。本次Sol只静态读取上述证据，保存文档前副本/差异并核对三个文件hash，不重复运行已通过的测试；同步不会把Astra测试写成Sol新跑结果。后续原Sol失败表格和专题原文均为历史，不再是当前阻碍。

## 已实现的行为

- `application/migrations.py`按内容识别V1完整包、兼容的三表SQLite V1、旧小说JSON和工作区JSON。SQLite通过在线backup包含已提交WAL；包复用B的受限解包/manifest/完整预检。未知schema、未来版本、重复JSON键、非法引用及不完整历史拒绝；不初始化、修复或修改来源。
- 来源在新暂存目录冻结并严格校验；先遍历当前状态、每条整书revision和实体snapshot的联合ID集合，再转换SQL归属、各类实体/版本/前版/当前版ID、IDEA键、卷/细纲/场景/人物关系的明确引用字段。不同书/实体类型分别作用域映射，卷号/场景顺序、时间、原文及领域列表顺序保持；不全局替换正文中的旧ID文字。
- 可信DDL重建转换后的独立暂存库并再次预检。目标通过同连接 `BEGIN IMMEDIATE` 锁内严格校验和冲突复查；项目、全部整书历史与待插入Skills一次事务提交。插入/提交前失败整批回滚，已有项目不变，不调用普通create/save冒充原历史。
- Skills是当前库的全局资料。同ID六列完全相同才复用；同ID任字段不同稳定重映射；映射再次冲突拒绝。同名/同内容但不同ID保留独立记录。报告逐条列原ID、新ID和实际复用/新增/重映射，不编造项目归属。
- 业务接口支持明确的 `project_ids`、`skills_mode=all/selected/none` 与 `skill_ids`，单列排除项目/Skills；专项已验证选一本与一个全局Skill。现有界面提供整来源/全部全局Skills导入及“当前小说”复制，不提供选择性备份包创建或细粒度选取界面，B的完整包/独立新目录语义保持。
- 有效空库如实报告无数据变更；仅Skills库独立规划和事务导入，不利用空项目集合伪称已导入小说。相同backup_id默认稳定映射，全部真实目标记录匹配才复用；不同显式复制操作使用不同身份。SQLite/旧JSON按规范化来源身份稳定映射，重复操作不凭名字去重。
- 提交前将映射计划及预期SQL行hash保存到目标父目录的 `.novel-migration-operations-<目标命名空间>/UUID.json`。收据不含正文、Skills原文、配置或凭据。相同编号换来源/范围拒绝；全部目标不存在可重试，全部项目/历史/Skills匹配才报告 `already_present`，部分存在、已编辑或收据损坏保守拒绝。无新业务表，无包格式/schema升级，无自动扫描或删除旧收据/authority。
- `preview=True`保留可恢复计划并返回 `ready/verified=false`，不写三张业务表；之后同来源和编号提交。状态核对来自真实SQL，收据只证明意图；提交后重新只读核对。取消如晚于提交，如实报告完成，不宣称回滚。
- 旧JSON只导入实际有的数据，保留现有实体版本，重设为1条初始导入整书快照；原revision、缺失的整书历史/Skills/IDEA/世界观/规则等单列报告。只补声明可兼容的缺省字段，生成ID确定化；缺失时间使用明确的1970年UTC占位，不冒充原时间。原输入保留；无法核对历史引用的旧输入拒绝，不猜测修复。

## 现有界面入口

展开左上角模块菜单 → “历史、备份与恢复” → “导入或复制为新项目”。选择来源文件后可“预检迁移来源”，查看编号映射/缺失范围/Skills冲突报告，再“导入为新项目”；已有小说可“预检当前小说副本”或“复制当前小说为新项目”。导入后刷新书架，仍保留原小说，复制本可独立打开并编辑。

能力端点 `/api/migrations/capabilities` 独立于B；旧后端不具能力时禁用控件。写入、状态和取消沿用Host/Origin/页面token；文件上传复用B两并发槽、限额、流式超时/取消及关闭信号，不接受浏览器指定任意磁盘路径。新增接口为 `POST /api/migrations/import`、`POST /api/migrations/copy`、`GET /api/migrations/operations/<UUID>`、`POST /api/migrations/operations/<UUID>/cancel`。

sessionStorage仅新增非秘密迁移操作UUID；原文件、正文、映射报告及token不落浏览器存储。复制仅包含已保存内容；草稿仍须先保存。上传单个SQLite文件不能携带作者机器上尚未合并的旁路WAL，迁移活跃源库应优先使用源工作台下载的完整包。

## 历史：Sol原开发及失败交接证据

仓库外根目录：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S2C-migration-20261015-e80117990a/`。继承123项旧基线和before，本次接手前副本另存sol-before；仓库外plan.md记录范围与轮次。每个run目录保留stdout.log/stderr.log/exit.json，退出码未覆盖。

| 检查 | 实际结果 | 证据目录 |
|---|---|---|
| 首批业务RED | 18方法因缺少正式迁移业务而失败，退出1 | red-business |
| 首次业务实现 | 合法暂存类型接入错误，退出1，失败保留 | green-business-1 |
| 第1次修复复测 | 18方法通过，退出0 | green-business-2 |
| HTTP及界面RED | 7 HTTP失败；现有界面缺少复制入口，均退出1 | red-http、red-browser |
| HTTP实现 | 7方法通过，退出0 | green-http-1 |
| 第2轮业务 | 21方法中逆映射SQL行排序比较失败，退出1 | green-business-3 |
| 第2轮界面 | 已完成复制/旧导入后，切书导航可见性等待不足，退出1 | green-browser-2 |
| 新边界RED | 空库/仅Skills/同包及预检/范围契约的失败分别保留 | red-contract-edges、red-preview-scope |
| 第3次修复后业务专项 | 24/24方法通过，退出0；含真实子进程提交前/提交后强杀两个窗口 | green-business-final |
| 第3次修复后HTTP | 7/7通过，退出0 | green-http-final |
| C headless | 7组场景通过，退出0，无外部请求/页面异常 | green-browser-final |
| B受影响headless回归 | 8组检查通过，退出0，含新目录恢复、断线核对、编辑重启、Skills与双窗口冲突 | regression-backup-browser |
| 完整core | **退出1，未通过**；277 Python方法，2个失败方法含3条failure记录，另1个error方法；6 Node与示例退出0 | core及core-evidence/20261014T163047Z-562a8529c662 |

完整core中失败方法不能按subTest重复统计：`test_backups...integrity...`产生1条failure；`test_migrations...real_process_kill...`的before/after两子场景产生2条failure；`test_dev_workflow...powershell...`产生1条error。277方法中274方法通过、2方法失败、1方法错误；没有skip。原 `FAILED (failures=3, errors=1)`完整保留。

完整core源码冻结128文件，检查期间modified/removed/added均为空，疑似凭据提示为空，diffcheck退出0。随后仅同步交付文档（含软件内指南文字），不据此冒称再次完整core通过。B历史246 Python/6 Node/39专项是历史，未冒充本轮结果；本轮完整core确实运行了全部277方法且失败。

界面检查走真实可见入口：等待切书完成，再展开现有模块菜单；没有force点击隐藏按钮、重新暴露首页手动标签或修改首页布局。SQL逆映射测试仅对SQL行按逆映射后的原主键重新排序；领域内列表、全部字段/原文/历史仍严格逐项比较，没有删字段、降断言或跳过。

## 历史：Sol到修复上限时交给领导的Astra专题

以下保留Sol原core失败时的交接原文；上述独立Astra已按领导授权处理并通过回归，不再构成当前待派或待修任务。Sol三次修复上限记录不被改名抹去。

本轮3次有新证据自动修复已经用完，Sol停止代码/夹具修复及失败复测，不改名重开轮次。该停止不是网络或安全策略阻断，当前不需DeepSeek；需领导安排独立GPT-6 Astra处理以下具体专题，再明确后续收口范围。尚未自行创建Astra或发送跨聊天消息。

1. **B错误分类回归。** `storage/backup_validation.py`抽取 `validate_connection` 后，`PRAGMA integrity_check`抛SQLite错误时走外层泛化错误，原有损坏库测试要求 `integrity` 分类的断言失败。输入仍被拒绝、没有恢复目标，但违反B错误契约。恢复明确完整性读取错误分类并保留取消传播与无私有内容错误，不删原断言。
2. **C强杀夹具在白名单环境失效。** 单项runner携带PYTHONPATH时两个强杀窗口通过；完整core经dev_workflow/validate_s2_b剥离PYTHONPATH，子进程 `-c` 没有自行加入仓库src。before/after均未出现目标窗口marker；子进程退出分支未communicate，伴随未关闭pipe的ResourceWarning。静态定位是显式导入路径与资源回收缺口，core未保留子进程stderr，需Astra用修正后的夹具收集原始子进程退出码/双流并确认，不能把未到窗口当作已测强杀。
3. **本次测试启动PATH不完整。** 仓库外run_check.py只前置Git/Node/System32，漏了已装 `C:/Windows/System32/WindowsPowerShell/v1.0/`，旧工具测试调用 `powershell` 得WinError2，未开始对应检查。仅为测试子进程补现有路径，不改全局PATH、不安装依赖，不删或跳过旧工具测试。

可写范围建议：`storage/backup_validation.py`、`tests/test_migrations.py`及本轮仓库外runner；如需改项目工具或其他文件，先明确唯一写入归属。Sol当前冻结业务代码，项目文档同步完后等待领导安排。Astra应先读原始core日志与已保存sol-before，保留既有失败及全部断言，再做针对性复验及必要core；不能擅自操作正式服务/数据/凭据或越阶段。

## 尚未验收与边界

- 本次S2-C技术回归已通过，作者体验验收/正式投用仍未完成，不勾选作者验收。API选择性导入已提供并测一个选择性组合；选择性备份包创建、细粒度UI选择、真实大库与更多组合不借本次通过宣称完成。现有B新目录恢复语义未扩展，原错误分类回归已由Astra收口。
- 本轮未验证物理断电、网络盘/非Windows、实际>4GiB、500章/百万字/每章多版本规模，也未重跑全部旧7类浏览器；D/章节与草稿余项/S3不在范围。旧SQLite仅接受当前可信三表V1，不能承诺任意历史产品数据库可自动升级或旧程序兼容新结构。
- 迁移收据不是来源认证或抗同用户任意代码执行保障。暂存/收据quota与资源上限可能明确拒绝；不删除历史达标，不自动清理旧暂存、authority或操作收据。
- 正式data、真实凭据未打开，8765未访问/重启/操作，未触碰作者窗口/输入/剪贴板或通知。所有运行、端口、配置和浏览器样本虚构；子进程隐藏。没有真实模型调用、安装依赖、全局设置修改、提交或推送。
- 技术回归通过不等于作者验收或正式服务已加载。作者体验验收仍待取得，正式8765未投用本轮代码，整体S2未完成；当前只完成指定文档同步，停止等待领导下一项具体派单，不进入D/S3。

## 下一步建议范围（仅建议，未执行）

建议下一步快速核对S3实际依赖，冻结已交付且通过回归的备份迁移能力；将S2的D长篇性能基线、章节重排/归档/恢复、磁盘草稿/异常恢复等余项明确排期。作者决定优先S3时，再由领导调整原阶段门槛并明确范围；当前没有调整或启动授权，也未执行依赖检查或新阶段开发。作者体验验收与正式投用仍另行安排，不擅自重启8765或读取正式data/凭据。
