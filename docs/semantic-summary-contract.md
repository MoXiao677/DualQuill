# 单章模型语义摘要提案（0.4.10 / V34）

此功能在0.4.8完整回归与143源SHA绑定之后实施。C05已新增单章语义摘要专用入口，复用模型审核与人工接受；书/卷模型压缩、自动增量、自动选择和语义冲突判断不在本切片完成范围。

0.4.8/V33已正式接受：841项/514.439秒/OK，full-source-binding为143文件/0差异，原固定产物不再构建或覆盖。按父最新确认继续本C05契约；C06/C14候选模型语义审核留作后续，没有改道。

## 准备与执行

`POST /api/projects/{pid}/model-summaries/prepare`：`request_id`、`chapter_id`、`expected_revision`、`instruction`、`max_output_chars`、`timeout_ms`、`model_options`。不接受调用者自行提供正文/来源快照、自由URL、tools或外部执行许可。返回既有generation task结构与确切冻结请求，准备不外发。

精确请求示例（连接/章节UUID为调用者当前保存的本书实体；数值非真实费用估算）：

```json
{
  "request_id":"<uuid>","chapter_id":"<saved-chapter-id>","expected_revision":12,
  "instruction":"摘要本章已发生事件，勿把计划当事实",
  "max_output_chars":10000,"timeout_ms":120000,
  "model_options":{
    "adapter_id":"configured-http-v2","connection_id":"<custom-uuid>",
    "model_id":"<saved-model>","temperature":0.3,"max_tokens":2048,
    "budget_limit":1.0,"allow_unknown_cost":true,
    "prompt_version":"chapter-summary-json-1"
  }
}
```

model_options可按原契约选填sampling；默认JSON/SSE声明从当前连接冻结，不能从payload自行加stream_mode。任务类型仍为 `audit_chapter`，`task.frozen.parameters.binding.prompt_version`精确为 `chapter-summary-json-1`。新增仅该模式使用的后端字段 `task.frozen.parameters.summary_memory_sha256` 冻结本书记忆集合指纹（不把记忆正文发给模型），旧普通审核省略该默认空字段，旧字节不变。任何正文或记忆集合变化均在实际发送和人工接受时复核，不能通过改revision或补旧hash绕过。

仅选择本书实际有效章的已保存非空正文作为证据；任务冻结正文ID、version/hash、Unicode范围与确切外发body/destination/configrevision/采样/风险预算。其他章节、未来章、章纲/IDEA、人物计划、未确认/冲突记忆和未保存窗口草稿不隐式加入。已有SSE与JSON模式可复用，默认编码仍不改旧记录。

执行/取消/读取复用 `POST /api/projects/{pid}/tasks/{id}/execute`、`.../cancel` 与GET；每个请求明确confirm_external与request_sha256，一次许可、无自动重试。换正文或配置后旧准备拒绝实际发送，冻结不重写。共享slot、deadline、SSRF/TLS/取消与SSE临时预览沿用现有实现。

## 输出与人工门

沿用模型审核的WireAudit/ModelReport/ModelDraft及原始ProviderResponse记录；新任务用可区分的新prompt版本/可省略默认的新模式标志，不能让旧普通审核静默变义。专用输出overview可解释，但findings/bridges必须为空；proposals只允许一项 `kind:chapter_summary` / `assessment:model_summary`，非空标题与摘要。每条证据必须来自被冻结的唯一该章正文，引用序号/Unicode区间/原文完全一致；模型给出处不代表语义正确，界面仍标“模型摘要待核实”。结构错误、工具、无引文、引用规划、跨章/未来/伪造来源一律不产生可接受提案。

模型正文JSON精确schema示例：

```json
{"overview":"待作者核对的本章摘要","findings":[],"proposals":[{
  "kind":"chapter_summary","title":"本章事件摘要","text":"模型摘要正文",
  "assessment":"model_summary",
  "evidence":[{"source_index":0,"start":0,"end":4,"quote":"正文原文"}]
}],"bridges":[]}
```

overview最多4000字符，title为1–300字符、text为1–4000字符，evidence为1–4条。source_index只能0，start/end为Python/Unicode code point索引（含start不含end，emoji算1），quote必须逐字等于被冻结正文切片，不接受UTF-16下标或调用者指定的其他source。bridges允许沿原兼容规则省略（等价空），其他未知字段拒绝。

复用原模型报告查看/证据跳转/接受或拒绝接口，不自动接受；来源变化显示过期且拒绝接受。明确接受只能新增带来源与模型提案出处的记忆，不能覆盖既有不同记忆、正文或已保存汇总；冲突仍要求作者明确保留。重复同一操作幂等且不重复新增。新摘要进入确定性汇总必须另行显式预览/重建。

GET `/api/projects/{pid}/model-reviews/{report_id}` 返回原报告结构，task读取含model_reports。接受/拒绝使用既有 `POST /api/projects/{pid}/model-reviews/{report_id}/proposal`：

```json
{"decision_id":"<uuid>","proposal_id":"<report-owned-proposal-id>",
 "decision":"accepted","expected_revision":15,
 "confirm_inference":true,"preserve_conflicts":true}
```

拒绝时decision为rejected；没有新增自动采纳API。prepare本身不授予执行许可；执行仍必须逐次发送 `{ "confirm_external":true,"request_sha256":"<frozen-hash>" }`。完成任务仅产生model_report/model_memory_proposal，不新增generation正文候选。只有上述人工接受新增memory/history/receipt，正式章节和现有rollups保持原样。

## 兼容和验收

首次专用新模式写入V34，默认值编码省略，旧ModelBinding/FrozenInput/requestbytes/hash保真；完整备份/恢复/复制与降级拒绝已同步接通。复制映射证据实体ID，但保留原始冻结binding和记忆指纹，不能悄悄改写已核对的外发许可。

先RED后实现：准备零外发/仅已保存章、三协议实际请求/合法摘要、坏JSON/无引文/跨章/计划/错区间、发送前/接受前来源与配置变化、取消/超时/SSE异常无提案、人工接受新增且不覆盖/幂等、V34恢复复制与旧库零写读取。隐藏桌面走记忆页准备→确切请求确认→临时预览→引用核对→接受新记忆→显式汇总重建；零真实付费，不将loopback工程验收冒称真实模型摘要质量。

## 当前定向验证

本机run123为35项/35.579秒通过，覆盖新摘要6项、旧模型审核、SSE与汇总上下文；run124真实HTTP鉴权、严格字段、准备零外发、hash许可、明确人工接受与幂等通过。run119缺失模块RED、run120夹具错用model_report（实际为model_review）保留。run125隐藏UI夹具通过API建章后未刷新页面快照，零请求即超时；修正仅刷新夹具，不放松产品保存源边界。

父独立capture-01的source-03为32组/29次loopback通过，含三协议JSON/SSE、15种非法输出、Unicode证据、发送/接受新鲜度、冲突/拒绝/幂等、V34恢复复制和取消85.968毫秒；capture-02真实HTTP另5组/1次loopback通过。父source-01准备阶段零_load断言、source-02漏初始化SkillLibrary均为夹具错误，原证据保留，未放松产品schema。以上是源码定向验证，最终完整回归、隐藏UI及新包验收仍单独记录。

记忆页入口为`#summary-prepare-form`，只读已保存正文为`#summary-saved-body`；冻结后跳转原任务`#model-outbound`，`#execute-model-task`仍须逐请求勾选。完成后`#open-model-report`打开提案，`[data-model-memory]`含独立确认与接受/拒绝按钮。当前连接的读取用于冻结配置绑定，准备阶段零外发、不改ciphertext、不暴露密钥；旧离线及内建零解密契约保持。

run128复现真实UI缺陷：准备时busy=true导致navigate提前返回，冻结任务已保存但不跳转；已改为与既有正文准备一致的直接设置任务视图并渲染。run130读取接受结果过早、run131将旧格式缺省汇总字段与空数组直接比较，均为夹具错误，修正后run132完整5组通过。父source-ui-01另复现新摘要只读正文和引文的首LF被HTML的pre规则吞掉；现用嵌套span保留首LF，并将CR编码为字符引用，库中正文不改。run133用首LF、emoji及HTML字符逐字检查保存正文与报告引文，5组/1次loopback通过，errors/external均空，截图已查看。

run129生成的0.4.9候选取样于busy与首LF修复之前，保留且不覆盖，不是可接受最终包。145源中与修复后差异为app.js与model_tasks.js。ZIP为165438584字节，SHA256 a898441e247784c9fff366c78f6ef7e68c993226cb473e5b2dd2f1b998c46ed1；NSIS为122057245字节，SHA256 9d2e95c090f599d26eace6c1cbe7939c4395162167f4898979150d172ea74fcf。准确候选索引candidate-0.4.9-preserved.json。下一固定版为0.4.10。

run126执行期间源有上述UI修改，且C盘耗尽后部分测试报错，已中止并保留原日志及G盘副本，不能标为完整通过或最终源绑定。最终run134在修复后145源冻结及G盘独立TEMP/TMP下完整848项/496.095秒通过，退出0；结束后145源SHA无差异。0.4.10真包268条目/145源与ASAR一致，摘要5/作者7/上下文5/SSE正文5/JSON长正文4组通过，父摘要32/HTTP5/摘要UI7/旧库与原SSE22/作者7/JSON对话6亦全绿。准确产物与全部失败见[最终本地验收](final-local-0.4.10.md)。磁盘问题未通过放松校验或删除作者资源处理，0.4.9候选及0.4.8正式产物继续封存。
