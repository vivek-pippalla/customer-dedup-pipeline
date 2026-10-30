"""Load and validate pipeline configuration."""

import math
import tomllib
from pathlib import Path


class ConfigError(ValueError):
    """Raised when pipeline configuration is missing or invalid."""


def load_config(path: str | Path | None = None) -> dict[str, object]:
    """Load TOML configuration and validate its decision settings."""
    config_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / "config" / "default.toml"
    try:
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot load configuration {config_path}: {error}") from error

    weights = config.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ConfigError("[weights] must contain numeric weights")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in weights.values()):
        raise ConfigError("[weights] values must be numeric")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ConfigError("[weights] values must sum to 1.0")

    thresholds = config.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ConfigError("[thresholds] must define review and auto")
    review = thresholds.get("review")
    auto = thresholds.get("auto")
    if (not isinstance(review, (int, float)) or isinstance(review, bool)
            or not isinstance(auto, (int, float)) or isinstance(auto, bool)
            or not 0 < review < auto <= 1):
        raise ConfigError("thresholds must satisfy 0 < review < auto <= 1")

    source_priority = config.get("source_priority")
    if not isinstance(source_priority, dict) or not source_priority:
        raise ConfigError("[source_priority] must contain at least one source")
    return config
