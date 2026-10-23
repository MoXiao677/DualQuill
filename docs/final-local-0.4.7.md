# 0.4.7 固定包验收｜2026-10-21

本版修复0.4.6新增汇总模式的两个真实产品RED：显式memory检索绕过当前章/冲突排除，以及没有rollup依赖时漏掉发送/采用复核。原0.4.6产物、825项绿和两个额外RED同时保留，不改写旧结论。完整回归829项通过（505.075秒，run-98，OK），父已正式接受本有限切片。实现说明见[上下文守卫](context-guards-0.4.7.md)。

## 固定产物

唯一构建 `run-99-build-0.4.7.log`，独立 `desktop/.cache/build-stage-8597ff57e570`，不覆盖旧版。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/s7/AI Novel Writer-0.4.7-win.zip` | 165428485 | `f24a33162ad6815ab6951b37a46af384318f0f2a48ab371bef5607be9a8ad672` |
| `dist/s7/AI Novel Writer Setup 0.4.7.exe` | 122048279 | `ed40caba72fa275cda99daccb60ca48b83e12276be57a724e6abca49ed2748eb` |

证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。`package-audit-final-0.4.7.json` 真解包 `extracted-final-0.4.7` 共264条目，141后端源码与工程及 `source-manifest-final-0.4.7.json`逐SHA一致，无禁带。`asar-audit-final-0.4.7.json`核对5个CJS、版本和notices；`signature-final-0.4.7.json` 为NotSigned，安装器未执行。父独立核对同一哈希/字节数、264/141及ASAR匹配。

## 已验证

- `run-98-0.4.7-full.log`：829项通过，505.075秒。结束后141源码逐SHA核对无差异，`full-source-binding-0.4.7.json`绑定本次完整测试与上述固定ZIP/NSIS哈希；本版不再重建。
- `run-97-context-search-writing.log`：新增上下文11项及原检索/任务回归共30项通过，17.733秒。包含真实start/采用拒绝新冲突、只发生任务事件revision时允许正常实际发送、原冻结不变。
- `run-101-search-packaged.log` 与 `run-102-guard-packaged.log`：使用父两个原RED脚本在最终解包直接转绿，不改脚本断言。
- `run-100-context-packaged.log`：最终解包上下文桌面5组通过，模型调用0、errors/external空。
- `run-103-node-0.4.7.log`：Node24项通过。29个JS与上一固定版相同，静态语法通过记录保持。
- `run-104-writing-packaged.log`：最终解包长正文4组通过，真实31.639秒、取消218ms、1秒超时、重开不重发；3次虚构loopback，errors/external空。

父独立证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/lead-independent-context-guards-20261021/`：最终包 `packaged-search`、`packaged-guard`、`packaged-lifecycle`4项（无rollup依赖的正常检索任务可发送/采用/幂等，以及新增冲突后采用原子拒绝）、`packaged-context`6组、`packaged-legacy`5库含2旧冻结、`packaged-context-ui`5组、`packaged-search-ui-01`4组、原对话6组（首轮31.942秒）及原作者7组全部通过。UI errors/external空、真实付费0，详见父 `acceptance-ledger.md`。

## RED 与边界

0.4.6两项为实际产品失败，本版统一资格判断且按opt-in触发复核；不是削弱原测试。新模式的检索资格复核保留旧冻结revision，比较当前实际版本/hash/位置，防止仅任务prepare/start/complete事件让合法检索任务误判过期；不替换请求体或许可。

`run-94-context-root-fix.log` 两项为新增测试误断言 `wait_idle` 返回值；该方法只join并返回None，修为wait后断言真实succeeded，run-95/97通过。父同类run05夹具RED另保留。父真实检索UI前两次误走顶层retrieval导航，修为memory子入口后最终包4组通过，均不是产品RED。

保持V32与旧flag关闭契约。真实付费0；正式data/8765、作者窗口/profile/凭据、冻结stage、author-preview及全局配置未触碰；无新聊天/子代理、提交推送、签名发布或安装器执行。SSE、模型语义摘要、自动记忆更新、真实供应商质量/费用与干净VM仍未齐。下一版在本版完整回归与141哈希封存后实现自建连接明确选择的SSE，默认JSON；流中只作临时预览，合法终止后才产生候选，取消/断流/工具/超限/凭据echo不产生候选，不重试。
