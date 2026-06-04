# QuantBridge

> FinceptTerminal + alphalens + LEAN + pyfolio — 全自动量化策略管线

## 是什么

QuantBridge 把四个量化工具串成一个**自动回环**：

```
FinceptTerminal（看盘/研究/AI 策略）
    │
    ▼
alphalens（因子检验：IC、分层回测、换手率）
    │
    ▼
LEAN（精密事件驱动回测：滑点、手续费、成交模拟）
    │
    ▼
pyfolio（绩效审计：VaR、回撤、尾部风险、月度收益）
    │
    └── 结果自动写回 FinceptTerminal ──→ 用户调整策略 ──→ 重新回环
```

## 架构

```
QuantBridge/
├── launch.sh                    # 一键启动全部
├── config/default.yaml          # 策略与参数配置
├── quantbridge/
│   ├── daemon.py                # 后台常驻：监听 + 定时 + 自动回环
│   ├── pipeline.py              # 管线引擎：调度全流程
│   ├── dashboard.py             # Streamlit 实时仪表盘
│   ├── data/fetcher.py          # 数据层：yfinance + 缓存
│   ├── factors/
│   │   ├── engine.py            # 因子计算引擎
│   │   └── alphalens_runner.py  # 因子检验
│   ├── backtest/
│   │   └── lean_runner.py       # LEAN Docker 回测
│   ├── reporting/
│   │   └── pyfolio_runner.py    # 绩效分析
│   └── fincept/
│       └── bridge.py            # FinceptTerminal 双向桥接
└── outputs/                     # 输出：信号、报告、缓存
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
- 设置 `fincept.fincept_home` 为 FinceptTerminal 安装路径

### 3. 启动

```bash
# 一键启动全部（FinceptTerminal + daemon + dashboard）
./launch.sh

# 或分开启动
quantbridge --daemon          # 仅后台服务
streamlit run quantbridge/dashboard.py  # 仅仪表盘
```

打开 http://localhost:8501 查看实时仪表盘。

### 4. 使用流程

1. **FinceptTerminal 看盘** → 选策略、看新闻、AI 给灵感
2. **修改信号** → FinceptTerminal 的策略变更自动写入 `outputs/watch/`
3. **自动回环** → daemon 检测变更，执行因子检验 → LEAN 回测 → pyfolio 分析
4. **Dashboard 查看** → 实时的 IC 分析、回测绩效、交易信号
5. **调整重来** → 在 FinceptTerminal 里修改参数，自动触发新回环

## 环境要求

- Python 3.11+
- Docker（LEAN 回测）
- Conda / Miniforge
- FinceptTerminal（可选，无它时 pipeline 独立运行）

## 路线图

- [x] v0.1 — 数据拉取 + 因子计算 + alphalens 检验
- [x] v0.2 — LEAN Docker 回测（含简易回测降级方案）
- [x] v0.3 — pyfolio 绩效分析 + Streamlit 仪表盘
- [x] v0.4 — FinceptTerminal 双向桥接
- [x] v0.5 — Daemon 后台常驻 + 自动回环
- [ ] v0.6 — 完整 LEAN Docker 集成（C# 模板生成）
- [ ] v0.7 — Paper trading 对接 Alpaca/IBKR
- [ ] v1.0 — 端到端验证：实盘模拟一个月

## License

MIT
