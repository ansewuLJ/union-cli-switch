from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from union_cli_switch.state import tool_paths, upsert_skill


def _skills_dir(tool: str) -> Path | None:
    path = tool_paths(tool)["skills_dir"]
    return path if isinstance(path, Path) else None


def scan_live_skills(tool: str) -> list[dict[str, Any]]:
    skills_dir = _skills_dir(tool)
    if skills_dir is None:
        return []
    skills_dir.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, Any]] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        result.append(
            {
                "id": child.name,
                "name": child.name,
                "source_path": str(child),
                "live_path": str(child),
                "enabled": True,
                "managed": False,
                "exists": True,
            }
        )
    return result


def merge_scanned_skills(state: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    scanned = scan_live_skills(tool)
    for skill in scanned:
        upsert_skill(state, tool, skill)
    return scanned


def import_skill(tool: str, source_path: str) -> dict[str, Any]:
    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Skill path not found: {source}")
    skills_dir = _skills_dir(tool)
    if skills_dir is None:
        raise ValueError(f"{tool} does not expose a stable skills directory")
    skills_dir.mkdir(parents=True, exist_ok=True)
    destination = skills_dir / source.name
    if destination.exists():
        raise FileExistsError(f"Skill already exists: {destination}")
    try:
        os.symlink(source, destination, target_is_directory=True)
        sync_mode = "symlink"
    except OSError:
        shutil.copytree(source, destination)
        sync_mode = "copy"
    return {
        "id": source.name,
        "name": source.name,
        "source_path": str(source),
        "live_path": str(destination),
        "enabled": True,
        "managed": True,
        "sync_mode": sync_mode,
        "exists": True,
    }


def sync_skill(tool: str, skill: dict[str, Any]) -> dict[str, Any]:
    skills_dir = _skills_dir(tool)
    if skills_dir is None:
        raise ValueError(f"{tool} does not expose a stable skills directory")
    skills_dir.mkdir(parents=True, exist_ok=True)
    source = Path(skill["source_path"]).expanduser()
    destination = skills_dir / skill["name"]
    if skill.get("enabled", True):
        if destination.exists():
            return {**skill, "live_path": str(destination), "exists": True}
        try:
            os.symlink(source, destination, target_is_directory=True)
            mode = "symlink"
        except OSError:
            shutil.copytree(source, destination)
            mode = "copy"
        return {
            **skill,
            "live_path": str(destination),
            "exists": True,
            "sync_mode": mode,
        }
    if skill.get("managed", False) and destination.exists():
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        else:
            shutil.rmtree(destination)
    return {**skill, "live_path": str(destination), "exists": destination.exists()}
