# 0.4.4 本地最终验收｜2026-10-20

本版完成原生请求配置、TXT/Markdown 前言保全与紧凑大文件导入、空书直接导入、有界长请求及 Windows 取消修复。它不代表 C01–C18 全部完成。完整操作及限制见 [原生配置与导入](native-request-profile-and-import.md)、[长请求与空书入口](long-request-and-empty-book-import.md)。

## 固定产物

最终构建为 `run-51-final-build-0.4.4.log`，独立 `desktop/.cache/build-stage-f5732d640aa6`。2026-10-20 15:53:55 UTC 核验时已固定；此前 run-46/run-50 为中间构建，不是最终哈希。首包到最终包的唯一产品源码差异是正文冻结页补充显示确切时限和候选字符上限。初包另存证据根 `pre-display-0.4.4`，旧 0.4.3 产物不覆盖。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/s7/AI Novel Writer-0.4.4-win.zip` | 165425255 | `44670dd5bb839d08d3f1ba00b150b3856a3257216d295e7245913b91c7636f05` |
| `dist/s7/AI Novel Writer Setup 0.4.4.exe` | 122045194 | `9abe7a2189458c42d56da09ad60161a1e85a8a361246a3dddbb64e35aebd8167` |

`package-audit-final-0.4.4.json`：真正解包到 `extracted-final-0.4.4`，264 条目、141 后端源码与最终工程逐字一致，无数据库、凭据、作者预览或其它禁带项。`asar-audit-final-0.4.4.json`：ASAR 五个 CJS、产品版本与 notices 逐字核对通过。`signature-final-0.4.4.json` 为 NotSigned；构建工具的 signing 文本不表示实际已签名，安装器从未执行。

## 最终源码与解包结果

证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/c03-parameters-20261020/`。

- `run-45-0.4.4-full.log`：完整 Python **807 项通过，507.890 秒，退出码 0**；包含大纲和正文各实际等待 31 秒、V30 完整备份恢复复制、短超时、取消无迟到候选与边界拒绝四项。全量期间最后补充的产品改动仅为上述一处正文冻结页文字，最终 Node、静态和解包正文回归已覆盖。
- `run-61-node-final.log`：Node **24 项通过**；最终 29 个静态 JS 语法通过。`run-62-example-final.log`：示例校验通过，仅终端默认编码显示乱码；未修改示例。
- `run-55-native-final.log`：最终解包自然对话三协议严格原生请求 **5 组通过**，5 次虚构 loopback；UI 检查默认 120000、编辑后冻结 60000 及显示。候选/明确采纳/取消/重开无重发保持，errors/external 均空。
- `run-56-import-final.log`：最终解包 **3 组通过**，空书无需占位章直接进入导入，前言含空格和 CRLF 原文保全；原文件 4604492 字节、GB18030 200 章的紧凑请求 6161420 字节，未放宽 12 MiB 限制。202 条导入结果重开逐字核对。
- `run-57-author-final.log`：最终解包作者流程 **7 组通过**，真实 TXT 下载、回收站/恢复、完整备份/恢复/复制及独立恢复库两次重开编辑均通过，providerCalls=0，errors/external 均空。
- `run-59-long-writing-final.log`：最终解包正文 **4 组通过**，实际响应 **31617ms** 后生成候选且原正文仍空；冻结 60000ms / 4000 字符、复用输入保持原时限；取消 **328ms**，迟到无候选；1000ms 明确 timeout，无重试；重开不重发，3 次 loopback、errors/external 均空。
- `run-58-scale-final.log` / `run-60-scale-ui-final.log`：最终解包百万字 200 章、12 次真实保存、完整历史备份恢复复制与桌面 30 次切章/保存重开均通过。第 12 次后端保存 **1.3836s**、桌面保存 **1420ms**、切章 p95 **50.3ms**；仅本机测量，不作跨机承诺。
- `run-53-tls-read.log`：临时自签证书 loopback TLS 完整响应通过；等待响应头时取消 **34ms**。仅测试客户端显式使用临时不信任上下文，产品证书校验未放宽。

父独立最终证据根 `%LOCALAPPDATA%/AI-Novel-Writer-review/lead-independent-0.4.4-final-20261020`，最终 ZIP/NSIS 哈希、264 条目/141 源码/ASAR 核对一致。大纲桌面 6 组（真实 31.958s）、空书导入 2 组、长输出 6 组（31.257/31.366s、取消43ms、V30恢复复制）通过，UI errors/external 均空。父首次包作者 7 组亦通过；不混称首次包和最终包证据。

## 保留的 RED 与修复

0.4.3 `run-30-0.4.3-full.log` 共 803 项，2 failures / 1 error，新增原生配置解析无条件读取旧内建连接凭据。修复仅让旧内建连接无采样准备路径提前返回；准备不读凭据/不发送的原测试不削弱。0.4.4 run-40 定向 11 项和最终 807 项均通过。内建连接拒绝 request_profile 管理，UI 明确只支持自建连接，不静默忽略已保存的配置。

`run-41-long-limits.log`：新增测试发现 Windows shutdown 未及时解除响应头阻塞，以及新测试将尚不存在的 generation_tasks 当必有集合；修复共享读传输和测试空集合访问后，run-44 定向 10 项及全量通过。`run-52-tls-read.log` 仅临时证书工具缺配置失败，改用已安装密码库生成临时证书后 run-53 通过。

`run-54-long-writing-final.log` 首次正文 UI 已验证 31.483 秒成功，之后夹具复用输入时未重新勾选费用未知许可，冻结被正确拒绝；只修测试显式重新确认，run-59 全部通过。该行为是既有权限边界，不自动继承许可。0.4.3 早期导入夹具的占位章/标题歧义 RED 继续保留。

## 保持边界与下一项

最终包固定后，父进一步发现正式允许的 localhost 在 Windows 先解析 ::1、后解析 127.0.0.1 时，IPv4-only 本机供应商连接失败（provider_calls=0）。这是 0.4.4 真实产品缺陷，不是夹具问题；`lead-independent-0.4.4-final-20261020/tls-localhost-red/report.json` 与 `red-08-localhost-tls.log` 保留。原最终哈希不变，下一版修复连接前对已验证地址的尝试，不把该修复冒称已经包含在 0.4.4。父另外独立 TLS 正常/碎片Unicode/响应头取消/半体取消/总超时/截断及私有信任撤销 6 组通过，取消21/28ms、超时202ms，见 `tls-output-03/report.json`。

真实付费调用为零。正式 data/8765、作者窗口/profile/凭据、冻结 stage、author-preview 和全局配置未触碰；无新聊天/子代理，无提交、推送、签名、发布或安装器执行。SSE、章节级独立汇总/自动语义摘要与汇总上下文、语义检索/审核、真实供应商效果与干净 VM 安装发布仍有缺口。下一实质切片为 C05 章节级独立汇总，保持显式预览/保存、原文来源、过期派生及 append-only 历史；不把它冒称模型语义摘要。
