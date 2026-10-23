# C05 分层记忆汇总与冲突交付｜2026-10-20

本轮补齐书/卷两级确定性记忆汇总：只用当前已启用、作者已确认、来源未过期且不晚于所选故事位置的记忆原文，生成可保存、可显式重建的汇总版本。预览不写库、不调用模型；冲突只报告，不自动合并或覆盖。

## 范围与选择规则

- 汇总范围仅支持 `book`（全书）和 `volume`（单卷）。`through_chapter_id` 决定截至故事位置；单卷范围还要求该章属于所选卷。
- 来源必须同时满足：记忆 `active`、`confirmed`、出处未过期、有效故事位置不晚于截至章。有效位置取“声明位置”和“出处章节”中更晚者，避免把未来事实提前纳入。
- `volume_number` 已明确时按记忆自报卷归属过滤；未明确时按有效故事位置所在卷过滤。
- 每条来源冻结 `memory_id`、记忆版本、类型、标题、原文、有效位置章/序号、人物与卷号；汇总正文逐字保留来源原文。
- 来源按有效位置、类型固定顺序、标题、记忆 ID 稳定排序。汇总正文由标题与来源确定生成，不依赖模型或随机数。

## 预览、保存与重建

- `POST /api/projects/{id}/rollups/preview` 只读：返回范围、截至章、来源 ID/快照、确定性正文、当前 revision、已有汇总及其是否过期，以及冲突是否允许保存。
- 同一范围与截至章只允许一条当前汇总。保存必须带 `operation_id` 与预览时的 `expected_revision`；小说 revision 已变化时拒绝。
- 保存走现有 `repository.atomic` 单事务并升级工作区到 V23。相同 `operation_id` 的重放返回原汇总，不新增版本；同编号换范围被拒。
- 记忆增删、编辑、归档或来源正文变化后，列表按当前可选来源重新计算来源快照并显示“来源已变化”。过期不会自动改写汇总。
- 重建必须显式指定汇总 ID、`expected_revision`、`expected_rollup_revision` 和新 `operation_id`；按当前来源生成下一版，追加历史，不覆盖旧历史。
- 汇总不能删除。`memory_rollup_history` 为 append-only，记录创建/重建、版本链、快照、时间与操作编号。

## 冲突报告

当前已启用、已确认、来源未变且位于所选范围内的记忆，若“类型 + 人物 + 卷号 + 有效位置章 + 标题”相同但正文不同，则形成冲突组：

- `GET /api/projects/{id}/rollups/conflicts`
- `GET /api/projects/{id}/rollups` 同时返回 `conflicts`

冲突只返回记忆 ID、版本和正文供作者处理，不自动挑选、合并、改写或删除记忆；存在冲突时保存/重建被阻止。归档或用普通记忆编辑解决差异后，冲突再从派生结果中消失。

## V23 持久化、备份与迁移

- 工作区 V23 新增 `memory_rollups` 与 `memory_rollup_history`；普通保存仍可保持 V22，只有首次保存/重建汇总才升级，避免无关旧测试和旧数据被动升级。
- 校验要求汇总 ID/范围唯一、正文与来源确定性一致、来源版本与不可变 `memory_history` 快照一致、来源顺序稳定、历史版本链连续且 append-only。
- 工作区为 V23 时完整备份格式为 23；备份能力返回 1–23，迁移能力包含 `backup_v23`。V1–V22 读取/恢复/复制保持。
- 复制迁移映射汇总 ID、来源记忆 ID、截至章、人物、位置章和汇总历史 ID，并按映射后的来源重新生成汇总正文及历史快照正文；不保留会指向旧记忆 ID 的陈旧展示文本。

## HTTP 与页面

- `GET /api/projects/{id}/rollups`
- `GET /api/projects/{id}/rollups/conflicts`
- `POST /api/projects/{id}/rollups/preview`
- `POST /api/projects/{id}/rollups`
- `POST /api/projects/{id}/rollups/{rollup_id}/rebuild`

记忆页新增范围/分卷/截至章预览、已保存汇总、来源变化标记、显式重建、冲突报告及跳转记忆按钮。预览不需要操作编号；保存和重建必须显式提交，页面不自动保存、不自动重建、不自动合并。

## 证据（本地虚构库与临时端口，真实费用 0）

证据根：`C:/Users/Administrator/AppData/Local/AI-Novel-Writer-review/c05-20261020/`

- `green-05-c05-unit-final-20261020T041054.log`：C05 共 6 项通过，覆盖零写入确定性预览、范围/位置/新鲜度过滤、保存/重建/幂等、过期、冲突阻止、篡改拒绝、重开、V23 备份恢复与复制 ID/正文重映射、HTTP 鉴权/只读预览/能力契约及 UI 资产标记。
- `green-06-c05-stability-20261020T041143.log`：同一最终源连续 5 次 6 项通过，末尾 `ALL_RUNS_OK`，用于确认冲突正文断言不受随机记忆 ID 排序影响。
- `green-lead-electron-c05-20261020T0442.log` 与 `electron-20261020T0442-report.json`：领导在最终源码上用隐藏 Electron/CDP 跑通记忆页 8 项：汇总面板、确定性预览、保存、来源编辑后过期标记、显式重建第 2 版、冲突双正文报告、冲突阻止保存、跳转原记忆；`status=passed`、`errors=[]`、`external=[]`。
- `green-lead-core-29-20261020T0447.log`：领导独立重跑交接核心 29 项通过；另重跑 C05 与备份/迁移/规则 98 项通过。
- `green-02-c13-rules-backup-20261020T040735.log`：C13 规则导入/历史 11 项与迁移/备份/HTTP/包案例 67 项，共 78 项通过。
- `green-03-c05-smoke-20261020T040825.log`：真实业务入口预览、保存 V23、来源未变检查、显式重建到第 2 版及冲突列表冒烟通过。
- `green-00-existing-memory-copy-20261020T040234.log` 与原名 `red-02-existing-memory-20261020T040234.log` 内容相同：既有记忆范围 14 项通过；早期文件误用 red 名，保留原件并另存绿色副本，不改写历史文件。
- `red-07-existing-memory-20261020T040734.log`：既有记忆/HTTP/检索 20 项中 19 项通过，保留已知失败 `test_confirmed_memory_filter_freshness_archive_position_and_budget`（`context_preview.py:49` 的既有规则文本超过 128 字符预算），不是本轮引入。
- `red-08-existing-backup-validation-20261020T040826.log`：备份校验 28 项中 26 项通过，保留既有 `content_blobs` 两列在默认 schema v1 下不存在的 2 个子测试错误；与 V23 汇总路径无调用关系。
- `red-03`～`red-06`、`debug_migrate.py`、`debug_migrate2.py` 保留迁移由失败到定位到修复的诊断过程；旧证据不删除、不覆盖。

## 未验与边界

- 未使用真实模型、真实付费、正式 `data/`、8765、作者窗口/preview profile/stage 或全局设置；未提交、推送、签名或发布。
- 本机仍无 Playwright；领导改用隐藏 Electron/CDP 基线完成记忆页交互链路，未在打包安装器或干净 Windows 环境中复验。
- 本轮汇总是作者触发的确定性拼接，不是模型语义摘要；长篇记忆规模、真实提取准确度、语义冲突判断、自动增量汇总及汇总进入创作上下文仍未实现或未验。
- 冲突判断只比较规范化后的精确文本；文字相近但不同不算冲突。
