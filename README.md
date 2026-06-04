# QuantBridge

> FinceptTerminal 旁路研究桥 + 因子检验 lite + 简易回测降级 + Streamlit 观察面板

## 是什么

QuantBridge 是一个轻量外部 orchestrator，用文件契约把研究结果写到 `outputs/`。
当前重点是稳定跑通原型闭环，而不是替代 FinceptTerminal 本体的策略系统。

```
显式触发文件 / 定时轮询
    │
    ▼
QuantBridge daemon
    │
    ▼
数据 → 因子 → 因子检验 lite → 简易回测/LEAN 预留 → pyfolio-style 摘要
    │
    ▼
outputs/signals.json + outputs/pipeline_state.json + outputs/runtime/heartbeat.json
```

说明：
- `alphalens_runner.py` 当前使用内置 IC/分层检验，尚未调用完整 alphalens API。
- `lean_runner.py` 当前优先检测 Docker/LEAN，但完整 LEAN Docker 执行仍是预留点，不可用时降级到简易 EMA 回测。
- `pyfolio_runner.py` 当前生成 pyfolio-style 指标摘要，尚未生成完整 pyfolio tear sheet。
- `fincept.integration_mode` 当前固定采用 `file` 语义；FinceptTerminal 本体尚未原生消费 `outputs/signals.json`，需要后续在 FinceptTerminal 内增加读取/触发入口后才能升级为 `native`。
- 文件契约见 `schemas/signals.schema.json`、`schemas/pipeline_state.schema.json`、`schemas/trigger.schema.json`。

## 架构

```
QuantBridge/
├── launch.sh                    # 一键启动全部
├── config/default.yaml          # 策略与参数配置
├── quantbridge/
│   ├── daemon.py                # 后台常驻：显式触发文件 + 定时轮询
│   ├── pipeline.py              # 管线引擎：调度全流程
│   ├── dashboard.py             # Streamlit 实时仪表盘
│   ├── data/fetcher.py          # 数据层：yfinance + 缓存
│   ├── factors/
│   │   ├── engine.py            # 因子计算引擎
│   │   └── alphalens_runner.py  # 因子检验 lite
│   ├── backtest/
│   │   └── lean_runner.py       # LEAN 预留 + 简易回测降级
│   ├── reporting/
│   │   └── pyfolio_runner.py    # pyfolio-style 绩效摘要
│   └── fincept/
│       └── bridge.py            # FinceptTerminal 文件桥接预留
└── outputs/                     # 输出：信号、运行状态、报告、缓存
```

## 快速开始

### 1. 创建环境

```bash
cd QuantBridge
conda env create -f environment.yml
conda activate quantbridge
```

### 2. 配置

编辑 `config/default.yaml`：
- 修改 `data.tickers` 为你的自选股
- 调整 `backtest.lean.cash` 为你的初始资金
- 设置 `fincept.fincept_home` 为 FinceptTerminal 本地仓库或安装路径

### 3. 启动

```bash
# 一键启动（daemon + dashboard + 可选 FinceptTerminal）
./launch.sh

# 或分开启动
quantbridge --daemon          # 仅后台服务
streamlit run quantbridge/dashboard.py  # 仅仪表盘
```

打开 http://localhost:8501 查看实时仪表盘。

### 4. 使用流程

1. **FinceptTerminal 看盘** → 选策略、看新闻、AI 给灵感
2. **写入触发文件** → 在 `outputs/watch/` 写入 `trigger_*.json`、`strategy_*.yaml` 或 `params_*.yaml`
3. **自动回环** → daemon 检测显式触发文件，执行因子检验 → 回测降级/LEAN 预留 → 绩效摘要
4. **Dashboard 查看** → 实时的 IC 分析、回测绩效、交易信号
5. **调整重来** → 修改参数或触发文件，进入下一轮

## 环境要求

- Python 3.11+
- Docker（可选；当前完整 LEAN Docker 执行仍在后续迭代）
- Conda / Miniforge
- FinceptTerminal（可选；当前不是原生双向集成）

## 路线图

- [x] v0.1 — 数据拉取 + 因子计算 + 因子检验 lite
- [x] v0.2 — 简易回测降级方案
- [x] v0.3 — pyfolio-style 绩效摘要 + Streamlit 仪表盘
- [x] v0.4 — FinceptTerminal 文件桥接预留
- [x] v0.5 — Daemon 后台常驻 + 显式触发文件
- [ ] v0.6 — 完整 LEAN Docker 集成（C# 模板生成）
- [ ] v0.7 — FinceptTerminal 原生读取 signals / 写入 trigger 入口
- [ ] v0.8 — Paper trading 对接 Alpaca/IBKR
- [ ] v1.0 — 端到端验证：实盘模拟一个月

## License

MIT
