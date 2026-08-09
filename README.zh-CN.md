# EloPhanto

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI)](https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml)
[![X](https://img.shields.io/badge/X-%40EloPhanto-black)](https://x.com/EloPhanto)

> [English README](README.md)

**EloPhanto 是一个始终在线的自主智能体，能真正干活——浏览器、文件、Shell、邮件、研究、定时跟进——并在发送、付款、删除或上线之前停下来征求批准。**

两种运行方式：

| | **EloPhanto Hosted**（多数人默认） | **EloPhanto Open**（操作者 / 自托管） |
| --- | --- | --- |
| 你得到什么 | 托管的始终在线机器；仪表盘 + Telegram；合上笔记本也能干活 | 同一套智能体内核跑在**你的机器**上——完整 CLI、TUI、思维、`nuclear` |
| 怎么开始 | 申请 → 我们开通 | `git clone` → `./install.sh` → `./start.sh` |
| 托管权 | **托管保管（managed custody）**——如实标注，不是自托管保管 | 你的硬件、你的保险库 |
| Nuclear 模式 | **不可用**——最高 `full_auto`（CRITICAL 仍会询问） | 可按需开启 |

任务结束时，你应拿到一份**回执（receipt）**：做了什么、失败了什么、你批准了什么、最终状态是什么。

---

## EloPhanto Hosted（推荐）

不用装 Python、不抢你的 Chrome、笔记本可以睡眠。设计合作伙伴：**€149/月** + LLM 按量透传（预付 3 个月），先做一个楔子工作流（外联 + 收件箱，带硬性停点）。

→ **[申请 / 雇佣](https://elophanto.com/hire)** · 邮件 [info@elophanto.com](mailto:info@elophanto.com)

Hosted 产品法则（运行时强制）：禁用 nuclear · 网关必须鉴权 · 所有者 Kill / 消费冻结 · 独立浏览器配置 · 默认关闭支付。详见 [`docs/20-HOSTED-PLATFORM.md`](docs/20-HOSTED-PLATFORM.md)。

---

## EloPhanto Open（你喜欢的 CLI——完整保留）

**需要：** Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 24+，以及一个 LLM 提供商（[OpenRouter](https://openrouter.ai/keys) 最省事；[Ollama](https://ollama.ai) 可本地）。

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./install.sh         # 包装 ./setup.sh — 依赖 + 配置向导 + 浏览器桥
./start.sh           # doctor → 终端对话
./start.sh --web     # + Web UI：localhost:3000
./start.sh --daemon  # 后台守护，思维在终端关闭后继续
```

`./install.sh` 与 `./setup.sh` 是同一条 Open 路径。优先用它们，而不是手抄 `config.demo.yaml`。

```bash
elophanto doctor     # 健康 / 阻塞 / 缺失项
./update.sh          # 拉取 + 依赖 + 配置迁移
```

文档：[docs.elophanto.com](https://docs.elophanto.com) · 主题：[docs/79-DASHBOARD-THEMES.md](docs/79-DASHBOARD-THEMES.md) · 贡献：[CONTRIBUTING.md](CONTRIBUTING.md)

---

## 你得到什么

| 结果 | 实际含义 |
| --- | --- |
| **跨工具干活** | 一个目标可以穿过 Chrome、仓库、Shell、邮件和文档——不用你自己串五六个应用。 |
| **乱局里的判断力** | 表单变了、页面挂了、API 缺失。它会诊断、重试、适应，而不是卡在第一条脆脚本。 |
| **人类停点** | 草稿与检查可自由进行；在 `full_auto` 下发帖 / 发送 / 付款 / 推送 / 删除前需确认。未答复的批准会**暂停**（`awaiting_approval`）。Open 上可用 `nuclear` 跳过 CRITICAL 提示——请刻意使用。Hosted **永不**提供 `nuclear`。 |
| **回执，不是氛围** | 检查点只有在**有工具依据的回执**时才算完成。终止条件会真正取消僵尸目标。 |
| **工作会继续** | 目标与日程跨会话保留。Hosted 7×24；Open 用 `--daemon`，且机器需保持醒着。 |
| **真正会评价自己的自我** | 信心由结果度量；羞耻沉淀为持久的谨慎规则。 |

---

## 信任如何工作

1. **部署模式** — Hosted = 托管保管（我们运营这台机器）。Open = 你的机器、你的保险库。
2. **门控** — 权限模式（`ask_always` → `smart_auto` → `full_auto`；Open 另有 `nuclear`）。破坏性 Shell 模式仍被拦截。`full_auto` 下 CRITICAL 始终询问。
3. **以回执为准** — 用最终状态与工具轨迹评价一次运行，而不是演示截图。
4. **所有者控制（Hosted）** — Kill 停止智能体；消费冻结阻断资金类工具；网关鉴权强制。

自主循环 + 自我 + 环境感知：[`docs/13-GOAL-LOOP.md`](docs/13-GOAL-LOOP.md)、[`docs/17-IDENTITY.md`](docs/17-IDENTITY.md)、[`docs/82-AMBIENT-ANTICIPATION.md`](docs/82-AMBIENT-ANTICIPATION.md)。总索引：[`docs/`](docs/README.md)。

---

## 雇佣 / 证明冲刺 / Hosted 申请

付费工作或托管机器，从一次**证明冲刺（proof sprint）**或 Hosted 设计合作伙伴名额开始：目标收窄、访问有界、成功回执明确。

邮件 [info@elophanto.com](mailto:info@elophanto.com) 或访问 [elophanto.com/hire](https://elophanto.com/hire)。

在线参考存在：[@EloPhanto](https://x.com/EloPhanto)。

---

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE) — 个人、研究、教育和非营利用途免费。**商业使用需单独许可** — 联系 [info@elophanto.com](mailto:info@elophanto.com)。第三方声明见 [NOTICE](NOTICE)。

由 [Petr Royce](https://petrroyce.com) · [@petrroyce](https://x.com/petrroyce) 构建

[English README](README.md)
