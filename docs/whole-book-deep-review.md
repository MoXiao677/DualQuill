# 整书分批深层审核（独立副本）

本次只修改 `G:/AGI/_work/w1`，不合并主仓，不打包、不提交、不推送；无真实供应商请求或真实费用。

## 使用

在深层审核准备区勾选“整书分批审核”，配置每批章数（1–40），核对选中的附加资料、检查项目与单次预算，然后冻结整书清单。清单仅选取当前有效、未归档/回收的章节，按章号排序；空书或存在空正文时明确拒绝，不跳过章节。

在清单内逐批点击“准备 / 查看本批任务”，仍须在原任务页核对冻结的实际请求并逐请求确认发送。准备、刷新、重开、汇总都不发送请求。不自动推进下一批，不自动改写正文。作者可随时停止操作或在任务页取消正在执行的批次。

重开同一原库后清单与原任务关联仍在。已完成、等待确认、正在执行的批次均返回原任务，不重新准备；失败/取消/中断默认也只返回原任务。只有“明确重试本批”才生成新的请求，且必须再次确认发送。运行中但本进程没有 worker 的任务，必须先经原任务页的显式恢复处理；不会猜测远端是否已经计费。

## 范围与报告

- 每批保留既有最多 40 章、80 来源、20 万来源字符限制；附加来源也占原上限，超限明确失败，不能把整书内容塞进一次上下文。
- 清单冻结有效章 ID、顺序、版本和身份摘要。准备后续批次前，章范围或任一正文来源发生变化会拒绝重绑，要求新建审核。
- 汇总给出原始冻结章节、各批任务及尝试历史、错误码、报告 ID、逐批报告正文，以及当前已审/未审/过期章节 ID 和覆盖率。
- 成功且存在合法持久报告才计为已审。已审正文修改后从当前覆盖率扣除；新章列入未审，归档/移除的冻结章保留过期标记。空的当前有效范围不记为 100%。
- “全部当前正文已审”表示逐章分批覆盖；没有跨批成对语义比较或二次模型总审，不能把覆盖率当作整书语义质量保证。原单批报告的 `selected_chapters` 断言保持原样。

## 持久化与恢复边界

`storage/review_batches.py` 将不可变清单存于原数据库同目录的 `<原库文件名>.deep-reviews.sqlite3`，默认 SQLite FULL 同步。每次尝试的请求 ID 由清单 UUID / 批次 / 尝试序号确定；任务和合法报告继续由现有工作区原子事务保存。即使在准备任务提交后、返回前中断，重新打开也能按请求 ID 找回原任务。

辅助清单不进入现有 `.nwbak`、工作区 JSON 或项目复制，避免未经版本化改变 V49 及冻结格式。原单批任务和报告仍走原备份格式。需要携带本机清单时须同时保留原库和辅助库；不宣称备份恢复后可凭清单续跑。本次未实现此迁移功能。页面始终显示此边界。

## 变更文件

| 文件 | 变更 |
| --- | --- |
| `src/novel_writer/application/deep_reviews.py` | 新建/列举/查看整书清单、准备单批、确定性尝试身份、显式重试、来源守卫、覆盖率及报告聚合；旧单批行为不变。 |
| `src/novel_writer/storage/review_batches.py` | 新增本机辅助库、不可变清单和创建幂等/版本校验；只读列举不创建文件。 |
| `src/novel_writer/ui/server.py` | 增加 `deep-review-books/list`、`create`、`/{id}`、`/{id}/prepare` 路由；沿用原授权和错误处理。 |
| `src/novel_writer/ui/static/deep_reviews.js` | 整书选择、批量上限配置、持久清单展示、逐批准备/查看/明确重试、已审/未审/失败及聚合报告；保留原任务页确认。 |
| `tests/test_deep_reviews.py` | 原 16 项保留，增加 12 项业务与 1 项 HTTP；直接运行的 `unittest.main()` 移到新增类之后。没有删除或放宽旧断言。 |
| `tests/ui-deep-review.test.mjs` | 原 4 项保留，增加整书清单冻结与单批准备的实际事件/请求验证。 |
| `docs/whole-book-deep-review.md` | 本报告。 |

## 新增测试

1. `test_empty_book_rejected_without_request`
2. `test_exact_batch_and_hard_limit`
3. `test_multi_batch_boundaries`（5 / 2 → 2、2、1）
4. `test_completed_batch_reopen_is_not_reprepared_or_billed`
5. `test_failed_batch_requires_explicit_retry_and_keeps_history`
6. `test_changed_body_is_not_counted_as_current_coverage`
7. `test_manifest_idempotency_and_cross_project`
8. `test_multiple_batches_failure_resume_and_book_coverage`（真实本地 HTTP，4 / 2，50% → 100%，成功批不重跑）
9. `test_pending_cancel_and_resume_needs_new_explicit_confirmation`
10. `test_source_change_blocks_unprepared_batch_and_new_chapter_lowers_coverage`
11. `test_more_than_forty_chapters_stays_bounded`（41 / 40 → 40、1；虚构内存源验证切分，非 41 章真模型质量验收）
12. `test_interrupted_execution_reopens_without_automatic_resend`
13. `test_book_batch_http_auth_bounds_resume_and_report`
14. Node: `whole book creates a durable plan without sending and prepares one explicitly selected batch`

## 验收环境与日志

Python 使用用户指定的 3.12.14 可执行文件。测试临时文件限制在本副本 `.task-temp`。原始 Windows Python 3.12 `mkdtemp(0700)` 在当前沙箱造成目录内 SQLite 无法打开；验收启动适配 `.task-tools/sitecustomize.py` 仅将 `os.mkdir` 的 `0700` 改成 `0777`，不改变业务、模型响应、测试断言或备份权限校验。此适配不能作为 Windows 权限安全功能的通过证据。

Node 默认测试隔离会报 `spawn EPERM`，改用 `--test-isolation=none` 运行原测试；不更改断言。

可复现脚本及实际输出在 `.task-tools/run-validation.ps1`、`deep-final.log`、`affected-final.log`、`new-final.log`、`ui-final.log`；各 `.exit` 保存真实退出码。初始尝试、失败和诊断日志保留。完整未过滤发现曾启动但中途停止，退出 -1，无完成统计，不作为全量验收结果。

最终实测（产品源码冻结后运行）：

| 运行 | 实际输出 | 退出码 |
| --- | --- | --- |
| `unittest discover -s tests -p test_deep_reviews.py -q` | `Ran 29 tests in 18.851s` / `FAILED (errors=3)` | 1 |
| `unittest discover -s tests -p test_*.py -k deep_reviews -k s4a -k s5c -k configured_tasks -k sse_tasks -k shared_execution_admission -q` | `Ran 82 tests in 55.182s` / `FAILED (errors=12)` | 1 |
| 新增业务 12 项 + 新增 HTTP 1 项独立复验 | `Ran 13 tests in 4.263s` / `OK` | 0 |
| `node --test --test-isolation=none tests/ui-deep-review.test.mjs` | `tests 5` / `pass 5` / `fail 0` / `duration_ms 25.0068` | 0 |
| `node --check src/novel_writer/ui/static/deep_reviews.js` | 无输出，语法通过 | 0 |

深层审核原有 3 项错误：

- `test_actual_candidate_producer_quotes_and_copy_identity`
- `test_mixed_sources_restore_two_copies_and_pending_needs_new_confirmation`
- `test_restore_copy_reopen_and_zero_automatic_execution`

这 3 项均在备份暂存流程中抛出 `BackupError: backup/invalid_or_io`，尚未走到复制内容断言。用新建的独立临时父目录保留原异常进行诊断，实际为 `backup_staging_recovery._authority()` 中 `pending.open("xb")` 报 `PermissionError`：沙箱拒绝在按当前 Windows SID 新建的私有目录内写入 `.key-*`；旧目录随后会报缺少 `signing.dpapi`。没有读取真实凭据、绕过 DPAPI/备份权限校验、放宽断言或把这些错误标为通过。

82 项过滤发现包含审核、通用任务/协议/HTTP、模型审核/HTTP、配置任务、SSE 任务和共享名额。12 个错误均落在备份/恢复调用，含重复收集的配置任务测试；不能把重复收集称为额外独立根因，也不能把过滤发现称为完整全仓测试。

最初未启用临时目录适配的尝试为 23 项 / 0.227 秒 / `FAILED (errors=80)` / 退出 1（包含 setup 与 cleanup 权限错误，不是 80 个业务缺陷）。初始实现后 23 项 / 14.030 秒 / 4 errors 包含一个新增测试 fixture 未传 registry 的错误，已修复测试 fixture；3 个备份环境错误保留。新增 API 实现前也已观察到缺少 `create_book` 的失败。所有后续最终统计均以本节日志为准。

## 未实现 / 未验证

- 清单随备份/恢复/项目复制迁移。
- 跨批语义重复成对比较、二次模型整书综合判断或真实模型语义质量。
- 真实付费与账单去重保证；失败/超时/中断请求可能已经计费，明确重试可能再次计费，绝不自动重发。
- Electron/浏览器真实窗口交互、真包安装、打包或发布。已做 Node 事件/请求测试和真实 loopback HTTP，不将其称作桌面端到端验收。
- 不把受影响模块回归称为完整全仓通过。
