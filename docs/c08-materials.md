# C08 本地 TXT/Markdown 资料库与字面索引｜2026-10-20

2026-10-21 隔离副本增量：新增明确选择的 Unicode/BM25/短语字面混合检索、可追溯标签建议、可取消增量窗口索引及精确引文的发送/采纳守卫。准确能力、建议 V44 和未测边界见 [后续交付](c08-hybrid-retrieval.md)。本文下方仍保留 2026-10-20 的历史实现及证据，不代表主仓已经整合新功能。

本轮补齐通用本地资料库：作者可创建、更新、归档和恢复 UTF-8 TXT/Markdown 资料，保留 append-only 版本，并对当前版本建立可显式重建的固定窗口字面索引。索引只用于定位原文，不是语义检索、向量索引或模型摘要；资料不会被自动选入检索结果或创作上下文。

## 数据与版本

- 工作区 V25 新增 `materials`、`material_versions`、`material_chunks` 与 `material_operations`。
- 每份资料有稳定 ID、标题、`txt|md` 格式、最多 20 个标签、归档状态、当前版本与资料 revision；资料不可删除。
- 创建和更新都追加版本，版本号从 1 连续递增，`previous_version_id` 形成不可变版本链；旧版本正文和标题等历史记录保持可读。
- 更新只切换 `current_version_id`，不会覆盖旧版本；归档后禁止更新与重建，但历史仍可读取；恢复不恢复已删除内容，因为没有删除入口。
- 文本只接受 UTF-8（上传时允许 UTF-8 BOM 并去除），拒绝 NUL、除换行/回车/制表外的控制字符、空正文、超过 4,000,000 字符或超过 8 MiB 的文件。
- `operation_id` 用于写操作幂等；同一编号只有在 action、资料和去除 `operation_id`/`expected_revision` 后的语义请求完全一致时才重放。资料 revision 已变化时返回冲突，不静默覆盖。

## 字面索引

- 当前版本按固定 800 字符窗口切分，相邻窗口重叠 120 字符；最后窗口在正文末尾结束。
- 每个窗口保存序号、精确 `[start,end)`、正文 SHA-256 与所属资料版本。重建时只替换该资料派生出的 chunks，不修改版本历史。
- 索引状态为 `missing`（尚无索引）、`stale`（当前版本没有完整索引或仍有旧版本索引）或 `current`（当前版本 chunks 完整且范围/哈希与正文一致）。
- 更新正文后索引变为 `stale`，必须由作者显式重建；检索不会自动重建，也不会用旧 chunks 冒充当前版本。
- `rebuild-all` 只重建启用资料，归档资料列入跳过列表，且不改变正文版本。

## HTTP 入口

- `GET /api/projects/{id}/materials`：列表，默认包含归档资料且启用资料优先；`include_archived=0` 可过滤，`tag` 可筛选。
- `GET /api/projects/{id}/materials/{material_id}`：详情、版本列表和 chunks；不含旧版本正文全文。
- `GET /api/projects/{id}/materials/{material_id}/versions/{version_id}`：只读查看指定旧版本原文、SHA-256 与版本说明。
- `POST /api/projects/{id}/materials`：创建；`text` 与 `data_base64` 二选一。
- `POST /api/projects/{id}/materials/{material_id}/update`：追加版本。
- `POST /api/projects/{id}/materials/{material_id}/archive`、`restore`：显式归档/恢复。
- `POST /api/projects/{id}/materials/{material_id}/rebuild`、`rebuild-all`：显式建立派生索引。
- 所有写入口要求会话令牌、来源校验、`operation_id` 与 `expected_revision`；响应返回写入后的 revision。

## 检索与上下文

- `materials` 已加入本地检索范围，但必须同时提供明确的 `material_ids`；不会按标签、全部资料或自动猜测选中资料。
- 检索前重新读取当前版本，并拒绝不存在、不属于当前书、已归档、索引缺失或索引过期的资料。
- 命中返回资料 ID/标题、版本号与 ID、正文 SHA-256、精确 start/end、snippet、chunk 序号与 chunk 范围；结果明确提示这是固定窗口字面扫描。
- 选入上下文预览时再次核对资料是否存在、是否归档、当前版本/指纹与索引状态；过期、归档或索引失效不进入 `context_text`，只报告排除原因。
- 检索命中不代表相关性或语义相似；没有命中不补造资料，也不调用模型。

## 页面

- 新增“本地资料”标签页：粘贴或上传、标签筛选、列表、详情、更新、版本历史、重建、归档与恢复。
- 资料详情中的更新/重建/归档/恢复按钮与列表处于同一绑定根节点，避免只渲染但不响应的假入口。
- “本地字面检索”增加资料多选；未勾选资料时不能以资料范围发起检索。检索结果可单选/多选后进入只读上下文预览。
- 页面明确说明资料不会自动进入模型上下文；本批没有自动选择、自动摘要或向量召回。

## V25 备份与迁移

- C08 交付时含资料的工作区完整备份格式为 25，备份能力返回 1–25，迁移能力包含 `backup_v25`。C07 已把当前工作区升级到 V26；V26 备份/迁移继续保留 C08 的全部资料、版本、chunks 与操作记录。
- 备份校验要求资料集合、版本链、当前版本、chunks 范围/哈希和操作记录一致；资料版本与操作记录为 append-only。
- 恢复保持原 ID、正文、版本与 chunks；复制迁移映射资料、版本、chunks、操作 ID 与项目/版本引用，并重新指纹化操作请求，不复制跨书所有权。

## 证据

证据根：`C:/Users/Administrator/AppData/Local/AI-Novel-Writer-review/c08-materials-20261020/`。

- C08 定向测试 13 项通过（`green-materials-20261020T053316.log`，`Ran 13 tests ... OK`）。
- Node 资产测试 21 项通过（`green-node-20261020T053122.log`）；最终 `node --check` 对 `materials.js`、`app.js`、`views.js` 均为 0（`green-node-final-20261020T053900.log`）。
- 全量 `python -m unittest discover -s tests -v` 共 713 项，4 failures、8 errors（`red-01-full-python-20261020T052207.log`，`EXIT_CODE=1`）。
- 上述 12 项失败均可在 C08 之前的 C09 源码快照复现：基线定向复跑 23 项为 4 failures、7 errors，另单跑 `test_s3b_retrieval` 为 1 error（`red-02-prec08-baseline-20261020T053650.log`、`red-03-prec08-s3b-20261020T054000.log`），失败签名一致，不归因于 C08。
- 既有失败清单：备份校验 `content_blobs` 的 2 个 schema v1 子测试；S3 规则预算 1 error + 默认预览 legacy 规则 1 failure；S3-B 规则预算 1 error；S4-A 迁移 2 errors；S5-A 迁移 2 errors；S6-B HTTP 1 failure；`test_server` 导出 1 failure + 指南编码断言 1 failure。
- 隐藏 Electron/CDP 页面验证 10 项通过，`status=passed`、`providerCalls=0`、`errors=[]`、`external=[]`（`electron-ui-20261020T052913.log`、`electron-c08-20261020T052913-report.json`、`green-electron-c08-20261020T052913.png`）。
- 未使用真实模型、付费调用、正式 `data/`、8765、作者窗口、凭据或全局设置；未提交、推送、签名或发布。

## 未验与边界

- 未使用真实模型、付费调用、正式 `data/`、8765、作者窗口、凭据或全局设置；未提交、推送、签名或发布。
- 未实现或未验语义检索、向量索引、重排、自动标签、自动增量索引、自动把资料放进创作上下文、跨书检索和真实长篇规模。
- 字面检索区分大小写；标签只用于筛选，不作为检索选择依据。字符预算不是精确 token 数。
- 本机隐藏 Electron/CDP 验证只覆盖开发版入口，不等同于干净 Windows 安装器、系统输入法或大规模性能验收。
