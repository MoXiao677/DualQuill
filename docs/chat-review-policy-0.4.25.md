# 0.4.25 Author-directed chapter review policy

2026-10-26: the author's latest instruction supersedes the previous unlimited automatic revision policy and the old 4000-Han-character upper limit. Historical delivery records remain historical.

- Review priorities: fidelity to the effective chapter and book outlines; causal logic, character facts and timeline continuity; natural prose and the imported anti-AI style guidance.
- Chapters should contain at least 4000 Han characters. No upper word-count limit is specified by this policy. Exceeding the former 4000-character ceiling is not grounds for rejection or shortening.
- Genuine substantive problems remain reportable. Optional polish, subjective preference and unsupported suspicion should not become major or blocking findings.
- Each chapter has a persisted budget of five actual automatic revision saves per job. Initial generation, transport retries and malformed-review retries do not consume this budget. The fifth saved revision is released automatically under the explicit author rule and proceeds to metadata maintenance and later chapters. The acceptance receipt identifies the exact saved body, preserves historical independent findings and distinguishes author-rule release from an actual independent pass. No sixth automatic revision or extra review request is needed. Release is required even if the independent findings remain unresolved; a policy acceptance flag does not rewrite the actual reviewer verdict.
- The composer has a visible stop control. Cancellation uses the existing job endpoint, retains saved content and should display pending cancellation while the task winds down.
- Running progress must refresh chapter review counts, findings and request context; completed tool counts are distinct from work inside an ongoing review or revision.

Implementation is delegated to the designated development relay API. Release evidence and the exact delivery path are recorded in the delivery section below. No test suite, E2E or real-novel model validation is authorized for this change. The currently running application and official author database are not modified by this development work.

## 2026-10-26 本轮交付记录

本轮功能代码由指定开发中转站 Responses / gpt-6.1-sol 写入，统筹完成代码审阅、修复要求、语法检查与构建核对。

- 核心源码：chat_agent.py 实现五次实际自动修订保存预算、第五次直接作者放行、真实审核结论与放行回执分离、资料维护继续执行；chat_context.py 保留工作流放行字段给规划模型，避免只收到 passed=false 后重复审核或误报失败。
- 界面：chat_workspace.js 实时更新审核与上下文回执、保留嵌套展开状态、相同内容不重复替换、停止请求按任务隔离并显示“正在停止…”；index.html / style.css 提供明显中文停止按钮。旧版的清屏新会话和临时故障重连实现保留。
- 规则：正文至少4000汉字，本轮无字数上限；大纲、剧情逻辑和连续性、去AI化文风优先。第五次成功保存后直接按作者规则放行，不再审核或自动修订；仍保留之前的真实审核报告。
- 已完成 Python AST（chat_agent.py、chat_context.py、chat_skills.py、ui/desktop.py）、Node 模块语法、git diff --check、独立目录构建和包内逐项比对。266个源文件、5个ASAR运行文件、运行元数据及第三方声明一致。中途发现的一处行尾空白已清理，最终检查通过。
- 构建目录：G:/AGI/_review-0.4.25-delivery-20261026-063621。
- 启动入口：G:/AGI/_review-0.4.25-delivery-20261026-063621/打开 DualQuill 0.4.25.lnk；使用已有 G:/AGI/DualQuill/user-data profile，未启动入口。
- 源码绑定 SHA256：ffeb317791a3fc04647db8fdb473d4a26a22108084fcd3545dabcc0b5977f67b。
- EXE SHA256：93103d178a8881c5098d18862742a158c476666f80398e8be9a531d3b3c37bff。
- 构建记录：G:/聊天/DualQuill修改备份/revision-five-0.4.25-build-20261026-063621.log；包内核对记录：G:/聊天/DualQuill修改备份/revision-five-0.4.25-package-review.json。

本轮按作者要求未运行测试套件、E2E或真实小说写作/审核模型请求，未启动新包或关闭当前作者窗口，未直接修改正式数据库。语法、构建与包内一致不等于功能验收；由作者实际使用判断。旧窗口仍运行旧代码，不会热更新；旧失败任务不会自动恢复。未提交、推送或公开发布，未覆盖旧交付目录。启动慢及此前其余待办没有由本轮自动标记完成。
