"""
因子检验 — 真 alphalens API 集成。

优先使用 alphalens-reloaded 做完整因子检验（IC、分层回测、tear sheet）。
alphalens 不可用或数据不足时降级到内置简易检验。
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
    logger.warning("alphalens-reloaded 未安装，使用内置简易检验")


class AlphalensRunner:
    """因子检验执行器 — 优先真 alphalens，降级内置。"""

    def __init__(
        self,
        forward_periods: list[int] | None = None,
        quantiles: int = 5,
        pass_threshold: dict | None = None,
        use_real: bool = False,
        output_dir: str = "outputs/reports",
    ):
        self.forward_periods = forward_periods or [1, 5, 21]
        self.quantiles = quantiles
        self.use_real = use_real
        self.pass_threshold = pass_threshold or {
            "min_ic_mean": 0.02,
            "min_icir": 0.3,
            "min_quantile_spread": 0.005,
        }
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        factors: dict[str, pd.DataFrame],
        data: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        if not factors:
            return {"passed": False, "summary": {}, "passed_factors": [], "per_factor": {}}

        if self.use_real and HAS_ALPHALENS:
            try:
                return self._run_real_alphalens(factors, data)
            except Exception as e:
                logger.warning(f"alphalens 真集成失败，降级到内置检验: {e}")
        elif self.use_real:
            logger.warning("alphalens-reloaded 不可用，降级到内置检验")

        return self._run_lite(factors, data)

    # ============================================================
    # 真 alphalens
    # ============================================================

    def _run_real_alphalens(
        self,
        factors: dict[str, pd.DataFrame],
        data: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        """使用真 alphalens-reloaded 做因子检验。"""
        tickers = list(factors.keys())
        if not tickers:
            return {"passed": False, "summary": {}, "passed_factors": [], "per_factor": {}}

        # 构建 alphalens 需要的 MultiIndex 数据
        factor_df = self._build_factor_frame(factors)
        price_df = self._build_price_frame(data)

        if factor_df.empty or price_df.empty:
            logger.warning("无法构建 alphalens 输入，降级内置检验")
            return self._run_lite(factors, data)

        all_results: dict[str, dict] = {}
        passed_factors: list[str] = []
        clean_by_factor: dict[str, pd.DataFrame] = {}

        for factor_name in factor_df.columns:
            try:
                factor_series = factor_df[factor_name].dropna()
                if factor_series.empty:
                    continue

                # alphalens expects one factor Series indexed by (date, asset).
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    clean = al.utils.get_clean_factor_and_forward_returns(
                        factor=factor_series,
                        prices=price_df,
                        periods=tuple(self.forward_periods),
                        quantiles=self.quantiles,
                        groupby=None,
                    )

                clean_by_factor[factor_name] = clean
                ic_data = al.performance.factor_information_coefficient(
                    clean, by_group=False
                )
                if ic_data.empty:
                    continue

                ic_summary = self._extract_ic_summary(ic_data, clean)
                all_results[factor_name] = ic_summary

                # 判断通过
                if (abs(ic_summary["ic_pearson"]) > self.pass_threshold["min_ic_mean"]
                        and abs(ic_summary["icir"]) > self.pass_threshold["min_icir"]
                        and abs(ic_summary["quantile_spread"]) > self.pass_threshold["min_quantile_spread"]):
                    passed_factors.append(factor_name)

            except Exception as e:
                logger.warning(f"alphalens {factor_name}: {e}")
                continue

        # 生成 tear sheet（对通过的第一个因子）
        if passed_factors:
            try:
                self._save_tear_sheet(clean_by_factor[passed_factors[0]], passed_factors[0])
            except Exception as e:
                logger.warning(f"tear sheet 生成失败: {e}")

        # 汇总
        summary = self._build_summary(all_results)

        logger.info(f"alphalens 真集成: {len(all_results)} 因子, {len(passed_factors)} 通过")
        for name in passed_factors:
            s = summary.get(name, {})
            logger.info(f"  ✓ {name}: IC={s.get('ic_pearson', 0):.4f}, ICIR={s.get('icir', 0):.2f}")

        return {
            "passed": len(passed_factors) > 0,
            "passed_factors": passed_factors,
            "summary": summary,
            "per_factor": {k: [v] for k, v in all_results.items()},
            "generated_at": datetime.now().isoformat(),
        }

    def _build_factor_frame(self, factors: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """将 {ticker: factor_df} 转为 alphalens MultiIndex (date, asset)。"""
        frames: list[pd.DataFrame] = []
        for ticker, df in factors.items():
            stacked = df.stack().to_frame("value")
            stacked["asset"] = ticker
            frames.append(stacked)
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames)
        combined.index.names = ["date", "factor_name"]
        # pivot: (date, asset) × factor_name
        result = combined.reset_index().pivot_table(
            index=["date", "asset"], columns="factor_name", values="value"
        )
        result.index = pd.MultiIndex.from_tuples(
            [(d, a) for d, a in result.index],
            names=["date", "asset"],
        )
        return result

    def _build_price_frame(self, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """提取所有标的的收盘价 MultiIndex。"""
        series = {}
        for ticker, df in data.items():
            if "close" in df.columns:
                series[ticker] = df["close"]
        if not series:
            return pd.DataFrame()
        result = pd.DataFrame(series)
        result.columns.name = "asset"
        result.index.name = "date"
        return result

    def _extract_ic_summary(
        self, ic_data: pd.DataFrame, clean: pd.DataFrame
    ) -> dict:
        """从 alphalens IC 结果提取摘要。"""
        ic_col = ic_data.columns[0] if not ic_data.empty else None
        if ic_col is None:
            return {"ic_pearson": 0, "icir": 0, "quantile_spread": 0}

        ic_series = ic_data[ic_col].dropna()
        ic_mean = float(ic_series.mean())
        ic_std = float(ic_series.std())
        icir = ic_mean / ic_std if ic_std and ic_std > 0 else 0.0

        # 分层收益
        quantile_spread = 0.0
        try:
            mean_ret = al.performance.mean_return_by_quantile(
                clean, by_date=False, by_group=False,
                demeaned=False, group_adjust=False,
            )
            if isinstance(mean_ret, tuple):
                mean_ret = mean_ret[0]
            if not mean_ret.empty:
                spread = mean_ret.iloc[:, 0]
                quantile_spread = float(spread.iloc[-1] - spread.iloc[0])
        except Exception:
            quantile_spread = 0.0

        return {
            "ic_pearson": round(ic_mean, 4),
            "ic_spearman": round(ic_mean, 4),  # alphalens IC 列通常是 Spearman
            "ic_mean_rolling": round(ic_mean, 4),
            "ic_std_rolling": round(ic_std, 4),
            "icir": round(icir, 4),
            "ic_positive_pct": round(float((ic_series > 0).mean() * 100), 1),
            "quantile_spread": round(quantile_spread, 6),
            "n_obs": len(ic_series),
        }

    def _save_tear_sheet(self, clean: pd.DataFrame, factor_name: str) -> None:
        """保存 alphalens tear sheet 到 outputs/reports/。"""
        import matplotlib
        matplotlib.use("Agg")

        import matplotlib.pyplot as plt

        # summary tear sheet
        ic = al.performance.factor_information_coefficient(clean, by_group=False)
        al.plotting.plot_ic_ts(ic)
        plt.savefig(str(self.output_dir / f"ic_ts_{factor_name}.png"), dpi=150, bbox_inches="tight")
        plt.close()

        mean_ret = al.performance.mean_return_by_quantile(
            clean, by_date=False, by_group=False,
            demeaned=False, group_adjust=False,
        )
        if isinstance(mean_ret, tuple):
            mean_ret = mean_ret[0]
        al.plotting.plot_quantile_returns_bar(mean_ret)
        plt.savefig(str(self.output_dir / f"quantile_bar_{factor_name}.png"), dpi=150, bbox_inches="tight")
        plt.close()

        logger.info(f"alphalens 图表已保存: {self.output_dir}")

    def _build_summary(self, all_results: dict[str, dict]) -> dict:
        summary = {}
        for name, result in all_results.items():
            summary[name] = {
                "ic_pearson": result.get("ic_pearson", 0),
                "icir": result.get("icir", 0),
                "quantile_spread": result.get("quantile_spread", 0),
                "n_stocks": 1,
            }
        return summary

    # ============================================================
    # 内置降级（保持和之前一样）
    # ============================================================

    def _run_lite(self, factors: dict[str, pd.DataFrame], data: dict[str, pd.DataFrame]) -> dict[str, Any]:
        all_results: dict[str, dict] = {}
        for ticker in factors:
            factor_df = factors[ticker]
            price_df = data.get(ticker)
            if price_df is None or factor_df.empty:
                continue
            ticker_results = self._analyze_single(ticker, factor_df, price_df)
            all_results[ticker] = ticker_results
        return self._summarize_lite(all_results)

    def _analyze_single(self, ticker: str, factor_df: pd.DataFrame, price_df: pd.DataFrame) -> dict:
        results = {}
        common_dates = factor_df.index.intersection(price_df.index)
        if len(common_dates) < 60:
            return results
        factor_df = factor_df.loc[common_dates]
        closes = price_df.loc[common_dates, "close"]
        for col in factor_df.columns:
            factor_series = factor_df[col].dropna()
            if len(factor_series) < 60:
                continue
            ic_result = self._compute_ic(factor_series, closes)
            if ic_result:
                results[col] = ic_result
        return results

    def _compute_ic(self, factor: pd.Series, closes: pd.Series) -> dict | None:
        common_idx = factor.index.intersection(closes.index)
        factor = factor.loc[common_idx]
        closes = closes.loc[common_idx]
        if len(factor) < 60:
            return None
        fwd_return = closes.pct_change(self.forward_periods[0]).shift(-self.forward_periods[0])
        common = factor.index.intersection(fwd_return.dropna().index)
        f = factor.loc[common]
        r = fwd_return.loc[common]
        if len(f) < 30:
            return None
        ic = f.corr(r)
        rank_ic = f.rank().corr(r.rank())
        roll_ic = f.rolling(60).corr(r).dropna()
        ic_mean = roll_ic.mean()
        ic_std = roll_ic.std()
        icir = ic_mean / ic_std if ic_std and ic_std > 0 else 0
        quantile_spread, _ = self._quantile_test(f, r)
        return {
            "ic_pearson": round(float(ic), 4),
            "ic_spearman": round(float(rank_ic), 4),
            "ic_mean_rolling": round(float(ic_mean), 4),
            "ic_std_rolling": round(float(ic_std), 4),
            "icir": round(float(icir), 4),
            "ic_positive_pct": round(float((roll_ic > 0).mean() * 100), 1),
            "quantile_spread": round(float(quantile_spread), 6),
            "n_obs": len(f),
        }

    def _quantile_test(self, factor: pd.Series, fwd_return: pd.Series) -> tuple[float, bool]:
        try:
            df = pd.DataFrame({"factor": factor, "return": fwd_return}).dropna()
            df["quantile"] = pd.qcut(df["factor"], self.quantiles, labels=False, duplicates="drop")
            grouped = df.groupby("quantile")["return"].mean()
            spread = grouped.max() - grouped.min()
            monotonic = grouped.is_monotonic_increasing or grouped.is_monotonic_decreasing
            return float(spread), bool(monotonic)
        except Exception:
            return 0.0, False

    def _summarize_lite(self, all_results: dict) -> dict:
        per_factor: dict[str, list] = {}
        for ticker, factors in all_results.items():
            for factor_name, result in factors.items():
                per_factor.setdefault(factor_name, []).append(result)

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

        min_ic = self.pass_threshold.get("min_ic_mean", 0.02)
        min_icir = self.pass_threshold.get("min_icir", 0.3)
        min_spread = self.pass_threshold.get("min_quantile_spread", 0.005)

        passed_factors = [
            name for name, s in summary.items()
            if abs(s["ic_pearson"]) > min_ic
            and abs(s["icir"]) > min_icir
            and abs(s["quantile_spread"]) > min_spread
        ]

        logger.info(f"因子检验(lite): {len(summary)} 个因子，{len(passed_factors)} 个通过")
        return {
            "passed": len(passed_factors) > 0,
            "passed_factors": passed_factors,
            "summary": summary,
            "per_factor": per_factor,
            "generated_at": datetime.now().isoformat(),
        }
