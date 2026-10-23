# S2-B：完整备份与独立恢复交付

最新暂存追加（2026-10-14）：正常/GC及显式清理按原对象归属执行，最终删除失败保留收据，提交后残留单独警告；最终237项Python、6项Node及示例通过，见[追加记录](s2-b-staging-cleanup.md)。元数据移出窗口强杀/断电及恢复目录自动恢复未验收，不能把4个已测进程场景推广到所有中断；正式服务和作者验收门槛保留。

前轮追加复核（2026-10-14）：Sol已独立验证滴流修复并修复首次请求与服务关闭的竞争；最终核心213项Python（含开发工具11项）、前端6项及示例通过，七类浏览器复用业务修复后已通过结果。正式8765仍为旧后端，作者验收及规模/耐久等边界保留，S2-C未开始。完整前轮证据见[接管报告](dev-takeover-2026-10-14.md)，下文数字保持原轮次含义。

后续独立验收确认原188项日志和实盘证据，但发现持续滴流会阻塞上传读取，原总时限/取消未完全有效。作者仅授权修复这一P2：现已改为非阻塞read1+有界select等待，新增12项真实HTTP回归，原188项及前端/浏览器复跑结果、失败记录与剩余风险见[专项交付](s2-b-upload-p2-fix.md)。下文测试数字保留原轮结果，不冒称最初无缺口或正式后端已更新；S2-C仍未开始。

日期：2026-10-14（Asia/Shanghai）。本批实际实现完整库 V1 包、严格预检及独立新目录恢复，等待作者验收。没有提交、推送、进入 S2-C 或调用外部模型。S2-A 的完整字段清单仍是范围依据；本文件记录 B 的实现、实际测试与限制，不改写 A 当时的结果。

## 1. 范围与正式服务边界

开始前重读 AGENTS/TASKS/ROADMAP/ARCHITECTURE/CHANGELOG、总计划及 S2-A 三份设计，记录 Git/文件基线。保留 `main / 0a84f89d4cb65eab5867819022839f32eff554f9` 上全部已有修改和未跟踪文件，没有 reset、clean、提交、推送或删除作者数据。

正式服务 PID **46484**，源码 `G:/AGI/AI-Novel-Writer`，数据库 `G:/AGI/AI-Novel-Writer/data/novels.sqlite3`，启动参数包括 `--no-browser --port 8765 --database … --offline`。前置审计只读结构/计数/SQLite完整性：三表15列与 A 冻结 profile 一致，projects=1、project_snapshots=8、skills=0，journal=delete，integrity=ok，外键错误0；审计前后正式文件SHA256相同。本批未对正式小说执行功能、恢复、故障或写入测试，没有重启服务或刷新作者窗口。

所有新增后端能力都在新建的虚构临时服务及 CLI 中验收。现有8765仍为旧 Python 进程；新静态页面通过无副作用的 `/api/backups/capabilities` 检查能力，旧后端返回404时禁用新备份/独立恢复按钮并提示安全更新。这个旧后端兼容场景用临时服务拦截验证，不把它称为正式服务已加载 B。

## 2. 已实现的数据范围和保真

| 持久数据 | 包内位置 | 恢复行为与证据 |
|---|---|---|
| projects全部5列：id/title/revision/payload/updated_at | snapshot.sqlite3原表 | 参数INSERT保留全部SQL单元格，包括payload原始JSON字符串、SQL时间和稳定ID |
| project_snapshots全部4列：project_id/revision/payload/saved_at | 所有整书历史逐条保留 | 不调用普通save，不补造revision或改历史；恢复保留三条历史保护触发器 |
| skills全部6列：id/name/description/imported_at/primary_path/files_json | 全局所有记录及有序原文列表 | 不按名称去重，不生成新ID/时间；BOM/CRLF/空行/尾空格在SQL/API中原样保留 |
| 项目元数据、语言/状态，全书大纲/分卷、章节细纲/场景、正文/状态/编号 | 当前及每个整书payload | 全字段、列表顺序、ID与时间不变；没有界面编辑入口的字段也保留 |
| 人物/目标/关系、IDEA、世界观、写作规则 | 当前及每个整书payload | IDEA章节键、人物关系与场景人物关联核验，不静默修复 |
| 五类实体版本、previous/current指针和snapshot所有嵌套字段 | document.versions及全部整书快照 | 递归检查快照内实体和引用，逐revision校验首现上下文、不变前缀和完整历史 |
| 真实schema、PK索引、外键及保护触发器 | manifest描述 + SQLite | 对照应用内可信profile；新库执行可信DDL，不执行输入包提供的SQL |

完整字段依据见 [A数据清单](s2-a-data-inventory.md)。三表不存在的模型任务/用量/记忆表不会被虚构进入包。API配置整份、DPAPI文件、环境、令牌、浏览器偏好、未保存草稿/未发送需求/窗口活动、程序文件全部排除；固定包成员也排除库外恢复操作收据。普通作者文本恰含假密钥不会被扫描删改，不能把内容过滤当作凭据排除。

## 3. 包与恢复流程

已实现 `.nwbak` ZIP，固定且仅含 `manifest.json` 和 `snapshot.sqlite3`。`format=ai-novel-writer-backup`、`backup_format_version=1`、schema profile=`novel-writer/sqlite-1`；数据库/workspace/document版本各为1。数据库/清单hash规则与 [A格式](s2-a-backup-format.md) 一致。仅支持 `full_library + skills.all + browser_preferences.excluded`；选择性包、偏好附件、已有目录、合并、ID迁移与旧JSON恢复均明确拒绝，不自动降级或转换。包未加密；SHA256/CRC检测损坏，不认证来源。

备份通过源库只读连接和 SQLite `Connection.backup` 分步采集，WAL及提交状态由SQLite处理；只对新冻结副本转换DELETE journal，不改源模式或强制checkpoint。校验快照后生成所有scope/count/schema/hash，再流式写ZIP、fsync、用正式读取器复核成包，最后在同父目录/同卷无覆盖发布。所有清单数据来自冻结副本。

恢复先检查ZIP目录、固定成员、格式与版本、大小/CRC/SHA256、SQLite头/完整性、精确schema、外键及所有业务历史。通过后用应用可信DDL建立受控暂存新库，单事务参数INSERT，关闭并重开，再次校验全库、逐单元格逻辑hash和报告。数据库fsync后用Windows无覆盖rename发布新目录。源库、包、已存在目标均不覆盖；失败回滚并清理本操作暂存。发布完成后清理失败单独报告警告，已核验结果仍保留。

新增生产历史校验也接入repository create/get/save；不能只靠备份夹具拒绝坏引用。版本snapshot按**首现revision**的章节/人物集合验证，未来实体和别书ID不能补历史缺口，合法历史独有对象仍能打开并继续保存。完整包严格解析全部字段，拒绝重复JSON键/非有限数/bool伪装版本/缺字段/非法时间/类型或枚举/不可信schema。

## 4. 作者入口与恢复操作身份

新源码服务的“历史与恢复”模块提供“下载完整库备份”“恢复到独立新目录”。空库也可进入；需要保留的页面输入须先保存。浏览器使用原生下载和文件二进制流式上传，不将大包转为JSON/base64或整体Blob到内存。

HTTP写操作继续验证Host/Origin/会话token，浏览器不能提交任意磁盘路径。恢复目标固定为当前库父目录下 `restored-backup-<operation_uuid_hex>/novels.sqlite3`；当前工作台继续使用原库。没有自动热替换数据库。要打开独立结果，用新的端口/另一工作台启动 `python run.py --offline --no-browser --port 0 --database "恢复结果的完整路径"`。

恢复前浏览器生成规范UUID，以 `X-Novel-Backup-Operation` 发送，sessionStorage只保留此非秘密操作编号。后端在库外 `.novel-backup-operations/<uuid>.json` 无覆盖落盘不可变收据：version、operation_id、package_sha256、backup_id、logical_sha256。先完整预检再保存收据，收据失败不发布目标。目标名称由UUID推导，不保存客户端任意路径。状态接口 `/api/backups/operations/<uuid>` 需token保护，服务重启后仍用真实目标全SQL校验核对完成，不能只相信文件存在。

同操作编号、同包重试只在原目标仍完全一致时复用；编号换包、目标已编辑/损坏/有附加内容、收据损坏均拒绝。响应丢失可“核对上次恢复结果”；未知编号返回404，目标未发布可用原编号和同包重试，不盲目生成另一目录。CLI没有浏览器操作收据，但严格拒绝已有目标；响应/进程状态不明时先verify输入并检查已发布目标，不能覆盖重试。

“取消当前恢复”提交取消请求；最终发布前检查取消，若发布先完成仍报告完成，不能将已完成结果宣称已取消。pagehide为最佳努力取消；服务关闭也触发取消。强制终止进程/断电可能留下本操作暂存，现阶段没有通配符清理或自动扫盘删除功能。

CLI离线入口（所有源/输出/目标均需明确参数，新目标不能存在）：

```powershell
python scripts/manage_backups.py backup --database "源.sqlite3" --output "新的完整库.nwbak"
python scripts/manage_backups.py verify --input "完整库.nwbak"
python scripts/manage_backups.py restore --input "完整库.nwbak" --target "尚不存在的新目录"
```

## 5. 真实测试矩阵

本批最终结果：**Python 188/188、Node状态6/6、示例通过、七个浏览器脚本7/7；无失败或跳过**。Python分组为原有112项，加完整包26、严格校验27、HTTP13、发布/压缩/取消故障6、包级语义/零数量4。首轮Skills页面回归失败已修复后重跑，HTTP身份/清理/解压等RED保留为开发证据，不将开发中失败隐藏成首次全绿。

| 最终检查 | 真实结果 | 证据（仓库外final-regression） |
|---|---|---|
| unittest discover全部Python | 188通过，0失败，32.897秒 | python/run.log逐个记录188项 |
| 前端状态 | 6通过，0失败/跳过 | ui-state/run.log |
| 虚构示例 | 通过 | example/run.log |
| 创建/正文/版本/人物/世界观/Skills smoke | 通过 | browser-smoke/run.log |
| 草稿/历史/双窗口冲突/确认/布局工作台 | 通过 | browser-workbench/run.log |
| 对话准备/作用域/导航/视窗 | 通过 | browser-chat-workbench/run.log |
| 假API配置保存/重开，零真实站点请求 | 通过 | browser-providers/run.log |
| 离线设置/禁用外发/不同尺寸 | 通过，仅临时服务 | browser-offline/run.log |
| 原生包下载/独立恢复/丢响应/旧后端能力/恢复库作者流程 | 通过 | browser-backups/run.log及backup-browser-report.json |
| S1已加载100章导航 | 通过，P95 17.20ms；非百万字存储基准 | browser-performance/run.log及s1-performance.json |

最终结果以仓库外 `s2-b-implementation/final-regression/` 的逐项日志和 `regression-results.json` 为准。以下都是虚构独立库，无外部模型请求。

| A矩阵B项 | 本批实际验证 | 入口/限制 |
|---|---|---|
| B-01/02 | 三表所有列、行数/PK/字段/时间/版本/原文逐项相同；关连接重开、再备份；空库/仅Skills/无大纲均成功 | test_backups、test_backup_package_cases；CLI保留实盘证据 |
| B-03/04/05/06 | 全revision/五类snapshot/版本链/首现引用/历史前缀、未知字段/类型/重复键/时间；重算hash的坏章节/版本/人物/IDEA包被拒绝 | test_backup_validation、test_backup_package_cases、生产历史测试；没有跳过失败反例 |
| B-07/08/09 | 缺文件、截断、坏hash/目录/DEFLATE、有效头损页SQLite、未知/未来包/库/workspace/document/schema、清单范围不符拒绝 | 不执行未知DDL、不返回原始zlib/SQL错误或攻击文本 |
| B-10/11 | 路径逃逸/重复/链接/未知成员、超成员/展开限额、超大SQL元信息、JSON深度/节点；合法高压缩历史可恢复 | 上限见下一节；实际4GiB以上ZIP64未做容量验收 |
| B-12/13 | 空间不足、磁盘/短写/fsync/SQL插入/事务中途/发布故障，源和旧目标不变，正常失败暂存清理；发布后清理警告与响应丢失可核对 | 故障注入+真实落盘检查；没有真的塞满作者磁盘 |
| B-14/15/16 | WAL已提交未checkpoint、排除未提交事务，分步采集间真实提交、持续提交超时和中途取消；HTTP事务中取消/已完成取消返回完成 | 最后发布有竞争，取消为请求；断电和强杀恢复未验收 |
| B-17 | 目标已存在/发布前突现拒绝，Windows真实无覆盖rename保留原内容 | 同卷原语与竞争注入；恢复不支持跨卷移动暂存 |
| B-18/19 | 假配置/环境凭据不进包；离线配置不读取；未知偏好附件/选择性scope拒绝 | 偏好应用和已有库导入属于未实现范围 |
| B-20 | 恢复库新服务：编辑/正式章授权/保存/服务重启读回，历史追加且旧版/顺序不变、人物/世界观/Skills、双窗口冲突保留输入 | 新e2e-backups及原作者流程浏览器回归；全部临时端口/库 |
| HTTP操作身份补充 | 同编号重试、换包拒绝、重启查回、目标编辑拒绝、收据失败不发布、响应丢失、慢下载配额/关闭清理 | test_backup_http、浏览器真实下载/恢复后丢响应 |

Python全部测试、Node状态测试、示例以及七个浏览器脚本（smoke/workbench/chat-workbench/providers/offline/backups/performance）必须全部通过才提交本交付供验收。providers只保存假配置，不发站点请求；回归入口采用白名单环境，不继承真实凭据或正式审计URL。性能脚本仍是S1已加载100章导航，不冒称百万字存储验收。

独立实盘CLI往返证据保留在仓库外 `s2-b-implementation/cli-roundtrip-ae2b68bf3c7e45218e0c70281cf800cf/`：2个项目、6个整书快照、3个Skills，15列逐单元格相同，源字节hash未变，backup/verify/restore三个独立子进程均退出0。其 `report.json` 包含虚构源/包/恢复库路径和各表逻辑hash。其他临时测试库前缀为 `novel-s2-b-`、`novel-backup-faults-`、`novel-s2-b-http-`、`novel-s2-b-validation-`、`novel-s2-b-package-cases-`、`novel-s2-b-browser-`；正常结束清理，仅保留报告，全部不在正式data目录。

## 6. 限额与仍未验证

- 快照8GiB、manifest1MiB、包8GiB+2MiB；目录解析前限中央目录16KiB和成员数，实际成员集合必须正好两项。磁盘预估另留64MiB或5%，晚到的写失败仍回滚，预估不是空间保证。
- 每SQL单元格64MiB、整行65MiB，取回前用SQL长度标量检查；JSON64MiB、64层、100万节点，解析前拒绝超限，解析后用深度栈，拒绝而不截断。
- 全库100万行、项目1000、Skills10000；manifest ID加权总量512KiB、报告768KiB，计入转义/缩进膨胀。限额是本批明确工程策略，边界反例实测，不是已证明8GiB规模性能。
- 核心备份/预检/恢复及HTTP恢复保留300秒预算。P2修复后上传正文读取为非阻塞read1+最长100ms等待，20秒无数据期限独立于总deadline；收到字节不延长总deadline，等待期间检查取消。下载仍使用原20秒socket超时。两并发槽也覆盖下载，最多四个待下载或在传包，下载票据五分钟一次有效。永久恢复操作收据最多1024项；不会自动删除收据来制造新身份。
- 全历史验证增加读取/保存成本；500章/100万字/每章5版及真实长期整书历史增长、峰值内存、断电耐久、杀进程暂存处理、Windows打包安装/网络盘/4GiB以上包均未验收。
- 正式库只完成前置只读schema/SQLite一致性核对，未运行新历史校验器逐条审计作者业务内容；旧缺口产生的坏历史可能被新校验拒绝，不能以虚构测试保证正式库全部业务引用有效。没有自动删改坏历史或静默兼容转换。
- S2-C已有库新项目合并、ID/Skills冲突与重复导入映射、旧JSON迁移/回退尚未实施；偏好附件、选择性范围、加密包、磁盘草稿、归档/重排也未实现。整体S2未完成。

本批停止等待作者验收；正式服务的安全更新另行安排，不能把临时库成功说成正式库已升级。
