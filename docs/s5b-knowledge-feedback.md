# S5-B：人工图谱、规划反馈和局部正文提案

2026-10-15。本批技术交付通过：最终364项Python、6项Node、示例及图谱界面四组/原workbench退出0。真实模型、正式8765与作者体验不计完成。

入口：章节写作 → 图谱与反馈。可手动维护人物、地点、组织、事件、道具、设定及伏笔节点、别名、记忆链接和关系。每条记录带固定保存编号/实体版本出处、生效章位及人工复核状态；计划来源明确标为计划，来源变化另显示过期，不因复核勾选变成已发生事实。固定出处可读取原保存版本，包含无独立实体版本的世界观。检索支持名称/别名、章位过滤、邻接及最多三层/100节点链；本书实体引用逐项核对，不跨书猜测关系。

别名合并先预览两个节点、关系和记忆链接影响，明确确认后追加节点映射/别名/关系修订，原记忆和正文保留。恢复追加新修订；合并后相关节点或关系改变、增加关系时拒绝恢复，保留后续编辑。合并/恢复身份及历史可重开核对。

规划反馈由作者基于已保存正文/明确结构资料填写，只建议一个全书大纲或章节细纲文本字段。界面展示旧值/新值/差异、后续章节及人工伏笔/记忆链接影响，保留“未判断语义矛盾或伏笔已解决”的限制。结局或其他文本字段可明确锁定/解锁，锁同时约束原手动保存入口及提案接受。接受/拒绝持久化；接受重核来源与目标版本，仅改单字段并追加原规划版本与收据。不能从计划提炼已发生事实，也没有语义规划AI声明。

查重问题可选择双侧之一，准备精确原文区间的删除/合并/作者改写提案，保留双侧出处、完整旧稿/新稿和差异。作者可修订替换文字，重新看最新提案版本再采纳。接受在同一仓储事务重核双侧来源、提案修订、保存编号及正式章明确授权，正文新草稿/原版本/整书快照/收据一起提交；失败一起回滚。拒绝/取消不写正文，原样修改拒绝。响应丢失重试同身份返回原收据，恰一次追加正文；旧记忆不会被重新确认。

workspace/完整包正式V5追加九个类型集合：knowledge_nodes、knowledge_edges、graph_merges、graph_restores、planning_proposals、planning_locks、planning_receipts、local_edit_proposals、local_edit_receipts。节点/关系/局部提案使用显式revision与edit_id的追加修订；不是藏在正文/浏览器存储中的JSON。SQL三表/user_version1与document1保持。完整包恢复及复制映射所有新旧实体、来源版本、合并前快照/修订身份、记忆和提案收据，原文字面ID不替换。实际V4库/包/SQL行在实现前冻结到tests/fixtures/s5b_legacy.json（内含旧1–3原oracle）；旧V1–V4读取字节与恢复行保持。

证据根：C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S5B-knowledge-20261015-8f2c19/。

| 检查 | 本轮实际结果 |
|---|---|
| 业务专项 | green-knowledge-2：11项通过，含合并恢复冲突/来源与章位/锁/正式授权/无变化/触发器回滚重试/V5全历史复制/旧1–4原始oracle |
| HTTP | green-fixed-source：3项通过，含只读固定出处与未授权/跨书拒绝 |
| 最终界面 | final-browser/s5b-browser-report.json四组通过，external/errors空；含固定出处、别名合并恢复、锁、差异和丢响应恰一次采纳 |
| 受影响工作台 | affected-workbench退出0，源码期间不变 |
| 一次完整core | core/exit.json及core-evidence/20261015T133936Z-a9b6a1141862/report.json：364 Python/Node6/示例退出0，169文件期间不变、diff0、credential_hints空 |

RED及原失败均保留：初始缺模块/入口、HTTP、固定出处、历史来源守卫；green-knowledge-1为8通过/1时间戳预期失败，原实体保存本应更新updated_at，之后独立核对全部其他字段及新版本时间；red-repository-guard最初被收据保存编号挡住，改为结构有效的反例后red-repository-guard-valid才有效失败，再补历史层来源验证。green-browser-1因包裹select的label混入选项文本停在精确标签定位，改用每个select/textarea唯一id+独立label for后通过，未放宽语义定位。累计记录不重算、不调用额外模型。green-knowledge-2运行中新增HTTP测试文件的hash变化如实保留；最终完整core与界面均无源码变化。

core经仓库外hidden_core.py仅隐藏控制台转发原入口。最终hash/相对起点差异及冻结POST/暂存核对见final-files.json、final-delta.json、diffs与frozen-contract.json；core后只同步当前三文档顶部及本交付。

按领导最新派单直接接续S5-C：共享协议的真实HTTP适配代码及有出处的模型审核/摘要提案，只用本地供应商替身验证。S5-C、S6及S7尚未计完成；没有真实站点生成、小说外发/费用、正式数据/凭据/8765、机器依赖安装或提交发布。
