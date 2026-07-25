<div align="center">

<img src="assets/llmquant-skills-logo.svg" alt="LLMQuant Skills" width="128" />

<h1>LLMQuant Skills</h1>

<p><strong>面向金融的可复用 Agent Skills，数据都来自 <a href="https://github.com/LLMQuant/data-mcp">LLMQuant Data</a></strong></p>

<p><a href="README.md">English</a> · <strong>简体中文</strong></p>

<p>
  <a href="https://github.com/LLMQuant/skills/stargazers"><img src="https://img.shields.io/github/stars/LLMQuant/skills?style=flat" alt="GitHub stars" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-lightgrey.svg" alt="License: MIT" /></a>
  <a href="https://github.com/LLMQuant/data-mcp"><img src="https://img.shields.io/badge/native%20data-LLMQuant%20Data%20MCP-0B5FFF" alt="Native LLMQuant Data MCP" /></a>
  <a href="https://llmquantdata.com/agent"><img src="https://img.shields.io/badge/agent%20playground-open-8A5A44" alt="Open LLMQuant Agent Playground" /></a>
  <a href="https://github.com/LLMQuant/skills/commits"><img src="https://img.shields.io/github/last-commit/LLMQuant/skills" alt="Last commit" /></a>
</p>

</div>

```bash
npx skills add LLMQuant/skills      # Claude Code · Codex · Cursor · Antigravity · OpenClaw · Hermes · …
```

> [!TIP]
> 一共 18 个大类 skill，覆盖股票、期权、宏观、加密、信用、组合、风险等。它们会把 Agent 带到合适的金融分析流程，并保证每个结论都有 LLMQuant Data 作为依据。

## 目录

- [概览](#概览)
- [大类 Skills](#大类-skills)
- [安装](#安装)
  - [推荐 `npx skills add`](#推荐-npx-skills-add)
  - [原生插件安装](#原生插件安装)
- [LLMQuant Data](#llmquant-data)
- [贡献](#贡献)
- [许可](#许可)

## 概览

<div align="center">
  <img src="assets/llmquant-skills-header.png" alt="LLMQuant Skills，数据都来自 LLMQuant Data 的金融 Agent Skills" width="820" />
</div>

这个仓库是一个 skill 目录。安装和使用的基本单位，是 `skills/llmquant-*` 下的一个大类文件夹。每个大类都有一个 `SKILL.md` 当入口：它列出这个大类里的所有流程（`workflows/*.md`），告诉 Agent 该用哪个，并要求所有外部事实都来自 LLMQuant Data。它不是一个单独的 `SKILL.md`，也不是单个流程文件。

<details>
<summary><strong>仓库结构</strong></summary>

```text
skills/
├── llmquant-data/
│   ├── SKILL.md
│   ├── workflows/
│   ├── scripts/
│   └── assets/
├── llmquant-etfs/
│   ├── SKILL.md
│   └── workflows/
└── ...

.claude-plugin/     # Claude Code 插件 + marketplace 清单
.codex-plugin/      # Codex 插件清单
.cursor-plugin/     # Cursor 插件清单
assets/
README.md
README.zh-CN.md
```

</details>

## 大类 Skills

| Skill | 范围 | 主要 workflows |
|---|---|---|
| [`llmquant-data`](skills/llmquant-data) | LLMQuant Data 基础数据和有来源的研究。 | 10-K 风险审查、13F 持有人、美国宏观快照、宏观简报 |
| [`llmquant-equities`](skills/llmquant-equities) | 股票研究、横向比较、估值、催化剂和卖出纪律。 | Five-lens analysis、equity compare、research memo、merger arb、take-profit lab |
| [`llmquant-etfs`](skills/llmquant-etfs) | ETF 持仓、重叠、集中度和敞口分析。 | ETF overlap report |
| [`llmquant-options`](skills/llmquant-options) | 期权、波动率、Greeks、异常交易和期权回测。 | IV rank、strategy builder、Greeks dashboard、P&L simulator、volatility surface |
| [`llmquant-equity-derivatives`](skills/llmquant-equity-derivatives) | 单只股票的衍生品和混合证券研究。 | Single-stock derivative playbook、convertible and warrant lens |
| [`llmquant-commodities`](skills/llmquant-commodities) | 商品现货、期货曲线、库存和宏观联动。 | Commodity market lens、futures curve monitor |
| [`llmquant-crypto`](skills/llmquant-crypto) | 加密市场行情、代币研究、永续资金费率、基差和杠杆监控。 | Crypto market regime、token research、perp funding monitor |
| [`llmquant-prediction-markets`](skills/llmquant-prediction-markets) | 事件赔率、预测市场合约、概率差和跨平台套利检查。 | Event probability brief、arb watch、probability vs options pricing |
| [`llmquant-macro`](skills/llmquant-macro) | 宏观面板、央行会议前瞻、流动性、增长、通胀和组合影响。 | Global macro dashboard、Fed policy preview、macro-to-portfolio impact |
| [`llmquant-credit`](skills/llmquant-credit) | 发行人信用、利差行情、高收益压力、再融资和违约风险。 | Issuer credit risk review、credit spread regime、high-yield stress monitor |
| [`llmquant-rates-fx`](skills/llmquant-rates-fx) | 利率、收益率曲线、央行分化、外汇 carry 和汇率风险。 | Yield curve trade lens、central-bank divergence、FX carry dashboard |
| [`llmquant-events`](skills/llmquant-events) | 财报、并购、监管、法律、政策和催化剂事件跟踪。 | Earnings event brief、M&A event tracker、regulatory risk monitor |
| [`llmquant-portfolio`](skills/llmquant-portfolio) | 公司档案、观点跟踪、关注列表、提醒和主题研究。 | Company profile、thesis tracker、theme research、watchlist monitor、alert manager |
| [`llmquant-portfolio-lab`](skills/llmquant-portfolio-lab) | 组合敞口图、假设推演和虚拟组合状态。 | Portfolio exposure map、portfolio what-if simulator |
| [`llmquant-risk`](skills/llmquant-risk) | 风险行情、对冲、恐慌打分和研究质量检查。 | Fear score、VIX status、hedge advisor、research health check |
| [`llmquant-strategies`](skills/llmquant-strategies) | 对冲基金和基金经理的策略手册。 | Equity long/short、long-biased、event-driven、macro、quant、multi-strategy |
| [`llmquant-market-intelligence`](skills/llmquant-market-intelligence) | 可复用的市场工具和信号视图。 | Macro view、market sentiment、event probability signals |
| [`llmquant-investor-lenses`](skills/llmquant-investor-lenses) | 用 LLMQuant Data 当证据的投资大师视角。 | Buffett、Graham、Munger、Lynch、Fisher、Burry、Ackman、Damodaran 等 |

## 安装

### 推荐 `npx skills add`

一条命令，适用于 Claude Code、Codex、Cursor、Antigravity、Gemini 等多种 Agent。

> [!TIP]
> 已经在某个 Agent 里了？直接运行 `npx skills add LLMQuant/skills`，它会自己认出当前环境，装到该装的位置。

```bash
# 在当前 Agent 里挑选要装的 skill
npx skills add LLMQuant/skills

# 全局安装全部大类 skill
npx skills add LLMQuant/skills -g --all

# 只装其中几个
npx skills add LLMQuant/skills -g --skill llmquant-options llmquant-equities

# 指定某个 Agent
npx skills add LLMQuant/skills -a codex
```

用 `npx skills list`、`npx skills update`、`npx skills remove` 管理已经装好的 skill。装好后在 Agent 里问一句 `What skills are available?`，或者直接调用，比如 `/llmquant-options`。

<div align="center">
  <img src="assets/skills-add-screenshot.png" alt="用 npx skills add 挑选 LLMQuant skills" width="720" />
</div>

### 原生插件安装

整个仓库也打包成了一个插件，一次就能装上全部大类 skill，适合自带插件系统的 Agent。

**Claude Code**：把这个仓库加成插件市场，再装这个插件包：

```text
/plugin marketplace add LLMQuant/skills
/plugin install llmquant-skills@llmquant
```

**Codex**：仓库里带了 `.codex-plugin/plugin.json`，已经可以当插件用。现在想装的话，用上面那条命令（`npx skills add LLMQuant/skills -a codex`），或者用 skill installer 装单个大类 skill：

```text
$skill-installer install https://github.com/LLMQuant/skills/tree/main/skills/llmquant-options
```

**Cursor、Antigravity、其他 Agent**：用上面推荐的命令，把 agent 名字换成对应的就行，比如 `npx skills add LLMQuant/skills -a cursor` 或 `-a antigravity`。

## LLMQuant Data

这些 skill 是 **[LLMQuant Data](https://github.com/LLMQuant/data-mcp)** 的流程层。LLMQuant Data 是一个 MCP server，把价格、财报、13F、宏观、ETF 持仓、加密等数据，送到你的各个 Agent。**配置一次，你用的每个 Agent 都能用上这些数据。**

<div align="center">
  <img src="assets/ecosystem.png" alt="LLMQuant Data 跟着你的 Agent 到处可用，包括 Claude Code、Cursor、Codex、Gemini 等" width="800" />
</div>

**用 AI 的方式装**，把下面这句话发给你的 Agent：

```text
Install the LLMQuant data-mcp server in this environment by following https://github.com/LLMQuant/data-mcp
```

或者自己手动加：

```bash
claude mcp add llmquant-data -e LLMQUANT_API_KEY=your_api_key -- npx -y @llmquant/data-mcp
```

> [!NOTE]
> 申请 API key、以及多个 Agent 的完整配置说明，见 **[docs.llmquantdata.com](https://docs.llmquantdata.com)** 和 **[`LLMQuant/data-mcp`](https://github.com/LLMQuant/data-mcp)**。

skill 会用大白话说明自己需要什么数据，让 Agent 去对接 LLMQuant Data 当前提供的能力，所以数据范围可以慢慢变大，而不用改任何 skill。就算没连 `llmquant-data`，skill 也能当普通流程用：这时 Agent 会让你提供数据，并把缺的部分标清楚。完整的数据使用规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。

<div align="center">
  <a href="https://llmquantdata.com/agent"><img src="assets/playground.png" alt="LLMQuant Agent Playground，已开启 Data MCP 和 Skills" width="800" /></a>
  <br/>
  <strong><a href="https://llmquantdata.com/agent">打开 LLMQuant Agent Playground →</a></strong>
</div>

<details>
<summary><strong>▶ 看一段 playground 演示</strong></summary>
<br/>
<div align="center">
  <img src="assets/llmquant-data-agentplayground-demo.gif" alt="LLMQuant Agent Playground 演示，Data MCP 和 Skills 实际运行" width="800" />
</div>
</details>

## 贡献

在对应的大类里新增或修改流程。目录结构是 `skills/llmquant-<category>/`，里面有 `SKILL.md`、`workflows/`、`scripts/`、`assets/`：

- 大类文件夹必须以 `llmquant-` 开头。`SKILL.md` 是入口，要列出这个大类的每一个流程。
- 流程文件里写清楚：可重复的操作步骤、输出长什么样、需要哪些数据、有哪些限制。
- 把需要的数据用大白话说清楚，不要在里面写死具体的 MCP 工具名。
- 新增、删除或重命名一个大类或主要流程时，记得更新这个 README。

完整规则和质量要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

采用 MIT 许可，见 [LICENSE](LICENSE)。在这里收录某个项目，不会改变它自己代码或文件的许可。

<div align="center">
  <br/>
  <img src="assets/llmquant-logo.svg" alt="LLMQuant" width="64" />
  <br/><br/>
  <strong><a href="https://llmquant.com">LLMQuant</a></strong>
  <br/>
  <sub>面向 AI、大模型和量化金融的开源社区。</sub>
  <br/><br/>
  <a href="https://llmquant.com">Website</a> ·
  <a href="https://github.com/LLMQuant">GitHub</a> ·
  <a href="https://linkedin.com/company/llmquant">LinkedIn</a>
</div>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=LLMQuant/skills&type=Date)](https://www.star-history.com/#LLMQuant/skills&Date)
