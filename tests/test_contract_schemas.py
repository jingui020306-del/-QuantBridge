import json
from pathlib import Path


SCHEMA_DIR = Path("schemas")


def test_contract_schemas_are_valid_json():
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        assert schema["type"] == "object"
        assert "$schema" in schema


def test_signals_schema_matches_current_writer_contract():
    schema = json.loads((SCHEMA_DIR / "signals.schema.json").read_text())

    assert set(schema["required"]) == {
        "source",
        "integration_mode",
        "generated_at",
        "passed",
        "passed_factors",
        "factors",
        "trades",
        "metrics",
    }


def test_trigger_schema_requires_explicit_event_and_timestamp():
    schema = json.loads((SCHEMA_DIR / "trigger.schema.json").read_text())

    assert schema["required"] == ["event", "timestamp"]
