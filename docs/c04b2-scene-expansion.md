# C04-B2 场景/选区正文扩写有限交付｜2026-10-20

已接通实际章的精确范围正文扩写：以已采纳细纲中的某个场景（按序号）或正文中的非空 Unicode 码点选区为目标，冻结当前正文、范围、前后文、场景节拍、人物/世界/事实/规则/文风与实际模型，单次确认生成候选；人工修正、具体差异复核后明确采纳为正文新版本。

## 范围语义

- **场景目标**：必须存在于本章当前已采纳 `ChapterOutline`；场景序号有序。扩写文本插入当前正文末尾；正文原有全部字符/字节保留。场景不会创建新人物、地点或章节。
- **选区目标**：`selection_start < selection_end`，按 Unicode 码点计，范围必须落在当前正文内；空选区、越界、同时带场景序号均拒绝。候选只替换该区间。
- 采用时用冻结原文的精确切片组合：`原文[:start] + 候选 + 原文[end:]`。因此范围外前缀/后缀（含 emoji、组合字符、CRLF/换行）逐字节不变，不做整章替换。
- 正文状态、IDEA、细纲、场景、人物、世界、规则、事实、文风、锁、连接配置或正文版本任一变化，旧执行/旧复核/旧采纳被拒；任务自身事件不假过期。

## 请求、候选与采纳

- 预览只读：返回实际 `context_text`、范围、正文字符数、来源指纹与预算；不联网。
- 冻结输入：当前正文全文（用于精确组合）、选区前后各最多 2000 字符、选中原文、场景/细纲快照、明确选入人物完整设定、既存人物 ID、当前可用已确认记忆事实、世界观、写作规则、已选文风；字符预算 512–24000，超限拒绝，不静默裁剪。
- 复用 `creation_presets` 的 `draft` 步骤作为正文扩写预设；单次 `model_options` 覆盖不改连接默认模型。`prompt_version=chapter-expand-1`，三种既有协议经共享 `ConfiguredHttpTransport` 发送。
- 候选是纯文本替换/插入内容，不是整章或 JSON。坏输出、空输出、部分输出、超时、取消都沿真实状态，不自动重试；人工修正追加历史，原响应只读保留。
- 复核返回选区前后值、完整正文前后值与逐行差异。采纳要求候选/复核指纹、`expected_revision`、`confirm_chapter:true`；已确认章节还须 `authorize_confirmed:true`。同一操作身份重放返回原收据，换内容或换身份重复采纳被拒。
- 取消后完整迟到响应保存在 `scene_expansion_late_results`，不生成候选、不写正文；恢复/复制后旧任务显示中断，执行许可不继承，不自动重发。

## V18 持久化与恢复

工作区 V18 新增 `scene_expansion_tasks`、`scene_expansion_events`、`scene_expansion_results`、`scene_expansion_candidates`、`scene_expansion_reviews`、`scene_expansion_adoptions`、`scene_expansion_late_results`。完整备份格式为 18；恢复逐行相等。复制映射章节、人物、细纲/场景、风格、记忆、任务/候选/复核/采纳/迟到响应，重算来源/复核/采纳请求指纹，保留原始请求/响应文字；V1–V17 读取与旧记录不变。

## 证据（仅本地虚构 loopback，真实费用 0）

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C04B2-scene-expansion-20261020/`

- `green-unit-20261020T014731Z.log`：9 业务通过（选区/场景、字节保持、非法范围、细纲/正文/锁/配置、正文预设、确认章幂等、取消迟到、V18 恢复复制、空输出）。
- `green-http-20261020T014324Z.log`（原 `red-04-http-20261020T014324Z.log` 实为通过，复制保留）：2 HTTP 通过。
- `green-affected-planning-20261020T014542Z.log`：C04-B1 12 项回归通过。
- `green-affected-writing-20261020T014542Z.log`：C04-A 17 项回归通过。
- `green-assets-20261020T014625Z.log`：桌面安全/打包 5 项与 UI state/i18n 7 项通过。
- `green-ui-20261020T014452Z.log` + `ui-20261020T014452Z/scene-expansion-ui.json`：最终源隐藏 Electron 通过，2 次虚构请求；选区扩写与场景扩写均保持范围外字节、只追加正文版本、重开不重发。截图 `scene-expansion-page.png`。

失败日志按文件保留：`red-01-import-missing.log`（入口缺失）、`red-02-first-run-20261020T014239Z.log`（一项测试更新细纲后场景序号消失）、`red-03-after-fix-20261020T014257Z.log`（实际全绿，保留原名）、`red-05/06/07-ui-*.log`（UI 码点切片、版本计数、重复 id）。`red-04`/`red-08` 实为通过，已另存 green 副本并保留原名，不把失败文件伪装成通过。

## 未验与边界

- 未使用真实供应商、真实付费、正式 data/8765、作者窗口/preview profile/stage 或全局设置；未提交、推送、签名或发布。
- 真实模型扩写质量/遵从率、长上下文极限、费用/限流未验。
- 场景目标固定为当前正文末尾插入；尚无场景锚点/区间标记。
- 磁盘草稿与异常恢复、控制台、TXT/MD、最终安装包仍属后续批次。
