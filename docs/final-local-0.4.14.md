# 0.4.14 本地收尾验收记录 / 主仓 V49

2026-10-22，Asia/Shanghai。最终证据快照：2026-10-22 08:35 +08:00。

主仓已从 V48 同步至 V49，0.4.14 已在独立 stage/output 重建，静态包审计通过，真包隐藏桌面启动已实际验证，主仓第二轮全量回归 1292 项全通过；历史库启动性能仍为 RED。本记录不构成全部模块接受或完整发布声明。

本页接续 [0.4.13 有限切片正式接受](final-local-0.4.13.md) 与 [0.4.14 / V48 联合候选历史](joint-candidate-0.4.14.md)。旧文档、原失败与固定产物保留，旧通过不能替代本轮证据。本次执行者只整理四份文档；以下合入、修复、构建、启动和全量运行均为此前已实际执行的事项，本次未重跑。

## 证据口径

| 等级 | 本轮证据 | 可支持的结论 |
| --- | --- | --- |
| 静态审计 | `G:/AGI/_deliver-1022/artifact-audit.json`，`verified=true`，`mode=static_read_only` | 固定 ZIP、源绑定及安装器有限静态检查通过；不证明安装行为、签名或运行时二进制完整性 |
| 实际运行 | `output-01/win-unpacked/AI Novel Writer.exe` 的隐藏启动与独立库；两轮完整全量日志 | 真包进程、后端握手及建库成功；第一轮 RED 已定位修复，第二轮主仓 1292 项通过 |
| 未验 / 未完 | 真实模型、安装器、干净 VM、签名及新 EXE 历史库性能 | 不填写通过数字，不把静态通过、源码冷读或启动冒烟扩大为这些验收 |

静态报告 SHA-256（首轮审计 `artifact-audit.json`）：`765a4f5c4341cd6f0a8c36c85517c9be3facdb21fa7e0d143128a961d5857978`，862 字节。文档与测试修复后已再次执行审计器（`artifact-audit-02.json`），`verified=true` 且 `source_digest` 不变；未重新构建，也未把二次静态复核当成安装或运行时验收。

## 主仓来源与打包卡点

此前 `G:/AGI/AI-Novel-Writer` 停在 V48，缺少 V49 `semantic_retrieval`。已审副本 `G:/AGI/_parallel/release-integration-20261022-group1-02`（交接记录 577 源文件）才是本轮最新来源；其 src/tests/docs、desktop 配置及根文档已同步回主仓，排除 node_modules 与 .cache。577 是副本来源口径，不是打包后端或审计文件计数，本次未重新做 577 文件逐项冻结。

主仓现有 `src/novel_writer/application/semantic_retrieval.py`、`src/novel_writer/domain/semantic_retrieval.py`。V49 接续 V36–V48 的联合候选；语义检索合入不等于真实语义质量通过。[语义检索契约](c08-semantic-retrieval.md) 中副本阶段的静态候选记录继续作为历史，不能单独作为本轮动态接受证明。

`desktop/package-lock.json` 此前被净化为 284 个依赖包均无 resolved/integrity（各 0），导致 `desktop/build.cjs` 的 `inventory()` 拒绝。这是在版本/许可不一致、BOM 报错两次构建问题之后，仍不能重建成功的直接阻断。此前已换入 group1-02 完整 lock，`inventory()` 实测通过；本次只读统计为版本 0.4.14、284 包、284 resolved、284 integrity。没有关闭 inventory 守卫，也没有在本文档任务中修改 lock。

## 固定构建与静态包审计

本轮构建 stage：`G:/AGI/_deliver-1022/stage-01`；输出目录：`G:/AGI/_deliver-1022/output-01`。构建输出 `sourceFiles=190`，`source_digest=56b597bf0e92b867a3bb247d216641e0ded4a3619ec65c0c6a7271f36c4e1bf3`。

`stage-01/resource-manifest.json` 的 source 列表为 190 项，binding.files 为 203 项，binding.digest 与上述 digest 一致；文件 SHA-256 为 `3995f30660554174f62d899ed0d1fc4b0ef40ed60517829be0e7d715d5488af9`。`stage-01/dependency-inventory.json` 为 0.4.14 / 284 包，SHA-256 为 `e32af64c27f8b55f16ec9ae6721a35b2c565f464b582eaee3051f5220cf4bd48`；其 `application_license=MIT`，`public_distribution_approved=false`，不能从 MIT 字段推导已获公开发布批准。

| 固定文件（均位于 output-01） | 实际字节数 | SHA-256 |
| --- | ---: | --- |
| `AI Novel Writer-0.4.14-win.zip` | 165661660 | `210f70a4dd6e2497b7c005e731d1f16731012b2c34589e3d851c3b48fa9fd8af` |
| `AI Novel Writer Setup 0.4.14.exe` | 122262861 | `6f48e1b58f09f8c415a275f5da7de1d38c99baeae3bc01965931578dc9002169` |

两份文件已只读重算 SHA，均与审计报告一致。交接所写 ZIP 117 MB / 安装器 158 MB 与实际文件大小不一致，本文采用上表精确字节数，不沿用概数。

`scripts/c18_artifact_audit.py` 已执行并生成上述报告：`verified=true`，`source_files=203`、`backend_files=190`、`desktop_files=6`、`dependency_declarations=284`，source_digest 与构建相同。各计数沿用原报告口径，不与副本 577 源混算。安装器 scope 原文为 `PE magic and SHA-256 only; NSIS behavior/signature not verified`。

审计明确自报：`installer_executed=false`、`runtime_binary_integrity_verified=false`、`signature_verified=false`、`clean_vm_tested=false`、`real_provider_calls=0`。上述 false 不因 verified=true 或后续启动成功而改写。固定产物不覆盖；本文没有创建完整回归结束后的源/包一致性绑定，也不把本轮文档追加后的主仓称为与构建 manifest 全文件相同。

## 真包实际启动

此前已实际启动 `G:/AGI/_deliver-1022/output-01/win-unpacked/AI Novel Writer.exe`，参数为 `--background-test --database=G:/AGI/_deliver-1022/smoke/novels4.sqlite3`。Electron 主进程与渲染进程存活，内置 `runtime/python.exe` 后端被拉起；桌面启动需后端握手成功才继续，最终生成 28672 字节 SQLite 库，随后相关进程全部关闭。本文仅复核该独立库的文件大小，没有打开数据库或再次启动应用。

原环境存在 `ELECTRON_RUN_AS_NODE=1`，最初 exe 被按 Node 运行，报 `bad option: --background-test` 与 `bad option: --database=...novels3.sqlite3`，保留于 `G:/AGI/_deliver-1022/smoke/out.log`。启动前 unset 该变量后才完成上述成功冒烟；`smoke/out2.log` 为后一次输出文件。不能只凭空输出判定成功，成功依据为此前实际进程、握手及独立建库观察。

这是同机隐藏桌面启动证据，未覆盖完整作者操作、模型语义、干净 VM 安装或百万字 history 库可交互 P95；本次未执行安装器。

## 全量回归：第一轮 RED 已定位并修复，主仓第二轮 GREEN

| 轮次 / 执行位置 | 日志 | 完整结果 |
| --- | --- | --- |
| 第一轮 / group1-02 副本 | `G:/AGI/_deliver-1022/full-test-01.log` | 1292 项；`Ran 1292 tests in 647.128s`；`FAILED (errors=3)`；退出 1 |
| 第二轮 / 主仓 | `G:/AGI/_deliver-1022/full-test-02.log` | 1292 项；`Ran 1292 tests in 653.682s`；`OK`；退出 0 |

第一轮完整日志为 13146 字节，SHA-256 `03ea72b669c0bd2fa959baae4bf6d05849c8a4c6e738a024308cffa508d3bbbf`。原交接记 657.905 秒，现存日志正文为 647.128 秒，未见可解释前者的原始计时字段；两者差异在此保留，测试耗时以日志正文为准。日志没有独立进程退出码字段，退出 1 引自已执行交接记录，不声称从该日志另行读得退出码。

第二轮为主仓修复后实测：2026-10-22 08:20 启动、约 08:31 结束，命令 `python -m unittest discover -s tests -q`（`PYTHONPATH=src`，独立 Python 3.12.14 解释器），日志正文 `Ran 1292 tests in 653.682s` 与 `OK`，进程退出码 0。两轮均为同一套 1292 项，第二轮未出现 FAIL 或 ERROR。

三条 error 对应两个真实根因，第一轮原日志保留未删：

1. `tests/test_body_planning.py:292` 的 `fail_after_decision(state)` mock 未接收实现新增的 keyword-only `_validated_versions`。`src/novel_writer/storage/sqlite_repository.py:305` 调用时抛 TypeError，尚未走到预期回滚故障。已改为 `fail_after_decision(state,**kwargs)`，并向原校验器原样转发 kwargs —— 异常注入条件（`body_planning_receipts` 非空即抛 `ValueError`）与回滚断言均未放宽；这是测试契约落后，没有改动实现的校验逻辑。
2. `tests/test_dev_workflow.py:78` 的 FileNotFoundError 来自副本缺 `scripts/Invoke-DevWorkflow.ps1`。主仓同名文件存在（3846 字节，10-14 文件），该条件在主仓不成立，第二轮未复现。
3. 第三条与第 1 条同名；`tests/test_model_planning.py:11` 导入 `BodyPlanningTests` 后被重复收集，是相同 TypeError 的重复报告，不是第三个独立根因。本次未改收集方式，第二轮该测试仍执行两遍且均通过。

第二轮 GREEN 的边界：它证明主仓 Python 套件在这一版源码上全通过，**不**证明固定包与该时刻全部工作树文件逐一同源。构建早于本次测试修复，但 `desktop/build.cjs` 的 `sourceFiles()` 只遍历 `src/novel_writer` 与登记的静态资源，`sourceBinding()` 只绑定 `LICENSE`、`desktop` 配置与 `pyproject.toml`，`tests/` 不在包绑定内 —— 因此测试修复不改变包绑定。文档改动后已重新执行 `scripts/c18_artifact_audit.py`（报告 `G:/AGI/_deliver-1022/artifact-audit-02.json`），结果仍为 `verified=true`，`source_digest` 与构建一致（`56b597bf…e1bf3`），`source_files=203`、`backend_files=190`、`desktop_files=6`、`dependency_declarations=284` 未变。该复核同时确认第一轮的 1292 项与 0.4.13 的 854 项、V48 的 1232 项不是同一口径，不互相替代。

## 性能遗留：history 启动仍为 RED

历史专项见 [百万字固定 EXE 启动实测与源码补丁](startup-performance-20261021.md)。其固定旧 EXE SHA-256 为 `839c255ac71eb0e2b0a0a5cc3963100917c3124e474bad9dc92aaa2494c6626a`，不是本轮新 EXE 性能报告。

500 章、1000180 字、每章至少 5 版、31 整书快照的 history 库，15 个实际样本可交互 P95 为 13.017061 秒（约 13.017 秒），<5 秒为 0/15，仍为 RED。不能用 fresh 小历史库的通过、保存 P95 或普通启动建库替代。

同主机同 history 夹具的源码 `repository.get` 独立冷读从 13.322248 秒降至 4.666733 / 4.737613 / 4.631700 秒（约 4.67 秒）；该终点不包含桌面启动、首次 profile 备份、DOM、导航与输入，尚未进入本轮新 EXE 实测。因此不声明新包 history 启动达到 <5 秒。

## 未验与发布缺口

- 真实供应商付费调用为 0；真实模型语义质量、相关性/排序、生成效果及实际账单均未验。loopback、结构校验和来源一致性不能替代真实模型验收。
- 安装器从未执行；干净 Windows 的安装、升级、卸载未验，`clean_vm_tested=false`。同机便携真包启动不能替代安装器验收。
- 代码签名未做，安装器未签名，`signature_verified=false`；不能把哈希一致写成签名有效。
- `runtime_binary_integrity_verified=false`；Python 后端被拉起不等于已完成运行时二进制完整性核验。
- 新 EXE 百万字 history 启动 <5 秒待实测，旧 RED 保留；主仓第二轮 GREEN 只覆盖 Python 套件，不含该性能终点。
- dependency inventory 的 `public_distribution_approved=false`，公开发布许可/批准仍需闭合，不从构建成功推导已发布或可公开分发。

## 本次文档边界

本次由两个执行者分工完成：收尾整理者（DSH 侧）执行源码同步、lock 修复、构建、审计、真包启动与测试修复；文档整理者（Codex 6.1 Sol，`codex exec`）新建 `docs/final-local-0.4.14.md`，并在 `TASKS.md`、`CHANGELOG.md`、`AGENTS.md` 顶部追加一节，原条目全部保留。文档整理者未修改 src/、tests/、desktop/；收尾整理者在文档完成后补入第二轮全量结果并重跑静态审计。全程未执行安装器，未操作正式 data/、8765、真实凭据、作者窗口/profile 或受保护冻结资源；未 commit、push、签名、发布，未覆盖 `dist/`、`_verification/` 或既有 stage/output 产物。

**本版可称为「0.4.14 本地候选交付」但不能称为完整发布。** 已确认：主仓 V49 合入、0.4.14 重建、静态审计 `verified=true`、真包隐藏桌面启动成功、主仓全量 1292 项通过。距真正发布还需：代码签名、干净 Windows VM 的安装/升级/卸载、获授权的真实模型语义质量与账单验收，并关闭 history 启动 RED、运行时二进制完整性及公开发布批准缺口。
