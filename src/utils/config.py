"""Configuration loading.

All tunable settings (categories, thresholds, FX rates, scenarios) are stored in
``config/settings.yaml`` so that a finance user can change them without editing
Python code. This module loads that file once and exposes typed helpers.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CONFIG_PATH: Path = PROJECT_ROOT / "config" / "settings.yaml"


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> dict[str, Any]:
    """Load and cache the YAML configuration."""
    cfg_path = Path(path) if path else CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def resolve_path(relative: str) -> Path:
    """Resolve a path from the config relative to the project root."""
    p = Path(relative)
    return p if p.is_absolute() else PROJECT_ROOT / p


def database_path() -> Path:
    return resolve_path(load_config()["paths"]["database"])


def sample_dir() -> Path:
    return resolve_path(load_config()["paths"]["sample_dir"])


def templates_dir() -> Path:
    return resolve_path(load_config()["paths"]["templates_dir"])


def categories() -> list[str]:
    """Recognised (budgeted) expense categories, in display order."""
    return list(load_config()["categories"])


def uncategorised_label() -> str:
    return load_config()["uncategorised_label"]


def transaction_statuses() -> list[str]:
    return list(load_config()["transaction_statuses"])


def base_currency() -> str:
    return load_config()["base_currency"]


def fx_rates() -> dict[str, float]:
    """Units of foreign currency per one unit of base currency."""
    return {k: float(v) for k, v in load_config()["fx_rates"].items()}


def default_project_id() -> str:
    return load_config()["default_project_id"]


def illustrative_label() -> str:
    return load_config()["app"]["illustrative_label"]


def status_rules() -> dict[str, float]:
    return dict(load_config()["status_rules"])


def anomaly_rules() -> dict[str, float]:
    return dict(load_config()["anomaly_rules"])


def reporting_rules() -> dict[str, float]:
    return dict(load_config()["reporting"])


def scenarios() -> dict[str, dict[str, Any]]:
    return dict(load_config()["scenarios"])
