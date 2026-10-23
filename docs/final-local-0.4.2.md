# 0.4.2 本地最终验收｜2026-10-20

本次交付涵盖 C03 采样参数、真正自然创作对话、V28 兼容与百万字历史保存性能；不代表全部 C01–C18 完成或公开发布。唯一工程写入者，保留原未提交修改，没有提交、推送、签名、发布或执行安装器。

## 功能与使用

创建或打开书，在「创作对话」新建会话，直接输入「帮我写一份大纲」，下一轮可说「主角改女主，扩成三卷」。需求先持久保存；冻结时显示当前正式来源、历史与候选，作者逐次确认发送。回复与完整大纲以可读候选保存，只有转提案、预览具体影响并另行确认才应用为正式大纲/人物/卷章；新增正文为空，复用章节保留原文和版本。取消、离线、重开不自动重发，不继承执行许可。详见 [操作和准确范围](creative-dialogue-and-sampling.md)。

top_p/seed/stop 接入用途预设、各模型入口、冻结摘要和三协议原生请求。支持未知时必须逐连接及当前默认模型明确声明；Messages 不支持 seed，top_p 模式不发送 temperature。参数非法或不支持拒绝，不静默丢弃。V28 首次新写升级，旧请求原字节与摘要保留；完整备份恢复复制支持 V1–V28，含采样共享预设使用格式 2。连接验证不再提前消耗实际外发限流额度。

历史保存仍逐条读取原快照、计算 SHA-256、核对修订号/保存时间/元信息；仅原字节相同的已验证前缀复用昂贵解析和领域验证。缓存最多四本、深拷贝隔离，失败事务不污染缓存；没有删历史或采用 mtime 捷径。

## 最终解包验收

本轮证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。正式 data、8765、作者窗口/凭据/profile、冻结 stage、author-preview 与全局配置均未操作。全部测试使用临时 DB/profile、随机端口、隐藏 Electron；模型请求仅本机虚构供应商，真实付费调用为零。

- `run-17-node-final.log`：七个 Node 文件，22 项通过；29 个静态 JS 文件语法通过，示例校验通过（`run-24-static-example.log`）。
- `run-15-final-full.log` 保留 792 项中的两项 Windows 临时库清理错误：新增测试使用 sqlite3 事务上下文但未显式关闭连接。已仅修复测试为 contextlib.closing，`run-22-history-handle.log` 四项在 ResourceWarning 提升为错误时通过；产品源码与已验包字节不变。修正后 `run-23-final-full.log` 全量 **792项通过/411.390秒/退出码0**，不覆盖失败日志。
- `run-18-dialogue-packaged.log`、`dialogue-packaged-01/dialogue-report.json`：真正解包 exe 的三协议对话 5 组通过，虚构 wire 5 次，errors/external 为空。含自然两轮、上一候选入上下文、HTML 字面显示、单独正式确认、Messages/Gemini 参数与原生结束原因、慢响应取消、重开零重发。
- `run-19-author-packaged.log`、`author-packaged-01/packaged-author-report.json`：真正解包 exe 作者流程 7 组通过，providerCalls=0、errors/external 为空。覆盖精确正文、人物/卷规划、重开、GB18030 自动导入、实际 TXT 下载、回收站确认/恢复、完整备份落盘/独立恢复/复制及独立恢复库续写后再次重开。
- `run-20-scale-packaged.log`、`scale-packaged-01/scale/report.json`：解包后端 200 章×5000 字、4 卷、12 次真实保存和 13 个历史快照通过。所有未编辑正文 SHA-256、重开、检索、完整备份/恢复/复制及版本完整性通过。
- `run-21-scale-ui-packaged.log`、`scale-packaged-01/scale-ui/report.json`：解包桌面百万字 3 组通过。30 次切章精确正文、实际编辑保存并重启逐字核对；providerCalls=0、errors/external 为空。
- 对话、作者流程和百万字截图已视觉核对。早期源码 UI 的启动竞态、设置控件 ID、最近会话选择问题及其 RED 日志保留；修复后新包重新完整验收。

独立父验收证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/lead-independent-0.4.2-20261020-final/`：新解包历史完整性 10 项通过（`integrity/report.json`、`green-04-integrity.log`），覆盖返回隔离、另一实例写入、陈旧保存、回滚、当前/历史损坏、不可变版本、历史缺失、元信息错误、同大小恢复 mtime 篡改。独立对话后端 7 组（`dialogue-backend/report.json`）、桌面 4 组（`dialogue-ui-02/report.json`）及作者 7 组（`author-ui/packaged-author-report.json`）通过；对话包含写过正文后再修改大纲、复用稳定三章 ID、原有空格换行正文逐字节保留及正式来源变化拒绝旧许可。桌面对话虚构请求 2 次，作者 0 次，errors/external 为空。父线程独立包审计同样通过。初次独立 UI 脚本对已是对象的新 source 重复 JSON.parse 失败，修正脚本后重跑通过，RED 保留；独立百万字后端（`scale-final/report.json`）和桌面（`scale-ui/report.json`）也通过；桌面保存1531ms、切章p95 50.3ms，重启逐字保真。

## 百万字观察值

新解包后端连续 12 次保存为 0.9001、0.9383、0.9682、0.9977、1.0341、1.0819、1.1180、1.1943、1.2878、1.2278、1.4019、1.3719 秒；上版独立 0.4.1 同规模第 12 次约 6.48 秒。重开 3.225 秒、检索 0.4525 秒、备份 7.9844 秒、恢复 8.2482 秒、复制 21.5777 秒。新解包桌面加载 3.571 秒，切章中位 49.2ms、p95 50.7ms，实际保存 1.536 秒并重启保真。属于本机虚构数据观察值，不是跨机器性能保证。

## 产物

`dist/s7/AI Novel Writer-0.4.2-win.zip`：165421136 字节，SHA-256 `1b63ad989a62051ffa67e219b7471c70a3930ddf99a71f6d50bbe0dae6f2347e`。

`dist/s7/AI Novel Writer Setup 0.4.2.exe`：122041648 字节，SHA-256 `abfdbdb0ec76fd231f7e00ad5cbf2cae1a3b84db87ffc7d4154f41b03f10ed51`。

`run-16-build-0.4.2.log` 记录独立 build-stage，未使用冻结 stage。ZIP 真正解包到证据根 `extracted-0.4.2/`，262 条目、139 个 backend 源文件逐一与当前源码字节一致；ASAR 版本 0.4.2 及五个 desktop 代码文件、外置 notices 字节一致。没有 DB/凭据/profile/stage/author-preview/.git/node_modules/tests/fixtures。见 `package-audit-0.4.2.json`、`asar-audit.json`、`signature-0.4.2.json`，安装器 NotSigned，未执行。初次 ASAR 人工核对误写不存在的 drafts.cjs，按实际归档的 localization.cjs 修正后五文件通过，是验收清单错误。旧 0.4.1 包保留。

## 仍有缺口

当前使用完整 JSON 响应，SSE 增量流式未实现；需另行完成三协议增量候选、取消迟到、原始响应和用量契约。真实供应商的支持能力、效果/账单、长篇连续创作质量、干净 Windows VM 安装升级卸载、签名和公开许可未验。本会话直接在线工具未取得返回；父线程2026-10-20成功核对官方文档，确认新Claude温度/top_p、Google新模型采样及OpenAI输出token字段兼容限制。0.4.2仍默认发送temperature、Chat使用max_tokens，下一批需补显式逐模型请求profile；本机通过不代表所有真实模型可用。工程仍为 UNLICENSED。
