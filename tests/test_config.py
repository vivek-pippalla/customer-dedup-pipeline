"""Configuration loader tests."""

from pathlib import Path

import pytest

from dedup.config import ConfigError, load_config


def test_default_config_loads() -> None:
    """The repository default TOML configuration is valid."""
    config = load_config()
    assert config["thresholds"]["auto"] == 0.90


def test_bad_weights_are_rejected(tmp_path: Path) -> None:
    """Weights that do not sum to one raise a clear error."""
    path = tmp_path / "bad_weights.toml"
    path.write_text("[weights]\na = 0.7\nb = 0.2\n[thresholds]\nreview = 0.5\nauto = 0.9\n[source_priority]\nCRM = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="sum to 1.0"):
        load_config(path)


def test_bad_thresholds_are_rejected(tmp_path: Path) -> None:
    """Thresholds outside their required ordering raise a clear error."""
    path = tmp_path / "bad_thresholds.toml"
    path.write_text("[weights]\na = 1.0\n[thresholds]\nreview = 0.9\nauto = 0.8\n[source_priority]\nCRM = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="0 < review < auto <= 1"):
        load_config(path)
