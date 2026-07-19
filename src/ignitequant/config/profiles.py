"""Load versioned Falcon decision profiles (Phase 6)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ignitequant.config.decision import (
    DecisionConfig,
    FactorConfig,
    RiskConfig,
    SignalConfig,
    SizingConfig,
    default_decision_config,
)

ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = ROOT / "configs" / "falcon"
DEFAULT_PROFILE = "falcon_legacy_v1"


def profiles_dir() -> Path:
    return PROFILES_DIR


def list_profiles() -> list[str]:
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


def load_profile_dict(profile_id: str) -> dict[str, Any]:
    path = PROFILES_DIR / f"{profile_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"profile not found: {profile_id} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


def decision_config_from_dict(data: dict[str, Any]) -> DecisionConfig:
    factor = FactorConfig(**{**asdict(FactorConfig()), **(data.get("factor") or {})})
    signal = SignalConfig(**{**asdict(SignalConfig()), **(data.get("signal") or {})})
    sizing_raw = {**asdict(SizingConfig()), **(data.get("sizing") or {})}
    lots = sizing_raw.get("lot_by_signal") or {1: 1, 2: 1, 3: 1}
    sizing_raw["lot_by_signal"] = {int(k): int(v) for k, v in dict(lots).items()}
    sizing = SizingConfig(**sizing_raw)
    risk = RiskConfig(**{**asdict(RiskConfig()), **(data.get("risk") or {})})
    return DecisionConfig(
        decision_mode=str(data.get("decision_mode") or "legacy_compatible"),
        entry_mode=str(data.get("entry_mode") or "intent_legacy"),
        config_version=str(data.get("config_version") or data.get("profile_id") or "unknown"),
        symbol=str(data.get("symbol") or "KQ.m@SHFE.au"),
        factor=factor,
        signal=signal,
        sizing=sizing,
        risk=risk,
    )


def load_decision_config(profile_id: str | None = None) -> DecisionConfig:
    """Load a named profile from configs/falcon/*.json.

    ``None`` / ``legacy`` / ``default`` / missing file for legacy → code default.
    """
    pid = (profile_id or "").strip()
    if not pid or pid in {"legacy", "default"}:
        pid = DEFAULT_PROFILE
    path = PROFILES_DIR / f"{pid}.json"
    if path.is_file():
        return decision_config_from_dict(load_profile_dict(pid))
    if pid == DEFAULT_PROFILE:
        return default_decision_config()
    raise FileNotFoundError(f"unknown profile: {pid}")


def active_profile_from_env() -> str:
    """FALCON_PROFILE selects candidate; unset → legacy production default."""
    return os.environ.get("FALCON_PROFILE", DEFAULT_PROFILE).strip() or DEFAULT_PROFILE


def load_active_decision_config() -> DecisionConfig:
    return load_decision_config(active_profile_from_env())
