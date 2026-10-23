# 本地开发与贡献材料

当前仅准备源码交付材料，应用公开许可证由作者决定。全部授权功能与关键余项完成验证前，不提交推送、创建Release或改变仓库可见性。

源码浏览器入口仍是run.py；桌面构建及公开依赖锁定步骤见[s7-desktop.md](s7-desktop.md)。桌面内置官方Python，不再分发开发工具私有运行时。当前Git未提交/未跟踪文件和失败记录应继续保留，不使用reset/clean覆盖现场。

修改前先定位实际调用链，并为新行为留下有效RED；只补本次变化需要的验证。Python业务用标准库unittest，桌面边界用node --test；界面脚本使用开发者显式提供的Playwright测试包，不随成品分发。界面只能运行虚构profile、随机loopback端口及隐藏窗口，不操作正式数据、模型凭据、8765或作者桌面。

每次验证先新建唯一临时根，再只在测试子进程环境设置TEMP/TMP；不得改用户级/系统级环境变量或沿用旧暂存authority。可先执行node desktop/build.cjs --prepare-only，随后对修改对应的tests/desktop-*.test.cjs或test_custom*.py进行定向验证；不要默认重跑已接受S6核心套件。公开内置Python位于desktop/.cache/stage/runtime/python.exe。

报告问题时提供复现步骤、预期与实际行为、命令退出码、源码哈希及虚构样本。保留原始失败与修正后差异；不上传作者小说、密钥、DPAPI文件或私有会话。缓存限项目批准目录，打包使用源码/资源白名单。安装、签名、发布和真实模型费用须遵循作者的明确授权。
