import json

from quantbridge.fincept.bridge import FinceptBridge


def test_bridge_formats_signal_contract_and_trade_shape():
    bridge = FinceptBridge(integration_mode="file")

    payload = bridge.format_signals({
        "generated_at": "2026-06-04T00:00:00",
        "passed": True,
        "passed_factors": ["rsi_14"],
        "factors": {"rsi_14": {"ic_pearson": 0.03}},
        "trades": [{
            "date": "2026-06-04",
            "symbol": "AAPL",
            "type": "buy",
            "shares": 10,
            "price": 100,
            "cost": 1001,
        }],
        "metrics": {"sharpe_ratio": 1.2},
    })

    assert payload["source"] == "QuantBridge"
    assert payload["integration_mode"] == "file"
    assert payload["passed"] is True
    assert payload["passed_factors"] == ["rsi_14"]
    assert payload["trades"] == [{
        "timestamp": "2026-06-04",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 10,
        "price": 100,
        "value": 1001,
    }]


def test_bridge_write_signals_returns_written_payload(tmp_path):
    bridge = FinceptBridge(integration_mode="file")
    output = tmp_path / "signals.json"

    payload = bridge.write_signals({
        "generated_at": "2026-06-04T00:00:00",
        "passed": False,
        "passed_factors": [],
        "factors": {},
        "trades": [],
        "metrics": {},
    }, str(output))

    assert json.loads(output.read_text()) == payload
