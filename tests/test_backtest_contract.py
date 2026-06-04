from types import SimpleNamespace

import pandas as pd

from quantbridge.backtest.lean_runner import LeanRunner
from quantbridge.config import load_config


def test_default_config_enables_real_reports_with_longer_lean_timeout():
    config = load_config("config/default.yaml")

    assert config["alphalens"]["use_real"] is True
    assert config["pyfolio"]["enable_external_reports"] is True
    assert config["backtest"]["lean"]["timeout_seconds"] == 600


def test_lean_docker_mounts_data_root_not_equity_subdir(tmp_path, monkeypatch):
    data = pd.DataFrame(
        {
            "open": [10, 11],
            "high": [11, 12],
            "low": [9, 10],
            "close": [10, 11],
            "volume": [1000, 1100],
        },
        index=pd.date_range("2022-01-01", periods=2),
    )
    runner = LeanRunner(lean_config={
        "data_dir": str(tmp_path / "lean_data"),
        "timeout_seconds": 600,
    })
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("quantbridge.backtest.lean_runner.subprocess.run", fake_run)
    monkeypatch.setattr(runner, "_parse_lean_results", lambda results_dir: {"equity": [1.0]})

    runner._run_lean_docker({}, {"AAPL": data})

    first_volume = captured["cmd"][captured["cmd"].index("-v") + 1]
    assert first_volume.endswith("/Data:/Data")
    assert "/Data/equity" not in first_volume
    assert captured["timeout"] == 600


def test_simple_backtest_trades_include_symbol_and_closed_trade_pnl():
    prices = [10, 9, 8, 9, 10, 11, 10, 9, 8, 7, 6]
    data = pd.DataFrame(
        {"close": prices},
        index=pd.date_range("2022-01-01", periods=len(prices)),
    )
    runner = LeanRunner(lean_config={
        "start_date": "2022-01-01",
        "end_date": "2022-12-31",
        "cash": 10000,
        "commission": 0,
        "risk": {"max_position_pct": 0.5},
        "strategy_params": {"fast_period": 2, "slow_period": 3},
    })

    result = runner._run_simple_backtest({"passed_factors": ["ema_200"]}, {"AAPL": data})

    assert result["trades"] == [
        {
            "date": "2022-01-05 00:00:00",
            "symbol": "AAPL",
            "type": "buy",
            "price": 10.0,
            "shares": 500,
            "cost": 5000.0,
        },
        {
            "date": "2022-01-08 00:00:00",
            "symbol": "AAPL",
            "type": "sell",
            "price": 9.0,
            "shares": 500,
            "cost": 5000.0,
            "proceeds": 4500.0,
            "pnl": -500.0,
        },
    ]
    assert result["metrics"]["win_rate"] == 0.0
    assert isinstance(result["metrics"]["total_return"], float)


def test_win_rate_uses_closed_trade_pnl_not_positive_proceeds():
    prices = [10, 10, 9, 8, 9, 10, 11, 10, 9, 8, 9, 10]
    data = pd.DataFrame(
        {"close": prices},
        index=pd.date_range("2022-01-01", periods=len(prices)),
    )
    runner = LeanRunner(lean_config={
        "start_date": "2022-01-01",
        "end_date": "2022-12-31",
        "cash": 10000,
        "commission": 0,
        "risk": {"max_position_pct": 0.5},
        "strategy_params": {"fast_period": 2, "slow_period": 3},
    })

    result = runner._run_simple_backtest({"passed_factors": ["ema_200"]}, {"AAPL": data})

    sells = [trade for trade in result["trades"] if trade["type"] == "sell"]
    assert [sell["pnl"] for sell in sells] == [-500.0, 0.0]
    assert result["metrics"]["win_rate"] == 0.0
