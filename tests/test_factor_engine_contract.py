from pathlib import Path

import yaml

from quantbridge.factors.engine import FactorEngine


def test_default_factor_registry_has_41_factors_from_config_windows():
    config = yaml.safe_load(Path("config/default.yaml").read_text())
    engine = FactorEngine(default_params=config["factors"]["default_params"])
    registry = engine._registry

    assert len(registry) == 41
    assert {
        "volume_over_ma_5",
        "volume_over_ma_9",
        "volume_over_ma_21",
        "volume_over_ma_50",
        "volume_over_ma_200",
    }.issubset(registry)


def test_factor_engine_expands_user_home_in_fincept_scripts_dir():
    engine = FactorEngine(fincept_scripts_dir="~/FinceptTerminal/fincept-qt/scripts")

    assert engine.fincept_scripts_dir == Path.home() / "FinceptTerminal" / "fincept-qt" / "scripts"
