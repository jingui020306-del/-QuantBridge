import sys
import types


if "watchdog" not in sys.modules:
    watchdog = types.ModuleType("watchdog")
    events = types.ModuleType("watchdog.events")
    observers = types.ModuleType("watchdog.observers")

    class FileSystemEventHandler:
        pass

    class Observer:
        def schedule(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def join(self):
            pass

    events.FileSystemEventHandler = FileSystemEventHandler
    observers.Observer = Observer
    sys.modules["watchdog"] = watchdog
    sys.modules["watchdog.events"] = events
    sys.modules["watchdog.observers"] = observers


if "yfinance" not in sys.modules:
    yfinance = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, *args, **kwargs):
            raise RuntimeError("yfinance is stubbed in contract tests")

    yfinance.Ticker = Ticker
    sys.modules["yfinance"] = yfinance
