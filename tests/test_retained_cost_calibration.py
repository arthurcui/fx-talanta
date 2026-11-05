import json

import pytest

from tools.qualification.retained_cost_calibration import assess, run


def snapshot():
    common = dict(
        symbol="EURUSD.",
        position_id=123456,
        volume=0.01,
        commission=-0.07,
        fee=-0.01,
        swap=0,
        price=1.234567,
    )
    return {
        "account": {"trade_mode": 0, "currency": "CAD", "login": "PRIVATE"},
        "deals": [
            dict(common, ticket=1, type=0, entry=0, time_msc=1000),
            dict(common, ticket=2, type=1, entry=1, time_msc=2500),
            {"type": 2, "profit": 10000},
        ],
    }


def test_actual_denominator_and_privacy():
    result = assess(snapshot())
    assert result["observed_commission_and_fee_cad_per_filled_lot"] == "-8"
    assert result["native_elapsed_ms_sorted"] == [1500]
    assert result["nontrade_deals_excluded"] == 1
    assert not result["broker_costs_qualified"]
    assert not result["replay_profile_created"]
    encoded = json.dumps(result)
    for secret in ("PRIVATE", "123456", "1.234567", "ticket", "position_id"):
        assert secret not in encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["deals"].pop(1),
        lambda d: d["deals"].append(d["deals"][0]),
        lambda d: d["deals"][1].update(time_msc=999),
        lambda d: d["deals"][1].update(type=0),
        lambda d: d["deals"][1].update(entry=2),
        lambda d: d["deals"][1].update(volume=0.02),
        lambda d: d["deals"][1].update(commission="NaN"),
        lambda d: d["account"].update(trade_mode=2),
        lambda d: d["account"].update(currency="USD"),
    ],
)
def test_reject_unsupported_evidence(mutation):
    data = snapshot()
    mutation(data)
    with pytest.raises(ValueError):
        assess(data)


def test_no_source_or_result_overwrite(tmp_path):
    source, output = tmp_path / "private.json", tmp_path / "result.json"
    source.write_text(json.dumps(snapshot()))
    before = source.read_bytes()
    run(source, output)
    assert source.read_bytes() == before
    result = output.read_bytes()
    with pytest.raises(FileExistsError):
        run(source, output)
    assert output.read_bytes() == result
