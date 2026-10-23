# S3首批：规划编辑与只读上下文预览

2026-10-15（Asia/Shanghai）。作者已授权优先进入S3。本批实现及技术验证完成；正式8765未加载新代码，作者体验验收待安排，不代表完整S3、整体S2或AI生成已完成。

## 实际入口与行为

- 左上角展开模块 → “大纲与分卷规划”：编辑分卷顺序、卷名、概要和多选章节归属，添加/删除后“保存全书大纲”。章节稳定ID不变，同一章重复归卷、缺失/跨书ID拒绝。
- “章节与正文编辑” → 选择章节 → “章节细纲”：编辑本章参与人物和多场景顺序、剧情目标、人物、地点、剧情时间，添加/删除后保存。沿用ScenePlan现有字段，没有新增schema或实体ID。
- “人物、世界观与记忆” → 人物资料：编辑多项目标和关系对象/名称/说明，引用本书人物；保存后刷新仍在。部分字段保存保留未展示嵌套字段，显式空列表清空；沿用revision冲突、追加版本和不可变历史。嵌套编辑统一提交/草稿序列化，切模块可还原未保存列表，冲突保留输入。
- 章节写作 → “预览已保存上下文”：选择写作章节、正文范围和128–20000资料字符上限，点击“生成只读预览”。默认仅取当前章之前正文，最近章优先；当前章正文须选“包含当前章”，后续章始终排除。页面显示实际保存revision、来源/实体版本、选入/排除、裁剪及最终资料串。

分卷概要、场景目标、人物目标与关系说明通过textarea.value恢复；未编辑值按原始字符串保留首换行、CRLF与尾空格，不经HTML正文解析吞换行。目标/场景等输入不是新模型指令，只保存作者资料。

## Astra引用顺序P2最终收口

三类多选（分卷章节、场景人物、本章人物）现在未改选择时保留原数组顺序及合法重复；成员变化时保留仍选中旧项的顺序/重复，再将新成员按选项顺序追加。沿用真实编辑入口，草稿捕获/还原、提交和刷新后再保存保持一致，旧历史不变。Astra只改`views.js`与`tests/e2e-s3-planning.cjs`，未改app.js、state.js、后端、schema或S2。

最终证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S3-Astra-order-20261015-e7663819/`。真实RED保留于`red-order/stderr.log`及`reference-order-probe.json`；单候选后`candidate-s3/s3-browser-report.json`九组通过、`candidate-workbench/exit.json`及`candidate-node/exit.json`（6项）均退出0。原六组断言保留，新增逆序引用/合法重复、只改文字、成员增删、草稿切换/未提前写入、刷新再保存及历史前缀检查；各检查期间hash未变。

**证据边界：** 下方原12专项与290 Python/core/示例是在顺序修复前通过，候选后未重跑全量。Astra接手135项只改两项，其余133项不变；`inherited-core-delta.json`区分已有文档同步与原core，未改后端/契约hash匹配，复用原Python及示例结果，最终前端由九组/workbench/Node6补验。不把旧core写成最终整库重跑。Sol原三轮、旧失败与此次Astra RED全部保留。Astra已停写交回领导；本次Sol仅四份文档静态同步，无测试复跑。

最终SHA256：`views.js=314f2a2e58c409c98f8113018d3437fcf1c3ad6c98c3c0fd4db16dc1dc02353a`；`tests/e2e-s3-planning.cjs=c299ea8f2d8ee92b56291b8f3f8e57f81ae25dcd8046c2811e07f85cbb797995`。全部差异/hash及原命令见Astra根的`candidate.patch`、`final-hashes.json`、`commands-and-results.json`；最终合并本轮起点差异见仓库外`S3-order-doc-sync-20261015-837b29/final-relative-to-s3-start.json`。本节技术收口不代表正式8765已投用、作者体验已验收或完整S3/S4完成。

## 上下文边界

一次服务端读取已保存本书状态后组装，不依赖PromptStore或前端草稿。无故事位置的全书大纲（含主线/结局）、完整人物、世界观、规则默认排除，必须分别明确选入并提示可能含未来设定；“本书全部人物”选项含本书全部人物，业务API也支持明确人物ID列表。本章细纲/场景/IDEA作为显式选入的创作计划，不冒充已发生事实。不宣称自动识别任意自然语言剧透。

后续章排除报告仅含ID/章序/原因，不回显被排除正文或标题。正文/人物/细纲版本按实体类型+ID定位；工作区世界观/规则或仅IDEA的来源无独立实体版本，version_id=null，引用实际工作区revision。预算按Unicode字符计数，资料串标题/分隔换行也计入，报告元数据不计；不是精确token数。

选项/选章变化立即失效旧预览，导航/切书或迟到响应不能回填上一范围。只读接口`POST /api/projects/<ID>/context-preview`要求页面token及既有Host/Origin约束，只接受白名单参数，不读取其它书、Skills、API配置/凭据或未保存输入，不发模型请求、不新增业务数据。

## 原Sol轮验证与原始证据（顺序修复前）

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S3-planning-20261015-5c9621/`。起点129项hash、需改文件before副本及plan.md保留，继承全部原未提交内容；每次运行保存exit.json及源码前后hash。

| 检查 | 本轮结果 | 证据 |
|---|---|---|
| 业务/HTTP专项 | 12方法通过，exit0；2本各2卷20章，保存重开/引用拒绝/历史/冲突、预算/来源与既有备份恢复迁移保真 | `green-business-final` |
| S3 headless | 六组实际入口检查通过，exit0，external/errors空；含保存刷新、嵌套草稿、首换行/CRLF/空格、只读预览、迟到响应和冲突保留 | `green-browser-final/s3-browser-report.json` |
| 原工作台headless | 原`e2e-workbench.cjs`退出0，source_changes为空；已有草稿/历史/正式章授权/冲突等受影响路径及截图 | `regression-workbench/exit.json`及`s1-*.png` |
| 一次完整core | **290 Python、6 Node、示例均通过，各exit0**；134候选文件期间不变、credential_hints空、diffcheck0 | `core/exit.json`、`core-evidence/20261014T172832Z-13113d4cce5f/report.json`及`regression` |

core复用仓库外hidden_core.py隐藏控制台转发原入口，不改测试选择/断言或项目检查脚本，原/实际argv留在hidden-core-transit.jsonl，非无shim运行。S2历史278不是本轮结果。充值中断后只收集已完成结果，没有另启core或修复轮。

有效RED保留：首批业务缺少字段/预览、HTTP缺少入口、来源元数据借错版本及嵌套首换行损失各有原失败；原断言未删、未跳过。3次有新证据修复依次处理来源元数据/浏览器双流收集、嵌套value保真及预览等待、第二次预览空报告等待保护；最终通过。最初浏览器runner未显式转发Node双流，red-browser/green-browser-1日志为空，只保留真实退出1，不能将其称为有完整失败诊断；后续改仓库外runner显式采集双流。工作台复用旧runner也仅有真实退出码和截图，stdout/stderr为空，不编造文字日志。

已冻结S2备份/恢复/迁移实现与schema不改；新增规划数据通过其真实往返/重开/重映射检查。当前改动范围为三个save handler、fields/service、新context_preview、server预览路由、views/app及小范围样式；新增S3夹具/业务HTTP/headless测试。相对起点文件清单/最终hash与副本差异存本轮仓库外`final-delta.json`、`final-files.json`及`diffs/`。

## 后续排期与未完成

本批完成后停止等待领导审阅及作者体验安排，不擅自更新正式8765、不自动进入S4。没有打开正式data/真实凭据、操作作者窗口/输入/剪贴板、收费小说模型、安装依赖、改全局环境、扫删旧authority/暂存或提交推送。

S2已交付的备份迁移冻结；长篇性能基线、章节重排/归档/恢复、磁盘草稿/异常恢复单列后续，未以本次通过标整体S2完成。完整S3手动记忆/出处过期、关键词或高级检索、模板/查重、导入导出等未在本批实现；物理断电、网络盘/跨平台、>4GiB和百万字多版本规模未验证。S4真实模型调用尚无授权。本轮预览是模型接入前可审阅的资料串，不是AI回复或生成任务。
