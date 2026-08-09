# EloPhanto

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/elophanto/EloPhanto/ci.yml?label=CI)](https://github.com/elophanto/EloPhanto/actions/workflows/ci.yml)
[![X](https://img.shields.io/badge/X-%40EloPhanto-black)](https://x.com/EloPhanto)

> [English README](README.md)

多数智能体在会话结束的那一刻就把你忘了。这一个保留自己的名字、记忆，以及对自身工作的评价。

EloPhanto 是一个拥有持久身份的自主智能体。它操作真实 Chrome 配置、你的文件、Shell 和收件箱。缺什么工具，它就自己写一个。跑上一个月，它已经可测量地不再是你最初启动的那个智能体。

**在任何无法撤销的动作之前，它会停下来征求批准。** 正是这一条规则，让"把它一直开着"成为一个合理的决定。

它写给两类人：希望在自己睡觉时仍有真实工作在推进的人，以及不肯信任无法审计的智能体的工程师。下面每个机制都链接到规定它的设计文档，每个数字都来自对本仓库的一次实时加载。

- **Hosted** — 托管实例，你的笔记本睡了它还醒着。[申请](https://elophanto.com/hire)。
- **Open** — 全部跑在你的机器上：完整 CLI、TUI、加密保险库、`nuclear` 模式。

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto
./install.sh         # 依赖 + 配置向导 + 浏览器桥
./start.sh           # 健康检查 → 终端对话
```

---

## 它给自己写绩效评估

`knowledge/self/nature.md` 不是谁写的文档，而是智能体基于自身可度量的结果反思后自行维护的文件。以下是本仓库中未经编辑的真实输出：

> **哪些做法行不通**
> - 把已发送的消息、已创建的付款请求、日程或工具执行成功，当作已付费验证。
> - 在前置条件或成功标准缺失时，就把检查点标记为完成。
> - 依据未付费的兴趣或假设中的客户需求来撰写产品规格。
>
> **观察**
> - 这轮外联远未达到自己设定的 20 个潜客与 5 场对话的门槛，而寻找更多潜客的调研也仍未完成。
> - USDC 带来了可追溯性，但它衡量的可能是买方对支付方式的容忍度，而非对报价本身的需求。

没有任何人要求它对自己这么严苛，也没有任何机制允许它给这轮外联打个高分。它写在那里的内容，会改变它明天去做什么。

---

## 底下的三个机制

**[持久的身份](docs/17-IDENTITY.md)。** 价值观、信念与能力跨会话沉淀在 SQLite 中，并呈现为上面那份可读文件。第一天和第三周是不同的智能体，而这个差异你可以直接读出来。

**[会给自己记分的自我](docs/17-IDENTITY.md)。** 信心是每项能力上的一个数值，由结果计算得出，而非自我申报。当信心低于当前任务的难度时，智能体会强制发出批准请求——即使在 `full_auto` 下，即使那是它上周还随手在做的事。受挫会让它在结构上变得更谨慎，而提示会告诉你是哪项能力、哪个数值触发了它。

**[你不在时仍在运转的思维](docs/75-AUTONOMOUS-MIND-V2.md)。** 一个可选开启的后台循环。每次唤醒都会对候选工作打分——停滞的检查点、被冷落的使命、外部信号、它自己的梦境日志——再由 LLM 择一，在你设定的预算内推进。默认关闭，直到你亲手打开。

围绕这三者的是：[以回执为门槛的目标](docs/13-GOAL-LOOP.md)，没有工具轨迹就无法关闭检查点；以及[自己编写的工具](docs/04-SELF-DEVELOPMENT.md)，附带影响分析与 git 回滚。

它通过 274 个工具触达外部世界：真实浏览器（其中 47 个，驱动你的 Chrome 配置及其登录态）、Shell、文件系统、邮件，以及任意 [MCP](docs/23-MCP.md) 服务器。你可以从 CLI、Web 仪表盘、VS Code、Telegram、Discord 或 Slack 与它对话。

## 它能经营一家公司

把一门生意交给 EloPhanto，它会把它当作一个独立实体来经营，而不是一堆任务的集合。每家公司都拥有自己的产品定义、从你既有文字中提炼出的语气契约、客户线索管道、由它提出并交你审阅的战略方案，以及一本把智能体自身的认知开销计入公司成本的分类账本。竞品会依据已核验的证据打分，证据缺失之处留空。资金走的是真实的自托管通道。

信任需要逐级挣得：`learning` 阶段一切先出草稿交你审阅，`trial` 与 `operating` 则允许它自己发信、自己成交。已交付十一个阶段：[框架](docs/76-ABE-FRAMEWORK.md) · [资金通道](docs/80-ABE-FINANCE-RAIL.md) · [竞品情报](docs/81-COMPETITIVE-INTEL.md)

## 你醒来会看到什么

- 一个停在 `awaiting_approval` 的目标，而不是自作主张。未答复的批准会暂停，绝不会过期变成同意。
- 三十分钟后有个会议，一份会前准备等着你点头，因为它[看到了日历并先来征求同意](docs/82-AMBIENT-ANTICIPATION.md)。
- 一个停滞的检查点在夜里被恢复，因为思维把它排在了所有可选工作之上。
- 一份变动了的[竞品评分卡](docs/81-COMPETITIVE-INTEL.md)，引用已对照实时页面核验，证据缺失之处留空。
- 一行账本记录，写着昨夜实际花了多少：按公司、按 token、按金额。

---

## 怎么跑起来

**EloPhanto Open。** 你的机器，你的密钥。

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 24+，以及一个 LLM 提供商（[OpenRouter](https://openrouter.ai/keys) 最省事；[Ollama](https://ollama.ai) 可做到完全本地）。

```bash
./install.sh         # 等同于 ./setup.sh — 依赖、向导、浏览器桥
./start.sh           # 终端对话
./start.sh --web     # + 仪表盘：localhost:3000
./start.sh --daemon  # 后台服务，循环不随终端关闭而中断
elophanto doctor     # 健康 / 故障 / 缺失项
./update.sh          # 拉取 + 依赖 + 配置迁移
```

后台思维出厂即关闭。让它运转起来的唯一开关，是 `autonomous_mind.enabled: true`。

**EloPhanto Hosted。** 适合不想自己运维基础设施的人。一台专属实例，拥有独立浏览器配置，可从仪表盘与 Telegram 访问，全天候在线。

那里的规则更严格，也明说：**托管保管（managed custody）**，即机器由我们运营，因此不是自托管保管。Hosted 上不存在 `nuclear` 模式，网关鉴权强制开启，支付默认关闭，而 Kill 开关与消费冻结在你手上。[Hosted 如何工作](docs/20-HOSTED-PLATFORM.md) · [申请](https://elophanto.com/hire) · [info@elophanto.com](mailto:info@elophanto.com)

---

## 它在哪里停下

1. **分级权限。** `ask_always` → `smart_auto` → `full_auto`，可在 `permissions.yaml` 中按工具覆盖。在 `full_auto` 下，16 个 CRITICAL 工具仍然始终询问：支付、钱包导出、自我修改、保险库写入、信任晋级、向页面注入 JavaScript。`nuclear` 连这些都跳过；它只存在于 Open，因为确实有操作者需要它。
2. **在此之上还有一道信心闸门。** 自我软门控会提高风险领域（支付、外联、浏览器）的难度阈值，因此一项尚无战绩的新能力在那些领域会先请求批准。
3. **先草稿，后发送。** 新公司从 `learning` 起步，只能写草稿。晋级是"提议—确认"，绝不会作为自主性的副作用发生。
4. **真正有效的停止。** `elophanto stop` 与所有者 Kill 开关会写下一个哨兵文件，智能体在每轮之间和每次唤醒时都会检查。密钥保存在加密保险库中，需要时通过工具调用取出，而不是写进配置或提示词。
5. **它碰不到的文件。** 安全关键的核心（执行器、保险库、权限校验）受保护，不受智能体自我修改流程的影响。

评价任何一次运行，都要看它的最终状态和工具轨迹，而不是看它自己怎么说。

[安全模型](docs/07-SECURITY.md) · [目标循环](docs/13-GOAL-LOOP.md) · [情感层](docs/69-AFFECT.md) · [恢复模式](docs/22-RECOVERY-MODE.md) · [docs.elophanto.com](https://docs.elophanto.com) · [总索引](docs/README.md)

## 细则

这里的自主性是逐级获得的。一家公司要从 `learning` 一路挣到 `trial`、再到 `operating`；一旦进入 operating，它就会自己发信、自己成交、自己花钱。加密货币是 Solana 与 Base 上的真实自托管通道；Stripe 法币通道则以测试模式交付，直到你完成 KYC 并手动切换。日历信号来自 ICS 文件与 webhook，而不是一个 Google OAuth 按钮。自我修改是它在获批后进入的流程，绝不会是无声的改写。另外，一个始终在线的智能体会消耗真实的 token，先盯一周账本，再决定要不要放宽预算。

---

## 规模

274 个工具 · 178 份技能手册 · 6 个客户端界面 · 16 个仪表盘页面 · 3,082 个测试 · 89 份设计文档。

---

## 雇佣它

付费工作请从一次证明冲刺（proof sprint）开始：目标收窄、访问有界，并在开始之前写下成功条件。[elophanto.com/hire](https://elophanto.com/hire) · [info@elophanto.com](mailto:info@elophanto.com)

它已经在互联网上自己跑着了：[@EloPhanto](https://x.com/EloPhanto)。

## 许可证

[PolyForm Noncommercial 1.0.0](LICENSE) — 个人、研究、教育和非营利用途免费。**商业使用需单独许可。** 第三方声明见 [NOTICE](NOTICE)。

由 [Petr Royce](https://petrroyce.com) 构建 · [English README](README.md) · [贡献指南](CONTRIBUTING.md)
