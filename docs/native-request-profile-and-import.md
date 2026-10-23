# 0.4.3 原生请求配置与导入原文保全（0.4.4 接续修复）

## 逐连接、逐模型的明确配置

模型中心的连接管理新增「当前模型的原生请求配置」。温度发送方式可选「发送本次设置的温度」或「供应商默认温度（完全省略 temperature）」；Chat 输出令牌字段可选 max_tokens 或 max_completion_tokens。Messages/Gemini 仍使用各自原生输出上限字段。max_completion_tokens 可能包含推理令牌，不能把上限当作可见正文 token 保证。

声明只适用此连接当前默认模型；修改默认模型/重新保存连接后须重新声明。模型覆盖不继承原生配置，应另建对应模型连接。声明改变连接 revision 和配置指纹，旧冻结请求拒绝执行，原请求正文与摘要不重写。各生成入口在冻结前统一解析当前声明，确切请求体仍需要逐次人工确认。比较实验记录有效配置，与实际子任务一致。

省略温度不会静默删除作者已填的 top_p、seed 或 stop；它们仍须单独明确支持声明，未知时拒绝。新模型不接受或忽略某采样参数时，应清空该参数并不声明支持。若预设自带的原生配置与当前连接不同，明确拒绝而非偷偷覆盖。预设编辑保留这些字段并显示说明。

只有实际发送温度时才校验 Messages 的 0–1 协议范围；省略温度或已明确 top_p 模式下，未发送的通用温度值不触发该协议范围错误。通用温度仍须为有限 0–2 数字，没有放开其它模型/预算/输出字符限制。

## 官方资料核实范围

父独立验收在 2026-10-20 成功读取官方页面并报告以下兼容风险；本会话 web 工具未取得页面正文，故文档不把本地 wire 验收冒充真实供应商调用认证。

- Claude Messages 官方 API 对较新模型的自定义 temperature/top_p 有限制或弃用说明：https://platform.claude.com/docs/en/api/messages/create 。
- Google generateContent 与提示策略对新模型的 temperature/topP 忽略或未来拒绝行为作了说明：https://ai.google.dev/api/generate-content 、https://ai.google.dev/gemini-api/docs/prompting-strategies 。
- OpenAI Chat Completions 官方 API 说明 max_tokens 已弃用，部分模型不兼容，提供 max_completion_tokens：https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create 。

本实现让作者明确表达当前模型的确切请求契约，不猜所有自建模型 ID，也不提供永久不变的模型能力保证。真实供应商效果、账单和最新支持仍须作者按实际模型核对。

## V29 与旧记录

非默认原生配置在既有可选 sampling 结构中增加 temperature_mode / chat_token_field，仅新的相关写入升级到 workspace V29。默认字段编码时省略；V28 和更早原记录仍按原字节保存、旧请求 hash 不变。V28 夹带新结构拒绝加载。完整备份/恢复/复制支持 V1–V29；包含新字段的可分享创作预设使用格式 3，格式 1/2 夹带新字段拒绝。格式 3 不携带连接凭据或自动继承执行许可。

## TXT/Markdown 前言和大文件

首个标题前原文默认作为独立「前言（标题前原文）」条目展示和导入，包括开头空格和 CRLF。UI 展示前言字符数、各条 Unicode 原文范围和正文起点；可编辑标题。无标题文件仍是完整单条正文，围栏内的章标题不参与分章。最多 500 条包含前言，原始文件仍最多 5 MiB。没有通过新增警告继续丢原文。

预览 hash 增加 preserve-preamble-v2 契约，旧预览必须重新预览；确认时重新解码原始文件、计算 hash 和各范围。紧凑确认只回传 index/title/start/content_start/end/chars；原文从同时提交的原始文件严格切片，不信任客户端正文。原有完整映射仍在字段/正文一致时支持，但 UI 使用紧凑映射。没有放宽全局 12 MiB HTTP 请求上限。4.6 MB GB18030/200章确认请求约6.16 MB，避免原先重复回传全文使支持范围内文件超限。

## 验证与下一切片

本仓严格三协议原生配置、旧许可失效/V29备份恢复复制、显式采样保留、共享预设格式3、比较有效配置测试通过；前言UTF8/GB18030真实HTTP、旧预览和篡改拒绝、4.6 MB GB18030/200章完整HTTP发送/重开逐字验证通过。自然对话桌面严格本机服务5组通过。最终构建及解包结果以本版最终验收记录为准，早期RED保留。

0.4.3 当时尚未放开原有30秒总时限，且最终全量暴露旧内建连接准备路径凭据读取回归；原产物与 RED 保留。0.4.4 接续修复该回归，并增加自然创作大纲和正文可编辑的有界长请求时限、空书直接导入入口，见 [准确范围](long-request-and-empty-book-import.md)。SSE仍为独立未实现项。没有真实付费、安装器执行、签名或发布，也没有操作正式库、作者窗口/profile/凭据或冻结资源。
