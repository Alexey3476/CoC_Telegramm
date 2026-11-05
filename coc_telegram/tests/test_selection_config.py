from pathlib import Path
import yaml


ROOT = Path(__file__).parents[2]


def test_selection_weights_total_one_hundred():
    cfg = yaml.safe_load((ROOT / "coc_telegram/config.yaml").read_text())
    options = cfg["options"]
    assert cfg["version"] == "0.2.1"
    assert sum(options[key] for key in (
        "score_weight_strength", "score_weight_attendance",
        "score_weight_attack", "score_weight_preference")) == 100
    assert options["max_accounts_per_owner"] == 1
