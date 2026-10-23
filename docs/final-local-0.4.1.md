# 0.4.1 本地最终验收｜2026-10-20

本次为用户授权的本地收尾，不是 C01–C18 全部产品功能完成或对外发布。当前会话实际模型已由 session turn_context 核实为 gpt-6.1-sol；唯一写入者，没有子代理、提交、推送、签名或发布。

## 已实现

- [C17 V27](c17-chapter-lifecycle-and-migration.md)：跨卷移动/拖拽、回收站影响预览/精确确认/恢复、隐藏项排除、V1–V27 备份恢复复制、严格 UTF-8/BOM→GB18030 自动检测和手工覆盖。
- [C03](c03-provider-management.md)：逐连接启停/凭据删除、旧任务失效、本进程请求间隔/RPM、自建模型发现、本地能力目录和手工 token/价格估算。
- 桌面 `--database=<绝对文件路径>` 传递到既有后端，能用独立 profile 打开恢复库继续写作；相对路径拒绝。TXT/MD 和完整备份通过受限 native save IPC 读取已有同源附件，正常界面使用系统保存对话框；只允许文本导出/备份票据，校验 owning frame，renderer 不能提交文件路径、任意 URL 或请求方法。隐藏测试的目录只由进程参数指定。
- 修复 JSON/模板导出被 TXT query 路由抢占；强制规则用含 ID/作用域/来源/版本的紧凑表示，完整元数据仍在 rules/sources，超预算仍拒绝；修正旧 schema 测试夹具及已变化指南/mandatory legacy 契约，不降低校验。
- C05 V23、C09 V24、C08 V25、C07 V26 已接受逻辑保留；migrations 的 legacy rule uuid5 与历史 hash 修复保留。
- 全量首跑暴露的关闭模式执行提前读取凭据已修正：会话/单次确认门槛先于连接失效检查，关闭模式返回原 422 且不读取凭据。旧配置任务现在在启动前拒绝，保持 pending、零外发；旧测试由期待运行后 failed 改为明确拒绝启动。资料能力测试同时验证 V26 和 V27，不再把 V26 当最大版本。
- 恢复库显式绝对路径允许位于独立 profile 之外；配置/草稿/升级快照仍归独立 profile。相对路径拒绝，启动前快照和初始化失败回滚保留。桌面应用版本 marker 从 0.3.0 同步到 0.4.1，触发既有升级保护。

## 证据

证据根 `%LOCALAPPDATA%\AI-Novel-Writer-review\final-local-20261020`。所有测试仅临时 DB/profile、随机端口及隐藏 Electron，模型传输仅虚构 loopback 供应商。

- `green-core-29-final-02.log`：最终源码 29 项通过；`node-final-03.log`：最终源码 19 项通过，含真实隔离后端启动停止、桌面保存路由边界/打包白名单和 UI 状态；`static-syntax-final.log`：27 个静态 JavaScript 文件语法通过。较早的核心/Node 日志保留。
- `c03-ui-01/provider-management-report.json`：四项通过；C17 新 UI 六项见 `%LOCALAPPDATA%\AI-Novel-Writer-review\c17-v27-20261020\ui-04`。
- `red-baseline-targeted.log`：61 项中的既有 4 failures/4 errors；修复后 `run-02-targeted.log` 61 项通过。早期核心失败 `run-core-29.log` 保留，以最终 29 项通过日志为准。
- `author-ui-01/02` 保留真实打包下载失败，03 保留独立 profile 打开恢复库失败；04 为修复后最终 ZIP 解包重跑。早期失败和页面上下文均保留。
- `build-0.4.1-01` 至 `06.log` 保留各构建；06 包含完整最新业务/UI/桌面版本和恢复路径修复。早期构建成功不当作最终验收。
- `full-unittest-01.log`：735 项中 1 failure/2 errors，完整保留；`full-fixes-targeted-02.log` 的剩余一项仅为“已变化”与“过期”的错误说明断言，实际都已拒绝旧请求。修正后的完整重跑及最终构建结果如下，不覆盖早期失败。
- `full-unittest-02.log`：736 项中仅上述错误说明断言 1 failure；该进程在修改断言前已经导入测试，保留其完整结果，不当作最终通过。修改断言后的独立 `full-unittest-03.log` 为最终源码 736 项全部通过（883.416 秒、退出码 0、无 skip）；前两轮失败不删除或覆盖。

## 产物核对

`dist/s7/AI Novel Writer-0.4.1-win.zip`：165406533 字节，SHA-256 `002b2d4fa9a7e712373d2b1bdba445afb7f04fd2d305803239be64f7135c4222`。

`dist/s7/AI Novel Writer Setup 0.4.1.exe`：122028411 字节，SHA-256 `51da07f113a545c9181bd52ba26dd2f8e1a8b7daf34c14a9fc37d5168495cb82`。

ZIP 257 条目，134 个 backend 源文件逐一 SHA-256 与当前源码一致；ASAR 版本 0.4.1，五个 desktop 代码文件与外置 notices 逐字节一致。无 DB/DPAPI/profile/冻结 stage/author-preview/.git/node_modules/tests/fixtures。`package-audit-06.json`、`signature-06.json` 保存最终校验；安装器为 NotSigned。早期 package-audit/signature 只属当时构建。

## 最终结果

`author-ui-04/packaged-author-report.json` 七项通过：解包 ZIP 的 exe 在全新 profile 创建小说/章节/人物/分卷规划、保存精确正文、关闭重开、GB18030 自动导入和真实文件导出、回收站影响确认/原卷恢复、完整备份实际落盘/独立恢复/复制，再用另一独立 profile 指向恢复库继续写作并再次重开核对。报告 status=passed、providerCalls=0、errors=[]、external=[]。同时验证 renderer 无 Node globals，native save 拒绝无关 API。`packaged-author.png` 已人工视觉核对，中文内容与保存状态正常；系统可见保存对话框使用隐藏测试目录替代，未操作作者窗口。

`full-fixes-targeted-03.log`：27 项通过；`desktop-upgrade-final.log`：三项通过，含显式外部恢复库与独立 profile/升级快照/相对路径拒绝，以及 V1–V7 原始行保真。最终 `full-unittest-03.log` 736 项全部通过；`node-final-03.log` 19 项全部通过，27 个静态 JS 语法通过，`git diff --check` 退出码 0。本地授权范围完成；系统可见保存对话框、真实供应商和干净安装仍按外部边界单列。

## 外部条件与边界

真实模型效果/费用、真实价格、语义质量/长篇规模，以及干净 Windows VM 安装/升级/卸载未验；top_p/seed/stop/流式等未实现。安装器未执行，许可仍 UNLICENSED。没有使用正式 data/8765、作者窗口/凭据/profile、冻结 stage、全局设置，也没有真实付费模型调用。原作者试用快照保留且未自动升级。
