<p align="center">
  <img src="./assets/banner.png" alt="DualQuill Banner" width="100%" />
</p>

<p align="center">
  <img src="./assets/logo.png" alt="DualQuill Logo" width="150" />
</p>

<h1 align="center">DualQuill</h1>

<p align="center">
  <strong>面向百万字长篇创作的 AI 多模型协同小说工作台</strong><br>
  <em>多模型流水线协同 × 全景设定矩阵 × 逻辑与时间线强质检 · 告别断层与崩坏</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/Architecture-Multi--Model%20Pipeline-8A2BE2?style=flat" alt="Multi-Model Pipeline" />
  <img src="https://img.shields.io/badge/Storage-Local%20SQLite-003B57?style=flat&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/Dependency-Zero%20External-success?style=flat" alt="Zero Dependencies" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat" alt="License" />
</p>

---

## 0.4.19：配置自己的 API 后通过聊天创作

Windows 下载：[最新版本](https://github.com/MoXiao677/DualQuill/releases/latest)。解压免安装 ZIP 后运行 `DualQuill.exe`，或使用安装器。

1. 打开“模型 / API 中心”，填写自己的 Base URL、API Key 和完整模型 ID，保存写作连接。
2. 添加另一条审核连接，在“独立审核”中选择并保存；名称可自定义，不需要作者使用的供应商。自动生成正文前需要配置独立审核。
3. 创建自己的小说，在创作对话中输入想法，上传大纲或导入本地文件路径，要求助手分类保存。
4. 直接要求规划、写章或修改设定。正文先保存，再独立审核；严重问题最多自动修订两次，失败会停止并保留记录。
5. 导出支持整本、分卷和单章；每次修改保留历史版本。

API 不随软件附送，调用按用户自己的服务计费。服务需要支持兼容 API 和结构化 JSON 输出；不是任意 API 都保证兼容。无需填写作者的连接名称、密钥或小说路径。

[完整上手说明](docs/getting-started-0.4.18.md) · [自动审核与上下文边界](docs/automatic-review.md)

## 💡 为什么需要 DualQuill？

长篇小说创作中，单一大语言模型普遍存在**长程记忆遗忘**、**设定断层**与**逻辑冲突**等硬伤。DualQuill 采用模块化流水线设计，解耦创作与质检流程：

- **发散创作流**：调用擅长叙事推进、细节刻画与文笔打磨的模型，专注章节起草与文风精修；
- **收敛逻辑流**：调用擅长长上下文推理与逻辑审校的模型，对照设定集、角色卡与全书大纲，执行逻辑审计与伏笔溯源。

写作与独立审核分别选择已保存的连接，独立审核连接必须与写作连接不同；可使用同一供应商提供的不同连接。供应商与模型由用户选择。

---

## 🌟 核心特性

- 🪶 **多模型协同流水线（Multi-Model Pipeline）**：按模型特长灵活分工，实现"起草 → 校验 → 润色 → 终审"的全流程协作。
- 🎭 **全景设定矩阵**：角色卡、世界观底色与分卷细纲动态管理，强约束生成内容，杜绝人设偏离与设定崩坏。
- 🛡️ **长篇一致性引擎**：动态追踪全书大纲脉络与伏笔进度，自动校验剧情前后因果与时间线先后顺序。
- ⚙️ **全自动设定维护**：保存章节后自动分析并更新大纲、人物状态、伏笔（埋/收）、时间线、世界观；每次变更留痕、可按章回退，模型输出不可靠时标记「本章设定未同步」而不是硬写。
- ⏪ **安全版本快照**：基于本地 SQLite 的全量版本追踪，任何章节生成均支持原子级快照回滚与作者授权确认。
- 🔒 **纯本地 & 零第三方依赖**：纯 Python 标准库开发，本地离线存储，小说原稿与设定保存在本机；发送创作请求时，相关内容会交给用户选择的 API 服务。

---

## 🚀 快速上手

**方式一：从源码运行**（无需 `pip install`，零第三方依赖）

```bash
git clone https://github.com/MoXiao677/DualQuill.git
cd DualQuill
python run.py --enable-model-generation
```

需要 Python 3.11 或更高版本。`run.py` 会自动启动本地服务并打开浏览器。

**方式二：桌面版（Windows）**

下载 release 中的免安装 zip，解压后双击 `DualQuill.exe`；或运行 `DualQuill Setup x.y.z.exe` 安装（未签名，首次运行需在 SmartScreen 里点「更多信息 → 仍要运行」）。

---

## 🏗️ 架构

```
src/novel_writer/
├── domain/          # 纯数据模型与校验（无 IO）
├── application/     # 业务编排：规划、审核、记忆、图谱、工作流、设定维护
├── storage/         # SQLite 仓储、备份校验、历史版本
└── ui/              # HTTP 服务与前端（原生 JS，无构建步骤）

desktop/             # Electron 外壳：进程管理、安全边界、打包
docs/                # 按特性拆分的契约与验收记录
tests/               # 1300+ 项 Python 测试 + Node 端到端
```

三条硬约束贯穿全项目：**文件是唯一事实源**、**历史不可覆盖**、**外发与写入必须可追溯**。

---

## 📚 文档

- [架构说明](ARCHITECTURE.md) · [产品需求](PRODUCT_REQUIREMENTS.md) · [路线图](ROADMAP.md)
- [开发任务与验收清单](TASKS.md) · [变更记录](CHANGELOG.md)
- [0.4.15 收尾记录](docs/final-local-0.4.15.md)（含全部测试数字与未验边界）

---

## 📌 状态与边界

当前版本 **0.4.19**。本版通过 Python/JavaScript 语法检查和 Windows 打包检查；历史版本的测试数字不代表本版全量回归结果。

已知边界（不粉饰）：

- 代码签名未做，安装包未签名
- 干净 Windows 环境的安装 / 升级 / 卸载未验
- 真实模型的端到端质量与费用，只做过最小验证
- 百万字历史库启动 P95 约 13 秒，目标是 5 秒，仍在优化

---

## License

MIT
