# C18 最终打包与安装器｜2026-10-20

2026-10-21 隔离开发增量：扩展本机逐版本授权、恢复依赖提示、独立新 stage/output、源码绑定/依赖清单及 CI/只读产物核验器见 [扩展与交付安全契约](c18-extension-delivery-contract.md)。该增量未重新打包、未运行安装器、未做干净 VM 验收，不改写下方历史产物结论。

## 当前 0.4.1（下文 0.4.0 为历史）

本轮已从独立 build-stage 重建 0.4.1 portable zip 和未签名 NSIS，版本同步 desktop package/lock/notices 与 pyproject。包含 C17 V27、C03 管理及 C05/V23、C09/V24、C08/V25、C07/V26。桌面支持绝对路径 --database 打开独立恢复库；TXT/MD 使用已有同源附件下载。最终产物哈希、ZIP/ASAR 源码逐文件核对、全量测试及独立解包完整作者流程统一见 [0.4.1 本地验收](final-local-0.4.1.md)。不把 win-unpacked 冒烟当作解包 ZIP 或安装器验收；安装器未运行，干净 VM、签名和许可仍待外部条件。

已用锁定版本 Electron 44.7.2 + electron-builder 26.15.3 生成 Windows x64 portable zip 与 NSIS 安装器。构建输入从仓内 Python embeddable zip 与源码在独立 `desktop/.cache/build-stage-<随机>` 组装；不再读取或使用冻结的 `desktop/.cache/stage`。

## 构建改动

- `desktop/build.cjs` 的 `prepare()` 生成新的独立 stage；`stagePath()` 拒绝显式指向冻结 `.cache/stage`，默认随机目录，也支持 `--stage=<独立目录>`。
- runtime 从 `desktop/.cache/python-3.14.8-embed-amd64.zip` 展开并写 `python314._pth`；backend 只复制 `sourceFiles()` 白名单（Python、schema、security.cjs 静态资源白名单）。
- `desktop/package.json` 的静态 `extraResources` 清空；构建时由 `build.cjs` 传入本次独立 stage 的 runtime/backend 与 `THIRD-PARTY-NOTICES.txt`。
- 版本从 0.3.0 升至 0.4.0，`package.json`/`package-lock.json`/`THIRD-PARTY-NOTICES.txt` 同步；产物名与版本一致。
- `desktop/security.cjs` 的 asset 白名单包含本轮新增 `console.js`、`chapter_planning.js`、`scene_expansion.js`、`rules_scope.js`、`migration.js` 等全部静态 UI 文件。

## 产物

目录：`G:/AGI/AI-Novel-Writer/dist/s7`

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| AI Novel Writer-0.4.0-win.zip | 165,339,839 | `3103ab3513a4a26e8c0581bbf9830be35db6138face2097e39ba9f928fe102e8` |
| AI Novel Writer Setup 0.4.0.exe | 121,966,860 | `bcec9b3d1b2b3a59c63a8ec9d44ec53898edf9b9df2596abd4ded65614b419eb` |
| AI Novel Writer Setup 0.4.0.exe.blockmap | 129,394 | `e184cd3d5f15a41f330ffcc20d699cf226f22f4daf8d8a49d75f993bc5dd8ac0` |

`Get-AuthenticodeSignature` 对安装器返回 `NotSigned`；本批未签名、未运行正式安装器、未写注册表自启、未发布。

## 构建与冒烟证据

证据根：`C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/C18-packaging-20261020/`

- `green-packaging-test-20261020T023736Z.log`：源码白名单/版本/stage 参数检查 2 项通过。
- `red-build-first-20261020T023738Z.log`（原误标 green，已保留 red 副本）：第一次 NSIS 下载因 `release-assets.githubusercontent.com` DNS 失败；portable zip 已生成。
- `green-build-20261020T023929Z.log`：首次镜像重试 zip 与 NSIS 成功；最终源码（含应用内指南更新）重建见 `green-build-final-20261020T024139Z.log`。
- `green-smoke-20261020T024252Z.log` + `smoke-20261020T024252Z/packaged-smoke.json`：从最终 `dist/s7/win-unpacked/AI Novel Writer.exe` 启动，独立临时 profile；自定义 `novel:` 协议加载、renderer `require/process` 均为 undefined、后端 ready、真实 UI 创建项目/章节、renderer 错误与外发为空、关闭后无后端进程。

ZIP 内容检查：245 个条目，无 `author-preview`、`stage/`、`.git`、`node_modules`、`tests/`、`fixtures/`、`.sqlite*`、`.dpapi`；包含 `runtime`、backend 源码与全部新增 UI 静态文件、`THIRD-PARTY-NOTICES.txt`。`app.asar` 内 package version 为 `0.4.0`。

## 未验与边界

- 干净 Windows VM 的安装、升级、卸载、快捷方式/权限及旧版本迁移未验；本机解包目录冒烟不能替代安装器验收。
- 代码签名未做；应用许可仍为 `UNLICENSED`，公开分发许可需作者决定。
- 未使用真实供应商/付费、正式 data/8765、作者预览 profile/stage、用户窗口或全局设置；未提交、推送或发布。
