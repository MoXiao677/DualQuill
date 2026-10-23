# 8765 服务与源码一致性修复

日期：2026-10-13，Asia/Shanghai。本轮仅修复运行服务与配置页，完成后停止；不实施 S2、不提交、不推送，不读取真实密钥或请求外部模型。既有 Git 修改和未跟踪文件保留。

## 原因与进程

旧服务 PID **26908**，2026-10-13 **20:10:17.920828 +08:00** 启动，命令为：

```text
"C:\Users\Administrator.USER-20260902RM\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -B -X utf8 G:/AGI/AI-Novel-Writer/run.py --no-browser --port 8765
```

`run.py` 将自身项目根下的 `src` 插入模块路径，未传数据库参数时使用自身项目根下的 `data/novels.sqlite3`。此前实际 `/api/settings` 已核对该数据库路径。Python 进程早于 `server.py`（22:35:56）、`provider_connections.py`（22:36:56）与 `app.js`（22:39:46）的更新：静态前端读取磁盘新文件，后端保留旧模块。旧设置响应没有 `connections`，前端 `Object.values` 报错。

作者明确确认“全部已保存/暂存，并已暂停操作”。停止前复查 PID/命令、独立控制台、1 个线程、仅本机监听、无建立连接；连续采样进程读写计数和数据库逻辑/文件哈希均稳定。`mode=rw` 只取得 `BEGIN IMMEDIATE` 锁后立即回滚，没有数据/结构写入；锁可取得。源码没有 AI 后台任务实现。

确认控制台只有目标服务及短暂辅助进程后发送 **Ctrl+C**，由 `run.py` 捕获 `KeyboardInterrupt`、关闭服务器并正常退出，退出码 **0**。没有使用强制终止，也未刷新作者原窗口。

新服务 PID **46484**，2026-10-13 **23:49:33.902579 +08:00** 启动，继续运行于 `127.0.0.1:8765`：

```text
"C:\Users\Administrator.USER-20260902RM\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -B -X utf8 G:/AGI/AI-Novel-Writer/run.py --no-browser --port 8765 --database G:/AGI/AI-Novel-Writer/data/novels.sqlite3 --offline
```

源码：`G:\AGI\AI-Novel-Writer\src`；数据库：`G:\AGI\AI-Novel-Writer\data\novels.sqlite3`。启动前确认原库存在且非空，未以空库替换。独立隐藏启动窗口和日志留在仓库外；stderr 为空。检查实际新进程命令、监听与 settings 返回路径一致。

## 最小修复

新增 `--offline` 维护选项，传至 HTTP 服务及 `ProviderConnections`。此模式只用公开站点元数据构建三张连接卡片，不调用凭据加载/解密，不检查环境密钥值，不保存配置、不执行模型目录检查。配置文件保留；离线保护不依赖删除配置或换成空凭据文件。

`/api/settings` 返回 `connections`（`gg/catie/odys`）、`offline_mode=true`、`connection_checks_enabled=false`、`model_calls_enabled=false`。连接中的 `key_configured=null`、`credential_access_enabled=false` 表示未读取，模型 ID 和历史检查状态同样未知。前端明确显示“离线维护中 · 配置未读取”，输入、保存、测试禁用；程序触发表单也不会发请求。合法 token 的供应商保存/检查请求由后端拒绝为 HTTP 422。正常非维护启动原有配置行为保留。

没有正文、存储模型或数据库版本变更；没有新增运行依赖。Python 后端仍不会自动热加载源码，日后修改后端应在保存并暂停操作后正常重启。

## 本轮实际验收

新增测试先失败，再补实现并通过：4 项 Python 维护边界测试及浏览器维护状态测试。所有业务写入测试使用仓库外临时数据库，配置测试只用虚构密钥、临时 DPAPI 文件及本机协议夹具/拦截响应。

| 验证 | 结果 |
|---|---|
| `python -B -X utf8 -m unittest discover -s tests -v` | **101/101**；领域、业务、存储、回滚、冲突、版本、HTTP、Skills、配置、离线边界通过 |
| `python -B -X utf8 scripts/validate_example.py` | 示例关联、历史和 JSON 往返通过 |
| `node --test tests/ui-state.test.mjs` | **6/6** |
| `node tests/e2e-smoke.cjs` | **离线服务**创建小说、正文/空行保存、刷新/重启、历史恢复、人物、世界观、Skills 导入/原文、指南和窄屏通过 |
| `node tests/e2e-workbench.cjs` | 草稿/多标签/跨项目、失败输入、冲突、正式章授权、历史、焦点和四尺寸通过 |
| `node tests/e2e-chat-workbench.cjs` | 对话准备、需求隔离、上下文复核、导航/工具、六尺寸和退出保护通过 |
| `node tests/e2e-providers.cjs` | 虚构配置加密保存/重开、密钥不回显、列表 UI、桌面/窄屏通过；未调用真实供应商 |
| `node tests/e2e-offline.cjs` | 临时维护服务设置三卡片、未知状态、禁用操作、程序触发表单/刷新及两尺寸通过 |
| `NOVEL_WRITER_AUDIT_URL=http://127.0.0.1:8765` + 离线浏览器脚本 | 实际打开现有 8765 设置页，直接使用实际 settings 和静态资源；无脚本错误、无写请求、无浏览器外部请求 |

实际服务的浏览器复核在独立浏览器中进行，书架/Skills 列表用空响应遮蔽作者资料，禁止所有写请求及外部来源；未修改作者窗口或正式数据。完整作者操作流程的写入回归在独立库完成，不在正式小说上创建测试项目。

正式库重启前后逐行全字段/全部历史和 schema 逻辑 SHA256 一致：`f19ac5280ecca8c534122bb31800678014009d6a10fe552b3ecf4d04540ae261`。`projects=1`、`project_snapshots=8`、`skills=0`；`user_version=1`；`integrity_check=ok`、`foreign_key_check` 无错误；无 WAL/SHM/journal 残留。

数据库文件二进制 SHA256 从 `63498d4fcd2083b263ff9342b3e6e44210398cc2556bea9fde5581c25518fd05` 变为 `7f880430e1dde945e43bfeb1833e70ec2223a278126f3a5103b94f71e1eb45ce`。现有 repository 启动初始化执行 `PRAGMA user_version=1`，会产生 SQLite 文件写入；本轮未修改此行为。全表记录和结构一致，不能把这一结果写成“数据库文件字节完全未变”。

独立临时库重复初始化复现文件头偏移27/95变化、数据页不变，支持上述原因判断。最终核对正式库逻辑哈希仍一致。对本轮开始前81个源码/测试/文档文件逐项核对，无文件消失，仅13个授权范围内文件变化，另新增维护测试/记录；Git仍为main/`0a84f89`，无暂存/提交/推送，按仓库换行设置执行`git diff --check`通过。

日志、PID/命令、只读数据库摘要、设置安全响应、截图和报告：`C:/Users/Administrator.USER-20260902RM/.codex/visualizations/2026/10/13/01a135bf-74fd-7153-8178-5663922332f1/runtime-service-fix/`。没有真实密钥或小说正文输出到这些报告。

## 保留的边界

- 原浏览器会话 token 已因重启失效。作者已确认保存并暂存需求，可重新打开页面；原窗口未自动刷新。内存需求/草稿仍不具备磁盘恢复能力。
- 本次服务继续带 `--offline` 运行。普通启动未传此选项时会恢复原有配置读取能力；不应把维护模式误当作密钥丢失，后续真实 API 测试仍需单独授权。
- S2 完整备份、恢复、迁移、历史引用校验缺口及长篇性能没有在本轮实现或验收；系统输入法仍待人工体验。
- 本轮没有自动重载/进程管理器、提交、推送或外部模型请求。当前运行问题已收口，停在此范围。
