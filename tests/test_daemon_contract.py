from quantbridge.daemon import QuantBridgeDaemon, StrategyChangeHandler


def test_daemon_only_accepts_explicit_trigger_files():
    daemon = QuantBridgeDaemon("config/default.yaml")

    assert daemon.is_trigger_file("outputs/watch/trigger_manual.json")
    assert daemon.is_trigger_file("outputs/watch/strategy_alpha.yaml")
    assert daemon.is_trigger_file("outputs/watch/params_alpha.yml")

    assert not daemon.is_trigger_file("outputs/watch/heartbeat.json")
    assert not daemon.is_trigger_file("outputs/watch/pipeline_state.json")
    assert not daemon.is_trigger_file("outputs/watch/signals.json")


def test_daemon_heartbeat_lives_outside_watch_dir():
    daemon = QuantBridgeDaemon("config/default.yaml")

    assert daemon.watch_dir == daemon.runtime_dir.parent / "watch"
    assert daemon.runtime_dir == daemon.watch_dir.parent / "runtime"


def test_strategy_change_handler_suppresses_cooldown_noise():
    class FakeDaemon:
        def __init__(self):
            self.runs = 0

        def run_cycle(self):
            self.runs += 1

    fake = FakeDaemon()
    handler = StrategyChangeHandler(fake)

    assert handler._trigger_if_cooled("first event")
    assert not handler._trigger_if_cooled("duplicate event")
    assert fake.runs == 1

    handler._last_run -= handler._cooldown + 0.1
    assert handler._trigger_if_cooled("later edit")
    assert fake.runs == 2


def test_strategy_change_handler_ignores_modified_trigger_events():
    class FakeDaemon:
        def __init__(self):
            self.runs = 0

        def is_trigger_file(self, path):
            return path.endswith("trigger_manual.json")

        def run_cycle(self):
            self.runs += 1

    class Event:
        is_directory = False
        src_path = "outputs/watch/trigger_manual.json"

    fake = FakeDaemon()
    handler = StrategyChangeHandler(fake)

    handler.on_modified(Event())

    assert fake.runs == 0
