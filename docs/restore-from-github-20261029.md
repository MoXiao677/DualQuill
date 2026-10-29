# 从 GitHub 恢复 DualQuill

本次发布标记为 `v0.4.33-20261029`，是 0.4.33 的响应诊断修订包，程序内部版本仍为 0.4.33。此标记对应的源码和安装包一起保存，旧版发布不覆盖。

## 恢复源码

仓库：https://github.com/MoXiao677/DualQuill

```powershell
git clone https://github.com/MoXiao677/DualQuill.git
Set-Location DualQuill
git checkout v0.4.33-20261029
```

Release 中另附完整已跟踪源码 ZIP 和 Git bundle。源码 ZIP 无需 Git 即可解压；bundle 包含本地分支、标签的可达历史，可离线恢复：

```powershell
git clone ./DualQuill-history.bundle DualQuill-restored
```

## 运行和构建

源码运行需要 Python 3.11 或更新版本：`python run.py`。桌面构建需要 Windows、Node.js/npm，以及网络下载锁定的依赖。

```powershell
npm ci --prefix desktop
node desktop/build.cjs --stage=C:/DualQuill-build-stage --output=C:/DualQuill-build-output
```

stage 和 output 必须是尚不存在的新目录，且位于源码目录外。构建脚本按 `desktop/inputs.json` 校验 Electron 和 Python 运行时，按依赖锁文件安装 npm 依赖；不需要备份 node_modules 和构建缓存。

普通使用可下载安装 EXE，或解压 Windows ZIP 运行 DualQuill.exe。发布包不附带 API 服务，需配置自己的写作与审核连接。

## 校验下载文件

Release 的 `SHA256SUMS.txt` 列出文件校验值。下载后使用 `Get-FileHash -Algorithm SHA256` 对照核验。`release-manifest.json` 记录源码提交、资源绑定和本次验证范围。

## 私人资料必须另行保留

GitHub 源码与软件发布不包含小说、历史快照、附件、自定义资料库、API 密钥或运行日志。删除本地前，应另外备份实际使用的整个 profile 目录及小说导出目录。profile 包含 library、drafts 和其他用户资料；只保留 TXT 无法恢复完整项目和历史。

`providers.dpapi` 依赖原 Windows 用户，复制到其他用户或重装系统后不能保证解密，届时需重新配置 API 密钥。不要将该文件上传到公开仓库。

本次响应诊断与后台任务定向测试共 22 项通过；完整功能、真实付费模型、干净系统安装与卸载未在本次重新验收。既有版本说明中的历史测试不替代本次结果。
