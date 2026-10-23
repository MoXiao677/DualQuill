# S2-A：manifest + SQLite 备份包设计 v1

后续状态（2026-10-14）：作者已另行授权S2-B，完整库V1包/严格预检/独立新目录恢复及生产历史校验已实现，实际结果见[S2-B交付](s2-b-acceptance.md)。B只支持完整库、全部Skills和偏好排除，选择性/偏好/已有库/旧JSON迁移明确未支持。以下A/较早轮次的“未实现、未执行”保持当时证据；B当前测试状态以新交付为准，不改写A旧证据，C仍未开始。

日期：2026-10-14（Asia/Shanghai）。这是待作者验收的格式与恢复契约，**不是已实现功能**。本轮只建立样本和断言，没有包写入器、包读取器、正式恢复入口、迁移接口或生产关联校验修复。

数据依据与完整引用规则见 [数据清单](s2-a-data-inventory.md)；验证区分见 [测试矩阵](s2-a-test-matrix.md)。JSON字段示例见 [s2-a-manifest.example.json](s2-a-manifest.example.json)，其大小/hash取自本轮独立虚构SQLite，不对应作者数据库，也没有已发布的备份ZIP。

## 1. 包结构与范围

建议扩展名`.nwbak`，内容为标准ZIP，允许STORED或DEFLATED，支持ZIP64；禁用ZIP加密，不含执行文件、符号链接或自定义解压脚本。初版没有加密备份，包内SQLite和偏好可被读取，不能标为加密。

```text
example.nwbak
├── manifest.json          必须，UTF-8 JSON，不带BOM
├── snapshot.sqlite3       必须，关闭后的独立一致性SQLite快照
└── preferences.json       可选，作者选入的浏览器白名单偏好
```

文件名大小写精确匹配；没有额外目录项/文件。固定路径减少解压歧义，拒绝其他名称/重复名称/大小写冲突、绝对路径、`..`、反斜杠、盘符、ADS、控制字符、尾点尾空格、symlink、未知压缩和加密标志。不调用extractall；只按固定成员名流式写到受控暂存位置。

scope两种模式：

| scope.mode | 内容与标注 | 采集策略（待实施） |
|---|---|---|
| `full_library` | 三表所有项目、全部整书历史、全部全局Skills；project_ids/skills.ids与实际数据相等，可为空 | SQLite一致性采集；全部清单/计数来自最终冻结快照 |
| `selected_projects` | 非空选定项目及每项目全部历史；Skills明确all/selected/none，显示“选择性迁移”及排除范围 | 先取得整库一致快照，再在**另一受控新库**用可信DDL/参数INSERT只重建选定行；新库才进包。不从整库副本DELETE筛选，不夹带其他小说/空闲页中的旧内容 |

V1无“只保留最新正文/删旧历史”的范围。UI偏好included/excluded独立标注；密钥配置始终排除。全局Skills无project_id，不能虚构某书所属Skills或按名称猜选择范围。

## 2. manifest精确契约

所有对象拒绝未知字段，整数不接受bool；大小/count非负，版本/revision为正数，UTF-8字符串可编码，SHA256为64位小写hex。集合语义的project_ids、skills.ids、索引名、触发器名、exclusions不得重复；tables.name、counts.projects.project_id和entries.path分别唯一。PRAGMA位置数组允许合法重复值，例如foreign_keys.definition中的两个0和两个NO ACTION；正文列表按领域规则校验，不笼统禁止重复文本。清单内不写作者书名、正文、源绝对路径、用户名、认证信息；项目ID等必要结构元数据仍属于私有范围，不承诺匿名。

| 字段 | 格式/含义 | 校验 |
|---|---|---|
| `format` | 固定`ai-novel-writer-backup` | 缺失/不同直接拒绝，不能靠扩展名猜 |
| `backup_format_version` | 固定整数1 | 与数据库/workspace/document版本独立；未知/未来版本拒绝 |
| `backup_id` | 规范UUID字符串，单次包身份 | 新采集新ID；重复包导入用该ID辅助映射，但不能只凭此认定内容一致 |
| `created_at` | UTC ISO8601 | 完成时刻；不是精确事务提交时点 |
| `capture` | `started_at, finished_at`，UTC时间 | 捕获时间窗口，开始≤结束≤created_at；不承诺快照一定对应开始时刻 |
| `producer` | `application_version, git_revision, working_tree_modified` | 软件版本和可选的40位git_revision（无Git时null），modified为bool；信息用于诊断，不替代数据版本。源码未提交状态如实记录 |
| `scope` | `mode, project_ids, skills, browser_preferences` | mode见上表，项目ID集与SQLite一致；browser_preferences为included/excluded |
| `scope.skills` | `mode, ids` | mode=all/selected/none；all指原冻结源全部记录，full_library只能all；none时ids为空。包内实际ID集严格一致，不伪造项目关联 |
| `database` | 下列结构/版本描述 | 与实际关闭后的snapshot逐项比较 |
| `counts` | `projects, skills` | projects数组逐项目计数，skills为总记录数；全部从最终快照生成 |
| `entries` | 每项`path, bytes, sha256` | snapshot必有一项，偏好选入才有一项；不列manifest自身，避免循环hash。ZIP成员集合必须恰为manifest+entries |
| `exclusions` | 固定排除项数组 | 与实际scope匹配；偏好另由scope表示；未知附件或密钥配置对象拒绝 |

database字段：`schema_profile="novel-writer/sqlite-1"`、`sqlite_user_version=1`、`workspace_version=1`、`document_schema_version=1`、`schema_sha256`、`tables`、`indexes`、`triggers`、`foreign_keys`。

- tables每项严格`name, columns, rows`，涵盖三表、真实列顺序与记录数，不用虚构空表；indexes为三PK自动索引名；triggers为三个历史保护触发器名；foreign_keys每项`table, definition`，definition为实际foreign_key_list的8列描述。
- schema_sha256使用固定profile的规范JSON描述，顶层精确为`user_version, objects, tables, triggers`：按(type,name)排序objects；tables按表名取冻结profile的columns(table_xinfo)/foreign_keys/indexes(index_list+index_xinfo)，**摘要输入去掉tables各项的ddl**；triggers按名保留SQL，使用空白折叠。JSON使用sort_keys、UTF-8、ensure_ascii=False和紧凑分隔，不含样本计数/路径。表DDL仍在冻结profile中，预检必须独立比对，不能因不进入摘要而忽略CHECK/COLLATE等约束。**schema hash不是执行SQL许可**，同时比对可信DDL/profile，拒绝未知对象/约束/列/索引/视图/触发器。
- 当前样本schema hash为`babc3a8d5fe36b6cca4af8b639db17529f5d3d6e2b2711a9623e31f281948bf2`；依据为仓库冻结schema-v1.json。新模式需要新profile/明确升级，不悄悄重算一个未知schema后接受。
- counts.projects每项：`project_id, revision, chapters, characters, chapter_outlines, entity_versions, project_snapshots`。entity_versions指该项目**最新document内唯一版本记录数**；不把多条整书历史里反复出现的同一版本重复累计。历史实体联合集/出现次数作为审计报告补充，不混入该count。跨项目相同字符串ID仍是两份身份。
- 范围真实性除包内ID核对，还须writer从被冻结源比较选入/排除集。reader能验证包自身范围与结构，无法仅凭包证明源库没有被作者主动排除数据。

exclusions固定值见示例：provider_configuration_and_credentials、environment_variables、session_tokens、browser_session_selection、in_memory_drafts、unsent_requests、in_memory_activity、program_files_and_executable_extensions。整份DPAPI配置不进包；既不导出api_key，也不以“只读安全元数据”为理由解密配置。V1无provider附件/模型检查历史。

可选preferences.json：`{"preferences_version":1,"values":{...}}`，values精确七项。theme=dark/light；navigation/left/right/bottom为bool；leftWidth为有限数值180–340，rightWidth为220–380。禁用未知键、正文、需求、token、密钥、来源路径；未来偏好版本拒绝。来自作者选择的页面白名单数据，不扫描浏览器用户资料目录。

## 3. 完整性、未知与未来格式

预检顺序（B计划）：

1. 检查ZIP成员名/类型/数量/压缩标志和限额；严格读取manifest；识别format和backup_format_version。没有完整清单则不是完整包，不尝试猜格式修复。
2. 按固定成员流式解包，累计实际展开字节，核对声明bytes和SHA256、ZIP CRC；SHA256只检查字节完整性，**不能认证来源或抵御重算清单的恶意包**。
3. 先只读SQLite，设置query_only与可信schema限制，不实例化SQLiteRepository/SkillLibrary。核对完整schema/user_version、integrity_check和foreign_key_check；不得加载扩展、ATTACH或执行包内DDL/trigger。
4. 严格解析全部payload/files_json，检查持久字段、类型、UTC时间、SQL/JSON元信息、全部revision、最新快照、不可变版本前缀、所有历史引用和Skills主路径/原文规则。计数及scope从快照复算。重算hash仍含非法章节引用的包必须拒绝。
5. 建立恢复/冲突计划并显示结果。只有预检全部通过才写目标，随后磁盘重开再校验。失败不是“部分导入成功”。

读未知SQLite时先用schema/profile白名单核对对象；只接受已支持的当前三表，不运行不可信schema SQL。恢复构造目标使用应用内可信DDL，不把“integrity_check=ok”当成可执行不可信SQL的理由。

严格拒绝：backup格式未来版、user_version未来版或0、workspace/schema未来版、缺字段/未知字段/表、重复JSON键、非法常量、未知source、额外包附件、未知profile、损坏SQLite及结构/语义矛盾。返回阶段+字段路径+记录ID，不回显正文/凭据/原始SQL错误中的私有内容。保留输入文件，不自动降级、升级或抹掉未知数据。

旧小说JSON、旧工作区JSON、旧SQLite是独立兼容导入路径（C计划），不能伪装成V1完整包。允许的旧格式默认补值需逐项报告，保留原输入，不补假整书历史；未来格式仍拒绝。

## 4. 一致性采集与WAL边界

采用SQLite在线备份能力，后续使用Python Connection.backup的分步/进度边界；禁止运行中裸复制主.sqlite3或依赖恰巧没有WAL。SQLite在线备份以SQLite连接取得一致内容，其他连接写入可能使分步备份重启；所有manifest计数/hash只从成功完成的冻结结果取得，不能混入之后源库的count。

源模式不被改变，不发强制checkpoint、不删WAL/SHM、不停止作者写作来冒充并发测试。B必须比较三种情况：无WAL、存在未checkpoint已提交WAL、存在未提交事务；已提交状态完整且内部一致，未提交文字不能进入包。持续写入导致无法完成时应有可取消/有界重试与明确失败，不能无限卡住或发布半快照。

备份步骤：确认scope/保存提示→在受控新位置采集→关闭并只读核验→需要选择性范围时用可信DDL重建→从最终快照生成manifest→同目标卷临时ZIP写完/flush/fsync/校验→**无覆盖发布新文件**。SQLite采集失败、ZIP写失败、取消或发布冲突都不出现成功文件，原库和已有备份不变；只清理本次明确拥有的暂存文件。

本轮WAL样本验证的是“仅主文件不完整”的反例，没有调用正式备份器或验收包级WAL一致性。官方行为依据列在末尾；B仍须实际验证本环境。

## 5. 恢复目的地与冲突

| 场景 | V1拟定行为 | 保留/失败边界 |
|---|---|---|
| 恢复到新目录 | 默认整库保真恢复；ID、revision、全部时间、正文/资料、列表顺序、实体版本/整书快照/Skills全保留 | 在同卷受控暂存目录用可信DDL重建、重开校验，再发布到不存在的目标。已有目录/文件或发布时新出现目标均拒绝，不热替换8765的原库 |
| 恢复到已有小说库 | 默认把选定源项目恢复为**新项目**，全历史一次映射；Skills单列范围/冲突报告 | 同连接、单BEGIN IMMEDIATE，锁内复查所有冲突，一次提交全部项目/历史/Skills；任一失败全部回滚，原项目不变 |
| 指定已有项目作为覆盖目标 | V1拒绝覆盖/拼接已有revision链，提示恢复为新项目 | 不以REPLACE、清空快照、自动版本追加或标题匹配绕过历史保护。未来覆盖模式需要单独契约及授权 |
| 同名不同ID项目 | 名称不作为键，允许同时存在；预览显示目标ID和导入副本身份 | 默认保留原标题，包括全部历史标题；不为消歧静默改旧历史或当前标题 |
| 同项目ID/实体ID冲突 | 新项目模式改项目和全历史身份；映射后的任何未解释碰撞拒绝 | 不按名称合并、不同书相同字符串不共享实体，锁内仍需复查 |
| Skills同ID、全六列及文件顺序/原文相同 | 显示复用该既有全局记录，不再创建 | 所有字段包含时间也必须相同，不能仅凭名称/content判同 |
| Skills同ID、任一持久字段不同 | 给源记录新稳定映射ID，完整保留两份，报告冲突 | 新映射ID也有冲突则拒绝或仅在明确新副本计划中重新分配，不覆盖旧记录 |
| Skills不同ID同名/同内容 | 保留两个独立记录 | 不按名称/hash自动去重，符合现有“每次导入独立记录”语义 |
| 重复普通Skills导入 | 仍由既有import_files创建新记录 | 与备份恢复的重复包处理区分，不改当前业务 |
| 同包重复恢复到同一新目录 | 已有目标拒绝，原结果保留 | 不自动生成另一目录，也不宣称覆盖恢复成功 |
| 同包重复导入已有库 | 见下文确定性映射；全部目标内容相同才报告已存在并跳过 | 已编辑或部分冲突拒绝自动覆盖；显式“另建副本”才使用新的副本身份 |

### 5.1 全历史ID映射

先遍历选定项目的当前及全部整书历史，收集身份与引用：源项目作用域+实体类型+原ID；版本记录单独type=version，Skills独立全局作用域。历史独有实体也必须收集，不能只遍历当前章/当前人物。

拟定映射为`uuid5(NAMESPACE_URL, JSON紧凑UTF-8(["ai-novel-writer/import/1", identity_token, source_project_id, kind, old_id]))`；kind包括project/book_outline/chapter_outline/character/chapter/version。默认identity_token=backup_id；显式“另建副本”生成新的规范UUID copy_id，并使用identity_token=copy_id。同一计划重试保持该identity_token，不重新生成。映射报告同时保留来源backup_id和本次identity_token，同一身份跨历史使用同一值。这只是**方案及测试样本示例**，没有应用导入实现。

修改白名单：SQL项目键/快照归属、project.id、各实体id/project_id、版本id/project_id/entity_id/previous_version_id、chapter.current_version_id、snapshot身份/嵌套引用、分卷chapter_ids、细纲chapter_id/character_ids/场景character_ids、人物关系target_character_id、IDEA键。禁止全局字符串替换；正文/大纲文本/goals/key_events/change_note/Skills原文中恰好出现旧ID也保持。

不同源项目同一个old_id不得映成同一对象。历史中的同项目同ID跨类型复用/身份歧义在预检中报告并拒绝，不能被一个old_id字典吞掉。映射完成后运行完整关联校验，并按逆映射逐字段对照；除了获准的ID及引用，无其他内容/时间/顺序改变。

Skills非冲突ID保留，同ID冲突使用相同结构的全局kind=skill、scope=global稳定映射；复查映射ID存在且全字段相同可复用，否则拒绝。Skills没有项目外键，不为它增加虚构的章节关联。

### 5.2 重复包与提交不确定

不新建尚未需要的导入账本表。默认映射在同backup_id下稳定，可找到同包先前目标。**不能只凭backup_id或UUID5推断已经导入**：先分类选定项目的映射目标，全部不存在是首次导入，全部项目/历史/元数据相同是重试，部分存在、已编辑或不同则冲突，不能自动删改/补半批。全局Skills单独分类和锁内复查；首次导入之前已有可复用Skills是合法状态，不能误判成项目批次已导入一半。项目与Skills都完整匹配才报告整批已存在并跳过。

零项目的完整库不能按“项目全部匹配”空集推断已导入：没有Skills时报告“有效空库，无数据变更”；仅Skills时逐条执行复用/冲突映射计划，可复用与待新增记录混合是合法状态，一次事务插入所有待新增Skills。全部计划目标已存在且全字段相同才跳过；任何稳定映射目标不同则冲突拒绝。仍不把这些全局资料伪装成项目或补造整书历史。

不同包ID即使内容相同也不按内容去重新小说；可在预览提示，作者明确选复用/跳过或另建副本。新副本与重试身份分开。随机copy_id计划在提交前必须以可恢复方式留存：库外受控操作凭据，仅含backup_id、identity_token、scope和目标ID，不含正文/密钥，并交给调用方用于重试；这属于C实现的操作恢复机制，不是新增业务表或包成员。预览内存不能代替留存。COMMIT后进程退出/响应丢失时先恢复该计划，再查完整目标记录；若操作凭据无法恢复则报告“提交状态待确认”，禁止自动生成新copy_id重试。B/C须实测留存写入失败、凭据损坏及提交后响应丢失。

任一项目冲突默认整个选定批次回滚/不写入。作者显式取消冲突项目后是**新的选择性导入计划**，重新预检和锁内复查，不能后台静默缩小范围。共享Skills复用仍全局共享，但项目正文/历史必须独立；后续编辑不能影响源项目。

### 5.3 SQL与偏好的事务边界

恢复不得调用ordinary create/save/import_files：它们会重设revision/时间、追加假历史或生成新Skills身份。专用恢复路径在目标用明确列名参数INSERT，保持三条历史触发器；已有库整批同连接事务，失败回滚全部业务数据。

数据库提交与localStorage偏好不是一个事务。先完成DB及验证，再由作者决定是否应用可选偏好；分别报告“数据恢复成功/偏好未应用或失败”，不覆盖已有设置来假装整体原子。新目录发布与已有库事务分别验收，禁止以HTTP200/toast代替磁盘重开结果。

## 6. 资源、IO与错误计划

初始防护建议：最多3个ZIP成员；manifest≤1MiB、preferences≤16KiB；snapshot≤8GiB；总展开≤8GiB+1MiB+16KiB。限制是初始工程策略，尚未经百万字长期历史样本验证；调策略不能掩盖损坏，也不能宣称8GiB足够所有小说。超过限制明确拒绝、不截断、不删历史；后续规模证据确定默认值。

逐块累计真实展开字节，同时校验ZIP声明大小与manifest.bytes，防止假大小/压缩炸弹。高压缩比本身不是拒绝理由，整书历史自然有大量重复；单文件和总字节硬上限、成员数与有界流式IO共同限额。计数、JSON递归深度/单记录上限及总时限将在B的合法规模样本基础上确定，不把本轮小样本当上限验收。

磁盘预估需区分源卷、目标卷、解包卷：采集快照S、临时包Z、重建目标T及报告/预留。采集/打包最坏同时需要S+Z；恢复最坏同时需要S+T；按各卷实际分配求和，预留建议max(64MiB,估算占用的5%)。压缩大小不能精确预知，给保守上界并在写入过程中复查；预检free space不是并发占用保证，SQLite FULL/ENOSPC/short write/flush/fsync/rename失败均必须无成功发布/无目标半项目。

同卷暂存后无覆盖发布，不能仅exists预检后用replace覆盖突然出现的目标；Windows平台发布原语/目录ACL/TOCTOU竞争须实测。只清理本操作持有的确定暂存路径，输入包、源库、已有目标/备份保留。取消/进程中断留下的孤立暂存恢复政策需先辨认归属，不按通配符删除作者文件。

现有HTTP仅12MiB整块JSON、全局短操作busy，不能直接承担大SQLite/ZIP。B需要受控二进制流式上传/下载或桌面受控文件交接、大小和取消边界；不开放任意文件读写接口，不把提高MAX_BODY当完整方案。保持127.0.0.1、Host/Origin/token/CSP及外部模型关闭。

## 7. 待验收与未确定事项

确定设计：文件名、包/数据版本独立、精确持久范围、严格未知拒绝、密钥配置整体排除、全部历史及时间保真、引用时点、全历史作用域映射、默认新项目、冲突/重复包计划、单事务与偏好分开、失败不发布和原数据保留。

仍需B/C真实证据：包往返、WAL捕获、不断写入时结束/取消、重算hash后的语义拒绝、磁盘/事务/发布故障、8GiB及深度/时间策略、跨卷/Windows无覆盖发布、正式库未知结构复核、旧JSON兼容、实际重复导入与冲突回滚。A测试只验证虚构样本的设计oracle、当前schema与现有解析/存储行为，不替代这些实现验收。

作者验收S2-A后才可另行开始B；首批B先整库备份/空新目录恢复及严格预检，已有库新项目迁移/重复冲突和旧JSON兼容归后续C。偏好/选择性包是V1已描述的可选能力，未实现时必须拒绝或显示未支持，不能默默放宽scope。S2全部完成还包括性能、草稿恢复、章节归档/重排等后续任务。

官方技术依据（原文仅作能力依据，实际验收仍需本项目测试）：

- SQLite Online Backup API：`https://www.sqlite.org/backup.html`
- SQLite WAL：`https://www.sqlite.org/wal.html`
- Python 3.12 sqlite3 Connection.backup：`https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup`
# 2026-10-15 当前状态补充

本文仍是A批格式/迁移契约。B完整包与独立新目录语义保持；C已有新项目/全历史/Skills/旧JSON及可恢复预检计划实现，专项与界面通过，完整core尚未收口，见[S2-C当前交付](s2-c-migration.md)。业务支持选择性项目/Skills范围，当前界面提供整来源及当前小说复制；选择性备份包创建仍未实现，不能以本条宣称A全部计划已验收。

