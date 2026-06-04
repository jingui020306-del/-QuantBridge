"""
Pipeline Engine — 编排核心。

负责按顺序调度各模块，串联起数据 → 因子 → 回测 → 报告的全流程。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from .data.fetcher import DataFetcher
from .factors.alphalens_runner import AlphalensRunner
from .factors.engine import FactorEngine
from .backtest.lean_runner import LeanRunner
from .fincept.bridge import FinceptBridge
from .reporting.pyfolio_runner import PyfolioRunner


class PipelineEngine:
    """主控引擎，调度全流程。"""

    def __init__(self, config: dict):
        self.config = config
        self.outputs = Path(config.get("general", {}).get("output_dir", "outputs"))
        self.outputs.mkdir(parents=True, exist_ok=True)

        # 状态追踪
        self._state: dict[str, Any] = {}
        self._last_data: dict[str, pd.DataFrame] = {}
        self._last_factors: dict[str, pd.DataFrame] = {}
        self._last_alphalens: dict = {}
        self._last_lean: dict = {}

    # ---- 步骤 1: 数据 ----

    def run_data(self) -> dict[str, pd.DataFrame]:
        """拉取/更新数据。"""
        data_cfg = self.config.get("data", {})
        fetcher = DataFetcher(
            tickers=data_cfg.get("tickers", []),
            start_date=data_cfg.get("start_date", "2022-01-01"),
            end_date=data_cfg.get("end_date", datetime.now().strftime("%Y-%m-%d")),
            frequency=data_cfg.get("frequency", "1d"),
            cache_dir=data_cfg.get("cache_dir", "outputs/cache"),
            fincept_export_path=data_cfg.get("fincept_export_path"),
        )
        self._last_data = fetcher.fetch_all()
        self._state["data_updated"] = datetime.now().isoformat()
        return self._last_data

    # ---- 步骤 2: 因子 ----

    def run_factors(self, data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """计算因子。"""
        factor_cfg = self.config.get("factors", {})
        engine = FactorEngine(
            fincept_scripts_dir=factor_cfg.get("fincept_scripts_dir"),
            default_params=factor_cfg.get("default_params", {}),
            custom_factors=factor_cfg.get("custom_factors", []),
        )
        self._last_factors = engine.compute_all(data)
        self._state["factors_updated"] = datetime.now().isoformat()
        return self._last_factors

    # ---- 步骤 3: alphalens ----

    def run_alphalens(
        self,
        factors: dict[str, pd.DataFrame],
        data: dict[str, pd.DataFrame],
    ) -> dict:
        """因子检验。"""
        alphalens_cfg = self.config.get("alphalens", {})
        runner = AlphalensRunner(
            forward_periods=alphalens_cfg.get("forward_periods", [1, 5, 21]),
            quantiles=alphalens_cfg.get("quantiles", 5),
            pass_threshold=alphalens_cfg.get("pass_threshold", {}),
        )
        self._last_alphalens = runner.run(factors, data)
        self._state["alphalens_updated"] = datetime.now().isoformat()
        return self._last_alphalens

    # ---- 步骤 4: LEAN ----

    def run_lean(self, alphalens_results: dict, data: dict[str, pd.DataFrame]) -> dict | None:
        """LEAN 回测。"""
        backtest_cfg = self.config.get("backtest", {})
        if backtest_cfg.get("engine") != "lean":
            logger.info("回测引擎不是 LEAN，跳过")
            return None

        lean_cfg = backtest_cfg.get("lean", {})
        runner = LeanRunner(
            docker_image=lean_cfg.get("docker_image", "quantconnect/lean:latest"),
            data_dir=lean_cfg.get("data_dir", "outputs/lean_data"),
            lean_config=lean_cfg,
        )

        try:
            self._last_lean = runner.run(alphalens_results, data)
            self._state["lean_updated"] = datetime.now().isoformat()
            return self._last_lean
        except Exception as e:
            logger.error(f"LEAN 回测失败: {e}")
            return None

    # ---- 步骤 5: pyfolio ----

    def run_pyfolio(self, lean_results: dict) -> dict:
        """绩效分析。"""
        pyfolio_cfg = self.config.get("pyfolio", {})
        runner = PyfolioRunner(
            benchmark=pyfolio_cfg.get("benchmark", "SPY"),
            output_dir=str(self.outputs / "reports"),
        )

        try:
            report = runner.run(lean_results)
            self._state["pyfolio_updated"] = datetime.now().isoformat()
            return report
        except Exception as e:
            logger.error(f"pyfolio 分析失败: {e}")
            return {}

    # ---- 步骤 6: 写回信号 ----

    def write_signals(self, alphalens_results: dict, lean_results: dict | None) -> None:
        """将稳定信号快照写入 outputs/。

        当前这是 QuantBridge 自己的文件契约；FinceptTerminal 本体尚未原生消费该文件。
        """
        fincept_cfg = self.config.get("fincept", {})
        signal_output = Path(fincept_cfg.get("signal_output", "outputs/signals.json"))
        bridge = FinceptBridge(
            fincept_home=fincept_cfg.get("fincept_home"),
            integration_mode=fincept_cfg.get("integration_mode", "file"),
            check_available=False,
        )

        signals = {
            "generated_at": datetime.now().isoformat(),
            "passed": bool(alphalens_results.get("passed", False)),
            "passed_factors": alphalens_results.get("passed_factors", []),
            "factors": alphalens_results.get("summary", {}),
            "trades": lean_results.get("trades", []) if lean_results else [],
            "metrics": lean_results.get("metrics", {}) if lean_results else {},
        }

        if fincept_cfg.get("enabled", True):
            bridge.write_signals(signals, str(signal_output))

        state_path = self.outputs / "pipeline_state.json"
        state_path.write_text(json.dumps(self._state, indent=2, default=str))


def main():
    """CLI 入口 — 单次运行全流程。"""
    import argparse

    from .config import load_config

    parser = argparse.ArgumentParser(description="QuantBridge Pipeline")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--stage", choices=["data", "factors", "alphalens", "lean", "pyfolio", "all"],
                       default="all")
    parser.add_argument("--daemon", action="store_true", help="持续运行模式")
    args = parser.parse_args()

    if args.daemon:
        from .daemon import QuantBridgeDaemon
        daemon = QuantBridgeDaemon(args.config)
        daemon.start()
        return

    config = load_config(args.config)
    engine = PipelineEngine(config)

    stage = args.stage
    data = engine.run_data()
    if stage == "data":
        return

    factors = engine.run_factors(data)
    if stage == "factors":
        return

    alphalens = engine.run_alphalens(factors, data)
    if stage == "alphalens":
        engine.write_signals(alphalens, None)
        return

    lean = engine.run_lean(alphalens, data) if alphalens.get("passed") else None
    if stage == "lean":
        engine.write_signals(alphalens, lean)
        return
    if not lean:
        engine.write_signals(alphalens, None)
        return

    engine.run_pyfolio(lean)
    engine.write_signals(alphalens, lean)


if __name__ == "__main__":
    main()
