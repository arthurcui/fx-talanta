import shutil
import zipfile
from datetime import UTC, datetime

import pytest
from test_session_study import source

from fx_talanta.research.acquisition import FixedOrigin, months, prepare
from fx_talanta.research.spool import file_hash
from fx_talanta.research.tick_index import TickIndex, build_index


def test_preparation_cache_retains_source_and_refuses_changed_index(tmp_path):
    archive, _ = source(tmp_path)
    calls = []

    def fetch(symbol, month, destination):
        calls.append((symbol, month))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, destination)
        return dict(symbol=symbol, month=month, sha256=file_hash(destination))

    args = (
        tmp_path / "history",
        "EURUSD",
        datetime(2025, 1, 16, 12, tzinfo=UTC),
        datetime(2025, 1, 16, 15, tzinfo=UTC),
        53,
        lambda state: None,
    )
    path, report = prepare(*args, fetch=fetch)
    assert calls == [("EURUSD", "202501")]
    assert report["rows"] == 6
    assert not report["qualification"] == "QUALIFIED"
    assert prepare(*args, fetch=fetch)[1] == report
    assert len(calls) == 1
    with (path / "ticks.sqlite").open("ab") as f:
        f.write(b"tamper")
    with pytest.raises(ValueError, match="changed"):
        prepare(*args, fetch=fetch)


def test_explicit_normalization_preserves_ties_and_original_rows(tmp_path):
    path = tmp_path / "source.zip"
    rows = [
        "20250116 080000000,1.1,1.1001,0",
        "20250116 070000000,1.2,1.2001,0",
        "20250116 070000000,1.3,1.3001,0",
    ]
    with zipfile.ZipFile(path, "w") as f:
        f.writestr("DAT_ASCII_EURUSD_T_202501.csv", "\n".join(rows))
    with pytest.raises(ValueError, match="reversed"):
        build_index(path, "EURUSD", tmp_path / "original")
    build_index(path, "EURUSD", tmp_path / "sorted", normalize_timestamps=True)
    index = TickIndex(tmp_path / "sorted/ticks.sqlite")
    try:
        assert [r[0] for r in index.db.execute("SELECT bid FROM ticks ORDER BY seq")] == [
            "1.2",
            "1.3",
            "1.1",
        ]
        assert index.metadata["timestamp_order"] == "STABLE_SORT_WITH_SOURCE_ORDER_RETAINED"
    finally:
        index.close()
    assert (tmp_path / "sorted/source-order.sqlite").exists()


def test_month_bounds_and_redirect_refusal():
    assert months(datetime(2025, 12, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)) == [
        "202512",
        "202601",
    ]
    with pytest.raises(ValueError, match="fourteen"):
        months(datetime(2020, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="trusted origin"):
        FixedOrigin().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/private")
