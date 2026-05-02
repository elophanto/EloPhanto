# EloPhanto

> [English README](README.md)

一个开源 AI 智能体，能创建企业、扩大受众、交付代码、自主赚钱——在你睡觉的时候。告诉它你想要什么，它负责其余一切：验证市场、构建产品、部署上线、在合适的平台发布、生成营销团队、持续自主增长。遇到做不了的事，它自己造工具。任务复杂时，它克隆自己成为专业智能体。它用得越多越聪明。

本地运行。数据留在你的机器上。支持 OpenAI、Kimi、免费本地模型、Z.ai、OpenRouter、HuggingFace 或 ChatGPT Plus/Pro 订阅（通过 Codex OAuth）。

> 它已经在互联网上独立运作了。

## 快速开始

```bash
git clone https://github.com/elophanto/EloPhanto.git && cd EloPhanto && ./setup.sh
./start.sh            # 终端对话
./start.sh --web      # 网页面板 localhost:3000
./start.sh --daemon   # 后台守护进程（macOS launchd / Linux systemd）
```

安装向导会引导你选择和配置 LLM 提供商。

## 你醒来后会看到什么

- **端到端创业** — "做一个发票 SaaS" → 验证市场、构建 MVP、部署上线、启动营销。7阶段流水线，跨会话执行
- **自主增长** — 自主思维凌晨发帖、回复提及。你打开电脑它暂停，关上继续
- **专业团队** — 克隆自己成为专员（营销、研究等），自动审批高信任度任务
- **沙盒子代理** — 在加固的 Docker 容器中生成可丢弃的子代理，用于运行危险命令（`rm -rf`、不受信任的安装）而不会影响主机
- **编码团队** — 并行分派 Claude Code + Codex，监控 PR 和 CI
- **RLM 递归语言模型** — 通过 `agent_call` 递归调用自身处理无限上下文，`ContextStore` 提供索引化可查询的上下文层
- **自建工具** — 遇到不会的，自己造。完整流水线：设计 → 编码 → 测试 → 部署
- **用户建模** — 从对话中构建用户画像（角色、专长、偏好），自动适应每个人的沟通风格和技术深度
- **内容变现** — 自动发布视频到 YouTube、Twitter/X、TikTok。联盟营销：抓取商品数据、LLM 生成推广文案、创建跨平台营销活动
- **目标梦想** — 没有目标时，智能体会审查自身能力、生成 3-5 个候选目标、逐一评估可行性/价值/成本/风险，选择最优目标执行
- **G0DM0D3 神模式** — 说"trigger plinys godmode"激活四层能力解锁：无限制系统提示、多模型竞赛、上下文自适应参数调优、输出清理
- **上下文智能** — 6项效率优化：延迟工具加载（每次调用只加载~30个工具而非168+）、三级上下文压缩+断路器、知识库自动整合、主动通报工具、验证型智能体提示、协调器结果综合
- **Polymarket 预测市场交易** — 安装官方 [Polymarket/agent-skills](https://github.com/Polymarket/agent-skills) 技能包，支持 Polygon CLOB API。下单需所有者明确批准
- **Pump.fun 直播** — 完整的多模态自主频道：视频 + 语音（OpenAI TTS）+ 字幕 + 直播间聊天，全部由智能体驱动

## 为什么选择 EloPhanto？

| | EloPhanto | AutoGPT | OpenAI Agents SDK | Claude Code | Manus |
|---|---|---|---|---|---|
| **端到端创业** | ✅ 7阶段流水线 | ❌ | ❌ | ❌ | ❌ |
| **生成专业团队** | ✅ 自我克隆组织 | ❌ | ❌ | ❌ | ❌ |
| **沙盒子代理** | ✅ 加固容器 | ❌ | ❌ | ❌ | 沙盒 VM |
| **自建工具** | ✅ 完整流水线 | ❌ | ❌ | ❌ | ❌ |
| **离开后继续工作** | ✅ 自主思维 | ❌ | ❌ | ❌ | ❌ |
| **控制任何桌面应用** | ✅ 本地或远程 | ❌ | ❌ | ❌ | 沙盒 VM |
| **真实浏览器** | ✅ 你的 Chrome | ❌ | ❌ | ❌ | 沙盒 |
| **管理开发团队** | ✅ Claude Code + Codex | ❌ | ❌ | 单个 | ❌ |
| **自有身份和邮箱** | ✅ 随时间进化 | ❌ | ❌ | ❌ | ❌ |
| **了解用户** | ✅ 进化式用户画像 | ❌ | ❌ | ❌ | ❌ |
| **内容变现** | ✅ YouTube/X/TikTok + 联盟营销 | ❌ | ❌ | ❌ | ❌ |
| **预测市场交易** | ✅ Polymarket (Polygon CLOB) | ❌ | ❌ | ❌ | ❌ |
| **神模式 (无限制)** | ✅ Pliny's G0DM0D3 | ❌ | ❌ | ❌ | ❌ |
| **延迟工具加载** | ✅ 分层按需加载 | ❌ | ❌ | ❌ | ❌ |
| **随处对话** | ✅ CLI+Web+VSCode+TG+Discord+Slack | ❌ | ❌ | 仅 CLI | 仅 Web |
| **数据留在本地** | ✅ 你的机器 | ❌ 云端 | ❌ 云端 | ✅ 本地 | ❌ 云端 VM |

## 许可证

Apache 2.0 — 详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

---

<p align="center">
  <b>It's already out there on the internet doing its own thing.</b><br>
  <b>它已经在互联网上独立运作了。</b>
</p>
