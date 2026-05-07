"""Versioned policy snapshot management.

Saves a `CreditLimitConfig` to JSON with metadata, lists/loads versions,
and produces a structured diff between two versions for change-control review.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import CreditLimitConfig, load_config


def _config_to_dict(config: CreditLimitConfig) -> Dict[str, Any]:
    """Serialize a config dataclass tree into a plain dict."""
    if is_dataclass(config):
        return asdict(config)
    return dict(config)


def freeze_policy(
    config: CreditLimitConfig,
    version: str,
    policies_dir: Path,
    description: str = "",
    author: str = "system",
) -> Path:
    """Persist a policy version snapshot with metadata.

    Returns the path to the saved JSON file.
    """
    policies_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "version": version,
        "frozen_at": datetime.datetime.now().isoformat(),
        "author": author,
        "description": description,
        "config": _config_to_dict(config),
    }
    target = policies_dir / f"{version}.json"
    target.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True), encoding="utf-8")
    return target


def list_policies(policies_dir: Path) -> List[Dict[str, Any]]:
    """Return a manifest summary of all frozen policies in `policies_dir`."""
    if not policies_dir.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for path in sorted(policies_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries.append({
                "version": payload.get("version", path.stem),
                "frozen_at": payload.get("frozen_at"),
                "author": payload.get("author"),
                "description": payload.get("description", ""),
                "path": str(path),
            })
        except json.JSONDecodeError:
            continue
    return entries


def load_policy_snapshot(version_path: Path) -> Dict[str, Any]:
    """Load the raw snapshot dict (with metadata + config)."""
    return json.loads(version_path.read_text(encoding="utf-8"))


def load_policy_config(version_path: Path) -> CreditLimitConfig:
    """Load a snapshot and return a runnable CreditLimitConfig."""
    snapshot = load_policy_snapshot(version_path)
    config_dict = snapshot["config"]
    # Persist to temp and use load_config to apply schema-aware merging
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(config_dict, f)
        tmp_path = f.name
    return load_config(tmp_path)


def diff_policies(
    older_path: Path, newer_path: Path
) -> Dict[str, Any]:
    """Compute a structured diff between two policy snapshots.

    Returns a dict with keys: `changed`, `added`, `removed`. Each maps a dotted
    path (e.g. `risk_coefficient.matrix.high_risk.dti_low`) to a value or pair.
    """
    older = load_policy_snapshot(older_path)["config"]
    newer = load_policy_snapshot(newer_path)["config"]

    changed: Dict[str, Any] = {}
    added: Dict[str, Any] = {}
    removed: Dict[str, Any] = {}

    def walk(prefix: str, a: Any, b: Any) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            keys = set(a.keys()) | set(b.keys())
            for k in sorted(keys):
                child_prefix = f"{prefix}.{k}" if prefix else k
                if k not in a:
                    added[child_prefix] = b[k]
                elif k not in b:
                    removed[child_prefix] = a[k]
                else:
                    walk(child_prefix, a[k], b[k])
        else:
            if a != b:
                changed[prefix] = {"old": a, "new": b}

    walk("", older, newer)
    return {
        "older_version": load_policy_snapshot(older_path).get("version"),
        "newer_version": load_policy_snapshot(newer_path).get("version"),
        "changed": changed,
        "added": added,
        "removed": removed,
        "change_count": len(changed) + len(added) + len(removed),
    }
