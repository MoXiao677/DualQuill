# S5-C：模型HTTP适配、有出处审核和人工提案

2026-10-15。本批代码与本地供应商替身技术验证完成。完整core 378 Python/Node6/示例通过；收口补了多出处记忆过期的窄修正，最终13项模型专项＋20项记忆/检索/HTTP通过。378是该修正前的全量证据，未声称最终379项全量实跑；两文件差异及最终专项另存。真实三站生成、语义检出率、双真实模型质量和正式8765未验收。

## 实际入口和门槛

章节写作 → 模型任务（需单次确认） → 选择固定连接和已配置模型编号、要求/温度/输出token/字符/时限、美元风险预算及未知费用许可 → 冻结外发请求供核对。准备只读取保存内容，不取生成凭据或发送小说。任务页展示确切messages请求、摘要、所选adapter/连接/模型和提示词版本；默认生成关闭。仅明确启动启用且非离线维护，并逐任务勾选内容/上限/预算/未知费用风险后，才能执行一次。计价未知时预算是作者风险声明，不能保证美元硬封顶；不允许未知费用或没有正数预算则拒绝。

执行复用唯一registry/coordinator、冻结输入、事件/取消/迟到裁决及原子采纳，不另建绕过的生成路径。本地协议和离线审核保持原表示/入口。模型中心仍使用三个固定连接id与DPAPI；生成adapter只在启用/单次确认后取用所选连接，并复查配置模型未改变。任务API不接收URL或密钥；endpoint替身只在测试内部构造，产品没有该入口。

HTTP实际构造model/messages/max_tokens/temperature/stream=false及Bearer头；不硬编码品牌型号，不自动重试。严格读取JSON、单条assistant文本、完整stop与声明大小/字符界限；401/429、超时、取消、截断、坏JSON、非完成finish_reason或工具调用如实失败/部分，不进可采纳候选。用量只取供应商字段，缺失标未知；本轮字段值来自虚构HTTP替身，不是真实LLM计费。费用一直未知。原始模型文本只读保存，不执行返回工具/URL；HTTP原始包保留上限64Ki字符并标截取，意外密钥回显删除并拒绝候选。没有SSE展示，HTTP截断不是完成输出；取消不保证供应商未计费。

## 审核、摘要和桥段提案

模型审核输出独立typed结构，必须给已保存正文的具体引文及字符区间；服务器从冻结来源补齐/核查版本、摘要和出处。只验证引文存在与范围，不证明摘要或因果推断成立；界面均标待核实，规划只作上下文，不当已发生事实。无效引文/任意额外动作字段拒绝形成报告。原始返回及已验证报告保留，不进入正文采纳。

摘要/事实意见须逐项明确核对/确认才新增记忆及收据，既有不同记忆需明确保留，不覆盖旧记录。任一支持引文变化，接受入口拒绝；接受后也沿提案/收据关联全部引文派生过期，确认状态保持，不因只跟随主出处而继续当新鲜事实。重复桥段建议须先明确确认才进入已有局部提案，正文此时不变；随后作者可编辑、看差异，再走原正式章授权/来源重核/原子恰一次采纳。没有模型自行写正文或自动确认记忆。

## 存储与本轮证据

workspace/完整包正式V6，追加model_results、model_reports、model_memory_proposals、model_bridge_proposals、model_proposal_receipts及明确类型的模型参数/候选/模型来源局部提案。旧V1–V5表示和SQL三表/user_version1/document1保持，实际V5库/包/SQL行在修改前冻结到tests/fixtures/s5c_legacy.json。备份/恢复/复制映射模型任务、响应、候选、出处、接受/拒绝收据、局部提案修订与记忆/全局Skills；冻结外发串/返回/正文中的字面ID不替换。能力元数据亦补全支持V5/V6。

证据根：C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S5C-model-http-20261015-72d4b1/。

| 检查 | 实际结果 |
|---|---|
| 一次完整core | core-evidence/20261015T145840Z-93513207a123/report.json：378 Python/Node6/示例exit0，179文件期间不变、diff0、credential_hints空 |
| 最终新鲜度修正 | red-multisource-freshness有效失败；green及final-model-specialized的13项、affected-memory-contract的20项通过，读状态不改SQL行 |
| HTTP门槛 | green-http-1两项通过；最终core还包含启用开关＋离线同时为真的拒绝反例，不读生成配置/不发送 |
| 最终C界面 | final-browser/s5c-browser-report.json四组passed，external/errors空，含默认关闭/确切冻结/单次执行/候选采纳/模型摘要/桥段转交再修改采纳 |
| 原入口 | affected-local-task-browser三组及affected-workbench通过；旧本地协议、草稿/历史保护保留 |
| 组合恢复复制 | composite-copy通过，且纳入378/最终13：有效记忆＋全局Skill冲突＋图谱＋接受/拒绝桥段＋局部提案修订/采纳＋模型正文候选，原文ID保留、无自动请求 |

原RED和准备失败保留：red-model-http、red-http（构造参数缺失）、red-http-gate（有效门槛失败）、red-bridge-handoff、red-browser。green-model-http-1有4个error：新小夹具未初始化Skills表，原行比较/完整包校验被挡；补齐与产品服务器一致的三表初始化后通过，未删断言。一次联动补丁校验未落盘亦没有当成成功。378后发现并修复的多出处问题有独立RED，原core不覆盖成379；post-core-source-delta.json证明仅domain/memory.py与该测试文件变化，最终33专项覆盖变化，其他core/界面源复用。最终hash/相对起点差异/frozen-contract另存。

core沿仓库外hidden_core.py只隐藏控制台转发原入口。随套件增长，Python验收子进程预算由300调为600秒；模型/API30秒上限、测试选择、断言、浏览器预算不变。没有通过调预算掩盖业务超时。

协议资料以实际抓取为准：DeepSeek官方介绍及Chat Completions参考返回200，缓存摘要/字段核对见official-intro-fetch.json、official-compatible-fetch.json；OpenAI403、Google本机取文失败，未冒称成功或三中转站已实测。入口分别为 https://api-docs.deepseek.com/ 与 https://api-docs.deepseek.com/api/create-chat-completion/ 。

按领导派单直接接续S6同题比较、受控数据模板与持久工作流；S6/S7不计本批完成。不读正式数据/凭据、不发真实生成请求、不动作者8765/窗口、不装依赖或提交发布。
