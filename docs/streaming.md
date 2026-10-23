# 可选 SSE 流式预览｜0.4.8 实作

0.4.7固定产物与829项/141源码绑定已封存，不覆盖。新模式默认关闭，只用于已保存的自建连接。模型中心逐默认模型核对后选择“SSE临时增量预览”并保存；任何配置变更都会换revision，旧冻结/单次许可失效。重新保存连接或更换默认模型不会继承声明。内建旧连接保持原契约。

## 明确接口与旧字节

`POST /api/providers/manage`，字段为 `id`、`action:"stream_profile"`、`confirmed:true`、`stream_mode:"sse"`；切回完整响应使用 `stream_mode:"json"`。未知字段、不明确确认和非法模式拒绝且不写配置。

只有SSE去向快照编码 `stream_mode:"sse"`；JSON默认领域值不编码该键，不改变旧请求bytes/hash。SSE声明只适用于所声明的默认模型，不继承给本次模型覆盖。Chat冻结 `stream:true`，Messages冻结 `stream:true`，Gemini固定 `:streamGenerateContent?alt=sse` 路径；没有自动协议降级、重发或续写。

`GET /api/projects/{pid}/tasks/{id}` 与 `GET /api/projects/{pid}/book-ai/{id}` 运行时可返回 `stream_preview:{text,chars,temporary:true}`。正文/改写、书级辅助和自然创作对话页面以转义纯文本展示并明确标注“尚非候选”。该字段只来自进程内取消令牌，不写业务库、历史、备份或正式正文；终态、取消、超时、重开即消失。沿用既有轮询，不使用EventSource或自动重连。

## 完成与失败

解析严格增量UTF-8与事件边界，支持首次BOM、中文/emoji跨字节、CR/LF/CRLF跨包、多行data、注释与未知SSE字段。1MiB总响应与冻结输出字符上限保持。网络保留原单次总deadline、可取消socket、全部DNS地址复核、TLS校验、固定已验IP与禁止重定向。

- Chat只收一个assistant选择的delta正文；需要 `finish_reason:"stop"` 后的 `[DONE]`。独立usage帧允许，缺失用量保持未知。
- Messages校验message_start、顺序block、message_delta和message_stop；只收text_delta，thinking/signature不进正文或预览，工具拒绝；合法stop_reason仅end_turn/stop_sequence。
- Gemini只收一个model候选的text parts，thought不进正文或预览；必须STOP。MAX_TOKENS、CONTINUATION或工具不自动续发。
- 截断、无合法终止、无完整事件、非法UTF-8、error、工具、非完成终因、超限、取消、超时和密钥echo均无候选。失败不保留可能含分片密钥的半成品响应，仅保留错误标记。

发布预览前保留“当前输出末尾与密钥前缀相同的最长部分”；密钥跨多次delta仍不会在任何历史预览中拼出。发现完整密钥立即拒绝并清空。成功结果保留有界的实际SSE原始响应（包括非正文思考事件），候选仍通过原有完整结果/结构化计划校验。截断原始响应明确raw_truncated。

首次含SSE冻结去向的写入升级V33，完整备份/恢复/复制支持V1–V33；降为V32拒绝，不改写旧冻结。公开Google搜索依赖原生完整grounding响应，本切片明确拒绝SSE连接用于搜索，请另建JSON连接；不以丢失引用元数据换取流式。

## 验证进展

本机仅虚构TEMP数据库/profile、随机loopback、隐藏Electron；真实付费0。`run-105-sse-red.log`为未实现解析器时真实RED；`run-106`解析7项绿，`run-108`新核心与旧JSON/原生配置/自建任务/书级AI共45项绿（28.471秒），`run-109`最终核心12项绿（3.213秒）。`run-107`误写不存在的测试模块test_custom_protocols导致1个导入error，实际模块为test_custom_providers，run108已改正确且全绿；保留原日志，不作产品回归。

父仓外 `lead-independent-sse-20261021`：capture02的20组流式整链通过，三协议预览/终止、坏终因/工具/error/断连/跨delta密钥、41ms取消、原冻结不变、V33精确恢复复制及重开不重发；capture01配置4组/旧兼容5库通过。首次父重开夹具漏注册ChapterWriting已修为真实wiring后run06完整20绿，之前实际1次loopback并非零请求；真实付费始终0。父桌面验收与本版完整回归/新固定包尚待收口，不提前宣称完成。

最终收口：841项完整回归通过（514.439秒），结束后143源SHA与唯一0.4.8固定包无差异；父最终HTTP22/TLS22、SSE对话6、JSON对话6、作者7及旧库/旧V32/配置/上下文/检索均绿。本机最终真包正文SSE5、作者7、上下文5及JSON长正文4组通过；Node24/静态29通过。准确哈希、原RED与失败边界见[0.4.8完整验收](final-local-0.4.8.md)。
