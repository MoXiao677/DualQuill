# 0.4.12 候选模型审核候选｜完整回归通过，重试预览缺陷未接受

本版仅C06/C14真实上游候选模型审核：显式`model_candidate_audit`、候选唯一文本及真实candidate/producer身份与SHA、专用`candidate-review-json-1`、待核实意见及严格Unicode引文、JSON/SSE共享传输、独立人审→apply。旧`model_audit`仍只审核保存正文。V35恢复逐字保留，复制映射本地身份并保留原外发来源及typed映射链。没有自动事实记忆、正文采纳或语义质量保证。完整边界见[有限契约](candidate-model-review-contract.md)。

## 当前冻结

证据根`G:/AGI/_verification/model-summary-20261021/`。`source-manifest-pre-full-0.4.12.json`冻结146源及10元数据文件。run164完整Python854项/580.448秒/OK/退出0。结束后146源与10元数据逐SHA无差异，`full-source-binding-0.4.12.json`于2026-10-21T02:17:23.486171+08:00绑定完整日志SHA256 `6b65048592efbffe9d37d7eed7fce6e3e621a1abdf1e6f183055b1d1a1f2e0a9`、固定ZIP/NSIS及未覆盖0.4.10/0.4.11产物。run166 Node24项、29静态JS通过。完整回归绿不代表所有UI边界已覆盖，见新增重试问题。

run165唯一固定构建完成，stage为`desktop/.cache/build-stage-f6cefa06e320`。真解包`G:/AGI/_verification/model-summary-20261021/extracted-final-0.4.12`共269条目/146源，逐SHA匹配冻结manifest，禁止项空。ASAR的main/preload/security/backend/localization五文件与源码逐字一致，版本0.4.12和resources第三方notices匹配；独立Authenticode为NotSigned，安装器未执行。父静态审计也核对269/146且与capture03、当前src差异为空。固定产物不再重建或覆盖。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `AI Novel Writer-0.4.12-win.zip` | 165443041 | `73dcc3288ffb8fddb53cd982258ca10418ae38343fa7fa26956d6ee23634fc52` |
| `AI Novel Writer Setup 0.4.12.exe` | 122061419 | `e44bed20c5fe35e5cb79b3900e871bde9447146652576d8cb4c32079a837ae0d` |

0.4.10正式接受产物不覆盖。0.4.11已实际构建为修布局前候选并封存哈希，不接受、不覆盖；其run160完整回归在视觉RED后中止，未计通过，见[候选原记录](final-local-0.4.11-candidate.md)。0.4.12修正仅增加工作流局部自动换行/按钮宽度/容器约束，保留所有控件。

## 已完成定向验证

- run150身份与双次复制3项通过，run152扩展为5项/78.810秒通过，含三协议JSON/SSE、六类非法输出、Unicode引文、取消/超时/截断、发送边界正文变动、完整V35恢复和两次copy保留binding与typed来源链。
- run154真实HTTP1项通过，跨书/不存在run或template均404，GET/POST均不改两书状态。父source-http-01发现的跨书GET500为真实产品缺陷，按缺失实体根因修复，未放宽鉴权/严格字段。
- run157隐藏桌面5组/4次loopback通过，完整候选→模型意见→人工→apply、临时SSE转义、取消与重开不重发。run163新增1440双栏每按钮边界/内容无横滚与390窄屏检查，6组/4次loopback通过，errors/external空。修后截图已人工查看，取消与刷新在第二行可见。
- 父独立source-01主链24组/46次loopback；source-guards-02守卫34组/64次loopback；修后source-http-02真实HTTP4组/2次loopback；capture03/source-ui-03隐藏桌面5组/6次loopback均通过。UI独验含取消等待控制落地、第三轮流中真实退出与重开、恢复许可清除、1440双栏和390边界。源捕获均前后差异为空。
- run167最终真解包候选桌面6组/4次loopback通过，包含1440双栏所有控制边界、390窄屏、严格typed引文、人工apply、取消和重开；errors/external空。
- run168最终真包原作者7组/0模型请求通过：正文/人物/分卷重开、GB18030导入与原生下载、回收恢复、完整备份下载/独立恢复/复制及恢复库再次保存重开。
- run169最终真包原摘要5组/1次loopback通过，首LF/emoji/HTML原文与引文精确保留，接受记忆不改正文，汇总另行明确保存，重开不重发。
- run170最终真包原汇总上下文5组/0模型请求通过，默认关闭、显式previous/through_current、当前/未来排除、去重、V32冻结依赖与重开保真。以上errors/external均空。
- run171最终真包原SSE正文5组/2次loopback通过，取消216毫秒；临时转义预览、候选/冻结保真、取消无迟到候选及重开不重发。
- run172最终真包原JSON长正文4组/3次loopback通过，实际31.481秒响应完成、取消224毫秒、1秒冻结总超时及重开不重发；errors/external空。
- 父最终真包候选24/守卫34/HTTP4、原摘要32、原SSE后端22、旧5库含2冻结/V32另2/V34另6三协议JSON/SSE任务物理零写均通过。最终exe候选UI5/摘要UI7/作者7/JSON自然对话6/原SSE自然对话6均通过，截图已看且取消/刷新正常换行；真实付费0，UI errors/external/serverErrors空。

## 新增重试预览缺陷与封存

完整回归结束前只读发现新轮询按node_id寻找卡片，同节点存在多个attempt时会选中旧失败卡。run173在固定0.4.12真实exe内加载实际workflow_views模块，挂载两个尝试并等待650毫秒跨轮询；实际preview所属状态failed而预期running，errors/external空，为有效DOM绑定RED，证据`retry-preview-probe-0.4.12.json`。父独立实际writer→首次audit失败→明确重试→有效SSE的首次即时采样2组/3次本地请求通过，不能记为父RED；父随后延长尾流2.5秒核查轮询时序。两类证据不得混称。

0.4.12固定包、run164完整绿与post-full绑定保留，不覆盖、不提前接受。0.4.13改为每张卡显式data-wf-attempt并按实际attempt_id更新预览；run174相同实际模块DOM探针所属running通过。修后真实重试、完整回归和新固定包均须另验。

父`packaged-retry-ui-02/report.json`随后实际复现有效RED：首次audit非法失败、显式重试、有效SSE尾流保持2.5秒跨多轮poll，旧failed卡与新running卡同时出现同一临时文本。1前置组/3次loopback/真实0；此前即时采样01的2组通过仍原样保留，注明时序覆盖不足，不倒写为失败。根因为按node_id找到第一张旧卡，而非按真实attempt_id定位。

## 保留原失败

run142实现前新节点RED；run143–145 typed union/新参数类型守卫与专用报告落盘校验错误已修；run146/147诊断保留，run147脚本退出0不代表内部单测通过。run148旧memories省略字段为夹具错误，修正后run149通过。

run151取消后仍step及截断流精确Content-Length造成预览提前结束为夹具问题，修正后run152通过。run153导航选择器、run155取消请求尚未完成即放尾流均为夹具问题，run157修正后通过。run158版本断言/notices未同步，run162/166版本同步后Node24通过。父source-guards-01误要求拒绝节点连生命周期失败事件也不能追加，改为仅允许精确失败attempt/events，其他集合强等式；父source-http-01跨书500、source-ui-02-visual-red控制栏溢出为真实缺陷，原证据全部保留。

## 验收边界

真实模型付费0，仅虚构临时库/profile、随机loopback端口和隐藏桌面/CDP；全部新TEMP/TMP仅进程内指向G盘。正式data、8765、作者窗口/profile/凭据、冻结stage、全局配置不动；无提交、推送、签名、发布，安装器不运行。真实模型意见准确率/长篇语义质量、真实费用与干净VM仍未验；不宣称C01–C18整体完成。此候选因新增重试预览归属问题未接受，0.4.13另行验收。
