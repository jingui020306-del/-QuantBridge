from quantbridge.daemon import QuantBridgeDaemon


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
