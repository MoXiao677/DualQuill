# C16 磁盘草稿与异常恢复｜2026-10-20

未保存输入不再只存在 renderer 内存：正文、IDEA、细纲、项目/全书大纲、世界观、规则、人物和记忆等现有可编辑表单会按“项目 + 文档键”自动写入本机应用数据目录；数据库、workspace 版本、备份包和项目复制均不改变。

## 存储与隔离

- 桌面 profile 下独立目录 `drafts/`（开发服务默认数据库同级 `drafts/`），不写入 SQLite，不升 workspace 版本，不进入备份包或复制。
- 文件名是 `sha256(project_id + NUL + document_key)`；文档键必须是四元 JSON `[project, view, entity, pane]`，项目必须匹配。只允许 `writing` 的正文/IDEA/细纲、`project`、`outline`、`world`、`rules`、`characters`、`memory`；设置/API 密钥等文档键明确拒绝。
- 每个草稿保存 `base_revision`、服务端 `updated_at`、表单字段值和光标/滚动位置。字段只接受字符串、布尔、整数或字符串数组，单文件上限 1 MiB；错误不回显正文。
- 写入使用同目录临时文件 + `os.replace` 原子替换；单个 JSON 损坏、格式不符或超限只加入 `corrupt` 报告并忽略，不删除其他草稿。草稿目录不扫描进日志，也不包含凭据。

## 前端生命周期

- 编辑输入约 800ms 防抖持久化；切页、窗口失焦、`visibilitychange(hidden)` 和 `pagehide` 会立即冲刷（pagehide 使用 keepalive）。
- 启动或切换项目时读取本项目草稿，恢复字段值与光标/滚动位置；标签与状态栏显示“本地恢复草稿（未保存）”。
- 草稿 `base_revision` 等于当前保存编号时只作为本地恢复提示；不等于时显示基于编号/最新编号、已保存值与草稿值，必须点击“保留草稿并绑定最新版本”或“放弃本地草稿”，绝不静默覆盖数据库或自动提交正文。
- 保存成功、关闭标签、明确放弃会清除对应磁盘草稿；其它未保存文档的草稿保留。不同项目草稿不互相显示；无云同步。

## 证据

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C16-disk-drafts-20261020/`

- `green-unit-20261020T015859Z.log`：6 项通过 — 服务重启后草稿仍在、保存/放弃清除、过期草稿显式 rebase 且不改正文、损坏文件忽略而不影响其它草稿、项目隔离/设置键拒绝、备份/复制不含草稿、workspace 版本与 revision 不变。
- `green-ui-20261020T020053Z.log` + `ui-20261020T020053Z/disk-drafts-ui.json`：最终源真实 Electron 强制终止整棵进程树后重开，草稿恢复并显示“本地恢复草稿（未保存）”；保存后清除；过期草稿显示最新编号并只允许显式放弃；再次重开无草稿。截图 `disk-drafts-recovered.png`、`disk-drafts.png`。
- `green-assets-20261020T015859Z.log`：UI state/i18n 与桌面安全 10 项通过。
- `green-affected-writing-ui-20261020T015903Z.log`：既有 C04-A 隐藏 UI 回归通过（该旧脚本复制既有 `desktop/.cache/stage/runtime` 作为测试运行时；本轮未修改 stage，但这次读取不符合本轮冻结边界，只作旧测试兼容证据，不用于 C16 结论）。

失败日志保留：`red-01-draft-api.log`（草稿 API 初始失败）、`red-02-draft-api-20261020T015134Z.log`（键规范/测试目标目录）、`red-03-ui-20261020T015234Z.log`（首屏无编辑器）、`red-05/06/07/08-ui-*.log`（进程终止方式、reload 被未保存提示拦截等）。通过输出只写 `green-*`，未把通过日志另存为 red 名。

## 未验与边界

- 草稿未加密，属于作者本机文本；不进备份/复制，也不是正式备份。
- 未做云同步、跨设备合并、磁盘满/权限拒绝的完整 UI 演练；原子写失败只保留当前输入并提示。
- 未使用真实供应商、真实付费、正式 data/8765、作者预览 profile 或全局设置；不提交推送发布。
