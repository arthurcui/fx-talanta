import json
import shutil
from pathlib import Path

from fx_talanta.input_readiness import main, report

ROOT = Path(__file__).resolve().parents[1]


def test_closeout_does_not_promote_failed_m1_evidence():
    result = report(ROOT)
    assert result["bounded_m2_closeout_verified"]
    assert not result["m1_qualified"] and not result["execution_enabled"]
    assert not result["brokers"]["forex"]["quote_readiness_accepted"]
    assert not result["brokers"]["cmc"]["collector_accepted"]
    assert len(result["required_groups"]) == 16
    assert result["provider_campaign"]["scheduled_release_checks"][0]["state"] == "ON_TIME"
    jolts = result["provider_campaign"]["sources"]["bls_jolts"]
    assert jolts["publication_to_receipt_seconds"]["max"] > 360
    assert not jolts["sampled_delivery_passed"]


def test_missing_evidence_and_output_overwrite_fail_closed(tmp_path, capsys):
    assert main(["--repository", str(tmp_path)]) == 2
    output = tmp_path / "report.json"
    assert main(["--repository", str(ROOT), "--output", str(output)]) == 0
    original = output.read_bytes()
    assert main(["--repository", str(ROOT), "--output", str(output)]) == 2
    assert output.read_bytes() == original


def test_duplicate_requirement_cannot_hide_missing_family(tmp_path):
    for relative in report(ROOT)["evidence_hashes"]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    path = tmp_path / "docs/provider-inventory.json"
    inventory = json.loads(path.read_text())
    inventory["requirements"][1] = inventory["requirements"][0]
    path.write_text(json.dumps(inventory))
    assert main(["--repository", str(tmp_path)]) == 2
