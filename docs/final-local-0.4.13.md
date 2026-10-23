# 0.4.13 候选审核重试预览｜有限切片正式接受

本版延续C06/C14真实上游候选模型审核与V35。相对0.4.12的146打包源仅`ui/static/workflow_views.js`变化：每张历史卡带真实`data-wf-attempt`，轮询逐实际attempt_id查找和更新预览；不再按同节点node_id选择第一张旧卡。另更新四个版本元数据文件至0.4.13。全部候选审核后端、保存/恢复/复制/许可及模型协议逻辑不变。

## 原失败与证据边界

0.4.12完整854项/580.448秒/OK及146源+10metadata post-full绑定均通过，但随后实际重试多轮poll暴露UI归属缺陷，不接受、不覆盖。其固定包、全量日志/绑定/初次即时采样通过与后续有效RED全部保留，见[0.4.12原记录](final-local-0.4.12.md)。0.4.11修布局前候选同样封存，0.4.10正式接受产物继续保护。

run173固定0.4.12实际模块DOM探针等待650毫秒后preview误挂failed卡；父实际writer→非法audit失败→新attempt重试的即时采样01通过，但未跨poll。父packaged-retry-ui-02有效SSE尾流保持2.5秒后，旧failed与新running卡同时显示第三次请求文本，1前置组/3次loopback为有效RED。两类证据严格区分，不倒写旧通过。

## 修后进度

- run174相同实际模块DOM探针归属running通过，errors/external空。
- run175修后真实隐藏桌面7组/7次loopback通过；run176进一步保持重试尾流2.5秒跨多轮350毫秒poll，严格断言只挂新attempt、旧failed卡无preview，完整7组/7次loopback通过。包括候选模板/两请求单独确认、1440双栏/390边界、Unicode/HTML、待核实报告、独立人审apply、取消、重开与无自动采纳；errors/external空。
- run177 Node24项及静态JS29语法通过。
- 父capture04前后146源差异为空，正常source-ui-04共5组/6次loopback、source-retry-ui-01加强重试2组/3次loopback均通过；后者尾流额外保持2.5秒跨多轮poll，旧failed卡preview始终为空，新running卡独占第三请求preview，完成后恰一报告且不写正文，errors/external/serverErrors空。
- 上述UI独验GREEN后，`source-manifest-pre-full-0.4.13.json`重新冻结146源及10元数据文件。run178本版完整回归和run179新构建均已完成，不复用0.4.12完整通过替代本版完整验证。

真实付费0，只使用虚构隔离库/profile及随机loopback；未操作正式data、8765、作者窗口/凭据、冻结stage或全局设置，无提交、推送、签名、发布，安装器不执行。真实模型语义质量、费用和干净VM仍未验，不称C01–C18整体完成。

## 固定构建与静态核对

run179唯一构建成功，stage为`desktop/.cache/build-stage-2745abfc264d`。真解包`G:/AGI/_verification/model-summary-20261021/extracted-final-0.4.13`共269条目/146源，逐SHA与pre-full manifest匹配，禁止项空。ASAR main/preload/security/backend/localization五文件逐字一致，版本0.4.13及resources第三方notices一致；Authenticode为NotSigned，安装器未执行。固定包不覆盖。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `AI Novel Writer-0.4.13-win.zip` | 165443051 | `89966273aa48012054e145ca3fd0e78057284dd8afcf600ff8600fab255a3963` |
| `AI Novel Writer Setup 0.4.13.exe` | 122061486 | `16e105d3be2ae99eb54aa852886e8a41308c8e0221258fd09970956f7bdb73e3` |

run180最终真包加强重试桌面7组/7次loopback通过，2.5秒多轮poll后旧failed卡无preview，新running卡独占预览；包含模板、单独确认、1440双栏/390边界、精确引文、独立人审apply、取消与重开，errors/external空。

run181最终真包原作者7组/0模型请求、run182原摘要5组/1次loopback、run183原上下文5组/0模型请求、run184原SSE正文5组/2次loopback、run185原JSON长正文4组/3次loopback均通过。SSE取消218毫秒，JSON实际31.513秒响应完成、取消218毫秒，超时/迟到无候选、恢复库重开和原冻结保真均验，errors/external空。

完整run178已通过：854项/605.084秒/OK/退出0。结束后146源及10元数据与pre-full manifest逐SHA无差异，固定ZIP/NSIS哈希不变，0.4.10正式包及0.4.11/0.4.12候选包哈希均保留。`full-source-binding-0.4.13.json`保存确切完整日志SHA、检查时间、146源/10元数据及全部产物绑定。完整日志SHA为`5f1ee8ef86b89f1f9884f51104a8f9dd34415b233b660ae1f7588ad724c72553`。

## 父最终接受与后续集成

父侧于2026-10-21正式接受0.4.13/V35有限切片。14份最终真包独立报告全部通过，共162组/181次loopback/真实供应商0：候选24、守卫34、HTTP4、摘要32、SSE22、旧库5、V32旧冻结2、V34旧摘要6、正常UI5、加强重试UI2、摘要UI7、作者UI7、JSON对话UI6、SSE对话UI6。加强重试保持合法尾流2.5秒跨多轮poll，旧failed卡不显示新预览、新running卡独占，最终恰一报告且不写正文。父已手看1440/390/重试图；errors/external/serverErrors均为空。

父`final_binding_independent.py`已实际执行退出0，`G:/AGI/_verification/lead-independent-candidate-audit-20261021/final-0.4.13-source-binding.json`为passed，完整日志、146源的pre-full/capture04/current/package、10元数据、固定ZIP/NSIS及14份报告逐SHA匹配。原作者及候选历史证据未改写。父`acceptance-ledger.md`记录正式决定。

主仓此后解冻以整合用户授权的13个并行工作包；各自仅改G盘副本，三件套经唯一主仓整合者审查后按共享接口与schema依赖统一合入，先定向回归再对集成候选统一完整验收，不逐模块重包。该接受只适用于上述固定0.4.13产物和有限契约，不把副本启动当交付，不宣称全程序或真实模型质量、干净VM安装/签名已完成。
