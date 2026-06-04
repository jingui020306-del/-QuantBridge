"""
pyfolio 绩效分析集成。

对 LEAN 回测结果做深度分析：
  - 收益分析（年化、月度分布、滚动夏普）
  - 风险分析（回撤、VaR、尾部风险）
  - 交易分析（胜率、盈亏比）
"""

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


class PyfolioRunner:
    """绩效分析执行器。"""

    def __init__(
        self,
        benchmark: str = "SPY",
        output_dir: str = "outputs/reports",
        periods_per_year: int = 252,
    ):
        self.benchmark = benchmark
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.periods_per_year = periods_per_year

    def run(self, lean_results: dict) -> dict[str, Any]:
        """执行绩效分析。

        Args:
            lean_results: LEAN 回测输出，含 equity, trades, metrics

        Returns:
            分析报告 dict
        """
        equity = lean_results.get("equity", [])
        trades = lean_results.get("trades", [])
        metrics = lean_results.get("metrics", {})

        if not equity:
            logger.warning("无净值数据，跳过 pyfolio 分析")
            return {}

        eq_series = pd.Series(equity)
        returns = eq_series.pct_change().dropna()

        report = {
            "return_analysis": self._analyze_returns(returns),
            "risk_analysis": self._analyze_risk(returns, eq_series),
            "trade_analysis": self._analyze_trades(trades),
            "monthly_returns": self._monthly_table(returns),
            "metrics_from_lean": metrics,
        }

        logger.info(f"绩效分析完成: 年化收益={report['return_analysis']['annual_return']}%, "
                    f"Sharpe={report['return_analysis']['sharpe_ratio']}, "
                    f"最大回撤={report['risk_analysis']['max_drawdown']}%")

        return report

    def _analyze_returns(self, returns: pd.Series) -> dict:
        """收益分析。"""
        if len(returns) == 0:
            return {}

        total = (1 + returns).prod() - 1
        annual = (1 + total) ** (self.periods_per_year / len(returns)) - 1
        sharpe = float(
            returns.mean() / returns.std() * (self.periods_per_year ** 0.5)
        ) if returns.std() > 0 else 0

        # 正负收益不对称性
        upside = returns[returns > 0]
        downside = returns[returns < 0]

        # Sortino
        downside_std = downside.std()
        sortino = float(
            returns.mean() / downside_std * (self.periods_per_year ** 0.5)
        ) if downside_std and downside_std > 0 else 0

        return {
            "total_return": round(float(total * 100), 2),
            "annual_return": round(float(annual * 100), 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "positive_days": round(float((returns > 0).mean() * 100), 1),
            "avg_daily_return": round(float(returns.mean() * 100), 4),
            "avg_positive_return": round(float(upside.mean() * 100), 4) if len(upside) > 0 else 0,
            "avg_negative_return": round(float(downside.mean() * 100), 4) if len(downside) > 0 else 0,
        }

    def _analyze_risk(self, returns: pd.Series, equity: pd.Series) -> dict:
        """风险分析。"""
        if len(returns) == 0:
            return {}

        # 最大回撤
        peak = equity.expanding().max()
        drawdown = (equity - peak) / peak * 100
        max_dd = float(drawdown.min())
        max_dd_idx = drawdown.idxmin()

        # VaR
        var_95 = float(np.percentile(returns, 5) * 100)
        var_99 = float(np.percentile(returns, 1) * 100)
        cvar_95 = float(returns[returns <= np.percentile(returns, 5)].mean() * 100)

        # 回撤分析
        dd_duration = 0
        max_dd_duration = 0
        for val in drawdown:
            if val < 0:
                dd_duration += 1
                max_dd_duration = max(max_dd_duration, dd_duration)
            else:
                dd_duration = 0

        # Calmar
        annual_return = self._analyze_returns(returns).get("annual_return", 0)
        calmar = abs(annual_return / max_dd) if max_dd != 0 else 0

        return {
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_date": str(max_dd_idx) if max_dd_idx else "",
            "max_drawdown_duration_days": max_dd_duration,
            "var_95": round(var_95, 2),
            "var_99": round(var_99, 2),
            "cvar_95": round(cvar_95, 2),
            "calmar_ratio": round(calmar, 2),
            "volatility_annual": round(float(returns.std() * (self.periods_per_year ** 0.5) * 100), 2),
        }

    def _analyze_trades(self, trades: list[dict]) -> dict:
        """交易分析。"""
        if not trades:
            return {}

        sells = [t for t in trades if t.get("type") == "sell"]
        buys = [t for t in trades if t.get("type") == "buy"]

        winning = [s for s in sells if s.get("proceeds", 0) > s.get("cost", s.get("proceeds", 0))]
        losing = [s for s in sells if s not in winning]

        win_rate = len(winning) / len(sells) * 100 if sells else 0

        # 平均盈亏比
        if winning:
            avg_win = np.mean([
                s.get("proceeds", 0) - s.get("cost", s.get("proceeds", 0) / 2)
                for s in winning
            ]) if winning else 0
        else:
            avg_win = 0

        if losing:
            avg_loss = np.mean([
                s.get("proceeds", 0) - s.get("cost", s.get("proceeds", 0) / 2)
                for s in losing
            ]) if losing else 0
        else:
            avg_loss = 0

        profit_factor = abs(avg_win * len(winning) / (avg_loss * len(losing))) if avg_loss != 0 and losing else 0

        return {
            "total_trades": len(buys) + len(sells),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 1),
            "avg_win_amount": round(float(avg_win), 2),
            "avg_loss_amount": round(float(avg_loss), 2),
            "profit_factor": round(float(profit_factor), 2),
        }

    def _monthly_table(self, returns: pd.Series) -> list[dict]:
        """月度收益表。"""
        if len(returns) == 0:
            return []

        df = returns.to_frame("daily")
        df["year"] = df.index.year if hasattr(df.index, "year") else 0
        df["month"] = df.index.month if hasattr(df.index, "month") else 0

        monthly = df.groupby(["year", "month"])["daily"].apply(
            lambda x: (1 + x).prod() - 1
        ).reset_index()

        return monthly.to_dict(orient="records")
