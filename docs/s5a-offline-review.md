# S5-A：离线审核、出处与记忆提案

2026-10-15。本轮技术交付通过：最终350项Python、6项Node和示例退出0；审核界面四组通过。正式8765和作者数据未加载本次代码。

章节写作 → 离线审核与查重 → 选已保存章节与规则 → 准备任务 → 执行离线规则审核 → 查看审核报告。审核复用同一registry/coordinator，冻结实际保存版本、字面规则、范围和有效白名单；只输出分析报告，不进入正文候选采纳。

支持禁用/必需字面串、规范化后的段落精确重复与SequenceMatcher基础近似比较；时间规则只比较场景明确声明的“第N天”或ISO日期。计算范围、上限、分数及方法可见，不提供语义、因果、原创性或全网检测。证据保存双侧版本、字段路径、精确原文区间与摘要，重复时间字符串按字段布局定位。计划时间不产生事实记忆提案；目前只提供已保存正文的逐字摘录。

问题可确认、误报、豁免、重开及撤销白名单，原因/处理追加保存。白名单按规则、策略及两侧出处摘要匹配。复审保留父报告，展示仍检出/本次未检出/无法判定及新旧版本证据；未改源、白名单、规则或范围不完整不当作修复，“本次未检出”也不等于已解决。

提案展示原文和已有冲突记忆。接受/拒绝在同一仓储事务按稳定操作编号核对，先查既有收据，再重核保存编号和具体来源；接受只新增可确认记忆及历史/收据，冲突需明确保留，不覆盖旧记录，不写正文。相关源改变显示过期，无关后续章保存不使整书报告一概失效。

workspace/完整包正式V4新增六个明确类型集合：review_reports、review_issues、memory_proposals、review_actions、proposal_receipts、rule_waivers；SQL仍三表/user_version1、document1。旧V1–V3原库/包/行字节在实现前冻结为tests/fixtures/s5a_legacy.json，读/恢复不改原数据。新数据完整包恢复及新项目复制映射所有审核/任务/来源/版本/记忆/Skills引用，保留原文和历史；组合含有效记忆、全局Skills冲突、白名单和子报告已实测。

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S5A-offline-review-20261015-41bc0a/`。

| 检查 | 实际结果与记录 |
|---|---|
| 新审核专项 | 4规则＋8业务＋2HTTP纳入最终core；源定位、复审及组合复制各有RED/GREEN |
| 最终完整core | final-core/exit.json退出0；final-core-evidence/20261015T130549Z-6f569f1ff315/report.json：350 Python/Node6/示例通过，161文件期间不变、diff0、credential_hints空 |
| 最终界面 | final-browser-lifetime/s5a-browser-report.json四组通过，external/errors空；affected-workbench原工作台亦通过 |
| 回调退出回归 | red-timeout-lifetime确定性失败，green-timeout-lifetime的全部13项协调器测试通过 |

原失败保留：green-review-1的来源桥接缺chapter_id、red-browser的测试入口拼写准备错误、core的349项中348通过/1项Windows清理error，以及其余原始RED。该清理错误根因是Timer.cancel不能终止已进入且持有SQLite连接的超时回调；最小修复仅在worker移出active前join Timer，新增实际连接屏障测试。没有删断言、skip、重算累计修复或另调模型。最终core经仓库外hidden_core.py隐藏控制台转发原入口，非无shim执行。最终hash/相对起点差异见final-files.json、final-delta.json及diffs。

本次无真实模型调用、费用、小说外发、全局依赖安装或提交发布，统一POST错误收尾/暂存/ACL保持。按已授权顺序继续S5-B手动图谱/别名、规划反馈与局部修改提案，再由领导调度S6/S7；这些功能与真实语义能力尚不计本批完成。
