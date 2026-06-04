"""因子计算引擎。

支持：
  - 内置技术因子（RSI、MACD、动量、波动率等）
  - 预留 FinceptTerminal 技术指标脚本目录作为后续集成点
  - 自定义因子表达式
"""

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger


class FactorEngine:
    """因子计算引擎。"""

    def __init__(
        self,
        fincept_scripts_dir: str | None = None,
        default_params: dict | None = None,
        custom_factors: list[str] | None = None,
    ):
        self.fincept_scripts_dir = Path(fincept_scripts_dir) if fincept_scripts_dir else None
        self.params = default_params or {}
        self.custom_factors = custom_factors or []

        # 注册所有可用因子
        self._registry = self._build_registry()

    def compute_all(self, data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """对每个标的计算所有因子。

        Returns:
            {ticker: DataFrame}，index=日期，columns=因子名
        """
        results: dict[str, pd.DataFrame] = {}
        for ticker, df in data.items():
            factors = self.compute_single(df)
            if not factors.empty:
                results[ticker] = factors
            else:
                logger.warning(f"{ticker}: 因子计算为空")

        logger.info(f"因子计算完成: {len(results)} 个标的")
        return results

    def compute_single(self, df: pd.DataFrame) -> pd.DataFrame:
        """对单个标的计算全部因子。"""
        o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
        out = pd.DataFrame(index=df.index)

        for name, func in self._registry.items():
            try:
                out[name] = func(o, h, l, c, v)
            except Exception as e:
                logger.debug(f"因子 {name} 计算失败: {e}")

        out = out.dropna(how="all")
        return out

    # ---- 因子注册表 ----

    def _build_registry(self) -> dict[str, Any]:
        registry: dict[str, Any] = {}

        # === 收益率因子 ===
        for w in self.params.get("momentum_windows", [5, 21, 63, 126]):
            registry[f"return_{w}d"] = self._make_return(w)
            registry[f"log_return_{w}d"] = self._make_log_return(w)

        # === 均线因子 ===
        for w in self.params.get("ma_windows", [5, 9, 21, 50, 200]):
            registry[f"sma_{w}"] = self._make_sma(w)
            registry[f"ema_{w}"] = self._make_ema(w)
            registry[f"close_over_sma_{w}"] = self._make_close_over_ma(w, "sma")
            registry[f"close_over_ema_{w}"] = self._make_close_over_ma(w, "ema")

        # === RSI ===
        rsi_w = self.params.get("rsi_window", 14)
        registry[f"rsi_{rsi_w}"] = self._make_rsi(rsi_w)

        # === MACD ===
        registry["macd"] = self._make_macd()
        registry["macd_signal"] = self._make_macd_signal()
        registry["macd_hist"] = self._make_macd_hist()

        # === 波动率 ===
        vol_w = self.params.get("volatility_window", 20)
        registry[f"volatility_{vol_w}d"] = self._make_volatility(vol_w)
        registry[f"atr_{vol_w}"] = self._make_atr(vol_w)

        # === 成交量因子 ===
        for w in self.params.get("ma_windows", [5, 21, 50]):
            registry[f"volume_over_ma_{w}"] = self._make_volume_ratio(w)

        # === Bollinger Bands ===
        registry["bb_position"] = self._make_bb_position(20, 2)
        registry["bb_width"] = self._make_bb_width(20, 2)

        # === 自定义因子（占位） ===
        for expr in self.custom_factors:
            registry[f"custom_{expr}"] = self._make_custom(expr)

        return registry

    # ---- 因子函数工厂 ----

    def _make_return(self, window: int):
        def fn(o, h, l, c, v):
            return c.pct_change(window)
        return fn

    def _make_log_return(self, window: int):
        def fn(o, h, l, c, v):
            return np.log(c / c.shift(window))
        return fn

    def _make_sma(self, window: int):
        def fn(o, h, l, c, v):
            return c.rolling(window).mean()
        return fn

    def _make_ema(self, window: int):
        def fn(o, h, l, c, v):
            return c.ewm(span=window, adjust=False).mean()
        return fn

    def _make_close_over_ma(self, window: int, ma_type: str):
        def fn(o, h, l, c, v):
            if ma_type == "sma":
                ma = c.rolling(window).mean()
            else:
                ma = c.ewm(span=window, adjust=False).mean()
            return c / ma - 1
        return fn

    def _make_rsi(self, window: int):
        def fn(o, h, l, c, v):
            delta = c.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            return 100 - (100 / (1 + rs))
        return fn

    def _make_macd(self):
        fast, slow = self.params.get("macd_fast", 12), self.params.get("macd_slow", 26)
        def fn(o, h, l, c, v):
            ema_fast = c.ewm(span=fast, adjust=False).mean()
            ema_slow = c.ewm(span=slow, adjust=False).mean()
            return ema_fast - ema_slow
        return fn

    def _make_macd_signal(self):
        def fn(o, h, l, c, v):
            fast, slow = self.params.get("macd_fast", 12), self.params.get("macd_slow", 26)
            sig = self.params.get("macd_signal", 9)
            ema_fast = c.ewm(span=fast, adjust=False).mean()
            ema_slow = c.ewm(span=slow, adjust=False).mean()
            macd = ema_fast - ema_slow
            return macd.ewm(span=sig, adjust=False).mean()
        return fn

    def _make_macd_hist(self):
        def fn(o, h, l, c, v):
            fast, slow = self.params.get("macd_fast", 12), self.params.get("macd_slow", 26)
            sig = self.params.get("macd_signal", 9)
            ema_fast = c.ewm(span=fast, adjust=False).mean()
            ema_slow = c.ewm(span=slow, adjust=False).mean()
            macd = ema_fast - ema_slow
            signal = macd.ewm(span=sig, adjust=False).mean()
            return macd - signal
        return fn

    def _make_volatility(self, window: int):
        def fn(o, h, l, c, v):
            return c.pct_change().rolling(window).std() * np.sqrt(252)
        return fn

    def _make_atr(self, window: int):
        def fn(o, h, l, c, v):
            tr = pd.concat([
                h - l,
                (h - c.shift()).abs(),
                (l - c.shift()).abs(),
            ], axis=1).max(axis=1)
            return tr.ewm(span=window, adjust=False).mean()
        return fn

    def _make_volume_ratio(self, window: int):
        def fn(o, h, l, c, v):
            return v / v.rolling(window).mean()
        return fn

    def _make_bb_position(self, window: int, n_std: int):
        def fn(o, h, l, c, v):
            sma = c.rolling(window).mean()
            std = c.rolling(window).std()
            upper = sma + n_std * std
            lower = sma - n_std * std
            return (c - lower) / (upper - lower)
        return fn

    def _make_bb_width(self, window: int, n_std: int):
        def fn(o, h, l, c, v):
            sma = c.rolling(window).mean()
            std = c.rolling(window).std()
            return (2 * n_std * std) / sma
        return fn

    def _make_custom(self, expr: str):
        """预留：自定义因子表达式，后续支持 pandas eval。"""
        def fn(o, h, l, c, v):
            logger.warning(f"自定义因子 {expr} 未实现，返回 NaN")
            return pd.Series(np.nan, index=c.index)
        return fn
