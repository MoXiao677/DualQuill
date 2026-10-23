# C04-B1 章节 IDEA 构思与细纲/场景有限交付｜2026-10-20

已接通实际章的 AI 构思与细纲链：从已保存的书/卷/章/人物/世界/位置/事实/规则/文风构造只读上下文，冻结实际请求，单次确认后生成结构化候选；候选可人工修正，查看具体差异并分步采纳为真实 IDEA 或 `ChapterOutline` 新版本。模型不写正文，不创建人物、地点或章节。

## 作者链与范围

- `brainstorm_chapter`：只输出 `{"idea": "..."}`。IDEA 为空也可构思；采用前不写入，采用时只替换该章 `ideas[chapter_id]`。
- `outline_chapter`：只输出 `core_idea`、`objective`、`character_ids`、`scenes`、`story_time`。场景必须非空且 `order` 严格为 1、2、3…；场景与本章人物只能是本书既存人物 ID；地点只是文本，不创建地点实体。
- 预设：复用 `creation_presets` 的 `brainstorm` / `outline` 步骤；单次 `model_options` 覆盖不改连接默认模型。预设未配置时明确要求覆盖或补配。
- 上下文：项目标题/类型/简介/语言、全书大纲与本章所属卷、章节编号/标题/状态、已保存 IDEA 与现有细纲、明确选入的本书人物完整设定、全部既存人物 ID、已保存场景位置名称、当前位置可用且已确认/未过期的记忆事实、世界观、写作规则、书/章已选文风。字符预算 512–24000，超限明确拒绝，不静默裁剪必要资料。
- 冻结：来源指纹覆盖上述内容与锁哈希；请求体保存实际协议消息、模型、温度、token、目的地和配置指纹。执行必须提交 `{confirm_external:true, request_sha256}`；准备、预览、修正、复核不联网。

## 候选、复核与采纳

候选始终先保存原始响应和结构化解析结果。坏 JSON、缺字段、未知人物、乱序场景都保留为需修正候选，不自动重试；人工修正追加候选历史，原响应不变。

复核在本次会话内完成，返回 IDEA 前后值或细纲字段/场景前后值。采纳要求同时提交候选与复核指纹、`expected_revision`、`confirm_chapter:true`，并在同一事务内写 `chapter_planning_adoptions` 与真实 IDEA 或 `ChapterOutline` 版本。同一操作身份重放返回原收据；换内容或换身份重复采纳被拒。

来源（章节、IDEA、细纲、人物、世界、规则、记忆、风格、锁）或连接配置变化会阻止旧执行、旧复核和旧采纳。取消后的完整迟到响应单独保存在 `chapter_planning_late_results`，不生成候选、不推进写入。恢复/复制后旧任务只显示中断，不继承执行许可，也不会自动重发。

## V17 持久化与恢复

工作区 V17 新增 `chapter_planning_tasks`、`chapter_planning_events`、`chapter_planning_results`、`chapter_planning_candidates`、`chapter_planning_reviews`、`chapter_planning_adoptions`、`chapter_planning_late_results`。完整备份格式随之为 17；恢复逐行相等。复制映射人物、章节、细纲版本、风格、预设、任务/候选/复核/采纳与迟到响应引用，重算内嵌来源指纹与复核指纹，保留原始请求/响应文字；V1–V16 读取与旧记录不变。

## 证据（均为本地虚构 loopback 供应商，真实费用 0）

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C04B1-chapter-planning-20261020/`

- `green-unit-20261020T013718Z.log`：10 业务用例 + 2 HTTP 用例通过。覆盖真实本书上下文（含已选文风）、人物/场景校验、坏 JSON 与缺字段拒绝、人工修正/差异复核/采纳、预设与覆盖、来源/锁/配置变化、预设调用预算、取消迟到、V17 备份恢复复制与旧许可不继承。
- `green-affected-writing-20261020T013042Z.log`：C04-A 正文 15 业务 + 2 HTTP 通过，确认新 IDEA/细纲被 C04-A 准备初稿消费后正文仍零改动。
- `green-affected-bookai-20261020T013042Z.log`：书级 AI 12 业务 + 2 HTTP 通过，V17 校验未破坏旧 V12 历史。
- `green-assets-20261020T013132Z.log`：桌面安全/打包 5 项通过。
- `green-ui-assets-20261020T013135Z.log`：UI state/i18n 7 项通过。
- `green-ui-20261020T013755Z.log` 与 `ui-20261020T013755Z/chapter-planning-ui.json`（同链先前 `green-ui-20261020T013245Z.log`/`012957Z` 也通过）：最终源真实隐藏 Electron，2 次虚构请求，renderer 错误/外发为空；IDEA→细纲/场景→采纳→C04-A 准备初稿贯通，重开不重发。截图 `chapter-planning-page.png` 为实际细纲页，`chapter-planning.png` 为返回正文页。

失败日志按时间保留：`red-ui-20261020T012653Z.log`、`012717Z`、`012743Z`、`012802Z`、`012825Z`、`012853Z`、`012923Z`（入口/表单/状态接线问题）以及最终 `green-ui-20261020T012957Z.log`。一次加严迟到断言后的失败被误命名为 `green-unit-20261020T013503Z.log`，已另存 `red-unit-20261020T013503Z.log` 并保留原名，不当作通过。**首次单元 RED 日志已被同一文件名覆盖，只剩聊天记录；现存 `red-chapter-planning.log` 实际是后续全绿输出，不能当作首次 RED 证据。** HTTP 日志 `http-chapter-planning.log` 为当时定向通过记录，未再覆盖。

## 未验与边界

- 未使用真实供应商、真实付费、正式数据、正式 8765、作者窗口/预览 profile/stage 或全局设置；未提交、推送、签名或发布。
- 真实模型 JSON 遵从率、长上下文极限、真实费用/限流和质量未验。
- 场景/选区正文扩写、控制台、磁盘草稿、TXT/MD 与最终安装包仍属后续批次。
