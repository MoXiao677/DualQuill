# 0.4.7：新汇总模式的统一资格与冻结复核

0.4.6固定产物及两个独验产品RED原样保留，见[原验收](final-local-0.4.6.md)。本版优先修复根因，不用新功能掩盖原失败。

## 资格一致

`include_memory_rollups=true` 时，原始记忆和显式 `search_result` 的memory来源共用同一资格判断：隐藏章、较晚有效位置、previous当前章、归档/未确认、来源过期及未解冲突。被排除的显式检索项只报告原选择ID/版本/hash和原因，正文不进入资料串或报告。`through_current` 明确允许当前章；关闭新flag保留旧显式检索契约及旧冻结编码。

## 发送与采用

新模式按opt-in开关触发发送前和采用前复核，不再仅按是否已有rollup依赖触发。即使没有保存汇总、或预算不够导致没有选入汇总，只要冻结后新冲突使原始/检索来源不再合格，真实start/采用入口也拒绝；事务不写入running/正文/采纳收据，原冻结字节保持。

复核读取当前来源实体、版本、hash、位置、确认和冲突状态，同时使用原冻结revision核对原显式检索选择。任务自身prepare/start/complete事件增加workspace revision不应误判选中资料过期；没有把来源版本/hash重新绑定到新值，也没有重写冻结选择、context_text、request_body或request_sha。初稿/续写的实际来源语义指纹同步使用这一只读复核约定。新模式关闭时旧任务路径不变。

## 有限验证

`run-93-search-fixed.log` 和 `run-96-guard-fixed.log` 分别用父原始RED脚本在修复源码转绿。新增测试总11项（比0.4.6新增4项），含显式current/conflict检索排除及旧行为保持、没有rollup依赖时真实start和采用拒绝新冲突、仅任务事件revision变化仍允许实际执行、真实正文选定检索来源单次loopback成功且冻结不变。`run-97-context-search-writing.log` 连同既有检索/任务回归30项通过，17.733秒。

`run-94-context-root-fix.log` 两个失败为新增夹具把只join且返回None的wait_idle当布尔值，修为等待后断言任务实际succeeded，run-95转绿；不冒称产品缺陷。父相同夹具RED单独保留。父修复源码独验search/guard/原context6/旧库兼容通过；最终完整回归/固定包结果另记，不将当前定向通过称全部验收完成。

保持V32，无新数据结构。真实付费0；正式data/8765、作者窗口/profile/凭据、冻结stage与全局设置不碰，不提交推送签名发布。SSE仍未实现，须本切片完成封存后另做。
