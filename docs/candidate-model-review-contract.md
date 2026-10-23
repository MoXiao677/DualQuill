# C06/C14有限契约：工作流真实上游候选模型审核

在0.4.10/V34正式接受、848项完整回归及145源绑定之后实施。0.4.10固定产物不再覆盖。本批仅工作流内已完成、未采纳的真实generation candidate，不添加自由正文、临时正文版本或绕过节点归属的单独模型调用入口。

## API与冻结

模板显式新增`kind:model_candidate_audit`节点，`role:auditor`，`source`必须为声明的父节点，参数沿用`context_budget/max_output_chars/timeout_ms`。旧`model_audit`仍只接保存正文，不改旧模板语义。既有`POST /api/projects/{pid}/workflows/preflight`、`templates`、`runs`与`runs/{rid}/step`准备节点；GET运行返回冻结请求和审核。准备零外发。

执行仍使用`POST /api/projects/{pid}/workflows/runs/{rid}/nodes/{attempt}/confirm`，精确字段`operation_id,decision,request_sha256,diff_sha256,authorize_confirmed,confirm_inference,preserve_conflicts,expected_revision`；外发decision=accepted、request_sha256匹配冻结，diff_sha256=null，三个授权布尔为false。模板或原节点许可不能代替本次确认。取消/暂停/恢复/重试沿用原control/retry入口，无自动重发。

后端从实际父节点解析`candidate_snapshot`，冻结candidate ID、producer task/attempt/node、文本SHA、范围及正式目标守卫；candidate.version_id必须为空。外发候选文本、作者审核要求和`input_origin:candidate`，sources唯一项为`source_index:0,kind:candidate,version_id:null,text,project_id,entity_id,task_id,attempt_id,producer_node_attempt_id,text_sha256`，身份及摘要来自真实生产者。typed `wire_source`保留原外发身份，`copy_mappings`初始为空；复制时保留原冻结body/hash和wire_source，追加before/after本地身份映射，链首须等于原身份、链尾须等于当前upstream、文本摘要不变，最多32跳。恢复逐字保留，复制后历史wire身份明确表示原请求来源，新执行仍须重新确认。不发送saved_target正文或其他章/规划/记忆正文。专用prompt版本`candidate-review-json-1`由后端产生，去向、JSON/SSE、采样和预算沿共享绑定。实际发送前复核真实候选、生产者、上游依赖和正式目标/配置；不将候选ID映射成保存章节ID。

runs.roles的审核角色精确示例：`{"role":"auditor","adapter_id":"configured-http-v2","connection_id":"<saved-uuid>","model_id":"<saved-model>","temperature":0.3,"max_tokens":512,"budget_limit":1.0,"allow_unknown_cost":true,"prompt_version":"review-json-1"}`。可选sampling沿原契约。角色配置仍用review-json-1，后台仅为model_candidate_audit任务替换专用提示版本；其他旧model_audit不变。

报告读取沿原`GET /api/projects/{pid}/workflows/runs/{rid}`。对应attempt含`node_kind:model_candidate_audit`、`audit`（overview/findings/method）、`audit_record_id`、`response_record_id`和`upstream`；完成前不含audit。原响应通过`GET /api/projects/{pid}/tasks/{task_id}`的model_results读取，不增加单独报告GET。全量工作区也保留typed workflow_audits，response_record_id关联真实model_results.id。没有记忆接受或正文采纳报告按钮；人工采纳走原human节点。

## 输出与后续

Wire JSON精确为`{"overview":"待核实", "findings":[{"category":"consistency", "statement":"意见", "assessment":"model_opinion", "evidence":[{"source_index":0,"start":0,"end":2,"quote":"候选"}]}]}`。overview最多4000字符；findings最多40条，category仅consistency/repetition/quality、statement非空最多4000、assessment固定model_opinion；每项1至4引文，source_index固定0，Unicode codepoint范围逐字等于候选，不接受UTF16错位。零意见可为空列表，不伪造“正确”或质量合格证明。未知字段、proposals/bridges/tools、伪引文一律拒绝整份报告。

持久化复用append-only`workflow_audits`，新typed output标记`model_candidate_semantic_review_v1`，并关联实际`model_results`响应记录；每条证据保留CandidateEvidence的candidate/producer task/attempt/node身份，version_id为空。不产生ModelMemoryProposal、局部正文提案或新的generation candidate。下游可读取待核实审核反馈，改写另需逐请求确认；写正文仍必须独立human→apply人工差异节点。候选不能转为已确认事实记忆。

## 数据兼容与验证门

首次新节点/任务/报告写入V35；旧字段默认省略，新记录typed解析、严格关系校验、原响应关联、备份精确restore、copy全ID映射、旧V34只读零写与降级拒绝同步完成。旧WorkflowAudit缺省response_record_id继续省略，旧模板/冻结请求bytes/hash不改。

验证覆盖实现前RED、真实三协议JSON/SSE、非法输出/Unicode证据、只发候选不发保存正文、候选生产者及依赖守卫、每次确认、预算/取消/超时、报告不写正文/记忆、人工节点、V35恢复复制及旧链回归。实际模型审核准确度与付费质量不在本机loopback工程验收结论内。尚未实现部分不记为GREEN。
