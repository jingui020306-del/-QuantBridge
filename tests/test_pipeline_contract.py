import json

from quantbridge.pipeline import PipelineEngine


def test_write_signals_includes_dashboard_contract_fields(tmp_path):
    signal_path = tmp_path / "signals.json"
    engine = PipelineEngine({
        "general": {"output_dir": str(tmp_path)},
        "fincept": {
            "enabled": True,
            "signal_output": str(signal_path),
        },
    })
    engine._state["alphalens_updated"] = "2026-06-04T00:00:00"

    engine.write_signals({
        "passed": False,
        "passed_factors": [],
        "summary": {"rsi_14": {"ic_pearson": 0.01}},
    }, None)

    payload = json.loads(signal_path.read_text())
    assert payload["source"] == "QuantBridge"
    assert payload["integration_mode"] == "file"
    assert payload["passed"] is False
    assert payload["passed_factors"] == []
    assert payload["factors"] == {"rsi_14": {"ic_pearson": 0.01}}
    assert payload["trades"] == []
    assert payload["metrics"] == {}

    state = json.loads((tmp_path / "pipeline_state.json").read_text())
    assert state == {"alphalens_updated": "2026-06-04T00:00:00"}
