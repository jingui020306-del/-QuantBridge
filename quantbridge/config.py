"""配置加载模块。"""

from pathlib import Path

import yaml
from loguru import logger


def load_config(config_path: str | Path = "config/default.yaml") -> dict:
    """加载 YAML 配置文件。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path) as f:
        config = yaml.safe_load(f)
    logger.info(f"配置已加载: {path}")
    return config


def ensure_output_dirs(config: dict) -> None:
    """确保所有输出目录存在。"""
    dirs = [
        config.get("data", {}).get("cache_dir", "outputs/cache"),
        config.get("backtest", {}).get("lean", {}).get("data_dir", "outputs/lean_data"),
        config.get("fincept", {}).get("report_output", "outputs/reports"),
        config.get("daemon", {}).get("watch_dir", "outputs/watch"),
        config.get("daemon", {}).get("runtime_dir", "outputs/runtime"),
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
