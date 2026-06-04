"""
LEAN 回测集成 — 真 Docker LEAN 执行。

1. 检测 Docker + LEAN 镜像可用性
2. 将 yfinance 数据转为 LEAN 格式
3. 生成 LEAN Python 算法代码
4. Docker 运行回测
5. 解析输出 JSON（orders + statistics + equity curve）
不可用时降级到内置简易回测。
"""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger


ALGORITHM_TEMPLATE = '''"""
QuantBridge auto-generated LEAN algorithm.
Strategy: {strategy_name}
Generated: {generated_at}
"""

from AlgorithmImports import *


class QuantBridgeAlgorithm(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate({start_year}, {start_month}, {start_day})
        self.SetEndDate({end_year}, {end_month}, {end_day})
        self.SetCash({cash})

        self._symbols = []
        self._fast = {fast_period}
        self._slow = {slow_period}
        self._ema_fast = {{}}
        self._ema_slow = {{}}
        self._position_size_pct = {position_size_pct}

        for ticker in {tickers}:
            equity = self.AddEquity(ticker, Resolution.{resolution}, Market.USA)
            equity.SetFeeModel(ConstantFeeModel({commission}))
            self._symbols.append(equity.Symbol)
            self._ema_fast[equity.Symbol] = self.EMA(
                equity.Symbol, self._fast, Resolution.{resolution}
            )
            self._ema_slow[equity.Symbol] = self.EMA(
                equity.Symbol, self._slow, Resolution.{resolution}
            )

        self.SetWarmUp(max(self._fast, self._slow) + 1)

    def OnData(self, data):
        for symbol in self._symbols:
            if not self._ema_fast[symbol].IsReady or not self._ema_slow[symbol].IsReady:
                continue

            price = data[symbol].Close
            holdings = self.Portfolio[symbol].Quantity

            if (self._ema_fast[symbol].Current.Value > self._ema_slow[symbol].Current.Value
                    and self._ema_fast[symbol].Previous.Value <= self._ema_slow[symbol].Previous.Value):
                if holdings <= 0:
                    self.SetHoldings(symbol, self._position_size_pct)

            elif (self._ema_fast[symbol].Current.Value < self._ema_slow[symbol].Current.Value
                    and self._ema_fast[symbol].Previous.Value >= self._ema_slow[symbol].Previous.Value):
                if holdings > 0:
                    self.Liquidate(symbol)
'''


class LeanRunner:
    """LEAN Docker 回测执行器。"""

    def __init__(
        self,
        docker_image: str = "quantconnect/lean:latest",
        data_dir: str = "outputs/lean_data",
        lean_config: dict | None = None,
    ):
        self.docker_image = docker_image
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = lean_config or {}

    def run(self, alphalens_results: dict, data: dict[str, pd.DataFrame]) -> dict[str, Any]:
        if not alphalens_results.get("passed"):
            logger.warning("无通过因子，跳过回测")
            return {"metrics": {}, "trades": [], "equity": []}

        if self.config.get("use_docker", False) and self._docker_available() and self._lean_image_available():
            try:
                return self._run_lean_docker(alphalens_results, data)
            except Exception as e:
                logger.error(f"LEAN Docker 失败，降级: {e}")

        logger.warning("LEAN Docker 未启用或不可用，使用内置简易回测")
        return self._run_simple_backtest(alphalens_results, data)

    def _docker_available(self) -> bool:
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def _lean_image_available(self) -> bool:
        r = subprocess.run(["docker", "images", "-q", self.docker_image], capture_output=True, text=True)
        return bool(r.stdout.strip())

    # ============================================================
    # 真 LEAN Docker
    # ============================================================

    def _run_lean_docker(self, alphalens_results: dict, data: dict[str, pd.DataFrame]) -> dict:
        logger.info("=" * 40)
        logger.info("LEAN Docker 回测启动")
        logger.info("=" * 40)

        tickers = list(data.keys())

        work_parent = self.data_dir.parent / "lean_work"
        work_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="quantbridge_lean_", dir=work_parent) as tmp:
            tmp_path = Path(tmp)

            # 1. LEAN 格式数据: Data/equity/usa/daily/{ticker}.csv
            data_root = tmp_path / "Data"
            market_dir = tmp_path / "Data" / "equity" / "usa" / "daily"
            market_dir.mkdir(parents=True, exist_ok=True)
            for t in tickers:
                csv = pd.DataFrame({
                    "Date": data[t].index.strftime("%Y%m%d"),
                    "Open": data[t]["open"],
                    "High": data[t]["high"],
                    "Low": data[t]["low"],
                    "Close": data[t]["close"],
                    "Volume": data[t]["volume"].astype(int),
                })
                csv.to_csv(market_dir / f"{t.lower()}.csv", index=False)
                logger.debug(f"LEAN 数据: {t} → {len(csv)} 行")

            # 2. 算法代码
            algo_path = tmp_path / "algorithm.py"
            algo_path.write_text(self._gen_algorithm(tickers))

            # 3. results dir
            results_dir = tmp_path / "results"
            results_dir.mkdir(exist_ok=True)

            # 4. Docker run
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{data_root}:/Data",
                "-v", f"{tmp_path}:/Project",
                "-v", f"{results_dir}:/Results",
                self.docker_image,
                "--data-folder", "/Data",
                "--environment", "backtesting",
                "--algorithm-type-name", "QuantBridgeAlgorithm",
                "--algorithm-language", "Python",
                "--algorithm-location", "/Project/algorithm.py",
                "--results-destination-folder", "/Results",
                "--close-automatically", "true",
            ]

            logger.info(f"LEAN 回测: {len(tickers)} 标的")
            timeout = int(self.config.get("timeout_seconds", 120))
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

            if result.returncode != 0:
                tail = result.stderr[-800:] or result.stdout[-800:]
                logger.error(f"LEAN 退出 {result.returncode}: {tail}")
                raise RuntimeError(f"LEAN 失败: {tail}")

            logger.info("LEAN Docker 回测完成")

            lean_res = self._parse_lean_results(results_dir)
            if lean_res and lean_res.get("equity"):
                return lean_res

        logger.warning("LEAN 结果解析失败，降级")
        return self._run_simple_backtest(alphalens_results, data)

    def _gen_algorithm(self, tickers: list[str]) -> str:
        sd = self.config.get("start_date", "2022-01-01")
        ed = self.config.get("end_date", "2024-12-31")
        sy, sm, day_s = sd.split("-")
        ey, em, day_e = ed.split("-")
        res = self.config.get("resolution", "daily").capitalize()
        params = self.config.get("strategy_params", {})
        risk = self.config.get("risk", {})

        return ALGORITHM_TEMPLATE.format(
            strategy_name=self.config.get("strategy_type", "ema_cross"),
            generated_at=datetime.now().isoformat(),
            start_year=sy, start_month=int(sm), start_day=int(day_s),
            end_year=ey, end_month=int(em), end_day=int(day_e),
            cash=self.config.get("cash", 100000),
            fast_period=params.get("fast_period", 9),
            slow_period=params.get("slow_period", 21),
            position_size_pct=risk.get("max_position_pct", 0.25),
            tickers=json.dumps(tickers),
            resolution=res if res in ("Daily", "Minute") else "Daily",
            commission=self.config.get("commission", 0.001),
        )

    def _parse_lean_results(self, results_dir: Path) -> dict | None:
        orders, equity, equity_dates = [], [], []
        for f in sorted(results_dir.glob("*.json")):
            try:
                c = json.loads(f.read_text())
                if isinstance(c, dict):
                    if "Orders" in c:
                        for oid, o in c["Orders"].items():
                            orders.append({
                                "id": str(oid),
                                "date": o.get("Time", ""),
                                "symbol": o.get("Symbol", {}).get("Value", ""),
                                "type": "buy" if o.get("Quantity", 0) > 0 else "sell",
                                "shares": abs(o.get("Quantity", 0)),
                                "price": o.get("Price", 0),
                            })
                    if "Charts" in c and "Strategy Equity" in c["Charts"]:
                        vals = c["Charts"]["Strategy Equity"].get("Series", {}).get("Equity", {}).get("Values", [])
                        equity = [v.get("y", 0) for v in vals]
                        equity_dates = [v.get("x", "") for v in vals]
            except Exception:
                continue

        if not equity:
            return None

        eq = pd.Series(equity)
        ret = eq.pct_change().dropna()
        initial = float(self.config.get("cash", 100000))
        total_ret = (eq.iloc[-1] - initial) / initial
        s = float(ret.mean() / ret.std() * (252 ** 0.5)) if ret.std() > 0 else 0
        peak = eq.expanding().max()

        return {
            "metrics": {
                "engine": "LEAN",
                "total_return": round(total_ret * 100, 2),
                "sharpe_ratio": round(s, 2),
                "max_drawdown": round(float(((eq - peak) / peak).min()) * 100, 2),
                "total_trades": len(orders),
                "final_equity": round(float(eq.iloc[-1]), 2),
            },
            "trades": orders,
            "equity": [round(float(e), 2) for e in equity],
            "equity_dates": equity_dates,
        }

    # ============================================================
    # 内置简易回测
    # ============================================================

    def _run_simple_backtest(self, alphalens_results: dict, data: dict[str, pd.DataFrame]) -> dict:
        tickers = list(data.keys())
        if not tickers:
            return {"metrics": {}, "trades": [], "equity": []}

        sd = self.config.get("start_date", "2022-01-01")
        ed = self.config.get("end_date", "2024-12-31")
        cash = float(self.config.get("cash", 100000))
        comm = float(self.config.get("commission", 0.001))
        max_pct = float(self.config.get("risk", {}).get("max_position_pct", 0.25))
        fast = self.config.get("strategy_params", {}).get("fast_period", 9)
        slow = self.config.get("strategy_params", {}).get("slow_period", 21)

        primary = tickers[0]
        df = data[primary].loc[sd:ed]
        if df.empty:
            return {"metrics": {}, "trades": [], "equity": []}

        c = df["close"].values
        equity = [cash]
        trades: list[dict] = []
        pos, bal = 0, cash

        ef = pd.Series(c).ewm(span=fast, adjust=False).mean().values
        es = pd.Series(c).ewm(span=slow, adjust=False).mean().values
        warm = max(fast, slow) + 1
        equity_dates = [df.index[min(max(warm - 1, 0), len(df) - 1)]]
        total_buy_cost = 0.0

        for i in range(warm, len(c)):
            px = c[i]
            if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
                if pos == 0:
                    shares = int(bal * max_pct / px)
                    if shares > 0:
                        cost = shares * px * (1 + comm)
                        bal -= cost
                        pos = shares
                        total_buy_cost = cost
                        trades.append({"date": str(df.index[i]), "symbol": primary,
                                       "type": "buy", "price": float(px), "shares": shares,
                                       "cost": round(float(cost), 2)})
            elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
                if pos > 0:
                    proceeds = pos * px * (1 - comm)
                    pnl = proceeds - total_buy_cost
                    bal += proceeds
                    trades.append({"date": str(df.index[i]), "symbol": primary,
                                   "type": "sell", "price": float(px), "shares": pos,
                                   "cost": round(float(total_buy_cost), 2),
                                   "proceeds": round(float(proceeds), 2),
                                   "pnl": round(float(pnl), 2)})
                    pos = 0
                    total_buy_cost = 0.0
            equity.append(bal + pos * px)
            equity_dates.append(df.index[i])

        if pos > 0:
            proceeds = pos * c[-1] * (1 - comm)
            pnl = proceeds - total_buy_cost
            bal += proceeds
            trades.append({"date": str(df.index[-1]), "symbol": primary,
                           "type": "sell", "price": float(c[-1]), "shares": pos,
                           "cost": round(float(total_buy_cost), 2),
                           "proceeds": round(float(proceeds), 2),
                           "pnl": round(float(pnl), 2),
                           "exit_reason": "final_liquidation"})
            equity[-1] = bal

        eq = pd.Series(equity)
        ret = eq.pct_change().dropna()
        if len(ret) < 2:
            return {
                "metrics": {},
                "trades": trades,
                "equity": equity,
                "equity_dates": [str(d) for d in equity_dates],
            }

        tr = float((eq.iloc[-1] - cash) / cash)
        sp = float(ret.mean() / ret.std() * (252 ** 0.5)) if ret.std() > 0 else 0
        peak = eq.expanding().max()
        dd = float(((eq - peak) / peak).min())
        sells = [t for t in trades if t["type"] == "sell"]
        wins = [s for s in sells if s.get("pnl", 0) > 0]

        return {
            "metrics": {
                "engine": "QuantBridge-lite",
                "total_return": round(float(tr * 100), 2),
                "sharpe_ratio": round(sp, 2),
                "max_drawdown": round(dd * 100, 2),
                "total_trades": len(trades),
                "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else 0,
                "final_equity": round(float(eq.iloc[-1]), 2),
            },
            "trades": trades,
            "equity": [round(float(e), 2) for e in equity],
            "equity_dates": [str(d) for d in equity_dates],
        }
