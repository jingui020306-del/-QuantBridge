"""
绩效分析 — 真 pyfolio + quantstats 集成。

优先使用 pyfolio-reloaded + quantstats 生成完整 tear sheet 和 HTML 报告。
不可用时降级到内置指标摘要。
"""

import warnings
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


class PyfolioRunner:
    """绩效分析执行器 — 优先真 pyfolio/quantstats，降级内置。"""

    def __init__(
        self,
        benchmark: str | None = None,
        output_dir: str = "outputs/reports",
        periods_per_year: int = 252,
        enable_external_reports: bool = False,
    ):
        self.benchmark = benchmark
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.periods_per_year = periods_per_year
        self.enable_external_reports = enable_external_reports

    def run(self, lean_results: dict) -> dict[str, Any]:
        equity = lean_results.get("equity", [])
        trades = lean_results.get("trades", [])

        if not equity or len(equity) < 2:
            logger.warning("无净值数据，跳过绩效分析")
            return {}

        returns = self._to_returns(equity, lean_results.get("equity_dates"))
        report: dict[str, Any] = {}

        # 1. 内置指标（永远有，作为基准）
        report["return_analysis"] = self._analyze_returns(returns)
        report["risk_analysis"] = self._analyze_risk(returns, equity)
        report["trade_analysis"] = self._analyze_trades(trades)
        report["monthly_returns"] = self._monthly_table(returns)
        report["metrics_from_lean"] = lean_results.get("metrics", {})

        if not self.enable_external_reports:
            logger.info("外部绩效报告未启用，仅生成内置绩效摘要")
            ann_ret = report["return_analysis"].get("annual_return", 0)
            sharpe = report["return_analysis"].get("sharpe_ratio", 0)
            max_dd = report["risk_analysis"].get("max_drawdown", 0)
            logger.info(
                f"绩效分析: 年化={ann_ret}%, Sharpe={sharpe}, 最大回撤={max_dd}%"
            )
            return report

        # 2. quantstats HTML 报告
        if find_spec("quantstats"):
            try:
                report["quantstats_html"] = self._run_quantstats(returns)
            except Exception as e:
                logger.warning(f"quantstats 失败: {e}")

        # 3. pyfolio tear sheet
        if find_spec("pyfolio"):
            try:
                report["pyfolio"] = self._run_pyfolio(returns)
            except Exception as e:
                logger.warning(f"pyfolio 失败: {e}")

        ann_ret = report["return_analysis"].get("annual_return", 0)
        sharpe = report["return_analysis"].get("sharpe_ratio", 0)
        max_dd = report["risk_analysis"].get("max_drawdown", 0)
        logger.info(
            f"绩效分析: 年化={ann_ret}%, Sharpe={sharpe}, 最大回撤={max_dd}%"
        )
        return report

    # ============================================================
    # quantstats
    # ============================================================

    def _run_quantstats(self, returns: pd.Series) -> str:
        import matplotlib
        matplotlib.use("Agg")
        import quantstats as qs

        path = self.output_dir / "quantstats_report.html"
        kwargs = {
            "output": str(path),
            "title": "QuantBridge Strategy Report",
        }
        if self.benchmark:
            kwargs["benchmark"] = self.benchmark
        qs.reports.html(returns, **kwargs)
        logger.info(f"quantstats 报告: {path}")
        return str(path)

    # ============================================================
    # pyfolio
    # ============================================================

    def _run_pyfolio(self, returns: pd.Series) -> dict:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pyfolio as pf

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            fig = pf.create_returns_tear_sheet(returns, return_fig=True)
            path = self.output_dir / "pyfolio_tearsheet.png"
            if self._save_plot(fig, path, plt):
                logger.info(f"pyfolio tear sheet: {path}")

            fig2 = pf.plot_drawdown_periods(returns)
            self._save_plot(fig2, self.output_dir / "pyfolio_drawdowns.png", plt)

            try:
                fig3 = pf.plot_monthly_returns_heatmap(returns, return_fig=True)
                self._save_plot(fig3, self.output_dir / "pyfolio_monthly_heatmap.png", plt)
            except Exception:
                pass

        return {"status": "ok"}

    def _save_plot(self, plot_obj: Any, path: Path, plt_module: Any) -> bool:
        if plot_obj is None:
            return False
        fig = plot_obj.figure if hasattr(plot_obj, "figure") else plot_obj
        if not hasattr(fig, "savefig"):
            return False
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt_module.close(fig)
        return True

    # ============================================================
    # 内置分析
    # ============================================================

    def _to_returns(self, equity: list[float], dates: list | None = None) -> pd.Series:
        if dates and len(dates) == len(equity):
            index = pd.to_datetime(pd.Index(dates), errors="coerce")
            if index.isna().any():
                index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(equity))
        else:
            index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(equity))

        values = pd.Series(equity, index=index, dtype="float64").sort_index()
        values = values[~values.index.duplicated(keep="last")]
        if getattr(values.index, "tz", None) is not None:
            values.index = values.index.tz_convert(None)

        returns = values.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        returns.name = "strategy"
        return returns

    def _analyze_returns(self, returns: pd.Series) -> dict:
        if len(returns) == 0:
            return {}
        total = (1 + returns).prod() - 1
        n = max(len(returns), 1)
        annual = (1 + total) ** (self.periods_per_year / n) - 1
        sharpe = float(
            returns.mean() / returns.std() * (self.periods_per_year ** 0.5)
        ) if returns.std() > 0 else 0

        upside = returns[returns > 0]
        downside = returns[returns < 0]
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

    def _analyze_risk(self, returns: pd.Series, equity: list[float]) -> dict:
        if len(returns) == 0:
            return {}
        eq = pd.Series(equity)
        peak = eq.expanding().max()
        drawdown = (eq - peak) / peak * 100
        max_dd = float(drawdown.min())
        max_dd_idx = drawdown.idxmin()
        var_95 = float(np.percentile(returns, 5) * 100)
        var_99 = float(np.percentile(returns, 1) * 100)
        cvar_95 = float(returns[returns <= np.percentile(returns, 5)].mean() * 100)
        dd_duration, max_dd_duration = 0, 0
        for val in drawdown:
            if val < 0:
                dd_duration += 1
                max_dd_duration = max(max_dd_duration, dd_duration)
            else:
                dd_duration = 0
        ann_ret = self._analyze_returns(returns).get("annual_return", 0)
        calmar = abs(ann_ret / max_dd) if max_dd != 0 else 0
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
        if not trades:
            return {}
        sells = [t for t in trades if t.get("type") == "sell"]
        buys = [t for t in trades if t.get("type") == "buy"]

        closed = [s for s in sells if "pnl" in s]
        winning = [s for s in closed if s.get("pnl", 0) > 0]
        losing = [s for s in closed if s.get("pnl", 0) <= 0]
        win_rate = len(winning) / len(closed) * 100 if closed else 0
        avg_win = np.mean([s.get("pnl", 0) for s in winning]) if winning else 0
        avg_loss = np.mean([s.get("pnl", 0) for s in losing]) if losing else 0
        gross_profit = sum(s.get("pnl", 0) for s in winning)
        gross_loss = abs(sum(s.get("pnl", 0) for s in losing))
        profit_factor = gross_profit / gross_loss if gross_loss else 0
        return {
            "total_trades": len(buys) + len(sells),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "closed_trades": len(closed),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": round(win_rate, 1),
            "avg_win_amount": round(float(avg_win), 2),
            "avg_loss_amount": round(float(avg_loss), 2),
            "profit_factor": round(float(profit_factor), 2),
        }

    def _monthly_table(self, returns: pd.Series) -> list[dict]:
        if len(returns) == 0:
            return []
        df = returns.to_frame("daily")
        df["year"] = df.index.year if hasattr(df.index, "year") else 0
        df["month"] = df.index.month if hasattr(df.index, "month") else 0
        monthly = df.groupby(["year", "month"])["daily"].apply(
            lambda x: (1 + x).prod() - 1
        ).reset_index()
        return monthly.to_dict(orient="records")
