# S2-A：持久化数据清单与关联规则

后续状态（2026-10-14）：作者已另行授权S2-B，完整库V1包/严格预检/独立新目录恢复及生产历史校验已实现，实际结果见[S2-B交付](s2-b-acceptance.md)。B只支持完整库、全部Skills和偏好排除，选择性/偏好/已有库/旧JSON迁移明确未支持。以下A/较早轮次的“未实现、未执行”保持当时证据；B当前测试状态以新交付为准，不改写A旧证据，C仍未开始。

日期：2026-10-14（Asia/Shanghai）。状态：数据审计及虚构样本验证完成，设计待作者验收。本轮未实现正式备份、恢复、迁移或生产校验修复，未进入 S2-B。

本轮从实际 repository 建立独立虚构 SQLite，查询 `sqlite_master`、`table_xinfo`、`index_list/index_xinfo`、`foreign_key_list`；全字段样本落盘重开。三表的 DDL/字段与2026-10-13已留存的脱敏结构证据一致。**本轮没有打开正式数据库、读取正式小说或查询8765**；不把旧结构记录当作今天正式库重新检查结果。生产源码全部保持不变。

交付关联：[包格式与恢复设计](s2-a-backup-format.md)、[测试矩阵与证据](s2-a-test-matrix.md)、[虚构 manifest 示例](s2-a-manifest.example.json)。历史总计划见 [current-state-and-s2-plan.md](current-state-and-s2-plan.md)。

## 1. SQL 结构：已核实

完整机器清单是 [schema-v1.json](../tests/fixtures/s2_a/schema-v1.json)，包括原始DDL、全部列与隐藏列标志、索引列/排序/排序规则、外键和触发器。

| 表 | 列（按实际声明顺序） | 主键/空值约束 | 备份与恢复设计 |
|---|---|---|---|
| `projects` | `id TEXT`、`title TEXT`、`revision INTEGER`、`payload TEXT`、`updated_at TEXT` | `id`主键；其他四列NOT NULL。SQLite的此TEXT主键未显式NOT NULL，`table_xinfo`标志为0 | 一致快照保留五列。新目录保真INSERT；已有库新项目导入同时映射SQL id和payload内ID；保留revision、标题和SQL更新时间 |
| `project_snapshots` | `project_id TEXT`、`revision INTEGER`、`payload TEXT`、`saved_at TEXT` | 复合主键`(project_id, revision)`；四列NOT NULL | 必须逐条保留全部整书历史；按revision顺序INSERT，保留saved_at、payload和稳定映射。不能只备份最新一条 |
| `skills` | `id TEXT`、`name TEXT`、`description TEXT`、`imported_at TEXT`、`primary_path TEXT`、`files_json TEXT` | `id`主键未显式NOT NULL；其余五列NOT NULL | 全局独立资料库，保留全部六列、文件列表顺序和原文；恢复不用普通导入函数重新生成ID/时间/元信息 |

不存在独立的章节、人物、大纲、世界观、版本、记忆、AI任务、候选、模型用量或导入账本表。前三类与版本在payload；世界观/规则在工作区。未来模块没有持久数据，不能虚构进备份清单。

| 结构对象 | 实际内容 | 恢复/预检要求 |
|---|---|---|
| 索引 | `sqlite_autoindex_projects_1(id)`、`sqlite_autoindex_project_snapshots_1(project_id,revision)`、`sqlite_autoindex_skills_1(id)` | 均为非partial、unique的PK自动索引，键升序、BINARY；xinfo还含非键rowid辅助项。没有手写索引/FTS索引。可信DDL重新生成并核对 |
| 外键 | `project_snapshots.project_id → projects.id` | `ON UPDATE/DELETE NO ACTION`、`MATCH NONE`，无延迟或级联声明。导入连接显式`foreign_keys=ON`，插项目后插快照，结束执行foreign_key_check |
| 触发器 | `snapshots_no_update`、`snapshots_no_delete`、`snapshots_no_replace` | 拒绝改写/删除及同项目同revision的重复插入；可信DDL创建、恢复后实测，不执行包提供的SQL，不关闭历史保护 |
| 数据库版本 | `PRAGMA user_version=1` | 与workspace/document/包版本分别检查。当前构造器接受0或1并写1；包预检不得调用它来把未知库“修正”为1 |
| 连接设置 | repository连接使用`foreign_keys=ON`、`synchronous=FULL`、10s timeout；Skills连接只设置FULL | 这些是连接行为，不等于全部是库内字段；合并恢复须同连接同事务，并显式开启外键 |
| 物理文件 | rowid、空闲页、journal/WAL/SHM、SQLite头 | 快照采集由SQLite完成；包不带活动WAL/SHM/journal。保真逻辑恢复不保证rowid、空闲页或数据库二进制hash与源相同，业务没有rowid引用 |

DDL还缺revision正数、payload JSON合法性、SQL元信息和语义引用的CHECK；因此通过SQLite完整性或外键检查不足以证明小说数据有效。预检另拒绝NULL/空ID、错误SQL类型、revision<1及损坏/未知payload。

## 2. 工作区与小说全字段：已核实

以下每一项都必须同时覆盖`projects.payload`及每条`project_snapshots.payload`。普通整库恢复保留原SQL TEXT；ID转换时只重序列化结构，字符串内容逐字段原样保留。不trim正文、不规范化换行/BOM、不按名字去重或排序列表。

| 层 | 精确字段集合 | 备份位置和恢复方式 |
|---|---|---|
| 工作区 | `workspace_version, revision, document, ideas, worldbuilding, writing_rules` | 两类payload全字段保留；当前版本1，完整包不能缺字段后再补默认值 |
| 小说文档 | `schema_version, project, book_outline, chapter_outlines, characters, chapters, versions` | 当前和每个整书状态均保留；schema_version=1；book_outline允许null |
| 所有Entity继承字段 | `id, created_at, updated_at` | 项目/大纲/人物/细纲/章节保留，UTC时间原样 |
| 所有ProjectEntity额外字段 | `project_id` | 大纲/人物/细纲/章节归属一致；复制按源项目映射 |
| NovelProject其余字段 | `title, author, genre, summary, language, status` | 包括作者、语言、项目状态；标题不是ID，同名允许 |
| BookOutline其余字段 | `theme, premise, main_plot, ending, key_events, volumes, status` | key_events为文本列表，volumes全保留；业务只编辑四个文本字段不能成为丢弃其他字段的理由 |
| VolumePlan | `number, title, summary, chapter_ids` | 分卷没有独立ID；保持number与列表顺序，仅转换chapter_ids |
| Character其余字段 | `name, role, personality, background, goals, notes, relationships` | goals、relationships虽无完整编辑入口仍持久化 |
| CharacterRelationship | `target_character_id, relation, description` | 关系没有独立ID；仅目标人物ID转换，其余文本保留 |
| ChapterOutline其余字段 | `chapter_id, core_idea, objective, character_ids, scenes, story_time, status` | 不丢角色和场景，关联跟随章节/人物ID |
| ScenePlan | `order, summary, character_ids, location, story_time` | 没有独立ID；order保留；story_time是虚构时间文本，不能套UTC时间规则 |
| Chapter其余字段 | `number, title, content, status, current_version_id` | 草稿/确认状态、正文、顺序与当前版本指针全部保留 |
| VersionRecord | `project_id, entity_type, entity_id, version_number, snapshot, id, created_at, previous_version_id, change_note, source` | 五类entity_type均支持；当前source只允许manual；不删旧版、不改来源，不只备份正文版本 |
| VersionRecord.snapshot | 对应project/book_outline/chapter_outline/character/chapter的完整实体字段 | 唯一例外：**章节snapshot不含current_version_id**，避免循环指针。其他嵌套内容仍完整；快照中的身份/引用也必须映射 |
| IDEA | `ideas`：章节ID→字符串 | 转换键，原文值不变。无独立IDEA版本表，由整书快照追溯 |
| 世界观/规则 | `worldbuilding, writing_rules`两个字符串 | 地点、组织、力量体系或文风目前均为自由文本；由整书快照追溯，不补造结构化对象或实体版本 |
| Skills文件列表 | `files_json`：有序列表，每项严格`path, content` | 相对Markdown路径、主文件定位、原文/BOM/CRLF/空行/空格和列表顺序保留；不把MD里的命令或HTML当程序执行 |

当前状态枚举：project=`planning/writing/completed/archived`；outline=`draft/ready`；chapter=`draft/confirmed`；entity_type=`project/book_outline/chapter_outline/character/chapter`。未知枚举或未来字段不能按现有格式忽略。

## 3. 库外持久状态与排除项

| 状态 | 实际所在位置 | 备份/恢复规则与范围 |
|---|---|---|
| API配置及密钥 | 仓库外`%LOCALAPPDATA%/AI-Novel-Writer/providers.dpapi`，整份DPAPI加密配置；路径可由环境变量覆盖 | **整份排除，不读取/解密**。地址、model_id、api_key、last_test混存，V1不尝试抽取模型配置。新机/恢复后独立重新配置，旧检查结果不冒充新机验证 |
| 环境密钥及运行环境 | DEEPSEEK_API_KEY/GEMINI_API_KEY等进程环境 | 排除，不枚举或读取值；不拷贝.env、认证头、全环境、用户系统目录或凭据文件 |
| 浏览器UI偏好 | localStorage的`novel-ui` | 可选`preferences.json`附件，仅7项：theme、navigation、left、right、bottom、leftWidth、rightWidth；默认排除，需作者选入并由页面提供白名单值。恢复单独应用并报告，失败不撤销已成功的数据库恢复 |
| 当前项目选择 | sessionStorage的`novel-project` | 浏览器会话状态，排除；恢复后由作者重新选，不能携带未映射的旧项目ID |
| 会话token | LocalServer随机token及前端内存 | 排除，重启重新生成，不作为数据迁移对象 |
| 正文/资料草稿、未发送需求/引用 | DraftStore/PromptStore及页面变量，仅内存 | 当前没有磁盘持久化，不属于本包可恢复数据。备份前显示保存提示，不能声称备份能恢复未提交文字；S2-06另行解决 |
| 当前窗口活动、焦点/查找/选区/临时标签状态 | 当前页面内存 | 排除，无对应数据库表或可靠磁盘恢复 |
| Skills原始来源文件夹 | 作者自行选择的外部文件 | 只备份已导入SQLite的Markdown原文；源绝对路径未持久化。未导入资料不扫描；可后续明确导出到新目录，不覆盖来源 |
| 程序文件、Python/插件/示例/报告 | 项目、运行时和用户文件目录 | 不属于小说备份。包不含可执行附件；诊断/导入报告独立导出，不创建未核实的持久表 |

“完整库”指全部已保存业务三表及其历史；偏好是否选入单列。库外凭据故意排除，内存草稿并非已持久数据。不能称完整机器镜像或带密钥迁移。原文若由作者主动粘贴了敏感字符串，结构性排除并不能证明文本不含秘密；不读取真实密钥做比对、不静默删改原文，分享备份前的内容审阅另由作者决定。

## 4. 完整关联与历史校验规则

### 4.1 解析与SQL对照

1. 包内所有JSON严格UTF-8，无BOM、重复键、NaN/Infinity、错误根类型；完整持久字段必须在转换器运行前检查，未知字段拒绝。正文/Skills字符串内部的BOM与空白照常保留。
2. SQL项目ID/title/revision与payload的project.id/title/revision一致；project_snapshots行ID/revision与自己的payload一致。每项目整书revision连续`1..projects.revision`；最新快照payload等于当前payload，最新saved_at等于SQL projects.updated_at。
3. 每个当前及整书状态完整校验类型/枚举/稳定非空字符串ID/UTC时间/归属。ID不要求UUID；SQL主键不是充分的非空检查。每个document内项目、实体、版本记录ID不得重复；不同项目可重复使用同一字符串，Skills独立全局命名空间。
4. 相邻整书状态的versions列表必须是不可变前缀，不改旧version的任何字段、snapshot或位置；版本新增可为0。SQL saved_at及实体/版本created_at、updated_at按真实字段含义核验，不把小说story_time当系统时间。

时间差异必须保留：SQL projects.updated_at与同次snapshot.saved_at相等；document.project.updated_at由业务层独立产生，不要求三者相等；保存IDEA/世界观/规则会更新项目时间和整书revision，却不会自动追加project实体版本。

### 4.2 引用矩阵

| 来源字段（当前与所有整书历史） | 目标与约束 |
|---|---|
| SQL `project_snapshots.project_id`及各ProjectEntity.project_id、VersionRecord.project_id | 对应项目，必须与其payload项目身份一致 |
| `book_outline.volumes[].chapter_ids[]` | 本项目相应状态中的章节；卷number为正且唯一，同章不能在卷内/跨卷重复分配 |
| `characters[].relationships[].target_character_id` | 本项目相应状态中的人物；不能用另一项目同名/同ID人物补齐 |
| `chapter_outlines[].chapter_id` | 存在的章节，每章最多一个当前细纲 |
| `chapter_outlines[].character_ids[]`、`scenes[].character_ids[]` | 相应状态中的人物；场景order为正且不重复 |
| `ideas`的每个键 | 相应状态中的章节，值严格为原文字符串 |
| `versions[].entity_id` | 根据entity_type寻找本项目目标；version.snapshot.id等于entity_id，非project快照project_id等于所属项目 |
| `versions[].previous_version_id` | 同项目、同entity_type、同entity_id、版本号恰好减1；首版为null；不存在断链、分叉或时间逆序 |
| `chapters[].current_version_id` | 若非null，必须指向同章正文版本；confirmed不可为null。v1没有强制指向最大版本号或要求当前正文等于该snapshot，不擅自加强为“旧数据已违反”的规则 |
| `versions[].snapshot`中的分卷/人物关系/细纲/场景引用 | 同样执行以上语义规则，在该version的首个可核对整书上下文验证，不能只检查结构和类型 |
| `skills.primary_path` | files_json内唯一SKILL.md的精确path；安全相对.md路径、不区分大小写重复、同目录限制、100文件/2MiB的现有约束须保留 |

历史语义还检查snapshot内title/name非空、章节/卷/场景number/order合法、重复分卷章节。章节历史顺序允许与当前章节顺序不同；正文恢复业务原本就保留当前顺序。

### 4.3 时点与可验证边界

遍历整书历史，从某version第一次出现的revision取该时点的章节/人物集合。每个旧version后续保持不变，只在首现上下文验证其外部引用；当前及每个历史document的当前实体仍按自身状态验证。

**非法章节引用必须拒绝**，包括不存在、错项目和只在未来revision才出现的章节。全历史ID联合集合只用于完整映射，不能作为历史引用合法性集合。样本已验证：历史存在而当前消失的无版本章节可保留；未来才出现的章节不能修补早期悬空引用。

revision1可能一次存入带多版实体历史的旧小说文档，此时没有更早整书证据。只按首个现存上下文检查，不宣称重建原始保存时点；若引用对象在所有可核对上下文中都缺失，拒绝并报告“历史关联缺失/上下文不足”，不创造假对象或删除版本。

### 4.4 已确认的生产缺口

- models当前实体引用检查完整于现有范围；version.snapshot只做完整字段/递归类型、归属、时间和版本链，遗漏上述嵌套关联与部分语义。虚构坏样本被当前validate_workspace接受，但被**测试专用设计oracle**拒绝。本轮没有修复生产校验器。
- 小说`document_from_json`已拒绝重复键/非法常量；缺口在repository及HTTP/Skills的普通json.loads路径。不能笼统称小说JSON解析器全部不严格。
- 普通document转换器会用默认值补缺失字段，包括新ID/时间；完整包预检不能用它掩盖遗漏。旧JSON兼容规范化须另报告。
- get只取当前payload，未提供SQL元信息/全部整书历史的一致性审计。完整包需要独立全库预检，不能仅调用get。

## 5. 已有导入导出能力：已核实

| 入口 | 当前真实行为 | 完整恢复中怎样处理 |
|---|---|---|
| GET `/api/projects/{id}/export` | 返回service.get当前工作区，带document.versions；无全部project_snapshots和独立Skills | 识别为“旧工作区JSON”，明确损失范围，不能称完整备份 |
| `read_document/document_from_json` | 读schema_version=1小说JSON、严格解析、领域转换；没有小说导入HTTP业务 | 后续C批兼容导入，缺IDEA/世界观/规则/SQL历史/Skills应报告，不造原历史 |
| repository.create/save | 重设revision或追加revision与snapshot，生成SQL保存时间 | 不用于保真恢复；可信恢复INSERT全部已核验行、元数据不变 |
| POST `/api/skills/import` / SkillLibrary.import_files | 验证Markdown、提取元信息，每次生成新ID/时间；重复导入保留独立记录 | 恢复保留原记录ID、元信息、时间和文件列表，冲突按设计处理，不能重新走普通导入 |
| 备份/恢复/项目迁移路由 | 尚不存在 | 仅为后续B/C计划。本轮没有添加API、页面、CLI正式功能或数据库迁移 |

主要代码证据：`domain/models.py:34–141,225–318`；`storage/sqlite_repository.py:17–133`；`storage/skills_repository.py:9–61`；`storage/json_codec.py:24–104`；`application/versions.py:11–43`；`service.py:37–66`；`skill_import.py:21–113`；`ui/server.py:97–102,146–150`；`ui/static/layout.js:1–18`及app.js的sessionStorage。

## 6. 本轮核实边界

已核实：当前源码DDL的全部三表/15列/三索引/一外键/三触发器、各层持久字段、两种历史、五类实体版本、导入导出损失范围、历史校验缺口、作用域映射、Markdown原文与WAL反例。

仍待后续证据：正式库自上次结构审计以来是否被手工扩展（本轮不打开）；真实备份/恢复往返及损坏/磁盘故障/并发/失败回滚；大规模资源限额和性能；Windows发布时无覆盖竞争；未来模型source/新schema兼容；生产严格校验修复。B开始前须在其授权范围内复核实际源库schema并拒绝未知数据，不能据本轮虚构库直接操作正式小说。
# 2026-10-15 当前状态补充

本文保留A批冻结清单与历史证据。C已按此清单实现迁移/复制及旧JSON，专项与受影响界面通过，但完整core有B错误分类、强杀夹具环境和runner路径阻碍，尚未收口或作者验收。当前以[S2-C统一交付](s2-c-migration.md)为准；不改写A样本或历史数字。

