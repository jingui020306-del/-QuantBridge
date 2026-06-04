"""
alphalens 因子检验集成。

对计算出的因子做完整的 IC 分析、分层回测，判定因子是否值得进入 LEAN 回测。
"""

import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger

try:
    import alphalens as al
    HAS_ALPHALENS = True
except ImportError:
    HAS_ALPHALENS = False
    logger.warning("alphalens-reloaded 未安装，因子检验将使用内置简易版")


class AlphalensRunner:
    """因子检验执行器。"""

    def __init__(
        self,
        forward_periods: list[int] | None = None,
        quantiles: int = 5,
        pass_threshold: dict | None = None,
    ):
        self.forward_periods = forward_periods or [1, 5, 21]
        self.quantiles = quantiles
        self.pass_threshold = pass_threshold or {
            "min_ic_mean": 0.02,
            "min_icir": 0.3,
            "min_quantile_spread": 0.005,
        }

    def run(
        self,
        factors: dict[str, pd.DataFrame],
        data: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        """对所有标的的因子做检验。

        Returns:
            {
                "passed": bool,          # 是否有因子通过
                "summary": {...},        # 汇总结果
                "per_factor": {...},     # 每个因子的详细结果
                "reports": [...],        # 生成的报告路径
            }
        """
        if not factors:
            return {"passed": False, "summary": {}, "per_factor": {}, "reports": []}

        all_results: dict[str, dict] = {}

        for ticker in factors:
            factor_df = factors[ticker]
            price_df = data.get(ticker)
            if price_df is None or factor_df.empty:
                continue

            ticker_results = self._analyze_single(ticker, factor_df, price_df)
            all_results[ticker] = ticker_results

        return self._summarize(all_results)

    def _analyze_single(
        self,
        ticker: str,
        factor_df: pd.DataFrame,
        price_df: pd.DataFrame,
    ) -> dict:
        """单个标的的全部因子检验。"""
        results = {}

        # 对齐日期
        common_dates = factor_df.index.intersection(price_df.index)
        if len(common_dates) < 60:
            logger.warning(f"{ticker}: 数据点不足({len(common_dates)}条)，跳过")
            return results

        factor_df = factor_df.loc[common_dates]
        closes = price_df.loc[common_dates, "close"]

        for col in factor_df.columns:
            factor_series = factor_df[col].dropna()
            if len(factor_series) < 60:
                continue

            # 计算 IC
            ic_result = self._compute_ic(factor_series, closes)
            if ic_result:
                results[col] = ic_result

        return results

    def _compute_ic(self, factor: pd.Series, closes: pd.Series) -> dict | None:
        """计算单个因子的 IC 及衍生指标。"""
        # 对齐
        common_idx = factor.index.intersection(closes.index)
        factor = factor.loc[common_idx]
        closes = closes.loc[common_idx]

        if len(factor) < 60:
            return None

        # 前向收益
        fwd_return = closes.pct_change(self.forward_periods[0]).shift(-self.forward_periods[0])
        common = factor.index.intersection(fwd_return.dropna().index)
        f = factor.loc[common]
        r = fwd_return.loc[common]

        if len(f) < 30:
            return None

        # Pearson IC
        ic = f.corr(r)

        # Spearman IC (Rank IC)
        rank_ic = f.rank().corr(r.rank())

        # 滚动 IC
        roll_ic = f.rolling(60).corr(r).dropna()
        ic_mean = roll_ic.mean()
        ic_std = roll_ic.std()
        icir = ic_mean / ic_std if ic_std and ic_std > 0 else 0

        # 分层回测（简易版）
        quantile_spread, monotonic = self._quantile_test(f, r)

        return {
            "ic_pearson": round(float(ic), 4),
            "ic_spearman": round(float(rank_ic), 4),
            "ic_mean_rolling": round(float(ic_mean), 4),
            "ic_std_rolling": round(float(ic_std), 4),
            "icir": round(float(icir), 4),
            "ic_positive_pct": round(float((roll_ic > 0).mean() * 100), 1),
            "quantile_spread": round(float(quantile_spread), 6),
            "monotonic": monotonic,
            "n_obs": len(f),
        }

    def _quantile_test(self, factor: pd.Series, fwd_return: pd.Series) -> tuple[float, bool]:
        """简易分层检验（不用 alphalens API 的情况下）。"""
        try:
            df = pd.DataFrame({"factor": factor, "return": fwd_return}).dropna()
            df["quantile"] = pd.qcut(df["factor"], self.quantiles, labels=False, duplicates="drop")
            grouped = df.groupby("quantile")["return"].mean()
            top = grouped.max()
            bottom = grouped.min()
            spread = top - bottom
            monotonic = grouped.is_monotonic_increasing or grouped.is_monotonic_decreasing
            return float(spread), bool(monotonic)
        except Exception:
            return 0.0, False

    def _summarize(self, all_results: dict) -> dict:
        """汇总所有结果，判定通过与否。"""
        per_factor: dict[str, list] = {}

        for ticker, factors in all_results.items():
            for factor_name, result in factors.items():
                per_factor.setdefault(factor_name, []).append(result)

        # 每个因子取中位数
        summary: dict[str, Any] = {}
        for factor_name, results in per_factor.items():
            if not results:
                continue
            summary[factor_name] = {
                "ic_pearson": np.median([r["ic_pearson"] for r in results]),
                "icir": np.median([r["icir"] for r in results]),
                "quantile_spread": np.median([r["quantile_spread"] for r in results]),
                "n_stocks": len(results),
            }

        # 判断是否有因子通过
        min_ic = self.pass_threshold.get("min_ic_mean", 0.02)
        min_icir = self.pass_threshold.get("min_icir", 0.3)
        min_spread = self.pass_threshold.get("min_quantile_spread", 0.005)

        passed_factors = [
            name for name, s in summary.items()
            if abs(s["ic_pearson"]) > min_ic
            and abs(s["icir"]) > min_icir
            and abs(s["quantile_spread"]) > min_spread
        ]

        logger.info(f"因子检验: {len(summary)} 个因子，{len(passed_factors)} 个通过")
        for name in passed_factors:
            s = summary[name]
            logger.info(f"  ✓ {name}: IC={s['ic_pearson']:.4f}, ICIR={s['icir']:.2f}")

        return {
            "passed": len(passed_factors) > 0,
            "passed_factors": passed_factors,
            "summary": summary,
            "per_factor": per_factor,
            "generated_at": datetime.now().isoformat(),
        }
