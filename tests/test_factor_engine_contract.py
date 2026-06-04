from pathlib import Path

from quantbridge.factors.engine import FactorEngine


def test_factor_engine_expands_user_home_in_fincept_scripts_dir():
    engine = FactorEngine(fincept_scripts_dir="~/FinceptTerminal/fincept-qt/scripts")

    assert engine.fincept_scripts_dir == Path.home() / "FinceptTerminal" / "fincept-qt" / "scripts"
