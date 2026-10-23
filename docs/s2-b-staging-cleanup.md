# S2-B暂存清理追加交付

日期：2026-10-14（Asia/Shanghai）。本轮已解决原始日志复现的生命周期误删、末尾失败归属丢失及提交后错误报告，最终237项Python/6项Node/示例通过；作者验收和正式投用未完成。元数据移出窗口中断及恢复目录自动恢复仍未验收。

## 职责、范围与基线

协调聊天`01a13a13-1ca3-7082-b4ac-159015f8bfc4`负责目标、派发、读取进度、证据审查与汇报。执行聊天`01a13a1d-74bd-7250-99ba-9785f793c3a3`经宿主list_threads实际确认，是唯一业务及文档写入者。旧Sol`01a13805-ce5c-7c21-b4a5-dbbadfe9a1a9`已systemError停用。DeepSeek已有测试完成，本轮未重新派单、没有写入授权；测试执行障碍由协调者承接转交，本轮没有这类执行障碍。

仓库为`G:/AGI/AI-Novel-Writer`，HEAD仍为`0a84f89d4cb65eab5867819022839f32eff554f9`。仓库外本轮目录：

`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S2B-sol-fix-20261014-01a13a1d/`

修改前保存119个Git非忽略候选文件hash、Git状态/HEAD及需修改文件before副本。业务仅改`application/backup_staging.py`、`application/backups.py`；测试仅改`test_backup_staging.py`、`test_backup_faults.py`；职责改AGENTS/dev-workflow，状态改TASKS/CHANGELOG/ARCHITECTURE及PRD/ROADMAP/原验收入口，新增本文。`test_backup_process_crash.py`、`manage_backups.py`与所有其他原改动保持本轮起点hash，不提交/推送。

## DeepSeek历史RED与探针审查

历史目录：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S2B-staging-review-20261014-190143/`。最终报告：`C:/Users/Administrator.USER-20260902RM/.codex/visualizations/2026/10/14/01a13a13-1ca3-7082-b4ac-159015f8bfc4/deepseek-final-report.md`。它是审查材料，不直接作为修复指令或通过证明。

- `logs/staging.err.txt`：UTF-16，`Ran 14 tests`、`FAILED (failures=6)`。10个测试方法通过，4个方法失败，其中锁移位方法有cleanup/context_exit/gc三个失败子用例；不能写成8通过/6方法失败。
- 原失败行188/214是末尾新增内容后`.operation.json`丢失；306是正常递归清理跟随junction删除虚构外部哨兵；168是锁移位后的三个生命周期删除未知替换目录。
- `logs/crash.txt`：`Ran 4 tests`、`OK`。PowerShell NativeCommandError包装stderr不表示测试失败；stdout为空也不表示未运行。DeepSeek报告声称父测试退出码1/0，但历史目录未找到独立保存的父进程退出码文件，不把报告声称改成已独立验证。JSONL的exit_code=1属于被强杀的子进程，不是父测试退出码。
- `probe_relocated.py`与`probe_stdlib_cleanup.py`支持自动路径递归缺口。`probe_failures.py`用owner.__exit__后假定残留，实际目录已清理，无法证明末尾产品行为正确；`probe_orphan.py`注入于第一次walk后、第二次核对前，覆盖的是更早窗口，无法反驳末尾_dispose注入。既有两项末尾测试本身已用子进程强杀构造真实孤儿，全部失败断言保留。

## 实现及最小验证

OwnedTemporaryDirectory使用mkdtemp及weakref.finalize，回调不持有self，所有生命周期保存原完整receipt和锁流。活动锁一直持有，清理前核对目录/收据/锁路径及锁句柄身份；只删除固定的原对象。失败释放锁并结束自动生命周期，不在后续GC按旧路径重试。初始化未完成时保守留下未知目录，不递归猜测删除。

显式清理先固定全部原对象并核对第二遍集合，删原payload时保留元数据。末尾发现新文件则保留新内容和原收据。根删除必须先移出元数据；同父独占恢复目录保留原两文件，按原DELETE句柄及固定目录句柄相对移动，禁止覆盖。原根/子对象在枚举和payload删除期间保持拒写共享；只有payload全部删除后，在原marker及父目录仍固定时切换根句柄并核对原identity，此后不再枚举或扫删新内容。

根删除失败时移回原元数据，保持原receipt字节/operation_id/lock_identity。部分移出失败也补偿。遇到同名新增元数据拒绝覆盖，错误报告明确检查原根及恢复位置。根删除成功是提交点；之后恢复目录清理失败仍返回removed=True并附精确残留位置，业务已发布结果保持成功，业务警告不泄露私有路径。

两项live replacement夹具明确验证安全拒绝的退出，不因正确StagingError让with退出变成错误；旧断言不删、不新增skipTest。故障夹具从stdlib TemporaryDirectory改为实际OwnedTemporaryDirectory出口，保持故障含义。新增5项暂存（GC锁关闭、失败不重试、部分元数据移动、同名补偿冲突、提交后残留）和1项发布后StagingError回归。

## Astra协作与Windows诊断

通过spawn_agent请求`gpt-6-astra`、high、fork_turns=none，宿主实际接受并返回`/root/staging_review`；后续使用同一子代理，不另建作者聊天。工具返回不含独立供应商底层模型身份，因此这里只记录请求模型与实际调度接受，不冒称额外验证了底层身份。Astra只读AGENTS及暂存源码/测试，未写文件、未执行测试；复杂问题围绕共享冲突、根重解析切换、元数据补偿和提交边界，由Sol核验落地。

第一版绝对路径移动与固定目录share1发生WinError32。探针依次保存普通/相对/native/权限及pending-disposition诊断原日志：Win32相对RootDirectory返回87，native share1仍拒绝，share3下相对移动成功；未关子句柄的pending删除不能删空根，撤销本身可行但不能替代末尾方案。未绕过保护而把初始root共享改松；Astra指出该做法可让枚举跨入外部junction，本轮已限定终末切换。

真重解析探针`probe_reparse_move.py`通过DeviceIoControl在虚构空目录上设置junction，再向原固定目录句柄相对移动元数据，实测WinError123拒绝；外部无元数据写入、哨兵不变、原元数据保留，清除重解析后核对。`relative-reparse-probe`退出1保留原拒绝；`relative-reparse-assertions`因在DELETE固定句柄仍开时用普通read_bytes触发共享冲突退出1；改用共享DELETE的实际读取方式，`relative-reparse-final`退出0。它们不算新增产品缺陷或假称第一次即成功。

## 实际结果

统一运行器`run_checks.py`位于本轮仓库外目录，使用已有Python3.12.14，清空真实模型环境，仅继承OS白名单；TEMP/TMP/TMPDIR、假配置及产物均指向本轮外部目录。stdout/stderr合并为UTF-8，父测试退出码写入各`*-exit.json`。每个测试子进程只按本测试实时Popen和握手处理，不用旧PID。

| 证据标签 | 实际结果与含义 |
|---|---|
| red-gap | 3项补缺口：2 failures、1 error，退出1；GC锁未关闭、失败清理路径、发布后清理错误确实存在 |
| green-1 | 23项，6 failures/8 errors，退出1；安全哨兵已保留，但元数据移动共享冲突导致正常清理失败，原日志保留 |
| green-2 | 16项暂存+7项故障+4项进程=27项OK，退出0 |
| affected-regression | 包/预检/恢复/HTTP/上传/旧服务/离线103项OK，退出0 |
| core | 第二次修复时234项Python、6项Node/示例通过；不是最终版本数字 |
| red-postcommit | 3项，提交后结果1 error，另2项通过，退出1；作为第三次修复RED |
| green-3 | 最终19项暂存+7项故障+4项进程=30项OK，退出0 |
| core-final | 最终237项Python、6项Node、示例全部通过，选定3项检查均退出0，顶层退出0 |

最终核心报告：`core-final/20261014T121323Z-8ffeab05617b/report.json`，原Python日志在其`regression/python/run.log`。2026-10-14北京时间20:13–20:14完成；检查期间119个候选文件hash无变化、credential_hints为空、git diff --check退出0。专项/受影响/最终core包含重复测试，不能相加当独立用例数。3次有新证据修复/复测已结束，不再追加业务修复；最终文档更新后仅做hash/差异核对。

## 未验证与作者验收

- 四个真实进程强杀场景为采集、恢复事务、发布前fsync之后、发布之后。新元数据移出窗口强杀/物理断电没有验证；不能由这四项推广。进程若在该窗口退出可能保留原根和`.novel-staging-recovery-<operation_id>-<随机值>`，现有inspect-staging仅读原目录，未实现恢复目录自动恢复/定位。补偿被权限、磁盘或新同名文件阻碍也保守保留元数据，不覆盖或扫描删除；新同名碰撞已经测试，其他实际磁盘/权限故障未测。
- 本轮仅当前Windows/本地虚构目录；非Windows安全清理、网络盘、真实断电、百万字长期历史、实际>4GiB未验收。浏览器没有重跑，也不把旧七类结果写成本轮通过；界面/API提供方未改。
- 未打开正式data库、真实凭据，不调用外部小说模型API、不更新/查询操作正式8765、不清理历史暂存、不提交/推送、不进入S2-C。Astra为作者授权的宿主只读协作，费用没有独立测量，不宣称其免费。
- 技术测试通过不等于作者验收或正式投用；由协调者读取本聊天及证据审查后向作者汇报。结束后等待下一项明确任务。
