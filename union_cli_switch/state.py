from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


APP_DIR = Path.home() / ".union-cli-switch"
STATE_PATH = APP_DIR / "state.json"

TOOLS = ("claude", "codex", "gemini")


def tool_display_name(tool: str) -> str:
    return {
        "claude": "Claude Code",
        "codex": "Codex",
        "gemini": "Gemini CLI",
    }[tool]


def tool_paths(tool: str) -> dict[str, Path | None]:
    home = Path.home()
    if tool == "claude":
        return {
            "provider": home / ".claude" / "settings.json",
            "mcp": home / ".claude.json",
            "skills_dir": home / ".claude" / "skills",
        }
    if tool == "codex":
        return {
            "provider": home / ".codex" / "config.toml",
            "auth": home / ".codex" / "auth.json",
            "mcp": home / ".codex" / "config.toml",
            "skills_dir": home / ".codex" / "skills",
        }
    return {
        "provider": home / ".gemini" / ".env",
        "settings": home / ".gemini" / "settings.json",
        "mcp": home / ".gemini" / "settings.json",
        "skills_dir": None,
    }


def default_provider(tool: str) -> dict[str, Any]:
    provider_id = f"{tool}-{uuid.uuid4().hex[:8]}"
    base = {
        "id": provider_id,
        "name": f"{tool_display_name(tool)} Provider",
        "base_url": "",
        "api_key": "",
        "tool_config": {},
    }
    if tool == "claude":
        base["tool_config"] = {
            "ANTHROPIC_MODEL": "",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "",
            "CLAUDE_CODE_SUBAGENT_MODEL": "",
        }
    elif tool == "codex":
        base["tool_config"] = {
            "model": "",
            "wire_api": "responses",
        }
    else:
        base["tool_config"] = {
            "GEMINI_MODEL": "",
        }
    return base


def default_tool_state(tool: str) -> dict[str, Any]:
    state = {
        "providers": [],
        "current_provider_id": "",
        "mcp": {"servers": []},
        "skills": [],
        "last_test_results": [],
    }
    if tool == "codex":
        state["write_mode"] = "preserve"
    return state


def default_state() -> dict[str, Any]:
    return {
        "claude": default_tool_state("claude"),
        "codex": default_tool_state("codex"),
        "gemini": default_tool_state("gemini"),
    }


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def save_state(state: dict[str, Any]) -> None:
    ensure_app_dir()
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_state() -> dict[str, Any]:
    ensure_app_dir()
    if not STATE_PATH.exists():
        state = default_state()
        save_state(state)
        return state
    text = STATE_PATH.read_text(encoding="utf-8").strip()
    if not text:
        state = default_state()
        save_state(state)
        return state
    raw = json.loads(text)
    state = default_state()
    for tool in TOOLS:
        tool_state = raw.get(tool, {})
        state[tool]["providers"] = tool_state.get("providers", [])
        state[tool]["current_provider_id"] = tool_state.get("current_provider_id", "")
        state[tool]["mcp"] = tool_state.get("mcp", {"servers": []})
        state[tool]["skills"] = tool_state.get("skills", [])
        state[tool]["last_test_results"] = tool_state.get("last_test_results", [])
        if tool == "codex":
            state[tool]["write_mode"] = tool_state.get("write_mode", "preserve")
    return state


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or uuid.uuid4().hex[:8]


def upsert_provider(
    state: dict[str, Any],
    tool: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    provider = deepcopy(provider)
    if not provider.get("id"):
        provider["id"] = f"{tool}-{slugify(provider['name'])}-{uuid.uuid4().hex[:6]}"
    providers = state[tool]["providers"]
    for index, existing in enumerate(providers):
        if existing["id"] == provider["id"]:
            providers[index] = provider
            break
    else:
        providers.append(provider)
    if not state[tool]["current_provider_id"]:
        state[tool]["current_provider_id"] = provider["id"]
    return provider


def delete_provider(state: dict[str, Any], tool: str, provider_id: str) -> None:
    providers = [provider for provider in state[tool]["providers"] if provider["id"] != provider_id]
    state[tool]["providers"] = providers
    if state[tool]["current_provider_id"] == provider_id:
        state[tool]["current_provider_id"] = providers[0]["id"] if providers else ""


def get_provider(state: dict[str, Any], tool: str, provider_id: str | None) -> dict[str, Any] | None:
    if provider_id:
        for provider in state[tool]["providers"]:
            if provider["id"] == provider_id:
                return provider
    current_id = state[tool]["current_provider_id"]
    for provider in state[tool]["providers"]:
        if provider["id"] == current_id:
            return provider
    return state[tool]["providers"][0] if state[tool]["providers"] else None


def append_test_result(
    state: dict[str, Any],
    tool: str,
    result: dict[str, Any],
) -> None:
    items = state[tool]["last_test_results"]
    items.insert(0, result)
    del items[8:]


def upsert_mcp_server(state: dict[str, Any], tool: str, server: dict[str, Any]) -> dict[str, Any]:
    server = deepcopy(server)
    if not server.get("id"):
        server["id"] = slugify(server["name"])
    servers = state[tool]["mcp"]["servers"]
    for index, existing in enumerate(servers):
        if existing["id"] == server["id"]:
            servers[index] = server
            break
    else:
        servers.append(server)
    return server


def delete_mcp_server(state: dict[str, Any], tool: str, server_id: str) -> None:
    state[tool]["mcp"]["servers"] = [
        server for server in state[tool]["mcp"]["servers"] if server["id"] != server_id
    ]


def upsert_skill(state: dict[str, Any], tool: str, skill: dict[str, Any]) -> dict[str, Any]:
    skill = deepcopy(skill)
    if not skill.get("id"):
        skill["id"] = slugify(skill["name"])
    skills = state[tool]["skills"]
    for index, existing in enumerate(skills):
        if existing["id"] == skill["id"]:
            skills[index] = skill
            break
    else:
        skills.append(skill)
    return skill
