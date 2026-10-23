# C03 显式模型验收工具与外部验收准备

本工具是开发验收入口，不是自动生成服务或数据库迁移。只包含内置虚构材料，不读取正式小说、环境密钥、DPAPI、作者 profile 或现有连接文件。`prepare` 和默认 `run` 都是零网络 dry-run。所有执行均须逐请求确认，没有批量许可、自动重试、自动采纳或写入正文；失败也消耗本次验收请求身份。

## 可直接运行的入口

标准库 Python 3.11+，从工程根运行。所有证据、TEMP/TMP 放在自己的独立验收目录，禁止指向正式数据或运行中的安装资源。示例地址仅为说明；回环供应商须使用测试分配的随机端口。

```powershell
# 纯本地预览；端口须替换为自己的虚构 loopback 夹具端口。
python -B -X utf8 scripts/accept_provider.py prepare `
  --protocol openai-chat --base-url http://127.0.0.1:12345/v1 `
  --model fictional-model --evidence-directory G:\isolated-acceptance `
  --budget 0.01 --currency USD --omit-temperature `
  --chat-token-field max_completion_tokens

# 使用 prepare 输出的真实文件名；此命令不读取密钥、不解析DNS、不发请求。
python -B -X utf8 scripts/accept_provider.py run --plan G:\isolated-acceptance\REQUEST.preview.json
```

`prepare` 输出三份独立文件：

- `UUID.preview.json`：确切 POST 正文、正文 SHA-256、地址/原生路径/模型、协议、JSON 或 SSE、鉴权头名称（不含密钥）、原生 profile、超时、输出上限、正数预算和币种、未知费用、执行证据目录、相关实现文件摘要。
- `UUID.confirmation.json`：默认 `confirm_external=false`、`accept_unknown_cost=false`，不能直接执行。作者看过完整预览后才可自行明确改为两个 `true`；其它身份、摘要、金额、币种必须原样匹配。
- `UUID.quality.json`：默认 `not_assessed`，每项分数为空；传输通过绝不自动填分。

`--scope real-provider` 只准备公开 HTTPS 供应商的预览，并不代表授权。实际发送还须作者另行授权该明确请求，传入 `run --execute --confirmation … --allow-real-provider`，工具才在确认校验和独占占位成功后通过交互式隐藏输入取得本次 key。**本模块交付没有进行该操作，真实供应商调用为 0。** 不支持 key 命令行参数、环境读取或自动借用已有凭据。不得为本机测试输入真实 key。

回环执行不需真实凭据，使用固定虚构 key `fictional-loopback-key`；该值不出现在结果记录中。通过 `run --execute --confirmation …` 执行单次已确认的 loopback 请求。真实 key 只接受支持隐藏输入的交互终端，非 TTY 或 getpass 回显降级被拒绝。Ctrl+C 设置取消事件；传输共享现有可取消 HTTP 实现，不重试、不跟随 3xx、不后台自动继续。请求超时从取到本次凭据后开始，包含 DNS、连接、响应全过程，输入等待不消耗供应商超时。

## 单次许可、预算和结果追溯

预览全体内容参与 `request_sha256`：变更一个字、预算、币种、模型、路径、profile、超时、证据路径或实现摘要均须重新准备和确认。未知字段和不符摘要被拒绝。以独占创建 `UUID.claim.json` 先占位，再读取 key 和连接网络；多进程/并发抢同一身份最多一个成功，崩溃、失败或取消后的请求身份不会重新获得执行许可。没有复制/恢复业务权限；不能复制授权目录来授予其它请求。

执行记录 `UUID.result.json` 包含请求摘要、实现绑定、UTC 时间、耗时、HTTP 状态、错误码、供应商实际返回的 ID/模型/usage、受限并去凭据的原始响应、输出摘要和结果摘要。执行前也保全确切预览。记录区分 `scope=loopback` 与 `scope=real-provider`，`transport_status` 与 `quality_status` 分开；回环永远不标真实供应商通过。工具的 `request_attempts` 是进入传输层的保守尝试计数，并不证明远端收到请求；`real_provider_calls` 在真实范围的传输尝试前加一，遇 DNS/连接失败也不夸称已生成。

预算是单次确认信息，不是供应商账单硬封顶。固定 `max_requests=1`、`automatic_retries=0`，输出 token 上限不是输入 token、隐藏推理或费用保证。报告始终 `cost_status=unknown`、`actual_cost=null`；HTTP 失败、超时、取消仍可能计费，不把费用未知写成 0。Messages 的合计是供应商 input/output 计数之和，不是缓存/账单总量证明；Gemini 未报告 total 时保留未知，不能用 prompt+candidate 冒充含推理的总量。原始响应保留额外 cache/thought 等实际字段，当前公共 Usage 结构未扩展成细项账单。

应用现有连接最小间隔/每分钟限流仍由 `ProviderConnections` 在应用任务链保留，本工具独立请求不读取那些已保存配置。429 标为供应商限流；401 为鉴权失败、403 为权限不足，3xx 为拒绝重定向。凭据回显被抹除时仍从 HTTP 状态保留诊断，不为诊断恢复敏感正文。它不自动发现模型或探测真实配额。

## 三协议兼容增量与边界

| 面向 | 已实现的本地 wire 检查 | 仍需真实验收 |
| --- | --- | --- |
| Chat Completions | messages/model、Bearer、JSON/SSE、明确省略温度、明确 max_completion_tokens、可空 refusal 元数据、实际 usage | 所选真实模型是否接受该 profile，SSE 是否返回 usage（未返回则未知） |
| Messages | system/messages、x-api-key 和版本头、JSON/SSE、text 与 thinking/redacted_thinking 区分 | 真实模型温度/采样限制、思考模式及缓存计费；工具/未知内容块仍拒绝 |
| Gemini Content | systemInstruction/contents/generationConfig、x-goog-api-key、不在 URL 放 key、JSON/SSE 原生路径、STOP 后唯一 usage 尾帧 | 所选模型原生/代理协议差异、实际 total/推理细项与账单 |
| 共同 | 不跟随重定向；有界 UTF-8/JSON/SSE；追加式元数据可兼容；未知语义块、工具/媒体混入、拒绝/截断/非法usage/晚到文本不算成功 | 真实供应商响应、区域/账户权限、配额、质量和价格 |

这是基于现有实现契约和虚构 wire 夹具的兼容结果，不是从真实供应商捕获的响应，也不承诺任意代理、任意新模型兼容。Gemini JSON/SSE 同样排除媒体/执行字段、错误 role、阻止反馈和非布尔 thought；Chat 明确 refusal 不能被当作成功候选。Messages 思考块只在类型结构合法时跳过，不能生成正文或工具权限。

## 虚构样本与人工量表

内置三个样本全部使用虚构钟楼/蓝色信封：`writing` 测正文约束与人物知识，`summary` 测已发生/计划区分及原文引用，`review` 测双侧引文与知识状态冲突。每个样本五项人工指标，0 未达到、1 严重问题、2 部分达到、3 达到、4 充分达到。不能用“出现关键词”冒充语义通过。

作者审阅实际输出后，在独立 scorecard 填 `status=human_reviewed`、自己的审阅标识、结果中的 `output_sha256`、五项整数评分及每项实际输出原文引用，再运行：

```powershell
python -B -X utf8 scripts/accept_provider.py record-quality `
  --plan G:\isolated-acceptance\REQUEST.preview.json `
  --result G:\isolated-acceptance\REQUEST.result.json `
  --scorecard G:\isolated-acceptance\REQUEST.quality.json
```

记录验证请求/结果/输出摘要、量表项目、0–4 整数和引用逐字属于输出；它只证明留痕和引文范围，不自动证明评分合理。生成新的 `UUID.quality-review.REVIEW_UUID.json`，不覆写传输结果或旧评分，状态仅为 `human_review_recorded`，正式验收仍由作者决定。测试中的虚构人工评分不能计为真实语义质量通过。

## 待作者授权的最小真实清单

1. 作者选择三个明确协议的实际连接/模型，自己核对 Base URL、区域、账户权限、当前 profile 和币种/单次可承受预算。不要以模型列表成功代替生成成功；不读取现有 key 来准备清单。
2. 分别为三协议准备 writing JSON 和 SSE 共六份预览，逐个审阅精确正文、原生字段、输出/超时上限、未知价格与单次风险；一次只授权一份。缺 SSE 支持的供应商记录为未通过/不支持，不能退回 JSON 后声称 SSE 通过。
3. 作者授权后逐一执行，不批量确认、不自动重试。核对实际响应、模型身份、完整终止、真实 usage（缺失保留未知）、供应商后台账单；错误 key/429/断流负例继续只在 loopback 做，不故意消耗真实额度。
4. 在作者选定的一个真实参考模型上另准备 summary、review 两份预览，逐份授权与人工评定。最小开发样本组合为八次显式请求，预算和次数不能汇总成整套执行许可；可能失败仍计尝试。它不代替应用自然对话、正文、结构化摘要/审核的实际 UI 全链验收；这些业务还须使用各自实际冻结请求另行逐次授权，不能沿用本工具的许可。
5. 记录所有预览、确认、claim、result、人工评分和供应商后台核对的独立证据；不携带 key、真实小说或未授权内容。该清单目前状态为 **等待作者具体授权，未执行**。

## 最终外部验收阻碍

- 干净 Windows VM：尚未取得/执行独立干净安装、启动、升级、卸载和重装保真环境；本机单测不等同此项。
- 签名：没有本模块可用且作者授权使用的代码签名证书/私钥和发布身份；不执行安装器、不签名、不发布。
- 应用与依赖许可：公开分发范围、应用最终许可选择及捆绑组件的实际归属/许可证核对需作者和最终交付模块确认；本工具不代替法律/发布结论。
- 真实模型：没有本轮真实凭据读取、真实正文外发或付费调用授权；传输、语义质量、限额及实际账单仍待上述明确验收。

## 定向验证

推荐使用带 socket 外发守卫的可重复入口；它只允许实际连接数字回环地址，保留九组定向单测日志、源码前后摘要，以及三协议 × JSON/SSE 的六组确切 preview/confirmation/claim/wire/result/空白质量量表。自动确认仅用于该脚本内固定的虚构回环，不能用于真实供应商。

```powershell
python -B -X utf8 scripts/verify_provider_readiness.py --evidence-directory G:\isolated-provider-verification
```

以下为相同核心的普通 unittest 入口（不含独立外发 socket 守卫）：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path + ';' + (Resolve-Path tests).Path
python -B -X utf8 -m unittest test_provider_acceptance test_custom_providers test_sse_protocols test_native_request_profile test_sampling_parameters test_provider_management -v
```

仅运行本模块和直接依赖的定向套件；完整全量、桌面、打包、V1–V35 旧库综合验收由主整合统一完成。此增量不改 workspace/schema、备份格式、正式采纳或历史数据。
