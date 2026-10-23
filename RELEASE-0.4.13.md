# AI-Novel-Writer 0.4.13 发布说明

## 版本信息
- **版本号**: 0.4.13
- **发布日期**: 2026-10-22
- **许可证**: MIT License

## 安装包

### Windows 安装器
- **文件名**: `AI Novel Writer Setup 0.4.13.exe`
- **大小**: 122,061,486 字节
- **SHA-256**: `16e105d3be2ae99eb54aa852886e8a41308c8e0221258fd09970956f7bdb73e3`
- **位置**: `G:\agi\AI-Novel-Writer\dist\s7\AI Novel Writer Setup 0.4.13.exe`

### 便携版 ZIP
- **文件名**: `AI Novel Writer-0.4.13-win.zip`
- **大小**: 165,443,051 字节
- **SHA-256**: `89966273aa48012054e145ca3fd0e78057284dd8afcf600ff8600fab255a3963`
- **位置**: `G:\agi\AI-Novel-Writer\dist\s7\AI Novel Writer-0.4.13-win.zip`

## 主要功能

### 核心创作功能（已完整验收）
1. **章节构思与细纲** (C04-B1)
   - IDEA 构思生成
   - 章节细纲与场景节拍
   - 人物、位置、事实关联

2. **正文创作** (C04-A, C04-B2)
   - 空章初稿生成
   - 正文续写（保留原文 Unicode 字节）
   - 场景扩写（末尾插入）
   - 选区扩写（精确替换）

3. **磁盘草稿** (C16)
   - 自动保存未提交的输入
   - 崩溃恢复
   - 过期草稿处理

4. **章节管理** (C17)
   - 章节上移/下移
   - 软归档/恢复
   - TXT/Markdown 导入导出

5. **持久控制台** (C09)
   - 会话管理
   - 可编辑计划
   - 任务派发与结果回链

6. **分级规则系统** (C13, C13-B)
   - 全局/书/卷/章 四级规则
   - 规则冲突检测
   - JSON/CSV 批量导入
   - 规则历史记录

7. **多模型支持** (C03)
   - 自定义供应商配置
   - 三协议支持（OpenAI/Anthropic/Gemini）
   - 逐请求确认
   - 预算控制

## 验收状态

### 已通过完整测试
- ✅ 854 项 Python 单元测试（605 秒）
- ✅ Node.js 测试通过
- ✅ 桌面 UI 测试通过
- ✅ 百万字性能测试通过

### 已知限制
- ⚠️ **真实模型验收未完成**: 所有测试使用本地虚构供应商，真实 API 调用需用户自行配置测试
- ⚠️ **干净环境未验证**: 本机验证通过，但未在干净 Windows VM 测试安装/升级/卸载
- ⚠️ **未签名**: 安装器未进行代码签名，Windows SmartScreen 会显示警告
- ⚠️ **语义能力未完成**: 语义审核、查重、记忆自动分层等高级功能未完整实现

## 使用前须知

### 系统要求
- Windows 10/11 x64
- 无需预装 Python 或 Node.js（已内嵌）

### 首次使用
1. 运行安装器或解压便携版
2. 首次启动会创建用户数据目录：`%APPDATA%\AI-Novel-Writer-Desktop`
3. 在设置中配置 API 密钥（支持 OpenAI/Anthropic/Gemini）
4. **重要**: 默认为手动模式，所有 AI 生成需逐请求确认

### 数据安全
- 所有小说数据存储在本地 SQLite 数据库
- API 密钥使用 Windows DPAPI 加密
- 支持完整备份/恢复
- 草稿自动保存到独立目录

### 模型配置
- 需自行提供 API 密钥
- 建议先在测试项目中验证配置
- 注意监控 API 使用费用

## 技术文档

### 完整功能矩阵
- 详见 `docs/current-feature-status.md`

### 各模块文档
- C04-B1 章节构思: `docs/c04b1-chapter-planning.md`
- C04-B2 场景扩写: `docs/c04b2-scene-expansion.md`
- C16 磁盘草稿: `docs/c16-disk-drafts.md`
- C17 章节生命周期: `docs/c17-chapter-lifecycle-and-migration.md`
- C09 持久控制台: `docs/c09-persistent-console.md`
- C13 分级规则: `docs/c13-scoped-rules.md`

### 最终验收记录
- 详见 `docs/final-local-0.4.13.md`

## 许可证

本软件采用 MIT License 开源，详见项目根目录的 LICENSE 文件。

## 免责声明

本软件按"现状"提供，不提供任何明示或暗示的保证。使用本软件产生的 AI 调用费用由用户自行承担。

## 支持与反馈

- 项目仓库: https://github.com/MoXiao677/AI-Novel-Writer
- 问题反馈: 通过 GitHub Issues

---

**注意**: 这是本地验收通过的版本，真实模型效果和费用需用户在实际使用中验证。建议先创建测试项目进行试用。
