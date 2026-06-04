"""
LEAN 回测集成。

职责：
  1. 将 Python 侧的策略/因子翻译为 LEAN C# 算法代码
  2. 通过 Docker 拉起 LEAN 容器执行回测
  3. 捕获并解析回测结果（净值、交易记录）
"""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger


class LeanRunner:
    """LEAN 回测执行器（Docker 模式）。"""

    def __init__(
        self,
        docker_image: str = "quantconnect/lean:latest",
        data_dir: str = "outputs/lean_data",
        lean_config: dict | None = None,
    ):
        self.docker_image = docker_image
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = lean_config or {}

    def run(self, alphalens_results: dict, data: dict[str, pd.DataFrame]) -> dict[str, Any]:
        """执行 LEAN 回测。

        Args:
            alphalens_results: 因子检验结果（含通过因子列表）
            data: 标的价格数据

        Returns:
            {"metrics": {...}, "trades": [...], "equity": [...]}
        """
        if not alphalens_results.get("passed"):
            logger.warning("无通过因子，跳过 LEAN")
            return {"metrics": {}, "trades": [], "equity": []}

        # 检查 Docker
        if not self._docker_available():
            logger.warning("Docker 不可用，使用内置简易回测代替")
            return self._run_simple_backtest(alphalens_results, data)

        return self._run_lean_docker(alphalens_results, data)

    # ---- Docker LEAN ----

    def _docker_available(self) -> bool:
        try:
            result = subprocess.run(
                ["docker", "info"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_lean_docker(self, alphalens_results: dict, data: dict[str, pd.DataFrame]) -> dict:
        """Docker 运行 LEAN。具体实现在后续迭代中完成。"""
        logger.info("LEAN Docker 回测启动...")

        # 检查镜像
        result = subprocess.run(
            ["docker", "images", "-q", self.docker_image],
            capture_output=True, text=True,
        )
        if not result.stdout.strip():
            logger.warning(f"Docker 镜像 {self.docker_image} 未找到，使用简易回测")
            logger.info("拉取镜像: docker pull quantconnect/lean")
            return self._run_simple_backtest(alphalens_results, data)

        # TODO(v0.3): 完整 LEAN Docker 集成
        # 1. 生成 C# 算法文件 → temp dir
        # 2. docker run -v temp:/Lean/Launcher/bin/Debug \
        #    quantconnect/lean --data-folder /data \
        #    --algorithm-location /Lean/Launcher/bin/Debug/algorithm.py
        # 3. 解析输出 JSON

        logger.info("LEAN Docker 集成将在 v0.3 完整实现，当前使用简易回测")
        return self._run_simple_backtest(alphalens_results, data)

    # ---- 内置简易回测（LEAN 不可用时的降级方案）----

    def _run_simple_backtest(
        self, alphalens_results: dict, data: dict[str, pd.DataFrame]
    ) -> dict:
        """简易事件驱动回测。

        在没有 LEAN 时提供基本的回测能力，作为降级方案。
        """
        passed_factors = alphalens_results.get("passed_factors", [])
        tickers = list(data.keys())
        if not tickers:
            return {"metrics": {}, "trades": [], "equity": []}

        start_date = self.config.get("start_date", "2022-01-01")
        end_date = self.config.get("end_date", "2024-12-31")
        cash = float(self.config.get("cash", 100000))
        commission = float(self.config.get("commission", 0.001))
        max_position_pct = float(self.config.get("risk", {}).get("max_position_pct", 0.25))

        # 使用第一个标的做单标的回测
        primary = tickers[0]
        df = data[primary].loc[start_date:end_date]
        if df.empty:
            return {"metrics": {}, "trades": [], "equity": []}

        closes = df["close"].values
        equity = [cash]
        trades: list[dict] = []
        position = 0
        cash_on_hand = cash

        # 简单 EMA 交叉信号
        fast = self.config.get("strategy_params", {}).get("fast_period", 9)
        slow = self.config.get("strategy_params", {}).get("slow_period", 21)

        ema_fast = pd.Series(closes).ewm(span=fast, adjust=False).mean().values
        ema_slow = pd.Series(closes).ewm(span=slow, adjust=False).mean().values

        warmup = max(fast, slow) + 1
        for i in range(warmup, len(closes)):
            price = closes[i]

            # 信号
            if ema_fast[i] > ema_slow[i] and ema_fast[i - 1] <= ema_slow[i - 1]:
                # 金叉买入
                if position == 0:
                    max_value = cash_on_hand * max_position_pct
                    shares = int(max_value / price)
                    if shares > 0:
                        cost = shares * price * (1 + commission)
                        cash_on_hand -= cost
                        position = shares
                        trades.append({
                            "date": str(df.index[i]),
                            "type": "buy",
                            "price": float(price),
                            "shares": shares,
                            "cost": round(float(cost), 2),
                        })

            elif ema_fast[i] < ema_slow[i] and ema_fast[i - 1] >= ema_slow[i - 1]:
                # 死叉卖出
                if position > 0:
                    proceeds = position * price * (1 - commission)
                    cash_on_hand += proceeds
                    trades.append({
                        "date": str(df.index[i]),
                        "type": "sell",
                        "price": float(price),
                        "shares": position,
                        "proceeds": round(float(proceeds), 2),
                    })
                    position = 0

            total_value = cash_on_hand + position * price
            equity.append(total_value)

        # 清仓
        if position > 0:
            final_price = closes[-1]
            cash_on_hand += position * final_price * (1 - commission)
            equity[-1] = cash_on_hand

        return self._compute_metrics(equity, trades, cash)

    def _compute_metrics(self, equity: list[float], trades: list[dict], initial_cash: float) -> dict:
        """计算回测指标。"""
        eq = pd.Series(equity)
        returns = eq.pct_change().dropna()

        if len(returns) < 2:
            return {"metrics": {}, "trades": trades, "equity": equity}

        # 基础指标
        total_return = (eq.iloc[-1] - initial_cash) / initial_cash
        sharpe = float(
            returns.mean() / returns.std() * (252 ** 0.5)
        ) if returns.std() > 0 else 0

        # 最大回撤
        peak = eq.expanding().max()
        drawdown = (eq - peak) / peak
        max_dd = float(drawdown.min())

        # 胜率
        winning = [t for t in trades if t["type"] == "sell" and t.get("proceeds", 0) > 0]
        win_rate = len(winning) / len([t for t in trades if t["type"] == "sell"]) if trades else 0

        return {
            "metrics": {
                "total_return": round(total_return * 100, 2),
                "sharpe_ratio": round(sharpe, 2),
                "max_drawdown": round(max_dd * 100, 2),
                "total_trades": len(trades),
                "win_rate": round(win_rate * 100, 1),
                "final_equity": round(float(eq.iloc[-1]), 2),
            },
            "trades": trades,
            "equity": [round(float(e), 2) for e in equity],
        }
