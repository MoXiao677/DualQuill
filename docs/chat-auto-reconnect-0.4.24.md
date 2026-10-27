# Chat automatic reconnect behavior in 0.4.24

Active chat model requests retry transient transport failures in a loop until the author cancels, the active task or project revision changes, the connection configuration changes, offline mode is enabled, or a permanent error occurs.

Each attempt rebuilds the request context, creates a fresh 180-second `CancellationToken`, validates the current project and connection, obtains a fresh provider connection, and increments the real model call counter. A retry returns one valid response to the original planner, writer, reviewer, revision, or maintenance call. Saved actions, chapters, tool results, and previous responses are not replayed.

Retryable failures include `OSError`, `TimeoutError` and transient HTTP transport exceptions such as `RemoteDisconnected`, `IncompleteRead`, and `BadStatusLine`. HTTP statuses 408, 425, 429, 500, 502, 503, and 504 are retryable. Retry delays are 2, 4, 8, 16, then 30 seconds for each later gap; cancellation and revision checks run while waiting. Progress records contain only the stage, attempt counts, retry kind, status code where applicable, and safe progress text.

Certificate verification failures, unsafe destinations, invalid configuration, cancellation, revision conflicts, permanent HTTP responses, malformed complete responses, rejected or truncated model output, and invalid review JSON do not retry. Valid failed review verdicts continue through the existing unlimited review and revision loop.

A reconnect may resend a request after the provider received it but the local client lost the response. The resend can be billed by the provider even when no response reached the application; automatic reconnect does not guarantee that duplicate upstream charges cannot occur.

Verification was not run for this change by request. No provider, novel, profile, database, credential, or end-to-end call was used.

## 2026-10-26 协调审阅补充

网络重试目前只包围连接建立、HTTP 提交、接收及相应超时检查；本地资料读取、运行记录保存、配置读取、编程错误不作为断网重试。HTTP 声明长度与实际响应不符按中断处理，完整但不合法的供应商响应仍保留错误。每次尝试重建连接及 180 秒期限，退避依次为 2、4、8、16、30 秒，随后保持 30 秒；不设重连次数上限。停止操作中断等待。只重发当前模型请求，不重放已完成的工具或章节保存。

截图中的 unknown evidence id P73 属于独立审核报告内容错误，不是网络错误。报告格式与证据错误的单独恢复功能仍在开发 API 修改中，尚未交付；必须保持严格证据验证，不可凭错误报告改写正文或宣称通过。

已完成源码人工审阅与阶段语法检查；本条记录时最终构建尚未执行。未运行测试套件、端到端操作、真实小说写作或审核请求，功能由作者自行验收。旧失败任务和程序重启不会自动恢复付费调用。

## 2026-10-26 05:46 本次交付完成记录

开发 API 已实际写入审核格式恢复逻辑。parse_review_response 校验出不存在的 evidence_id、非精确引文、JSON、字段或判断不一致时，原始响应作为 unverified / retry_review 报告保存到资料库和审核历史，不算审核通过或有效未通过。随后携带校验反馈、同一份正文及当前精确 evidence_catalog 重新独立审核，按 2、4、8、16、30 秒退避，无固定次数上限。该路径不据错误报告改写正文。合法未通过仍进入既有持续修订，合法通过才继续同步资料。审核轮数与实际正文修订次数分开记录。

此前“仍在开发”的阶段记录至此更新：清屏新会话、当前请求重连、审核报告格式恢复均已实现并构建。Python AST、Node 模块语法、git diff --check 通过；0.4.24 独立目录构建退出 0。包内 266 个源文件及 ASAR 五个运行文件与源码逐项一致，源码摘要 c83d2e49c87316966985a2d50792f1bfd97cff75c754b202420d786bed52ddd3。

入口：G:/AGI/_reconnect-0.4.24-delivery-20261026-053830/打开 DualQuill 0.4.24.lnk。沿用 G:/AGI/DualQuill/user-data。未启动新包、未关闭作者程序、未修改正式数据库；旧失败任务不自动恢复。未运行测试套件、端到端、真实小说写作或审核，作者自行试用。中转开发终端结束后自动关闭，当前无遗留开发窗口。
