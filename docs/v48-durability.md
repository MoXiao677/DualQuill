# V48 故障耐久与恢复定向验收

任务：05-durability；基于父已接受的 0.4.14/V48 精确 555 路径副本。本轮定向验收完成，副本变更待父独立审核和唯一主整合语义合并；实际执行结果以任务根 `verification.json`、原始日志及 SHA 为准。

## 实测与最小修复

2026-10-21（Asia/Shanghai），父明确授予独占窗口后实际于 09:49:26.682 开始执行：

- 原始终态故障 RED：2 项 / 0.567 秒 / 退出 1；日志 SHA-256 `84705596614d93129382430d620e4319d764bf1044851613c0cdbdc029f6c738`。
- 新增故障夹具：13 项 / 10.497 秒 / 退出 0；日志 SHA-256 `59ad6c8153d0253c16d88b3a68116f0add50a3a50fa4f4e8dbcb374ce2d23bc1`。
- 直接相关回归：70 项 / 72.972 秒 / 退出 0；日志 SHA-256 `55453c6ba47e5a14983fef7b1ea5205e294a2ac254eb531e49dd900700ff202b`。
- 总计 85 次方法执行，最终 83 项通过。原始两个失败均发生在先行通过零部分提交及名额释放断言后：V46/V47 后台 worker 已退出，但同 owner 的页面投影仍显示 `running`。
- 最小修复只涉及 `application/model_planning.py`、`application/rule_reviews.py`：按既有共享 coordinator 口径，持久 `running` 且不在本进程 `parent.active` 中时显示 `interrupted`；规则审核的流预览也使用该显示状态。保留真实持久状态与原始异常，不造终态、不自动重试、不吞错、不退还已开始的次数。
- 新测试验证规则审核可明确恢复中断，正文规划可明确取消；修复后不重发、不生成部分候选。四个新中断点及四个既有备份中断点的自有子进程均经握手退出，11 个已记录 runner/worker PID 的实际 CIM 查询均不存在。

原失败日志、当时产品源及测试源副本、各次运行完整源 SHA、子进程握手记录与资源释放证据保存在任务根 `evidence/` 和对应 `temporary/*/artifacts/`。没有改动 schema、备份校验、迁移映射、历史断言或许可守卫；没有导入 01/03 副本优化。

## 既有覆盖与本轮补充

- `test_history_cache` 已有逐历史快照 SHA、防篡改、跨实例更新、回滚及 JSON 容器一致性。
- `test_author_scope` 已有 Unicode 选区锁、锁外保存 rebase、作者生命周期、末端 SQL 回滚及恢复复制不继承解锁许可。
- `test_author_stability` / `test_drafts` 已有草稿替换失败注入、损坏/权限报告、未保存恢复、项目隔离及草稿不进备份。
- `test_backup_faults` / `test_backup_process_crash` / `test_backup_staging_recovery` 已有备份取消、发布前后清理、四个真实自有进程中断窗口及五个暂存恢复窗口。本轮不重做完整历史套件。
- V46 规则审核、V47 正文规划、V45 图谱、V41 深审、V40 工作流既有恢复复制测试核对原始 wire、source 身份、claims、待核实意见及人工许可。本轮保留这些原断言，选必要定向项回归。

新增 `tests/test_v48_durability.py` 使用小型虚构库验证以下边界：

1. SQLite `max_page_count` 触发真实 `SQLITE_FULL`，正文版本、V48 锁、V42 影响队列、blob、新快照及暖缓存零部分提交。这是 SQLite 容量故障，不填满整块 G 盘。
2. SQLite 只读 URI 触发真实 `SQLITE_READONLY`；另一写连接触发真实 `SQLITE_BUSY`，随后陈旧 revision 仍被拒绝。
3. snapshot 最后一步故障阻止锁 rebase、队列与正文分别提交；解除夹具后正常续写并保持旧历史 SHA。
4. V47 候选转提案与 link 在最后 SQL 故障时一起回滚，同 operation 身份可明确重试且只产生一条提案；不采纳正式规划。
5. V46/V47 后台终态提交失败保留已开始的收费次数归属，结果/候选不部分落盘、名额释放；页面必须如实显示中断，人工取消或恢复后不重发。
6. Win32 不授予 delete-sharing 的自有草稿句柄导致真实替换拒绝，旧草稿完整、错误可见，关闭自有句柄后重试成功。
7. 四个 nonce + PID + 自有路径握手的隐藏子进程中断：SQL 提交前/后、草稿替换前/后。只杀持有的 `Popen`，确认退出；重开分别验证完整旧态或完整新态、继续保存与历史锁完整。

## 执行边界

父资源窗口授予前仅静态读取和准备夹具；不自行改资源队列。测试由任务根 `run_durability.py` 使用 G 盘独立 TEMP/TMP/profile/artifacts、新虚构库、随机 loopback、白名单子进程环境执行。禁止 8765、真实供应商、真实凭据、正式 data、作者窗口/profile、受保护 stage、安装器、npm install、全量固定包重跑、提交推送签名发布。

本轮不是物理断电、OS 关机、硬件掉盘或跨平台/网络盘承诺；实际包及干净 Windows、真实模型质量和费用仍按既有外部门槛独立验收。不改变 schema、原始来源或历史，也不把副本定向通过称为整体产品完成。
