# S3-B手动记忆与字面检索：当前交付

2026-10-15（Asia/Shanghai）。**S3-B本批功能技术交付完成**：独立Astra统一修订后，50定向、S3-B四组及最终316 Python/Node6/示例全部退出0，144文件检查期间不变、diff0、credential_hints空。正式8765未加载新功能、作者体验尚未取得，整体S3/S2余项未完成，S4真实模型/费用/发布未授权。本次Sol只同步四份文档，不改源码/测试或重跑；原三轮及310两error、Astra前期失败保留，没有子代理/重复聊天或跨聊天回发，不自动下一阶段。

## 可见入口

模块菜单 → 人物、世界观与记忆 → “长篇记忆”：新增/编辑全书、卷、章摘要，人物状态、事件、伏笔/回收，选择适用章位/卷/人物及本书来源，保存、确认、归档和查看不可变编辑历史。固定出处可查看旧版本内容；正文改写或恢复新版本会显示过期，保存作者纠正不静默更新出处，须“复核来源并更新确认”。确认与新鲜度独立，自身/无关保存不使记忆全部过期。

长篇记忆 → “本地字面检索”：选择本书正文/规划/人物/记忆/世界规则范围、写作章位；默认不搜后续章，无时间定位自由资料须主动选入，全书检索须显式选择。全局Skills须选中具体资料并标明全局及完整记录hash；这是区分大小写字面扫描，不是语义检索。命中/无命中与上限如实报告，可跳到实际章/人物/记忆/资料入口。

命中勾选“选入此来源” → “预览已选资料”；原章节写作的只读上下文也可显式选择已确认、启用、未过期的记忆。服务器重新读取核对所属书、revision、来源版本/指纹与章位，不接受缓存片段当正文，旧结果不能绕过未来/过期/未确认过滤。记忆有效章位取作者声明与捕获的可定位出处章位较晚者，防止把20章来源提前标成1章后注入第5章。无位置自由来源仍依作者声明/主动选入，不做语义剧透判断。字符预算含资料串标题与换行，不是精确token数；选章/选项/切书/本窗口保存使旧结果失效，迟到响应不回填。

## 持久格式与兼容

- SQLite仍三表/SQL user_version=1，小说document.schema_version=1；workspace V2新增明确`memories`、`memory_history`，每条记忆及编辑有稳定ID/版本链、来源、确认/归档状态。没有将结构数据藏进世界观、正文、备注、Skills或浏览器存储。
- 旧V1逐条按自身声明读取，内存里按已声明默认值确定化归一，不调用ID/当前时间工厂、不回写旧快照。首次显式写记忆只升级当前payload；混合V1/V2历史逐条验证，记忆历史不可变前缀，新编辑snapshot按首次出现时的本书集合完整验证，出处过期不等于损坏。
- 纯旧库仍V1包及原database/counts；含V2数据才声明backup_format_version=2/workspace_version=2，仍manifest+SQLite两成员。新数据全部当前值/记忆编辑历史/出处随备份恢复保真，复制两遍收集并映射memory/编辑ID、前版链与明确来源/章位引用；源库和原历史不改。
- V1旧SQLite、完整包、workspace/novel JSON（含允许省略的旧默认字段/集合）经实际入口验证，ID/revision/既有时间/原版本链和原SQL行/字节独立对照。旧JSON缺整书历史仍如实报告；V2单条workspace JSON缺来源依赖的整书历史时明确拒绝，要求完整包/SQLite，不补造出处。
- 无变化重存保护仅适用于原payload确有legacy缺省差异的路径；普通完整V1/V2保持正常保存追加版本语义。Astra已在`repository.create`显式新建入口调用既有构造器填默认后严格验证；旧持久read/save的身份/时间要求未放宽。

## 最终Astra收口与验证

最终证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S3B-Astra-20261015-b11ffcfc/unified-transport/`，`result.md`、`combined-astra.patch`、`final-hashes.json`和`commands-and-results.json`保存实际修复/差异/hash/命令。仅合并四个产品文件：仓储显式新建入口、server统一POST错误生命周期及两份相应存储/HTTP测试；没有改记忆/检索/迁移或暂存/ACL/authority。

最终不是“仅403关闭收尾”的候选：server透明包装原reader，统计生产read/read1实际已读正文；POST错误响应成功写出后，在统一finally只对未读剩余体做最多4096字节/200ms总时限收尾，覆盖403/404/413/422等。已读尽的JSON/备份预检错误不再等待；未知长度/传输编码也仅有界丢弃、不解析落盘。原Host/Origin/token、上传保护和错误状态/分类不变。因果对照证实这一提前响应关闭机制能复现10053；原Sol那次没有事件记录，不伪称其历史精确时序已追溯。

| 阶段 | 原始结果与边界 | 相对Astra根的证据 |
|---|---|---|
| Sol原三轮/310 core | 308通过、2 errors，exit1；原记录完整保留 | 原`S3B-memory-20261015-9d124a/core`及报告 |
| Astra初始定向 | 21中20通过，时间戳相等导致新增观测断言失败；不能标通过 | 父目录`candidate-targeted`、`result.md` |
| 领导授权观测更正 | 21定向通过，改用真实事件/接收握手；随后314 core有1个422早返回10053错误，exit1，不能把仅403修复写成最终成功 | 父目录`corrected-targeted`、`final-core`、`final-result.md` |
| 统一修订前RED | 7子场景中4个迟到正文分支error，exit1，原3类403通过 | `red-late-errors` |
| 最终统一候选 | 50定向全部通过，S3-B四组passed且external/errors空，均exit0 | `candidate-targeted`、`candidate-s3b-browser` |
| 最终core | **316 Python OK、Node6及示例均exit0**；144文件期间无变化、diff0、credential_hints空 | `candidate-core/exit.json`、`core-evidence/20261014T231252Z-d8b4fc524b0e/report.json`及`regression` |

真实迟到体、静默/滴流/大声明上限和正文已消费尽不再读取的证据在`core-early-error-events.json`，不是放宽时间/吞连接错误或重复直到通过。仍经仓库外隐藏控制台shim转发原入口，非无shim运行。领导已核对最终报告并交回四文档归属；Sol本次只静态读取与hash/diff核对，不把Astra结果记为Sol新跑。

## 历史：Sol原证据与三轮修复记录

根目录：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S3B-memory-20261015-9d124a/`。135项起点hash/before/plan保留。`tests/fixtures/s3b_legacy_v1.json`在生产修改前冻结了真实库/包hex、原payload/SQL行，并独立构造缺已声明默认字段的旧表示，不由新序列化器伪造oracle。

| 检查 | 实际结果 | 证据相对路径 |
|---|---|---|
| 最终记忆/兼容/检索/HTTP专项 | 20方法通过，exit0 | `green-specialized-final` |
| S3-B headless | 四组通过，external/errors空，exit0：保存重开→正文过期→旧出处→复核→检索/跳转→上下文→归档/无命中 | `green-browser-final/s3b-browser-report.json` |
| 受影响首批规划/原workbench | 九组规划及workbench均exit0，期间hash不变 | `regression-planning`、`regression-workbench` |
| 旧校验/应用定向 | 旧完整性校验及旧应用方法通过，exit0 | `affected-old-validation`、`affected-old-application` |
| 唯一完整core | **310 Python中308通过/2 errors，exit1**；Node6及示例exit0，143文件期间不变、diff0、credential_hints空 | `core/exit.json`、`core-evidence/20261014T223624Z-2c335b35b592/report.json`及`regression` |

有效RED及原失败全部保留：`red-memory`、`red-search`、`red-http`、`red-browser`；两项存储P2分别见`red-storage-edges`、`red-legacy-collection`，未来出处反例见`red-future-source`。没有删断言/skip。3次修复：①preflight专项取错返回层的测试修正；②两项存储P2统一旧集合归一化、首次历史snapshot语义验证；③记忆异步切换加载保护/等待与实际出处章位过滤。未来版本/未知字段等原负例保留；原290/旧310前其它阶段证据不冒称本轮新通过。

core复用仓库外隐藏控制台shim转发原入口，原/实际argv留痕，非无shim运行；未改项目检查脚本/测试选择/环境白名单。所有检查均新虚构库/TEMP/配置/随机端口，隐藏后台/headless，无真实模型、正式data/凭据/8765、作者窗口/输入/剪贴板、全局环境/依赖安装/提交推送、旧authority/暂存清理。

## 历史：Sol原两个阻碍（已由上述Astra修订收口）

1. `test_storage.StorageTests.test_optional_document_fields_are_normalized_before_storage`：新建状态允许应用工厂生成缺省ID/时间，但`repository.create`现走严格旧持久归一化而拒绝。修复应区分“显式新建”与“读取旧库”，不能放松旧持久数据或改原断言。
2. `test_migration_http.MigrationHTTPTests.test_token_origin_status_and_upload_protection`：本地Origin拒绝请求读响应时WinError10053，未获响应退出；本轮未定位是否环境/可复现HTTP问题，不宣称已403通过、不换名字重试，也不先认定为安全策略阻断。

上述为原失败时的交接，保留本轮仓库外`astra-handoff.md`及原日志，不再是当前未修任务。S2性能/章节整理/磁盘草稿、完整S3记忆扩展/高级检索/查重/图谱/模板等仍待后续，物理断电/网络盘/跨平台/>4GiB/百万字规模未验证。正式8765未投用、作者体验未验收，S4真实模型/费用/发布未授权；本次文档同步完成后停止等待。
