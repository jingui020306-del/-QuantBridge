"""
FinceptTerminal 桥接层。

职责：
  1. 复用 FinceptTerminal 的 Python 脚本（技术指标、数据源）
  2. 将 QuantBridge 产出写为稳定 JSON 文件契约
  3. 为后续 FinceptTerminal 原生桥接保留触发文件入口
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger


class FinceptBridge:
    """FinceptTerminal 文件桥接预留。

    当前支持的是 file 模式：QuantBridge 写文件，FinceptTerminal 本体尚不原生消费。
    """

    def __init__(
        self,
        fincept_home: str | None = None,
        integration_mode: str = "file",
        check_available: bool = True,
    ):
        self.integration_mode = integration_mode
        self.fincept_home = Path(os.path.expandvars(fincept_home)).expanduser() if fincept_home else None
        self.scripts_dir = self.fincept_home / "fincept-qt" / "scripts" if self.fincept_home else None
        self.available = self._check_available() if check_available else False

    def _check_available(self) -> bool:
        """检测 FinceptTerminal 是否可用。"""
        if not self.fincept_home or not self.fincept_home.exists():
            logger.info("FinceptTerminal 未检测到，桥接层处于独立模式")
            return False
        logger.info(f"FinceptTerminal 已检测到: {self.fincept_home}")
        return True

    def get_technicals_scripts(self) -> list[Path]:
        """获取 FinceptTerminal 的技术指标脚本路径。"""
        if not self.scripts_dir:
            return []
        tech_dir = self.scripts_dir / "technicals"
        if tech_dir.exists():
            return list(tech_dir.glob("*.py"))
        return []

    def get_analytics_scripts(self) -> list[Path]:
        """获取 FinceptTerminal 的分析脚本路径。"""
        if not self.scripts_dir:
            return []
        analytics_dir = self.scripts_dir / "Analytics"
        scripts: list[Path] = []
        if analytics_dir.exists():
            for d in analytics_dir.iterdir():
                if d.is_dir():
                    scripts.extend(d.glob("*.py"))
        return scripts

    def format_signals(self, signals: dict) -> dict:
        """将 QuantBridge 内部信号标准化为文件契约 payload。"""
        return {
            "source": "QuantBridge",
            "integration_mode": self.integration_mode,
            "generated_at": signals.get("generated_at", ""),
            "passed": signals.get("passed", False),
            "passed_factors": signals.get("passed_factors", []),
            "factors": signals.get("factors", {}),
            "trades": self._format_trades(signals.get("trades", [])),
            "metrics": signals.get("metrics", {}),
        }

    def write_signals(self, signals: dict, output_path: str = "outputs/signals.json") -> dict:
        """将 QuantBridge 产出的信号写为当前 file 模式契约。

        注意：FinceptTerminal 本体目前没有原生消费该文件，需要额外桥接入口。
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        payload = self.format_signals(signals)
        output.write_text(json.dumps(payload, indent=2, default=str))
        logger.info(f"信号快照已输出: {output}")
        return payload

    def _format_trades(self, trades: list[dict]) -> list[dict]:
        """将交易记录转为 FinceptTerminal 兼容格式。"""
        formatted = []
        for trade in trades:
            side = trade.get("type", "").upper()
            value = trade.get("proceeds", 0) if side == "SELL" else trade.get("cost", 0)
            formatted.append({
                "timestamp": trade.get("date", ""),
                "symbol": trade.get("symbol", ""),
                "side": side,
                "quantity": trade.get("shares", 0),
                "price": trade.get("price", 0),
                "value": value,
            })
        return formatted

    def run_fincept_script(self, script_name: str, args: dict | None = None) -> dict:
        """调用 FinceptTerminal 的 Python 脚本并返回结果。

        这样 QuantBridge 可以直接复用 FinceptTerminal 的分析能力。
        """
        if not self.scripts_dir:
            return {"error": "FinceptTerminal scripts 目录不可用"}

        # 查找脚本
        script_path = None
        for py_file in self.scripts_dir.rglob(f"{script_name}*.py"):
            script_path = py_file
            break

        if not script_path:
            return {"error": f"脚本未找到: {script_name}"}

        import subprocess

        cmd = [sys.executable, str(script_path)]
        if args:
            cmd.append(json.dumps(args))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            return {"error": result.stderr or "脚本执行失败"}
        except Exception as e:
            return {"error": str(e)}

    def write_watch_trigger(self, event_type: str, payload: dict | None = None) -> None:
        """向 watch/ 目录写入触发文件，通知 daemon 执行回环。

        FinceptTerminal 侧调用此方法时，daemon 检测到文件变化，
        自动执行完整 pipeline。
        """
        watch_dir = Path("outputs/watch")
        watch_dir.mkdir(parents=True, exist_ok=True)

        trigger = {
            "event": event_type,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "payload": payload or {},
        }

        trigger_file = watch_dir / f"trigger_{event_type}.json"
        trigger_file.write_text(json.dumps(trigger, indent=2))
        logger.info(f"触发已写入: {trigger_file}")


def get_bridge(
    fincept_home: str | None = None,
    integration_mode: str = "file",
    check_available: bool = True,
) -> FinceptBridge:
    """工厂函数：获取 FinceptBridge 实例。"""
    return FinceptBridge(fincept_home, integration_mode, check_available)
