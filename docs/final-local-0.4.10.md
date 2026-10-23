# 0.4.10 单章模型摘要本地验收｜2026-10-21

本版C05仅实现专用单章模型语义摘要：唯一已保存正文、逐请求明确确认、三协议JSON/SSE、精确Unicode引文、待核实提案与人工接受新增记忆。复用既有registry/coordinator、ModelReport、记忆历史与收据；不新增正文候选，不自动覆盖/增量/重建汇总。首次写入V34。完整契约见[摘要说明](semantic-summary-contract.md)。

## 冻结与证据

最终工程验证证据根为`G:/AGI/_verification/model-summary-20261021/`；早期定向证据根为`%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。所有新增测试TEMP/TMP/隐藏桌面shell/profile仅在独立子进程指向G盘，不改全局设置。

修复后145源已以`source-manifest-pre-full-0.4.10.json`冻结。run134完整848项通过，496.095秒，OK/退出0。结束后145源逐SHA无差异，`full-source-binding-0.4.10.json`于2026-10-21T01:36:18.063281+08:00绑定完整日志SHA、源及固定ZIP/NSIS；完整日志SHA256为`9b1a95fd2cea9fc81047d73d57031fd8b2ed7a9a441e44413126321fff968ffa`。run136 Node24项已通过，29个静态JS语法通过。

run135唯一固定构建成功，独立stage为`desktop/.cache/build-stage-0d6421c6f1d9`。真解包`G:/AGI/_verification/model-summary-20261021/extracted-final-0.4.10`共268条目，145后端源与冻结manifest逐SHA相同，禁止项空。5个ASAR CJS、版本和独立resources第三方notices逐字一致；安装器NotSigned，未运行。初次审计误从ASAR内部寻找notices，改为实际resources路径后通过，未改包。对应package-audit-final、asar-audit-final、signature-final三个0.4.10记录。

| 固定文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/s7/AI Novel Writer-0.4.10-win.zip` | 165438619 | `f3c483c184efa3e29fa201a2c314fd620f7baa864bd9c65bd45eb2cca37cf67d` |
| `dist/s7/AI Novel Writer Setup 0.4.10.exe` | 122057234 | `d0d432aec30861c3a5ca062cf3efb013be9489592b200c315c48272b6ed1d0d0` |

该固定构建不再覆盖；若最终发现产品缺陷，另开新版本并保留本次证据。

## 定向与独验

- run123摘要/旧模型/SSE/上下文35项，35.579秒通过；run124真实HTTP鉴权、严格字段、prepare零外发、hash许可、人工接受及幂等通过。
- run132隐藏桌面5组通过；run133进一步保留首LF、emoji和HTML字符，逐字检查只读正文和报告引文，完整5组/1次loopback通过，errors/external空。截图已查看。覆盖显式冻结/执行、合法终止前无报告或记忆、人工接受不改正文/旧汇总、另行明确汇总保存与重开不重发。
- run137最终真包摘要同一隐藏桌面5组/1次loopback通过，errors/external空，profile与全部临时文件位于G盘。
- run138最终真包原作者7组通过，模型调用0；含正文/人物/分卷保存重开、GB18030导入、原生下载、回收恢复、完整备份独立恢复/复制及恢复库再次续写重开。
- run139最终真包汇总上下文5组通过，模型调用0；默认关闭、明确启用、排除当前/未来、去重、冻结版本和重开保持通过。
- run140最终真包旧SSE正文5组通过，2次loopback，取消217毫秒，原始候选/冻结保真、临时预览转义与重开不重发均绿。上述errors/external均空。
- run141最终真包原JSON长正文4组通过，3次loopback，31.635秒响应完成、取消219毫秒、1秒总超时与重开不重发；errors/external空。
- 父capture01/source03独立32组/29次loopback通过；父capture02真实HTTP5组/1次loopback通过。
- 父capture03修复后145源稳定，独立后端32组/29次loopback、HTTP5组/1次loopback及真实隐藏桌面7组/3次loopback均通过；桌面保留首LF强等式、三段Unicode/HTML、采纳与另行汇总、第二轮取消、第三轮流中退出重开不重发。source-ui02为父未等异步选章重绘的夹具竞态，source-ui03等待选章与正文确切匹配后通过。
- 父0.4.10静态真包审计268/145，与capture03和当前源0差异，ASAR一致，ZIP/NSIS字节哈希同表，NotSigned未执行。
- 父最终真包摘要32组/29次loopback、HTTP5组/1次loopback、摘要桌面7组/3次loopback、旧5库含2冻结、旧V32两冻结、原SSE22组均通过。原作者7组、原JSON自然对话6组亦通过，后者首响应32.002秒/2次loopback，无UI异常或外网。父独立读取run134完整终态，再对145源逐个SHA重算0差异、固定ZIP/NSIS哈希不变，正式接受0.4.10/V34有限切片。父最终绑定为`G:/AGI/_verification/lead-independent-model-summary-20261021/final-0.4.10-source-binding.json`。父账本为`%LOCALAPPDATA%/AI-Novel-Writer-review/lead-independent-model-summary-20261021/acceptance-ledger.md`，大产物证据位于G盘同名仓外目录。

## 保留的失败与候选

run119缺失模块为实现前RED；run120调用不存在model_report为夹具错误，改为model_review后通过。run125直接API建章后未刷新UI为夹具错误。run128是真实busy跳转缺陷，已修；run130异步接受未完成即断言、run131旧缺省数组比较为夹具错误。父source-ui01首LF显示缺陷真实，已以span和CR字符引用修复，未改原正文或放松断言。

0.4.9/run129是修复前候选，取样145源，与修复后源差异app.js/model_tasks.js，不覆盖且不接受。ZIP 165438584字节/SHA256 `a898441e247784c9fff366c78f6ef7e68c993226cb473e5b2dd2f1b998c46ed1`；NSIS 122057245字节/SHA256 `9d2e95c090f599d26eace6c1cbe7939c4395162167f4898979150d172ea74fcf`。父静态审计268条目/145源，确认精确匹配capture02，禁止项空，但状态仅static_only_not_accepted。

run126期间源被修正且C盘耗尽，已中止，原日志与G盘副本保留，不计完整通过。父首两次后端夹具错误（configured准备零_load断言、漏SkillLibrary导致strict schema拒绝）均已纠正，未改产品校验。父候选解包因磁盘耗尽而不完整的167772160字节exe转存G盘，原故障日志保留。

## 范围

真实付费0，只访问虚构loopback供应商，未测试真实模型摘要质量/费用或干净VM。0.4.8正式接受产物及全部旧记录封存，不覆盖。不操作正式data、8765、作者窗口/profile/凭据、冻结stage或全局配置；不提交、推送、签名、发布，不运行安装器。
