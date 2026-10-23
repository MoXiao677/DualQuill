# S7 Windows桌面底座（接续中，2026-10-16）

## 当前恢复入口：F1手动切片已保存｜2026-10-16

最新进展转至[从零手动规划](f1-manual-planning.md)：9 Python/3 Node、最终7组隐藏作者UI通过，V11方案/分支/锁/确认及实体恢复复制已接通；book级AI仍未接。F1证据根为C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/F1-planning-20261016-4ce2b227/，最终source-delivery.json及delivery-summary.json保存快照和未完成项。下方S7/配置证据保留历史，不重跑已接受套件。

本切片提前交付后idle等作者明确继续；11:36:15停止新增工作、11:46:15正常关机由领导安排。下一批需book级AI与候选/费用权限，之后文风、完整中英和关键余项，全部完成再最终包；当前不新业务、不打包发布、不自动跨关机续作。

## 本切片技术交付｜2026-10-16（覆盖下方旧停机及未GREEN状态）

S7底座＋自建供应商/逐步骤创作预设的有限代码切片已收口。领导已读取并接受resume-094615原始定向证据：公开内置Python3.14.8共26项（配置21、桌面5），Node共11项（后端5、边界/打包/i18n6）；ui-config四组、ui-desktop八组、ui-lifecycle通过，运行期间对应源码均未变化。最终源码/报告差异索引见原证据根resume-094615/delivery-summary.json及source-delivery.json。

恢复时240份停机源码哈希完全一致。missing-runtime案例已改独立profile；每个测试进程有独立TEMP/TMP，桌面内部TEMP及authority确实在自身profile/tmp，父测试TEMP未建该authority。原生未知用量/坏响应、配置改址拒绝、V10组合复制、比较/工作流自建连接与角色默认均已定向通过。恢复期间还修正了比较表单的异步等待，以及模型完成后工作流入口仍用旧保存编号导致模板保存422：现在先重读当前工作区，服务端保护不变；全部原失败留档。

作者入口、格式/许可边界及虚构示例见[配置交付](custom-providers-presets.md)，构建/贡献材料已准备。此处为同机隐藏开发入口验证，ui-desktop明确packaged=false；没有验证最新win-unpacked exe，没有生成新安装器。旧zip早于新增功能，不是新功能交付。按作者时点，全部功能和关键余项完成后再统一最终包及打包运行验证，不在本切片重复构建/发布。未调用真实收费模型，不将协议wire通过等同真实语义质量或干净Windows验收。

本turn到此交回领导，下一turn接第0步大纲、方案版本/分支与锁，不自行在本turn扩写。11:36:15仍是本次工作窗无条件收尾时刻，11:46:15正常关机由领导安排，关机后不自动继续。下方记录保留历史与已知余项，不再表示最新修正仍未验证。

## 当前恢复｜2026-10-16 09:46:15 Asia/Shanghai

作者已明确恢复开发两小时，覆盖下方旧停机冻结；停机240份源码快照与全部失败保留。当前仅收S7底座＋供应商/步骤预设有限切片，完成后立即短交付，不同turn扩写大纲文风。11:36:15无条件停止新增开发/测试/下载/构建并保存现场，11:46:15正常关机由领导安排。恢复证据在原证据根的resume-094615，不重跑S6-B412，不把旧zip当最新应用，不提交推送发布。

## 停机恢复入口｜2026-10-16（当前最高优先级）

作者出门并要求保存后关机；领导已安排2026-10-16 08:12:56（Asia/Shanghai）正常关机。本轮已停止新增开发、测试、下载、构建，不提交/推送；直到作者下次明确继续才恢复。源码、所有未提交/未跟踪文件、旧失败与中间产物均保留。未创建Release或改变仓库可见性。

证据根：C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S7-desktop-20261016-886a74ba/。本轮停止前未发现仍在运行、且命令行与路径归属本轮的桌面测试/临时Python进程；未操作正式8765或其他应用。stop-state.json、source-stop.json、status-stop.txt及stop-snapshot保存本次停机现场。

最近已通过：green-creation-preset-ui-1（真实隐藏桌面：自建供应商、步骤预设选择/分享、原任务采用配置后单次确认出候选，不改正文）；green-configured-tasks-3（5项：三原生/兼容协议、改址拒绝与新摘要、V10组合复制、跨协议比较、工作流等待确认）；green-creation-presets-2（3项：版本/选择、跨书复用/纯数据分享补配、完整恢复复制）；green-custom-providers-2（7项）、green-custom-deadlines-1（3项）、green-custom-http-1（2项）。早期S7界面8组、生命周期与旧V1–V7原始行/文件保真证据仍保留，不冒称后续全部改动都已回归。

停机时最新改动尚未GREEN：

- desktop/backend.cjs新增profile内TEMP/TMP/APPDATA/LOCALAPPDATA/USERPROFILE与必要Windows环境白名单；desktop.py同时固定本应用tempfile目录。对应red-profile-temp.log已失败后修正代码，未复测。早期测试曾沿用系统TEMP，不能作为完整隔离验收；既有authority不扫描、不清理。
- test_custom_providers新增原生响应未知usage与坏candidate反例，red-native-response-shape.log为两个error；custom_protocols.py已补严格归一处理，未复测。
- 比较/工作流新增自建连接下拉、预设角色默认、目的地DTO/预览；原生角色/消息共题逻辑已有green-configured-tasks-3，但这些最新界面与DTO收尾尚未复验。
- e2e-s7-desktop已补NOVEL_WRITER_DESKTOP_EXE分支中app.isPackaged===true及exe/asar哈希断言，未用最新产物执行。中间zip早于语言/配置新功能，不能算本轮最新应用；NSIS原ECONNRESET保留，未生成安装器，不重建旧zip冒充交付。
- 工作区/包已实现V9配置目的地快照、V10正式创作预设/选择历史，SQL仍三表/user_version1、document1。最后整合与必要回归未完成；S6-B412仅是已接受的历史基线，未重跑。

续作第一步：先读本段和AGENTS/TASKS顶部。修正tests/desktop-backend.test.cjs中missing-runtime案例仍以os.tmpdir()作profile的问题，改为本案例独立mkdtemp，避免新环境初始化写共享TEMP子目录。然后为每个测试子进程指定新建的独立TEMP/TMP；先node desktop/build.cjs --prepare-only更新已批准项目内暂存资源，再node --test tests/desktop-backend.test.cjs验证最后隔离修改；随后定向运行test_custom_providers、test_custom_deadlines、test_configured_tasks、test_creation_presets及两组配置/桌面界面。保留所有RED/超时，不补跑旧S6整套，不清空计数。

尚未交付：配置切片最终HTTP/UI与V10兼容回归、准确短文档/源码哈希冻结；从第0步大纲及多方案/锁定、文风导入/真实搜索/风格卡/试写对比、完整中英界面，以及旧S2磁盘草稿与长篇性能等关键余项。先收完S7＋配置有限切片，短final交领导，再由领导下一turn派接续。全部功能及关键余项验证后才统一最终包/发布；现在不发布。

S6-B已接受，见[s6b-workflows.md](s6b-workflows.md)。[作者新增功能及补充验收](new-author-features.md)均已授权；桌面底座与新功能继续推进，最终统一构建后才交付最新应用。中间zip不能当作后续功能产物。

## 已实现

desktop/main.cjs通过可信ready握手启动公开CPython子进程，仅监听随机127.0.0.1端口。令牌与nonce由main生成，经私有stdin传递；桌面HTTP读取和写入均要求令牌，保留原Host/Origin及POST错误收尾。renderer只加载novel://app/白名单资源，main受限代理固定本应用后端；/api/session只返回空兼容值，真实token不进renderer。

renderer禁用Node，启用contextIsolation/sandbox/CSP；外网、导航、新窗口、webview与权限请求受限。preload只提供受限应用信息、UI语言和服务停止通知；main校验自己的顶层frame及参数。无任意URL、路径或命令执行入口。启动超时、失败、单实例、正常退出与stdin父进程生命线只处理本应用，不终止无关进程。

默认完全手动，不读凭据、不发模型请求。设置可显式启用本次会话模型或切回手动；仍须原冻结输入、预算/未知费用及逐请求确认。模型许可不持久。新增桌面设置与原生关闭/启动错误使用中英语言键；UI偏好独立持久，不翻译正文。全界面翻译尚待F3后续。

真实beforeunload保护未保存草稿/需求/忙碌操作，正常保存后可退出。安装资源与用户目录分离，默认profile为当前账户AppData下AI-Novel-Writer-Desktop，库为library/novels.sqlite3，DPAPI在同profile；--profile-dir=<absolute directory>可建立独立练习环境。不自动读取源码目录正式data。

旧profile首次打开或版本变更前，SQLite一致性快照保存在profile/upgrade-backups；初始化失败从快照回退，成功再写版本标记。原历史/迁移入口支持完整包导入为新项目；独立恢复保留当前原库。

## 源码与构建

锁定Electron44.7.2、electron-builder26.15.3、官方Python3.14.8 x64 embeddable。desktop/package-lock.json锁npm SHA-512；desktop/inputs.json锁公开二进制SHA-256及来源。Electron镜像内容用独立官方npm包内checksums.json核验，Python用python.org发布页核验。不分发Codex私有运行时。

开发机安装公开Node（22.12以上，本轮24.21.0）和Windows PowerShell。建立desktop/.cache及空的npm-user.npmrc、npm-global.npmrc后，在desktop执行：npm ci --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org --cache=.cache/npm --userconfig=.cache/npm-user.npmrc --globalconfig=.cache/npm-global.npmrc。不读取作者全局npm配置或安装全局工具。

根目录执行node desktop/build.cjs --prepare-only校验并准备运行时与白名单源码；node desktop/build.cjs构建Windows x64 zip和未签名NSIS，--dir只构建目录。缓存限desktop/.cache与desktop/node_modules，结果限dist/s7。GitHub不可达时可在单次构建进程设置ELECTRON_BUILDER_BINARIES_MIRROR=https://cdn.npmmirror.com/binaries/electron-builder-binaries/，仍核验npm包内独立强校验值；不改DNS/hosts/TLS或全局配置。构建脚本拒绝缺失的请求产物。

资源仅明确允许的main/preload/安全/生命周期/语言模块、第三方声明、Python源/静态UI/schema及公开Python。排除正式data、凭据、备份、.git、fixture与开发缓存。第三方声明为desktop/THIRD-PARTY-NOTICES.txt，完整Python许可证在runtime。应用公开许可证由作者决定，签名发现、自动更新和发布均未启用。

## 当前证据

证据根：C:/Users/Administrator.USER-20260902RM/AppData/Local/AI-Novel-Writer-review/S7-desktop-20261016-886a74ba/。保留204文件副本/哈希与全部RED、失败和超时。已通过9项新Node边界/生命周期/打包/i18n、5项Python桌面测试（含V1–V7七个冻结旧库原始行及文件哈希不变、升级失败回退）、原6项浏览器状态测试。green-desktop-e2e-6含8组真实隐藏桌面检查和V8二进制备份/独立恢复/预检后复制，external/errors空。green-lifecycle-4验证端口冲突、单实例、IPC/导航、实际main强退后Python退出、重启保留已保存小说与语言而模型复位、数据目录阻塞时安全失败。

Playwright启动PID与实际main PID不同，异常退出按应用自身回报并核对路径/profile后的实际main PID测试；原错误目标与UI初次渲染未结束导致关闭受保护的失败/超时均保留。最终等待实际UI渲染完成，不关闭或弱化产品草稿保护。

build-1已生成中间win-unpacked和zip；NSIS下载ECONNRESET，原日志及部分产物保留。原builder调用外层exit0却没有安装器，现脚本已补独立产物检查。此中间zip早于新语言与作者功能，不可用于最终交付。最终统一重建后，必须从dist/s7/win-unpacked实际exe断言app.isPackaged===true，记录资源/产物hash，并用脱离开发PATH的TEMP profile完成保存/备份恢复等路径。

## 明确未验收

以上仅同机隐藏隔离，未完成干净Windows安装/卸载、跨版本安装更新、系统策略兼容、正式安装器/注册表/自启、签名或发布。新作者功能尚待逐批实现。旧S2磁盘草稿恢复及长篇性能未完成：异常退出保留已保存小说，未保存正文/需求仍仅在窗口内存，不能声称崩溃后恢复。真实模型生成、语义质量和作者体验未验收，不标整体S7或全程序完成。
