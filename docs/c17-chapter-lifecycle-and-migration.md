# C17 章节生命周期与 TXT/MD 迁移｜2026-10-20

## 当前 V27 补齐（下文旧批次记录保留）

已新增跨卷移动、卷内位置和真实拖拽；移动不改正文及版本。回收站先预览引用影响，精确标题与引用确认后隐藏章节，保留正文/细纲/IDEA/版本和历史，恢复原卷与顺序。回收站与归档章节均排除活跃树、选择器、上下文、相关记忆检索和全书导出；C07 隐藏引用显示受阻。V27 完整备份、独立恢复和复制保留回收站/跨卷操作并映射 ID，V1–V27 兼容；旧 V19 操作仍沿原首次写升级语义。

编码 auto 已改为严格 UTF-8/BOM 优先，失败再严格 GB18030，均失败拒绝；支持手工覆盖重做预览，不 replace/ignore 坏字节。原章号在重排前保存，无卷恢复按原章号插回。

新证据 `%LOCALAPPDATA%\AI-Novel-Writer-review\c17-v27-20261020`：`run-02-lifecycle-migration.log` 75 项通过；`ui-04/v27-ui-report.json` 六项通过（GB18030 文件 UI、真实 DragEvent 跨卷、重开、回收影响/确认、隐藏及导出排除、恢复原卷顺序），providerCalls=0、errors/external 为空。ui-01 至 ui-03 和早期失败保留，不能列为通过。最终打包版实际文件下载和恢复后继续写作见 C18 最新记录。

已接通章节重排、软归档/恢复、TXT/Markdown 分章导入预览与追加导入、章/卷/全书导出。所有写操作沿用既有 revision 原子事务；不新增网络调用。

## 重排

- `move_chapter` 只接受 `up`/`down` 与 `confirmed:true`，只与相邻的**未归档**章节交换章号；归档章不参与可见排序。
- 交换后每个分卷的 `chapter_ids` 按当前章号重排；正文、IDEA、ChapterOutline、版本记录、人物与任务历史不改，不新增正文版本。
- 保存编号变化抛 `ConflictError`；到边界、未确认、归档章节尝试排序均拒绝。

## 归档与恢复

- V19 新增 append-only `chapter_lifecycle_events`（`archive`/`restore`），不删除正文、版本、细纲、IDEA、记忆或任务历史，不改 `Chapter` 持久字段。
- 归档章默认从章节树、章节选择器、上下文预览和导出选择中隐藏；归档详情区可直接恢复。
- 新任务目标在 `TaskCoordinator` 与 C04-A/B1/B2 的构建入口统一拒绝 `chapter_lifecycle.archived_target`。归档章仍可读取历史和恢复。
- 删除类操作未实现。

## TXT/MD 导入

- 支持 `.txt`/`.md`，上限 5 MiB、500 章；按行识别 `第X章`、`第X节`、`Chapter N`、一级/二级 Markdown 标题，跳过围栏代码块。标题行本身作为章节标题，章节正文为标题行后到下一标题前的原文切片，不做换行/空白规范化。
- 预览返回每章标题、起始位置、正文起点、字符数、正文与预览；标题可编辑。`preview_sha256` 绑定原始字节、编码与实际范围，提交时重解析并核对范围与正文，标题可改但范围/内容不可替换。
- 编码 `auto` 只接受 UTF-8/UTF-8 BOM；失败明确要求选择 GB18030（或其他明确选项），不猜测乱码。显式 GB18030 严格解码。
- 确认后追加新章节与一个新建分卷，保留已有章；不覆盖、不删除。标题/文件扩展名/大小/编码/映射不一致均拒绝。

## 导出

- `chapter`/`volume`/`book` × `txt`/`md`；只读数据库已保存内容，不含窗口草稿或本地恢复草稿。UI 下载前明确提示草稿不会包含。
- UTF-8，TXT 使用 `第N章 标题`，Markdown 使用 `## 第N章 标题`；分卷 Markdown 增加 `# 卷名`。文件名移除 `\/:*?"<>|` 与控制字符并限长。
- 导出的章标题/正文可重新预览导入；正文往返允许导出器补的一个分隔换行，正文内部 CRLF/emoji 等原字节保持不变。

## 证据

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C17-lifecycle-20261020/`

- `green-unit-20261020T020739Z.log`：7 业务通过（重排、归档/恢复、导入预览/追加/字节、编码/大小/扩展名、导出往返、范围文件名、V19 备份恢复复制）。
- `green-http-20261020T020403Z.log`（原 `red-04-http-...` 实为通过，复制保留）：2 HTTP 通过（预览/提交/导出下载头、重排/归档/非法导入）。
- `green-ui-20261020T021148Z.log` + `ui-20261020T021148Z/chapter-lifecycle-ui.json`：最终源隐藏 Electron 覆盖导入预览→改名→确认→章节出现、上移/下移、归档隐藏→恢复、导出 attachment 响应与 UI 状态。
- `green-affected-writing-20261020T020755Z.log`：C04-A 17 项回归；`green-affected-planning-expansion-20261020T020756Z.log`：B1+B2 23 项回归。
- `green-affected-writing-ui-20261020T020856Z.log`：C04-A 隐藏 UI 回归；其 `stage()` 已改为从仓内 `desktop/.cache/python-3.14.8-embed-amd64.zip` 展开到独立 shell，不再读取冻结 `desktop/.cache/stage`。

失败日志保留：`red-01-lifecycle-import-missing.log`、`red-02/03-lifecycle-*`（模块/导出标题）、`red-05..09-ui-*`（导入选择器、数组比较、视图导航、导出 query 被桌面路由拒绝）、`red-11-ui-20261020T021124Z.log`（误命名为 green 的 download 事件超时，已另存 red 副本）。`red-10-ui-*` 实际通过，保留原名；最终源另跑 `green-ui-20261020T021148Z.log`。

## 未验与边界

- Playwright Electron 未提供 download 事件，隐藏 UI 只核对导出 attachment 响应/Content-Disposition/UI 状态；实际操作系统保存落盘未验。
- 未做真实供应商/付费、正式 data/8765、作者预览 profile/stage；未提交推送发布。
- 文件编码仅提供 UTF-8/BOM/GB18030 明确选项；不做其他编码自动猜测。
- 章节删除/危险清理、跨卷拖拽、持久控制台与最终安装包仍属后续。
