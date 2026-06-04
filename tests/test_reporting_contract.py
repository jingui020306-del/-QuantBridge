from pathlib import Path

from quantbridge.reporting.pyfolio_runner import PyfolioRunner


def test_returns_use_datetime_index_from_equity_dates():
    runner = PyfolioRunner(enable_external_reports=True)

    returns = runner._to_returns(
        [100, 101, 99, 102],
        ["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"],
    )

    assert type(returns.index).__name__ == "DatetimeIndex"
    assert str(returns.index[0]) == "2022-01-02 00:00:00"
    assert returns.name == "strategy"


def test_save_plot_accepts_axes_like_objects(tmp_path):
    class FakeFigure:
        def __init__(self):
            self.saved = None

        def savefig(self, path, dpi, bbox_inches):
            self.saved = (Path(path), dpi, bbox_inches)

    class FakeAxes:
        def __init__(self):
            self.figure = FakeFigure()

    class FakePyplot:
        def __init__(self):
            self.closed = None

        def close(self, fig):
            self.closed = fig

    runner = PyfolioRunner(output_dir=str(tmp_path), enable_external_reports=True)
    axes = FakeAxes()
    pyplot = FakePyplot()

    assert runner._save_plot(axes, tmp_path / "plot.png", pyplot) is True
    assert axes.figure.saved == (tmp_path / "plot.png", 150, "tight")
    assert pyplot.closed is axes.figure
