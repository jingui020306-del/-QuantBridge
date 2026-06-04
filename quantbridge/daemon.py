"""
QuantBridge Daemon — 后台常驻服务。

职责：
  1. 监听 watch/ 目录中的显式触发文件
  2. 定时轮询（兜底机制）
  3. 执行 pipeline：数据 → 因子 → 因子检验 → 回测 → 绩效摘要
  4. 结果写回 outputs/，供 Dashboard 和外部桥接读取
  5. 自动回环
"""

import json
import threading
import time
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import ensure_output_dirs, load_config
from .pipeline import PipelineEngine


class StrategyChangeHandler(FileSystemEventHandler):
    """监听 watch/ 目录的文件变更。"""

    def __init__(self, daemon: "QuantBridgeDaemon"):
        self.daemon = daemon
        self._last_run = 0
        self._cooldown = 5  # 冷却秒数，避免频繁触发

    def on_created(self, event):
        if not event.is_directory and self.daemon.is_trigger_file(event.src_path):
            self._trigger_if_cooled(f"检测到策略变更: {event.src_path}")

    def on_modified(self, event):
        # Writing a new file often emits created + modified. Responding only to
        # creation keeps the file contract deterministic and avoids log noise.
        return

    def on_moved(self, event):
        if not event.is_directory and self.daemon.is_trigger_file(event.dest_path):
            self._trigger_if_cooled(f"检测到策略变更: {event.dest_path}")

    def _trigger_if_cooled(self, message: str) -> bool:
        now = time.time()
        if now - self._last_run > self._cooldown:
            self._last_run = now
            logger.info(message)
            self.daemon.run_cycle()
            return True
        return False


class QuantBridgeDaemon:
    """后台常驻服务。"""

    def __init__(self, config_path: str = "config/default.yaml"):
        self.config = load_config(config_path)
        ensure_output_dirs(self.config)

        daemon_cfg = self.config.get("daemon", {})
        self.watch_dir = Path(daemon_cfg.get("watch_dir", "outputs/watch"))
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir = Path(daemon_cfg.get("runtime_dir", "outputs/runtime"))
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.trigger_patterns = daemon_cfg.get("trigger_patterns", [
            "trigger_*.json",
            "strategy_*.json",
            "strategy_*.yaml",
            "strategy_*.yml",
            "params_*.json",
            "params_*.yaml",
            "params_*.yml",
        ])

        self.engine = PipelineEngine(self.config)
        self.observer: Observer | None = None
        self._cycle_lock = threading.Lock()

        # 轮询间隔（秒）
        self._poll_interval = daemon_cfg.get("poll_interval_seconds", 300)

        logger.info("QuantBridge Daemon 初始化完成")

    def start(self):
        """启动 daemon：文件监听 + 定时轮询。"""
        logger.info("=" * 50)
        logger.info("QuantBridge Daemon 启动")
        logger.info(f"  监听目录: {self.watch_dir}")
        logger.info(f"  运行状态目录: {self.runtime_dir}")
        logger.info(f"  触发模式: {', '.join(self.trigger_patterns)}")
        logger.info(f"  轮询间隔: {self._poll_interval}s")
        logger.info("=" * 50)

        self.observer = Observer()
        self.observer.schedule(
            StrategyChangeHandler(self),
            str(self.watch_dir),
            recursive=False,
        )
        self.observer.start()

        # 首次立即运行
        self.run_cycle()

        try:
            last_poll = time.time()
            while True:
                time.sleep(1)

                # 定时轮询
                if time.time() - last_poll > self._poll_interval:
                    last_poll = time.time()
                    logger.debug("定时轮询触发")
                    self.run_cycle()

        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            self.stop()

    def stop(self):
        """停止 daemon。"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        logger.info("QuantBridge Daemon 已停止")

    def is_trigger_file(self, path: str | Path) -> bool:
        """只接受显式触发文件，避免 heartbeat/state 输出反向触发回环。"""
        name = Path(path).name
        return any(fnmatch(name, pattern) for pattern in self.trigger_patterns)

    def run_cycle(self):
        """执行一次完整回环。"""
        if not self._cycle_lock.acquire(blocking=False):
            logger.warning("已有回环正在执行，跳过本次触发")
            return

        cycle_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info(f"\n{'#' * 40}\n  回环开始: {cycle_id}\n{'#' * 40}")
        status = "ok"
        error = None

        try:
            # 1. 拉取/更新数据
            data = self.engine.run_data()

            # 2. 因子计算
            factors = self.engine.run_factors(data)

            # 3. alphalens 因子检验
            alphalens_results = self.engine.run_alphalens(factors, data)

            # 4. 因子通过 → LEAN 回测
            if alphalens_results.get("passed", False):
                lean_results = self.engine.run_lean(alphalens_results, data)
            else:
                logger.warning("因子检验未通过，跳过 LEAN 回测")
                lean_results = None

            # 5. pyfolio 绩效分析
            if lean_results:
                self.engine.run_pyfolio(lean_results)

            # 6. 写回信号给 FinceptTerminal
            self.engine.write_signals(alphalens_results, lean_results)

            logger.info(f"回环完成: {cycle_id}")

        except Exception as exc:
            status = "error"
            error = str(exc)
            logger.exception(f"回环失败: {cycle_id}")
        finally:
            heartbeat = {
                "last_cycle": cycle_id,
                "status": status,
                "timestamp": datetime.now().isoformat(),
            }
            if error:
                heartbeat["error"] = error
            (self.runtime_dir / "heartbeat.json").write_text(json.dumps(heartbeat, indent=2))
            self._cycle_lock.release()


def main():
    """Daemon 入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="QuantBridge Daemon")
    parser.add_argument("--config", default="config/default.yaml", help="配置文件路径")
    parser.add_argument("action", nargs="?", default="start", choices=["start", "stop"])
    args = parser.parse_args()

    daemon = QuantBridgeDaemon(args.config)
    if args.action == "start":
        daemon.start()


if __name__ == "__main__":
    main()
