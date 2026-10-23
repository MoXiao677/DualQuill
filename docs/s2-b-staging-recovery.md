# S2-B：暂存清理中断后的显式恢复

日期：2026-10-14（Asia/Shanghai）。这项中断恢复收口的技术验证已完成：专项39个测试方法、完整246个Python测试方法、6个Node测试及虚构示例检查全部通过。它不等于整体S2完成、作者验收或正式服务已更新；S2-C及S2其余任务未开始，本轮也未启用AI创作。

## 1. 接管与本次变更

旧Sol已新增`application/backup_staging_recovery.py`、创建时权威归属登记、清理阶段持久意图及显式CLI恢复入口，但其green-1退出码1，随后执行聊天中断。本轮保留原实现和所有未提交内容，由协调者审查范围、派发并读取证据；接管Sol只做静态分析、最小修复、测试编写及本文档，DeepSeek负责本轮全部测试、现场判别和原始证据输出。未向中断聊天重复派发，未由DeepSeek修改项目文件。

本轮业务修复仅在`backup_staging_recovery._private_root`：旧代码直接比较手写完整用户SID的SDDL与Windows读回的字符串。DeepSeek核对原始SID、owner、两条ACE及控制位后确认它们等价，失败来自SDDL渲染形式不同。现在预期与实际描述符都经同一`ConvertSecurityDescriptorToStringSecurityDescriptorW(revision=1, OWNER|DACL=5)`渲染后严格比较。仍要求当前用户owner、受保护DACL，以及仅当前用户和SYSTEM的两条OICI完全访问ACE；没有硬编码用户别名、启用特权或重设既有目录ACL。原报告对别名身份的矛盾推断不作为实现依据。

新增权限回归的首次执行发现一个夹具问题：输入`D:`创建目录，落盘仍为受保护DACL，未建立负例前提。只修正测试：在本用例新建的`unprotected`目录上以原DACL调用`SetNamedSecurityInfoW(0x20000004)`解除保护，读控制位明确断言`protected=false`。Windows回填继承ACE后才记录ACL基线，再保留产品拒绝、调用前后ACL和虚构哨兵不变断言。额外主体、缺SYSTEM的负例也核对实际前提；没有删除断言或增加skip。生产校验在这次夹具修订中保持冻结。

## 2. 已实现的恢复契约

真实创建暂存时登记可信记录，绑定原目录、原marker及lock对象身份、完整receipt和marker字节哈希。权威记录使用新生成的HMAC材料签名，材料由当前Windows用户DPAPI保护；这里只调用字节工具，不加载API连接配置或真实凭据。恢复操作另有持久的per-operation OS锁，不按PID推断活动状态。

移出元数据前写入`prepared`及恢复目录身份，删根前写入`root_remove_intent`，删除每份元数据前写入对应对象删除意图。原根仍可信存在时，显式恢复只归还原元数据，保留根内其他内容；原根已缺失且有可信删除意图时，只完成已登记元数据和已登记空恢复目录的清理。完成记录保留，重复调用可核对相同结果。

接口必须提供原暂存目录、恢复目录及对应操作UUID，不扫描发现、不自动恢复、不自动清理未知目录。路径、对象或签名不符，重解析点、同名新对象、残缺记录或活动锁无法安全确认时保守保留；检查不能给未知目录补发可信归属，也不能重建缺失的key或gate。它不提供正文恢复、已有库合并或旧格式迁移。

## 3. CLI用法

从仓库`G:/AGI/AI-Novel-Writer`执行。以下尖括号内容必须替换为原操作记录中已保存的确切值，不能按目录前缀认领、猜路径或新生成UUID：

```powershell
python -B -X utf8 scripts/manage_backups.py inspect-staging-recovery --directory "<原暂存目录绝对路径>" --recovery-directory "<原恢复目录绝对路径>" --operation-id "<原operation_id>"
python -B -X utf8 scripts/manage_backups.py recover-staging --directory "<原暂存目录绝对路径>" --recovery-directory "<原恢复目录绝对路径>" --operation-id "<原operation_id>"
```

`inspect-staging-recovery`核对归属及活动锁，不修改被恢复对象；可恢复结果包含`can_recover`、原路径状态及元数据位置。`recover-staging`执行上述两种受限操作，成功返回`restored`或`completed`。活动锁返回`active_or_locked`且`can_recover=false`，调用方必须检查结果字段，不能只把CLI退出码0解释成已经恢复。CLI的受控错误退出码为1；本轮没有新增UI、后台恢复或正式服务入口。

## 4. 五个真实强杀窗口

测试只在本轮独占虚构目录运行。父进程先核对自己创建子进程的PID、nonce和指定窗口握手，再强杀该子进程；之后由新CLI进程依次inspect、recover、再次recover。不是根据历史PID结束进程，也不是物理断电实验。

| 窗口 | 原根状态 | 最终结果 | inspect / recover / 再次recover实际退出码 |
|---|---|---|---|
| 移出第一份元数据后（move_one） | 仍在 | restored，原对象归还 | 0 / 0 / 0 |
| 移出两份元数据后（move_two） | 仍在 | restored，原对象归还 | 0 / 0 / 0 |
| 原根删除后（root_removed） | 缺失 | completed | 0 / 0 / 0 |
| 元数据删除后（metadata_removed） | 缺失 | completed，核对持久删除意图 | 0 / 0 / 0 |
| 恢复目录删除后（recovery_removed） | 缺失 | completed，重试不重建路径 | 0 / 0 / 0 |

五个窗口均验证幂等、恢复目录消失及外部哨兵字节不变；原根仍在的两个窗口还核对原operation_id、lock_identity和directory_identity。五个被强杀worker的实际退出码均为1，属于预期中断；最终父测试进程实际退出码为0。

## 5. 逐轮结果与计数

四模块专项命令：

```text
python -B -X utf8 -m unittest -v tests.test_backup_staging_recovery tests.test_backup_staging tests.test_backup_faults tests.test_backup_process_crash
```

| 轮次 | 方法级结果 | 实际父进程退出码 | 说明 |
|---|---|---|---|
| 旧green-1及DeepSeek修复前核对 | 35方法，2通过、33失败 | 1 | 原始19 failures/17 errors包含subTest记录；不是36个方法 |
| 第二轮，规范化修复后 | 39方法，38通过、1个方法失败 | 1 | 该方法内unprotected子用例前提未建立，另两子用例通过；5个恢复窗口及原30关联方法全部通过 |
| 第三轮，夹具修正后 | 39/39通过，0失败、0错误、0skip | 0 | 唯一一次专项执行，不重复运行计数脚本 |
| 随后首次实际完整core | 246/246 Python、6/6 Node、示例通过 | 聚合0，三项各0 | 不是第四轮代码修复；代码和测试保持冻结 |

39方法的组成是4个权限/材料方法、5个恢复窗口方法、19个原暂存方法、7个故障方法和4个进程方法。权限负例中的3个subTest属于同一个方法，不另加3个；修复前3个subTest错误也属于一个已失败方法。完整246已包含这些专项方法，不能把39再加到246上。旧237、213等数字仅保留各自历史范围。

完整core入口为`Invoke-DevWorkflow.ps1 -Mode Validate -Checks core`，实际选择`python/example/ui-state`，未运行浏览器。其首次准备阶段因DeepSeek子进程PATH找不到既有Git而退出1，`checks_run=[]`，没有执行任何检查；旧报告保留。协调者随后只在该子进程PATH前置既有Git/Node并显式传入Node路径，未安装工具、修改全局PATH或改脚本。首次实际core记录`checks_run`非空、三项退出码0、`during_check_changes`三类均空、`credential_hints=[]`及`diff_check_exit_code=0`。敏感提示为空不等于对所有秘密形状作出证明。

## 6. 原始证据位置

所有证据在仓库外。共同前缀：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/`。下表中的目录和文件接在此前缀后：

| 目录 | 原始文件及用途 |
|---|---|
| S2B-staging-recovery-20261014-01a13a1d | `green-1-exit.json`（exit_code=1）、`logs/green-1.txt`；`logs/method-counts.json`（35方法/33失败方法）；`logs/ds-rec-1.err.txt`及`logs/ds-core-1.err.txt`保留修复前确认 |
| 同上 | `logs/sddl-equivalence.out.txt`、`logs/acl-exact.out.txt`、`logs/line-trace2.out.txt`证明原始SID/ACE等价及字面比较失败 |
| S2B-postfix-verify-20261014-231345 | `postfix-1-exit.json`（parent_exit_code=1）、`logs/postfix-1.err.txt`（38/39）；`logs/fixture-unprotected.out.txt`和`logs/unprotected-fixture-v2.out.txt`记录夹具前提及可靠构造法 |
| S2B-final-verify-20261014-232648 | `final-1-exit.json`（parent_exit_code=0、hash前后相同）、`logs/final-1.err.txt`（39/39）；`probes/staging-recovery-handshakes.jsonl`及`probes/staging-recovery-crash-probes.jsonl`记录5窗口握手、worker和CLI退出码、幂等及哨兵；`probes/owned-process-crash-probes.jsonl`记录原4窗口 |
| 同上 | `logs/core-1-exit.txt`及`core/20261014T152731Z-9f481ced07a6/report.json`保留缺Git时退出1、checks_run为空的准备失败 |
| S2B-core-verify-20261014-233914 | `core-2-exit.json`（wrapper_exit_code=0、仅子进程PATH）；`core/20261014T153959Z-1d68af251e31/report.json`及`validation.log`记录实际core |
| 同上core运行目录 | `regression/regression-results.json`记录三项独立退出码0；`regression/python/run.log`（Ran 246 tests / OK）、`regression/ui-state/run.log`（6/6）、`regression/example/run.log`记录各实际结果 |
| S2B-staging-recovery-sol-fix-20261014 | `baseline.json`及`before/`保存接管前122候选文件hash/副本；`before-fixture-fix/`、`fixture-fix-*-hashes.json`保存夹具修订；`before-docs/`及`docs-before-hashes.json`保存本次文档修订前副本/hash |

DeepSeek摘要报告在`C:/Users/Administrator.USER-20260902RM/.codex/visualizations/2026/10/14/01a13aaf-a3ee-7bc2-9aab-fa9dbca086f1/`：`deepseek-current-report.md`、`deepseek-postfix-report.md`、`deepseek-fixture-diagnosis.md`、`deepseek-final-verification.md`、`deepseek-core-verification.md`。摘要里更早的未完成状态以后续原始结果为准，历史报告未覆盖。

冻结hash：`backup_staging_recovery.py`为`4a65c11996476034f7b49643889a5247ed8e16b70df53855c6bf9ebebb061fbf`；`test_backup_staging_recovery.py`为`07541d8c051eecfd33fc4594d6a04441e73b76d382bac3f7440b3afdc25d92b0`。第三轮与实际core均核对前后相同；之后只同步本文及五份主文档，没有再改源码或测试。

## 7. 限制与阶段边界

权威根固定为`tempfile.gettempdir()/AI-Novel-Writer-staging-authority-v1`。TEMP变化、系统临时目录清理、权威根或签名材料丢失，都可能使旧操作无法核对；当前不提供稳定位置迁移、扫描重定位或材料重建。已有authority缺`signing.dpapi`时失败关闭，可能阻塞该TEMP下新暂存登记；不能认领旧根、重新签发材料或清理旧残留来冒充恢复成功。旧失败轮空authority及其他历史暂存均未清理，复测使用全新独占TEMP。

当前Windows用户及固定authority是信任边界。DPAPI、ACL和签名用于限定主体与核对已登记对象，不宣传抵抗同用户任意代码执行或管理员。文件fsync和进程强杀验证不等于物理断电耐久；实际断电、网络盘、跨平台、超过4GiB包、500章/百万字/多版本规模及全部权限/磁盘故障组合仍未验证。本轮没有重跑浏览器，不把历史浏览器结果当作本次结果。

正式data库及真实凭据未打开，正式8765未操作或更新，没有提交/推送。正式服务加载及作者验收仍待明确步骤；整体S2、S2-C已有库/旧JSON迁移、规模基准及其余S2任务尚未开始，本轮不自动推进。真正AI创作仍需S2余项、S3规划上下文、S4模型生成；完整原范围延续S2–S7六个阶段，本轮测试通过不是AI产品完成。
