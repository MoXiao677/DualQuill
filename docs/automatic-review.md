# Automatic chapter review

DualQuill can independently review generated chapters and chapters that are already saved. Select a reviewer connection in the chat settings; it must be enabled and different from the writer connection. The reviewer selection does not switch the writer connection. Review requests use the saved reviewer connection, and reports retain reviewer metadata without credentials.

For generated chapters, the body is saved before review. The reviewer receives the chapter, its outline, writing rules, and selected context, then must return a valid verdict and issues with quoted evidence. Blocking or major issues can trigger up to two narrow automatic revisions. Each revision is saved as a new chapter version and reviewed again. A review or API failure, invalid verdict, or unresolved issues stops the task without marking the chapter passed; saved text and review reports remain available. Maintenance summaries are updated only after the final body passes.

To audit existing chapters, ask in chat to review the desired chapter numbers—for example, “审核已保存的第1至10章，通过的章节不要重写”—or use the `review_chapter` operation. A passing chapter is not rewritten. Reports are saved in the project Materials and include the chapter identity, content hash, source revision, verdict, evidence, and decisions. If chapter text changes, its prior report no longer represents the current body.

Context selection is explicit rather than a claim that the assistant has read the whole book: chapter generation includes the target chapter and outline, up to two preceding chapter bodies, and selected characters and earlier memories. Full worldbuilding and writing rules are retained. Future-positioned and unknown-position chapter memories are excluded; static setting or book-level material may still describe future plans, so the target outline remains authoritative. Material contents can be retrieved by pages with `read_material`. The latest author request is preserved in full. If the assembled model request exceeds the context limit, it stops before sending rather than silently trimming required text.

The chat retains a bounded recent message history. Review status, call counts, and readable report details appear with the job in chat. The export button opens saved-content export options for a whole book, volume, or chapter; unsaved drafts are not included.


## 0.4.19 审核响应修复

审核支持单个 JSON 代码围栏、BOM/首尾空白及不影响必需字段的额外元数据。布尔值、问题分类、严重程度、逐字原文证据及判定一致性仍严格校验；重复键、非有限数值及伪造引文不会被接受。

失败报告保存具体字段/问题索引与脱敏原始回复，聊天可展开查看。不会自动发起额外的付费格式修复请求。前端状态读取遇临时错误会重试状态查询，不重复生成。正文计数明确标注“正文章节”，不代表人物、大纲等全部资料保存数。

审核请求还提供程序生成的原文段落编号和实际汉字数。审核可返回 evidence_id，由程序从同一份正文精确解析引文；未知编号或与编号矛盾的引文会停止并保留诊断，不做模糊匹配。

2026-10-25 本机实际创作验证：独立审核返回有效段落编号与意见，自动窄范围修订后复审通过，报告与旧正文版本保留。该次验证覆盖单章，不代表所有供应商或长篇场景均已验收。未运行完整回归测试套件，未在干净 Windows 环境安装/卸载。

0.4.20 同步修复：人物更新过滤只读元数据，按真实 ID 或姓名定位已有角色，合并合法字段并保留未提供字段。未知业务字段明确报错，脱敏同步响应保存在任务记录，不静默丢弃内容。

0.4.20 本机实际补同步任务已完成，记忆及人物更新保存成功；未重新生成或审核正文。自动生成、审核、修订、复审和补同步分别已有实际记录，尚未对所有供应商做完整回归。
