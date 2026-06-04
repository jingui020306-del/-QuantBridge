"""
FinceptTerminal 桥接层。

职责：
  1. 复用 FinceptTerminal 的 Python 脚本（技术指标、数据源）
  2. 将 QuantBridge 产出写回 FinceptTerminal 可读取的格式
  3. 双向通信：FinceptTerminal ↔ QuantBridge daemon
"""

import json
import sys
from pathlib import Path
from typing import Any

from loguru import logger


class FinceptBridge:
    """FinceptTerminal 双向桥接。"""

    def __init__(self, fincept_home: str | None = None):
        self.fincept_home = Path(fincept_home) if fincept_home else None
        self.scripts_dir = self.fincept_home / "fincept-qt" / "scripts" if self.fincept_home else None
        self.available = self._check_available()

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

    def write_signals(self, signals: dict, output_path: str = "outputs/signals.json") -> None:
        """将 QuantBridge 产出的信号写为 FinceptTerminal 可读格式。

        FinceptTerminal 的 strategy/algo 模块能读取这个 JSON。
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "source": "QuantBridge",
            "generated_at": signals.get("generated_at", ""),
            "factors": signals.get("factors", {}),
            "trades": self._format_trades(signals.get("trades", [])),
            "metrics": signals.get("metrics", {}),
        }

        output.write_text(json.dumps(payload, indent=2, default=str))
        logger.info(f"信号已写回 FinceptTerminal: {output}")

    def _format_trades(self, trades: list[dict]) -> list[dict]:
        """将交易记录转为 FinceptTerminal 兼容格式。"""
        return [
            {
                "timestamp": t.get("date", ""),
                "symbol": t.get("symbol", ""),
                "side": t.get("type", "").upper(),
                "quantity": t.get("shares", 0),
                "price": t.get("price", 0),
                "value": t.get("cost", t.get("proceeds", 0)),
            }
            for t in trades
        ]

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


def get_bridge(fincept_home: str | None = None) -> FinceptBridge:
    """工厂函数：获取 FinceptBridge 实例。"""
    return FinceptBridge(fincept_home)
