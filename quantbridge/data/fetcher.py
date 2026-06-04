"""
数据层：统一数据获取与缓存。

支持：
  - yfinance 美股 OHLCV 拉取
  - 本地 parquet 缓存（避免重复请求）
  - FinceptTerminal CSV 导出读取
  - 统一输出格式
"""

from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger


class DataFetcher:
    """美股数据获取器，带本地缓存。"""

    def __init__(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
        frequency: str = "1d",
        cache_dir: Optional[str] = None,
        fincept_export_path: Optional[str] = None,
    ):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.frequency = frequency
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.fincept_export_path = fincept_export_path

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """拉取所有标的数据。

        Returns:
            {ticker: DataFrame}，index 为日期，columns 含 OHLCV。
        """
        results: dict[str, pd.DataFrame] = {}

        for ticker in self.tickers:
            df = self._fetch_single(ticker)
            if df is not None and not df.empty:
                results[ticker] = df
                logger.info(f"{ticker}: {len(df)} 条记录")
            else:
                logger.warning(f"{ticker}: 无数据，已跳过")

        logger.info(f"拉取完成: {len(results)}/{len(self.tickers)} 标的有数据")
        return results

    def _fetch_single(self, ticker: str) -> Optional[pd.DataFrame]:
        """拉取单个标的，优先读缓存。"""
        # 1. 优先 FinceptTerminal 导出
        if self.fincept_export_path:
            df = self._read_fincept_export(ticker)
            if df is not None:
                return df

        # 2. 本地缓存
        if self.cache_dir:
            df = self._read_cache(ticker)
            if df is not None:
                logger.debug(f"{ticker}: 命中缓存")
                return df

        # 3. yfinance 拉取
        df = self._download(ticker)
        if df is not None and self.cache_dir:
            self._write_cache(ticker, df)
        return df

    def _download(self, ticker: str) -> Optional[pd.DataFrame]:
        """从 yfinance 拉取，包含分红拆股调整。"""
        try:
            yf_ticker = yf.Ticker(ticker)
            yf_interval = self._to_yf_interval()
            df = yf_ticker.history(
                start=self.start_date,
                end=self.end_date,
                interval=yf_interval,
                auto_adjust=True,  # 自动调整价格
            )
            if df.empty:
                return None

            df.index = pd.to_datetime(df.index).tz_localize(None)
            df.index.name = "date"

            # 标准化列名
            col_map = {
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            }
            df = df.rename(columns=col_map)
            return df[list(col_map.values())]
        except Exception as e:
            logger.error(f"{ticker}: 下载失败 — {e}")
            return None

    def _to_yf_interval(self) -> str:
        return {"1d": "1d", "1h": "1h", "30m": "30m", "15m": "15m", "5m": "5m", "1m": "1m"}.get(
            self.frequency, "1d"
        )

    def _read_cache(self, ticker: str) -> Optional[pd.DataFrame]:
        cache_path = self._cache_path(ticker)
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            # 过滤日期范围
            df = df.loc[self.start_date : self.end_date]
            return df if not df.empty else None
        return None

    def _write_cache(self, ticker: str, df: pd.DataFrame) -> None:
        if self.cache_dir:
            cache_path = self._cache_path(ticker)
            df.to_parquet(cache_path)

    def _cache_path(self, ticker: str) -> Path:
        safe_ticker = ticker.replace("/", "-").replace(":", "-")
        safe_start = self.start_date.replace("/", "-")
        safe_end = self.end_date.replace("/", "-")
        return self.cache_dir / f"{safe_ticker}_{self.frequency}_{safe_start}_{safe_end}.parquet"

    def _read_fincept_export(self, ticker: str) -> Optional[pd.DataFrame]:
        """从 FinceptTerminal 导出的 CSV 读取数据。"""
        export_path = Path(self.fincept_export_path) / f"{ticker}.csv"
        if export_path.exists():
            df = pd.read_csv(export_path, index_col=0, parse_dates=True)
            df.index.name = "date"
            return df
        return None

    def get_price_matrix(
        self, data: dict[str, pd.DataFrame], field: str = "close"
    ) -> pd.DataFrame:
        """将 {ticker: df} 转为标的 × 日期的价格矩阵。"""
        series = {t: df[field] for t, df in data.items() if field in df.columns}
        return pd.DataFrame(series).dropna(how="all")

    def get_return_matrix(
        self, data: dict[str, pd.DataFrame], periods: int = 1
    ) -> pd.DataFrame:
        """计算收益率矩阵。"""
        price = self.get_price_matrix(data, "close")
        return price.pct_change(periods).dropna(how="all")
