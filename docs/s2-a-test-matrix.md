# S2-A：样本验证与后续备份验收矩阵

后续状态（2026-10-14）：作者已另行授权S2-B，完整库V1包/严格预检/独立新目录恢复及生产历史校验已实现，实际结果见[S2-B交付](s2-b-acceptance.md)。B只支持完整库、全部Skills和偏好排除，选择性/偏好/已有库/旧JSON迁移明确未支持。以下A/较早轮次的“未实现、未执行”保持当时证据；B当前测试状态以新交付为准，不改写A旧证据，C仍未开始。

日期：2026-10-14（Asia/Shanghai）。S2-A只交付审计、设计和独立虚构样本。**正式包写入、预检、恢复与迁移尚未实现，下面B/C用例全部未执行**；样本oracle通过不能代表生产校验器已修复。

契约依据：[完整数据清单](s2-a-data-inventory.md)、[备份格式设计](s2-a-backup-format.md)、[manifest示例](s2-a-manifest.example.json)。原16项TC-S2见[current-state-and-s2-plan.md](current-state-and-s2-plan.md) §6，本矩阵把它们展开；草稿/重排/归档仍属后续任务，不提前验收。

## 1. 数据、环境与共同断言

本轮样本：[full-dataset-v1.json](../tests/fixtures/s2_a/full-dataset-v1.json)、[schema-v1.json](../tests/fixtures/s2_a/schema-v1.json)及[test_s2_a_samples.py](../tests/test_s2_a_samples.py)。2本同名小说、6条整书快照、3条同名Skills；每本2章/2人物/1细纲/1全书大纲，最新6条实体版本，五类实体版本全部覆盖。章节/人物/版本ID字符串跨小说重复；涵盖分卷、关系、场景、IDEA、世界观、规则、确认稿与草稿、UTC时间、Markdown BOM/CRLF/前后空行/尾空格/有序多文件。长篇性能和资源限额另用500章/100万汉字/每章至少5版、按真实保存序列增长的虚构库，不能以本轮小样本代替。

所有后续用例只在本次拥有的临时目录、虚构源/目标库和假偏好/凭据上执行。正式8765、小说库、真实DPAPI配置和作者浏览器均不接触；网络只允许本机夹具。破坏性测试前记录输入包hash、源/既有目标的全表逻辑hash、schema、逐表/逐项目数量、各历史revision及字符串UTF-8 hash。操作后关闭全部连接、独立重开复核。

共同通过条件：

- **保真成功**：三表全部持久列及每条历史逐字段一致；正文和Markdown原文、ID、时间、顺序、状态不变。已有库复制按逆映射核对，仅获准身份/引用改变；SQLite物理字节、rowid不要求相同。
- **安全失败**：源库/输入包/既有备份保留；没有成功目标或半项目；既有目标逻辑hash、schema和数量不变且重开可用；只清理操作拥有的暂存文件。并发源允许作者自己的合法提交，校验其写入日志，不能误要求并发源hash不变。
- **错误可核对**：记录阶段、记录ID/字段路径和错误类别，不打印正文、Skills原文、凭据或私有原始SQL；报告不以HTTP200/toast替代落盘结果。SQL成功而可选偏好失败分别报告。
- **进度/资源**：有界IO、取消和锁等待；不截断/删历史达标，不执行包内SQL/脚本，不跟随未知附件路径。

## 2. A：本轮已执行的11项样本测试

自动入口：`python -B -X utf8 -m unittest discover -s tests -p test_s2_a_samples.py -v`。均包含在本轮完整112项回归中。

| ID | 对应测试方法（省略test_前缀） | 实际核对与结果 | 边界 |
|---|---|---|---|
| A-01 | frozen_fixture_contains_all_persistent_fields_and_can_be_reopened | 冻结JSON=工厂；全字段、五类snapshot字段，虚构库当前项目/Skills落盘重开一致，通过 | 样本构造与读取，尚无包往返 |
| A-02 | real_sqlite_schema_matches_frozen_profile_with_indexes_and_foreign_key | 实际repository DDL及PRAGMA=冻结profile；三索引/一外键/三触发器/版本/NULL标志，通过 | 未重新打开正式物理库 |
| A-03 | historical_invalid_chapter_references_are_rejected_by_design_oracle | 历史分卷/细纲引用不存在章节，oracle拒绝；生产validate_workspace仍接受，通过 | 证明生产缺口，未修复 |
| A-04 | historical_character_and_scene_references_are_rejected | 历史关系/细纲/场景不存在人物，oracle拒绝，生产仍接受，通过 | 生产预检尚无实现 |
| A-05 | historical_semantic_errors_are_rejected | 历史卷/场景/章节顺序非法、重复分卷章节、空白名称拒绝，通过 | 有限样本断言，非通用校验器 |
| A-06 | history_only_chapter_remains_valid_in_its_first_available_context | 历史独有无版本章节引用合法，复制映射保留，通过 | 历史上下文设计示例 |
| A-07 | future_entity_does_not_repair_earlier_invalid_reference | 未来才出现的章节不能补平早期历史引用，通过 | 不使用全历史联合集判合法 |
| A-08 | copy_mapping_is_scoped_repeatable_and_reversible_without_replacing_text | 两小说作用域不混，重复稳定、逆映射全数据相同，正文旧ID字符串/Skills不变，通过 | 无目标库导入或重复冲突算法 |
| A-09 | missing_persistent_field_and_sql_or_history_mismatch_are_rejected | 缺language、错SQL标题、缺revision、错Skills主路径拒绝，通过 | 不代表全部坏格式已覆盖 |
| A-10 | uncheckpointed_wal_fixture_proves_main_file_is_not_complete | WAL已提交revision4可见，忽略WAL的主文件只见revision3，通过 | 裸复制反例，未验收包级WAL捕获 |
| A-11 | sample_database_path_must_not_overwrite_an_existing_file | 样本工厂拒绝已有目标且字节不变，通过 | 测试辅助工具的保护 |

本轮完整Python回归112/112通过，虚构示例校验通过。测试涵盖原业务/存储/HTTP/离线/本机假供应商协议，未发送外部模型请求。本轮不改生产/UI代码，因此未重新执行浏览器UI验收，不用上轮页面结果冒充本轮结果。

## 3. B：正式完整备份与新目录恢复（全部计划，未执行）

默认P0必须逐项通过；P1也不能作为已支持功能的已知数据丢失例外。自动化包括真实磁盘集成、故障注入和独立进程；它们属于后续实现，不在A编写生产接口。

| ID/优先级；原TC | 前提与步骤 | 必须观察的结果 |
|---|---|---|
| B-01/P0；01 | 全字段虚构源→正式备份包→不存在的新目录恢复→关连接重开→再备份 | 全表/原文/所有历史保真；第二包与第一包逻辑数据一致，包身份/捕获时间可不同 |
| B-02/P0；01/02 | 空库、无Skills、无大纲、多项目多Skills，分别完整往返 | 零数量合法；manifest范围/计数与冻结结果一致，不补虚构记录 |
| B-03/P0；02 | 多次真实业务保存和仅资料保存，遍历全部整书revision/实体版本 | 1..revision连续，最新payload及SQL时间一致，旧版本不可变前缀；资料保存不强制新增实体版本；document更新时间独立 |
| B-04/P0；02/04 | 对每个当前/历史/首现version分别注入坏卷chapter_ids、细纲chapter_id、IDEA键、人物关系/场景人物；重新计算包hash | 每个非法引用拒绝；仅未来存在/另一小说存在仍拒绝；历史独有合法引用通过，错误不输出原文 |
| B-05/P0；02/04 | 损坏previous/current指针、version归属/类型/编号/时间、改旧snapshot、SQL id/title/revision、最新payload/saved_at或中间快照 | 全部拒绝，不因SQLite完整性或hash通过而接受；confirmed缺current指针拒绝；不强加“必须最新版本/正文等于snapshot” |
| B-06/P0；03/04 | 缺/多字段、重复JSON键、NaN/Infinity、bool伪装整数、NULL/空ID、错误枚举/source、非法UTF-8、非UTC系统时间、错Skills主路径 | strict预检拒绝且不生成ID/时间补洞；字符串内部BOM/CRLF/空白保真，story_time自由文本合法 |
| B-07/P0；03 | 截断ZIP/SQLite、坏中央目录/CRC、缺manifest/主文件、字节/大小/hash不符、SQLite损页 | 分类拒绝，无半恢复目标；原包及旧备份不变 |
| B-08/P0；03/06 | 包/库/workspace/document分别未来版、缺版本、user_version0、未知format/profile/表/列/索引/视图/触发器/字段 | 显式拒绝，不先调用repository初始化或运行包内DDL；不能降级到普通JSON导入 |
| B-09/P0；03/04 | 重算hash和manifest后删除历史/Skills或篡改count/scope/schema描述；冒名可信trigger | 数据与清单不一致及不可信schema拒绝；reader只证明包自身一致，不假称能证明源数据没被选择性排除 |
| B-10/P0；10 | 重复/大小写冲突ZIP成员、路径逃逸、绝对/ADS/反斜杠/尾点空格、symlink、加密、未知压缩、额外脚本 | 固定成员白名单拒绝，零越界文件/执行/扩展加载；合法PRAGMA位置数组重复值接受 |
| B-11/P0；10 | 欺骗压缩/展开大小、超成员/单项/总限额、流式累计超限；合法高压缩历史包 | 超限有界拒绝；合法高压缩比在字节限额内可恢复，不单以压缩比拒绝 |
| B-12/P0；05/10 | 快照/ZIP/解包/重建不同阶段预估空间不足，预估后另进程抢空间；注入SQLITE_FULL/ENOSPC/short write | 提前拒绝或写入失败安全结束；无成功发布，既有数据/hash/数量不变，不删除历史腾空间 |
| B-13/P0；05 | 注入源读取/backup/ZIP关闭/flush/fsync/目标INSERT/校验/最终rename错误，含commit前后响应丢失 | 各失败点有确定报告；发布前失败无成功目标；已落盘成功但响应丢失可核对，不盲目重复新建；旧文件不覆盖 |
| B-14/P0；09 | DELETE journal模式及WAL已提交未checkpoint、WAL未提交事务，分别备份恢复 | 已提交数据在包内完整，未提交数据排除；所有表/历史属于一致状态；不强制checkpoint/改源模式 |
| B-15/P0；09 | barrier控制另一连接在分步采集间保存正文、资料及Skills，捕获前后有多合法事务状态 | 包等于某个完整可提交状态，不混搭；清单从最终快照取得；源仅有测试计划中的合法提交 |
| B-16/P0；09/10 | 持续并发写使采集反复重试；取消、锁超时、关窗口/子进程中断 | 有界结束/取消，未发布半包；按操作归属处理遗留暂存，不通配符清理；无自动模型请求 |
| B-17/P0；05/14 | 发布前其他进程创建同名文件/目录，目标存在、锁住、不同卷；Windows真实文件原语测试 | 不覆盖突现目标，输入/原库可用；同卷原子无覆盖发布有证据，跨卷只允许明确安全策略 |
| B-18/P0；11 | 临时凭据/环境/token塞入假运行配置，旁置“不可读取”假DPAPI文件，检查包/日志/响应 | 配置整份排除且读取探针为0；不解密真实文件、不外发，不把普通作者文本含假密钥当作可静默删改内容 |
| B-19/P1；11/14 | 选入合法七项偏好及未知键/未来偏好版；DB成功后localStorage写失败 | 不支持的附件明确拒绝；合法附件独立应用并报告；偏好失败不破坏成功DB或既有偏好 |
| B-20/P0；13 | 恢复虚构库启动临时UI：创建、正文/资料保存、差异/历史恢复、正式确认、双窗口冲突、人物/世界观/Skills读取 | 可继续创作且旧历史/顺序不变；仅临时端口/库；浏览器外部请求拦截为0，配置不自动连接 |

B的真实资源限额、单记录/递归深度/时限、传输及取消原语由合法规模样本测定；本轮8GiB是提案，不是验收结果。选择性包/偏好若B不实现，应明确不支持，不能让UI宣称成功。

## 4. C：已有库迁移、冲突与旧数据兼容（全部计划，未执行）

| ID/优先级；原TC | 前提与步骤 | 必须观察的结果 |
|---|---|---|
| C-01/P0；07/14 | 多本同名/跨书同实体ID/历史独有对象导入已有库；遍历所有映射再逆映射 | 新项目/全历史关系不混，除结构ID外所有字段/时间/原文相同，原项目不变；各自编辑隔离 |
| C-02/P0；07 | 预检后另连接插入冲突项目/Skills；锁内复查及超时 | BEGIN IMMEDIATE内复查；任一项目冲突整批拒绝或回滚，不能静默缩范围/覆盖已有项目 |
| C-03/P0；05/07/08 | 项目、当前payload、任一历史、Skills插入及提交分别注入故障 | 单连接单事务无半项目/半Skills；既有目标全表hash/schema/数量不变；源输入不变且可重开 |
| C-04/P0；08 | Skills同ID完全相同/任字段不同/稳定映射ID已有不同记录；不同ID同名同内容；首次导入前已有可复用Skills；零项目空库/仅Skills包 | 完全相同才复用；冲突新ID，映射再冲突拒绝；其他独立记录保留；BOM/换行/列表/时间不变；已有共享Skills不误判半批项目；空库无变更，仅Skills按独立计划一次事务 |
| C-05/P0；07/14 | 同包重导、响应丢失后重试；一项目被编辑或缺部分行；仅存在相同backup_id/UUID | 全部映射行/历史/Skills相同才跳过；已编辑/部分冲突整批拒绝，不凭ID冒称完成，不修补半批 |
| C-06/P0；07/14 | 同内容新backup_id；另建副本copy_id；提交前操作凭据留存失败、COMMIT后进程退出、响应丢失、凭据损坏后重试 | 新副本身份与默认包身份明确；留存失败不提交；可恢复同identity_token且核对全部记录；无法恢复计划则显示提交状态待确认，不自动生成新copy_id；原项目/副本不变 |
| C-07/P0；01/08/10 | full_library/all及selected_projects配Skills all/selected/none；选定库与冻结源集合对照 | 只从冻结源在新库重建选定行，未选小说/历史原文不进包或空闲页；范围/排除可见，不虚构Skills归属 |
| C-08/P0；07/14 | 请求覆盖已有项目/合并旧revision或同包恢复到已有新目录 | V1拒绝；同名允许且原标题/历史标题保留；无REPLACE、删旧快照或普通save伪造恢复 |
| C-09/P1；06/12 | 旧小说JSON、旧工作区JSON、v0.2SQLite合法输入及缺可兼容字段，未来版本/非法关联反例 | 来源与损失/一次规范化报告，保留原文件；不造原整书历史/Skills；未来或非法引用拒绝 |
| C-10/P0；06 | 旧库转独立新目标，转换/写入/发布失败，随后用旧程序重开旧库 | 旧库保留可运行、新目标不发布；不得宣称旧程序能读新格式，schema版本分别核对 |

## 5. 后续S2任务与验收门槛

| ID/优先级；原TC | 计划验证 | 状态 |
|---|---|---|
| D-01/P1；15 | 500章/100万汉字/每章≥5版，固定真实保存序列；记录整书快照数量、增长、数据库/ZIP/展开体积、峰值内存；30次读/保存P95<1s、启动可交互<5s，含完整备份恢复 | 未执行，S2-01/02/07 |
| E-01/P0；16 | 磁盘草稿后异常退出恢复，章节重排/归档/恢复后再次备份，确认/ID/引用/历史不变，更新包契约 | 未实现、未执行，S2-05/06 |

S2-A通过条件是清单/schema全字段可追溯、好坏虚构样本可区分、格式/范围/未知策略及恢复冲突规则明确，且生产缺口和未执行项完整披露。作者验收本交付后，才可另行授权B。B/C支持范围内的P0/P1全部通过才称相应业务验收完成；整体S2还需后续规模/草稿/章节操作，不以测试覆盖率或小样本数量抵消数据丢失。

本轮日志及虚构SQLite证据在仓库外：`C:/Users/Administrator.USER-20260902RM/.codex/visualizations/2026/10/13/01a135bf-74fd-7153-8178-5663922332f1/s2-a-design/`。没有发布真实备份ZIP；manifest的SQLite大小/hash只对应此处虚构样本。既有生产代码及原有测试不变，无提交/推送、无S2-B实现。
# 2026-10-15 当前状态补充

下方A历史和B/C“全部计划”按当时记录保留。C本轮已实际运行24业务、7 HTTP、C headless 7组及B受影响headless 8组并通过；完整277方法core存在2失败方法（3条failure记录）及1错误方法，C未收口。逐项范围、选择性界面/包创建及强杀环境限制见[S2-C统一交付](s2-c-migration.md)，不能把C-01至C-10全部勾选验收。

