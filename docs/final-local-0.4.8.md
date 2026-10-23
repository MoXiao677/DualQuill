# 0.4.8 固定包验收｜2026-10-21

本版实现自建连接逐默认模型明确启用的SSE，默认JSON；旧冻结省略新键，保持bytes/hash。临时转义纯文本预览只驻内存，合法完整终止并通过原验证才生成候选。V33完整备份恢复复制、配置变化使旧许可失效、公开搜索明确拒绝SSE。准确范围与三协议契约见[流式说明](streaming.md)。0.4.7固定包及全量829项/141源SHA绑定与0.4.6两个真实RED全部保留。

## 唯一固定构建

`run-113-build-0.4.8.log`，独立stage `desktop/.cache/build-stage-ccc3c5b91f89`，143源码；不再重建或覆盖本版产物。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/s7/AI Novel Writer-0.4.8-win.zip` | 165434059 | `4685caa800a905235fabd249581c8e5b1352f0ab1f6b93701f2fc2bab6a6e9d8` |
| `dist/s7/AI Novel Writer Setup 0.4.8.exe` | 122053294 | `e584662fabec3870d3b66fc109fc13d77fd95a6b66384f4d9f213e130a1b69ce` |

证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。真解包 `extracted-final-0.4.8` 的266条目/143后端源码与工程及manifest逐SHA匹配，无禁带；5个ASAR CJS/版本/第三方notices字节一致。对应 `package-audit-final-0.4.8.json`、`source-manifest-final-0.4.8.json`、`asar-audit-final-0.4.8.json`。安装器NotSigned（`signature-final-0.4.8.json`），未运行；构建工具的“signing with signtool”日志不代表已签名。

## 测试记录

- `run-108-sse-integration.log`：45项定向通过，28.471秒；含新SSE核心、旧JSON、原生profile、自建协议和书级AI。
- `run-109-sse-final-core.log`：12项最终核心通过，3.213秒；三协议真实loopback、终止前预览、失败/密钥/取消、旧冻结与V33完整恢复复制。
- `run-112-node-0.4.8.log`：Node24项通过，29个JS语法核对通过。
- `run-111-sse-writing-ui.log` / `sse-writing-source-01/sse-writing-report.json`：隐藏源桌面5组通过，可见配置/预览转义/合法完成/344ms取消/重开不重发；2次虚构loopback，errors/external空。截图 `sse-writing-preview.png` 已视觉核对。
- `run-114-sse-writing-packaged.log`：最终真包同一正文SSE桌面5组通过，取消217ms，2次loopback，errors/external空。
- `run-115-author-packaged-0.4.8.log`：原作者真包7组通过，模型调用0、errors/external空；含真实恢复库续写和再次重开。
- `run-117-context-packaged-0.4.8.log`：最终真包上下文桌面5组通过，模型调用0、errors/external空。
- `run-118-writing-json-packaged-0.4.8.log`：原JSON长正文真包4组通过，实际31.462秒、取消219ms、1秒超时、重开不重发；3次虚构loopback，errors/external空。
- `run-110-0.4.8-full.log`：841项通过，514.439秒，OK/退出0。结束后143源码逐SHA无差异，`full-source-binding-0.4.8.json`绑定完整测试终态及本次唯一固定ZIP/NSIS哈希；结束前未改封存源码。

## 独立验收

父仓外 `lead-independent-sse-20261021`：source-profile01配置4组、source-legacy01旧5库/2冻结通过；capture02/source-stream02真实三协议20组通过（20次loopback），覆盖BOM/UTF8/CRLF/multiline、终止前preview、缺终止/length/tool/error/thought/断连/跨delta密钥、41.019ms取消、终态/重开无临时预览与不重发、冻结不变及V33精确恢复复制。

capture03/source-dialogue-ui01隐藏自然对话桌面6组通过：显式配置、未发送输入跨轮询保留、escaped预览、合法多轮含历史、独立提案确认三卷女主、取消和流中退出重开；4次loopback，errors/external空。父timeout/overlong、最终真包审计与全范围重跑待反馈。

父最终真包静态审计再次确认同一ZIP/NSIS字节和SHA、266条目/143源码与capture03及当前工程完全一致，无禁带，ASAR三主文件一致，NotSigned未运行。最终包profile4、旧5库2冻结、旧V32/raw2正文冻结、上下文生命周期4及检索保护均通过。`packaged-stream-01/report.json`扩展22组通过（22次loopback），新增1秒总超时和128字符超限无候选/清预览，取消41.766ms；原20及V33恢复复制保持通过。真包SSE对话UI6组亦绿（4次loopback），源UI作为独立重复保留。父真实TLS22与原JSON/作者UI回归待反馈。

父最终补验全部通过：`packaged-tls-stream-01/report.json`为真正TLS SSE22组（22次仅loopback，取消42.171ms；只在测试进程信任虚构证书，不改全局）；原JSON对话6组首轮32.049秒、原作者7组均绿，errors/external空。父最终各批与本机完整测试已闭合；仅真实供应商质量/费用与干净VM等外部范围继续单列。

## RED 与边界

`run-105-sse-red.log` 为未实现时解析器导入RED；`run-107`误写不存在的测试模块，run108以正确test_custom_providers完整通过，原日志保留。父首次重开夹具漏注册ChapterWriting已纠正为真实app wiring后完整20绿；旧该次实际1次loopback，不冒称零请求。预期服务端ConnectionReset噪音不作产品错误。

`run-116-context-packaged-0.4.8.log` 为旧UI夹具仍断言英文reason码；本版按既定要求将说明中文化，原上下文实际去重/排除正确。夹具改为精确断言三个对应中文说明，数据/冻结/无泄漏断言保持，run117最终真包5组通过；未改产品或重建产物。

真实付费0。正式data/8765、作者窗口/profile/凭据、author-preview、冻结stage与全局配置未操作；唯一工程写入，无子代理/新聊天，无提交推送签名发布。真实供应商兼容/质量/费用、干净VM、模型语义摘要和自动增量/自动选择仍未验或未实现，不宣称全部功能完成。
