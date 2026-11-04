import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "probe_required_sources",
    Path(__file__).resolve().parents[1] / "tools/qualification/probe_required_sources.py",
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
NOW = datetime(2026, 11, 3, tzinfo=UTC)


def test_bea_retains_precise_source_offsets_and_reports_duplicates():
    raw = json.dumps(
        {
            "file_last_updated": "2026-11-02",
            "Gross Domestic Product": {
                "release_dates": ["2026-11-25T08:30:00-05:00", "2026-11-25T13:30:00+00:00"]
            },
            "Personal Income and Outlays": {"release_dates": ["2026-11-25T13:30:00Z"]},
        }
    ).encode()
    result = probe.bea_summary(raw, NOW)
    assert result["families"] == 2
    assert result["duplicate_dates"] == 1
    assert len(result["upcoming_gdp_pce"]) == 2
    assert all(
        e["scheduled_utc"] == "2026-11-25T13:30:00+00:00" for e in result["upcoming_gdp_pce"]
    )


@pytest.mark.parametrize("timestamp", ["2026-11-25", "2026-11-25T08:30:00", "not-a-date"])
def test_bea_never_invents_release_time_or_timezone(timestamp):
    raw = json.dumps({"GDP": {"release_dates": [timestamp]}}).encode()
    with pytest.raises(ValueError):
        probe.bea_summary(raw, NOW)
