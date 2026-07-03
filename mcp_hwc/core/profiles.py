from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

_EXCLUDED_SUFFIXES = {"example", "bak", "sample", "template"}


def list_profiles() -> dict[str, object]:
    base_dir = _base_dir()
    active_file = _active_file(base_dir)
    entries = []
    for name, path in sorted(_discover(base_dir).items()):
        entries.append(
            {
                "name": name,
                "file": str(path),
                "active": path == active_file,
            }
        )
    active = next((e["name"] for e in entries if e["active"]), None)
    return {"profiles": entries, "active": active}


def switch_profile(name: str) -> dict[str, object]:
    base_dir = _base_dir()
    available = _discover(base_dir)
    path = available.get(name)
    if path is None:
        known = ", ".join(sorted(available)) or "none"
        raise ValueError(f"Unknown profile '{name}'. Available profiles: {known}")

    values = {
        key: value
        for key, value in dotenv_values(path).items()
        if key is not None and value is not None
    }
    missing = [key for key in ("HWC_AK", "HWC_SK") if not values.get(key)]
    if missing:
        raise ValueError(
            f"Profile '{name}' ({path}) is missing required keys: {', '.join(missing)}"
        )

    # Stale process-env keys from a previous account would shadow the profile
    # file (process env wins in config resolution), so drop them all first.
    for key in [k for k in os.environ if k.startswith("HWC_")]:
        del os.environ[key]
    os.environ.update(values)
    os.environ["MCP_HWC_ENV_FILE"] = str(path)

    return {
        "profile": name,
        "file": str(path),
        "access_key": _mask(values["HWC_AK"]),
        "region": values.get("HWC_REGION"),
    }


def _base_dir() -> Path:
    configured = os.getenv("MCP_HWC_ENV_FILE")
    if configured:
        return Path(configured).parent
    discovered = find_dotenv(usecwd=True)
    if discovered:
        return Path(discovered).parent
    return Path.cwd()


def _active_file(base_dir: Path) -> Path | None:
    configured = os.getenv("MCP_HWC_ENV_FILE")
    if configured:
        return Path(configured)
    default = base_dir / ".env"
    return default if default.exists() else None


def _discover(base_dir: Path) -> dict[str, Path]:
    profiles: dict[str, Path] = {}
    default = base_dir / ".env"
    if default.exists():
        profiles["default"] = default
    for path in base_dir.glob(".env.*"):
        suffix = path.name.removeprefix(".env.")
        if not suffix or suffix.lower() in _EXCLUDED_SUFFIXES:
            continue
        profiles[suffix] = path
    return profiles


def _mask(value: str) -> str:
    return value[:4] + "***" if len(value) > 4 else "***"
