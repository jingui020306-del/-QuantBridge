from quantbridge.data.fetcher import DataFetcher


def test_cache_path_includes_date_range_and_frequency(tmp_path):
    fetcher = DataFetcher(
        tickers=["BRK/B"],
        start_date="2022-01-01",
        end_date="2024-12-31",
        frequency="1d",
        cache_dir=str(tmp_path),
    )

    assert fetcher._cache_path("BRK/B").name == "BRK-B_1d_2022-01-01_2024-12-31.parquet"


def test_cache_path_changes_when_date_range_changes(tmp_path):
    first = DataFetcher(
        tickers=["AAPL"],
        start_date="2022-01-01",
        end_date="2024-12-31",
        frequency="1d",
        cache_dir=str(tmp_path),
    )
    second = DataFetcher(
        tickers=["AAPL"],
        start_date="2023-01-01",
        end_date="2024-12-31",
        frequency="1d",
        cache_dir=str(tmp_path),
    )

    assert first._cache_path("AAPL") != second._cache_path("AAPL")
