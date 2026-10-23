<p align="center">
  <img src="assets/logo.png" alt="DualQuill" width="180">
</p>

<h1 align="center">DualQuill</h1>

<p align="center">
  <strong>双笔共写 · 长篇小说 AI 写作工作台</strong><br>
  <sub>一支笔负责把故事写活，另一支笔负责让它始终自洽</sub>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="Electron" src="https://img.shields.io/badge/Electron-44-47848F?logo=electron&logoColor=white">
  <img alt="Dependencies" src="https://img.shields.io/badge/第三方依赖-0-success">
  <img alt="Tests" src="https://img.shields.io/badge/tests-1343%20passing-success">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue">
</p>

![DualQuill](assets/banner.png)

---

## 这是什么

DualQuill 是一个**离线优先**的长篇小说创作工作台。

你给全书大纲和每章的核心想法，它按流程产出细纲、正文、审核意见与改写候选；同时自动维护设定集、人物状态、伏笔与时间线，让一本几十万字的书在写到第 200 章时，第 3 章埋的伏笔依然会被记得。

所有内容保存在本地 SQLite，不联网也能写，不绑定任何一家模型供应商。

## 双笔分工

DualQuill 的设计前提是：**写得好**和**写得对**是两件不同的事，交给两支笔。

| | 负责什么 | 干什么 |
|---|---|---|
| **起稿笔**（可绑 Gemini 等） | 把故事写活 | 发散式正文起稿、情节推进、场景扩写、文风润色 |
| **校对笔**（可绑 DeepSeek 等） | 让故事自洽 | 全文大纲对齐、设定集约束、时间线校对、伏笔闭环、前后矛盾检查 |
| **你来定** | 拍板 | 大纲、人设、取舍、最终采纳 |

两支笔可以绑同一个模型，也可以各接不同供应商（OpenAI / Anthropic / Gemini 兼容协议都支持），甚至接自建连接。

## 核心特性

- **全自动设定维护** —— 保存一章，系统自动分析并更新大纲、人物状态、伏笔（埋/收）、时间线、世界观。每次变更留痕、可按章回退、拿不准会标记而不是硬写。
- **AI 只作建议，写入你说了算** —— 正文、大纲、记忆的正式写入都需要明确确认；唯一的例外是自动设定维护，它默认开启、可随时关掉。
- **长篇不失控** —— 分层摘要、人物状态追踪、伏笔回收、时间线校对、整书分批审核，百万字级别的书也能查清"这句话跟前面哪一章冲突"。
- **模型可控** —— 逐请求确认、预算上限、可取消、超时保护；每笔调用的输入来源与输出都留痕。
- **数据是你的** —— 本地 SQLite 存储，完整备份/恢复/复制（含未保存草稿），不加密钥不外传。
- **零第三方依赖** —— Python 后端 `dependencies = []`，只用标准库；桌面端 Electron 打包，Windows 免安装即可运行。

## 快速开始

**方式一：免安装**

下载 release 里的 zip，解压后双击 `DualQuill.exe`。

**方式二：安装**

运行 `DualQuill Setup x.y.z.exe`（未签名，首次运行需在 SmartScreen 里点「更多信息 → 仍要运行」）。

**方式三：从源码跑**

```bash
git clone https://github.com/MoXiao677/DualQuill.git
cd DualQuill

# 后端（需要 Python 3.11+，无第三方依赖）
PYTHONPATH=src python -m novel_writer.ui.server

# 桌面端
cd desktop && npm install && npm start
```

## 架构

```
src/novel_writer/
├── domain/          # 纯数据模型与校验（无 IO）
├── application/     # 业务编排：规划、审核、记忆、图谱、工作流
├── storage/         # SQLite 仓储、备份校验、历史版本
└── ui/              # HTTP 服务与前端（原生 JS，无构建步骤）

desktop/             # Electron 外壳：进程管理、安全边界、打包
docs/                # 按特性拆分的契约与验收记录
tests/               # 1300+ 项 Python 测试 + Node 端到端
```

三条硬约束贯穿全项目：**文件是唯一事实源**、**历史不可覆盖**、**外发与写入必须可追溯**。

## 文档

- [架构说明](ARCHITECTURE.md) · [产品需求](PRODUCT_REQUIREMENTS.md) · [路线图](ROADMAP.md)
- [开发任务与验收清单](TASKS.md) · [变更记录](CHANGELOG.md)
- [0.4.15 收尾记录](docs/final-local-0.4.15.md)（含全部测试数字与未验边界）

## 状态与边界

当前版本 **0.4.15**，Python 全量测试 1343 项通过。

已知边界（不粉饰）：

- 代码签名未做，安装包未签名
- 干净 Windows 环境的安装/升级/卸载未验
- 真实模型的端到端质量与费用，只做过最小验证（4 次调用 / 2405 token）
- 百万字历史库启动 P95 约 13 秒，目标是 5 秒，仍在优化

## License

MIT
