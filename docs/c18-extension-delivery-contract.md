# C18 扩展与交付安全契约（2026-10-21）

本增量在隔离源码副本完成，不是新版本发布，不选择应用许可证，不签名。应用继续为 `private: true` / `UNLICENSED`。没有自动下载运行扩展、远程市场、自动升级、任意 Python/JS 模块注册入口。模板中的说明即使包含指令也只是文本。

## 已实现的扩展流程

1. “受控数据模板”页粘贴 JSON → 预检 → 明确导入。只能选择内置注册的 `saved-text-reference`（`read_saved_source`）或 `model-request-preset`（`prepare_model_request`）V1 契约。未知字段、接口、权限、URL/文件路径来源和可执行入口拒绝。
2. 新导入默认未授权。页面逐版本展示所需权限；作者勾选核对框后点“明确授权并启用”。参考模板只读取本书已保存章节，预览不改正文/项目修订；模型预设即使获授权仍仅为数据默认值，不能调用模型、写正式正文或继承单次请求许可。
3. 停用撤销本机权限，重开仍停用；恢复使用需再次明确启用。授权操作有独立修订号、operation_id 幂等和追加历史，不能改写/删除旧事件。失败不授予权限。
4. 导入目标可选已有模板家族，升级追加版本而不覆盖历史。新版本不继承旧授权；旧版本只能导出查看，不能继续参考或重新启用。若需恢复旧配置，将该版本纯数据显式导入为新版本，再重新授权。升级预检失败不损坏原已启用版本。

本机权限保存在同数据库旁的 `<database>.extension-policy.sqlite3`，绑定规范化数据库绝对路径、项目 ID、模板版本 ID 和内容 SHA-256。它是本机授权旁车，不是小说持久格式，不加入工作区快照、完整备份或迁移；没有新工作区/schema 版本。读列表/拒绝未授权预览不创建旁车。复制到不同路径即使误带旁车也不能使用原许可。相同绝对路径的物理文件替换不构成跨机器权限证明；按正式备份/新目录恢复流程操作，不能把复制整套本机授权文件当作迁移 API。

已有 V1–V35 的纯数据模板在本版本也需本机授权，这是明确的安全收紧。原模板/正文/历史不改写、不自动迁移。注册只覆盖内置审查实现；通用可执行插件沙箱、第三方模型插件装载仍未实现。

## API

- `GET /api/projects/<project>/extensions`：原 versions/presets 保留，新增 dependencies/authorizations。
- `POST .../extensions/authorization`：`operation_id`, `expected_revision`, `expected_policy_revision`, `version_id`, `enabled`, `permissions` 全部必填。启用权限必须与注册权限逐项精确相同；停用为 `[]`。经既有会话令牌、Host/Origin 和项目归属守卫。非法为 422，未授权请求为 403。
- `POST .../extensions/reference-preview`：除已有书/章节边界外要求当前版本的有效本机授权。不是模型调用入口。
- 完整备份预检/恢复响应新增 `extension_dependencies` 和 `extension_authorizations_restored=false`；HTTP 首次恢复、重试/重开核对也返回。界面提示依赖数据保留，但本机许可未继承。原包 manifest/SQLite 格式不变。

## 干净源码检查（无需 npm 依赖）

在一个只有本工程源码、Python 3.14.7、Node 24.21.0 的干净目录运行：

```powershell
Set-Location -LiteralPath '<isolated-source>'
python -B -X utf8 scripts/c18_verify.py --output '<new-evidence-directory>'
node desktop/delivery-contract.cjs > '<new-evidence-directory>\source-and-dependencies.json'
```

输出目录必须尚不存在，避免覆盖既有失败证据。runner 为子进程重建环境白名单；TEMP/TMP/HOME/USERPROFILE/LOCALAPPDATA/APPDATA、缓存和虚构凭据路径均位于该证据目录。Python socket 只许 loopback，所有素材虚构，无真实 provider。CI 使用 Windows 2025 和固定 Python/Node，三个 GitHub actions 固定提交 SHA、checkout 不保存凭据、权限只读，不注入 secrets、不安装应用、不打包、不上传、不发布。固定 actions 引用来自各官方仓库 tag 的只读元数据核对；本机运行不能代替 GitHub 托管 runner 实跑。

## 干净源码打包路径（由主整合者执行）

本轮未安装 npm 依赖、未下载二进制、未运行打包。以下为可执行准备，需主整合者在自己的独立源码构建副本/独立输出路径执行，不能指向冻结 stage 或主仓既有 dist：

```powershell
Set-Location -LiteralPath '<isolated-source>\desktop'
$env:TEMP='<owned-build-root>\temp'; $env:TMP=$env:TEMP
$env:npm_config_cache='<owned-build-root>\npm-cache'
$env:NOVEL_WRITER_BUILD_CACHE='<owned-build-root>\runtime-cache'
npm ci --ignore-scripts --no-audit --no-fund
node build.cjs --stage='<new-stage-directory>' --output='<new-output-directory>' --zip-only
# 生成 ZIP+NSIS（仍绝不执行安装器）：省略 --zip-only；不使用 --publish。
```

先手动建立自己所有的 temp/cache 父目录；stage/output 必须不存在且不相交于源码/冻结目录。npm 只按现有 package-lock 安装到构建副本，绝不复制 node_modules/.cache。`prepare()` 校验输入名称/版本/官方原址/镜像/哈希与锁；Electron SHA 还与 npm 包内 checksums.json 比对。每次都从已校验 ZIP 展开 Electron 和 Python 到新的 stage，不复用现存 Electron dist/runtime，不删改既有 stage。二进制下载仅指锁定公开构建输入，绝不来自模板。

构建前后绑定后端、桌面源码、构建脚本、package/lock/inputs、notices、pyproject 的逐文件 SHA-256；验证新增源文件、stage 字节/额外文件和符号链接/目录联接。ZIP 包含 `resources/resource-manifest.json` 与 `dependency-inventory.json`。`publish:'never'`、关闭签名自动发现和 NSIS 完成后运行；输出默认改为缓存下新的 `build-output-<随机>`，**不再默认覆盖 dist/s7**。`--output` 可指定新的独立输出。

这保证构建输入及源码绑定，不声称 ZIP/NSIS 字节级可重复：时间戳、托管 runner、electron-builder 后续 NSIS 工具下载/平台差异尚未离线封存复验。仅固定 npm 包版本及 metadata 并不是完成公开许可审核。当前锁文件有 284 个传递工具依赖，均有 integrity、npm 官方 registry 原址和 license 声明；清单是包的声明值，不代替法律判定或完整许可证正文核查。

## 产物静态核验与安装边界

```powershell
Set-Location -LiteralPath '<isolated-source>'
python -B -X utf8 scripts/c18_artifact_audit.py `
  --zip '<new-output-directory>\AI Novel Writer-<version>-win.zip' `
  --source-root '<exact-source-used-for-build>' `
  --installer '<new-output-directory>\AI Novel Writer Setup <version>.exe' `
  --report '<new-artifact-audit-report.json>'
```

不提供 NSIS 时省略 `--installer`。核验只读 ZIP/ASAR，不解包或执行任何程序：检查路径遍历/重复/符号链接/私有库日志、全部后端成员、源码绑定、ASAR 桌面源码、应用版本、依赖清单、三方声明文件存在。NSIS 只检查 MZ 头与 SHA-256，**不表示安装器有效/签名有效**；runtime 二进制最终再分发字节未由此核验，需主整合者对锁定 ZIP/最终包另做比对。核验器本轮以明确标为 synthetic 的夹具测试，不当作真实 ZIP 已验。

干净 Windows VM 的 portable 启停、安装/升级/卸载、旧库恢复、快捷方式、路径权限、注册表差分均未测；准备顺序是：保存 VM 快照→导入纯虚构库和独立 profile→先 portable 无外发作者链→再经授权执行未签名 NSIS→升级/卸载前后逐项核对库和历史/默认不启动/不清用户数据→回滚快照。只有得到独立 VM 和单独执行授权后才运行安装器；本任务未做注册表安装/升级卸载。签名证书和公开应用/贡献许可证由作者决定。
