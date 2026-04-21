from __future__ import annotations

import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import tomllib
import tomli_w

from union_cli_switch.state import APP_DIR, tool_paths


CODEX_DEFAULT_TEMPLATE: dict[str, Any] = {
    "suppress_unstable_features_warning": True,
    "developer_instructions": "请使用中文回答，优先准确、简洁；涉及改代码时先说明将修改什么。",
    "approval_policy": "never",
    "sandbox_mode": "danger-full-access",
    "model_provider": "custom",
    "model": "gpt-5.4",
    "model_reasoning_effort": "medium",
    "model_reasoning_summary": "detailed",
    "model_verbosity": "high",
    "model_providers": {
        "custom": {
            "name": "custom",
            "base_url": "",
            "wire_api": "responses",
            "requires_openai_auth": True,
        }
    },
    "features": {
        "shell_tool": True,
        "shell_snapshot": True,
        "apply_patch_freeform": True,
        "unified_exec": True,
        "undo": True,
        "multi_agent": True,
        "child_agents_md": True,
        "memories": True,
        "sqlite": True,
    },
    "memories": {
        "consolidation_model": "gpt-5.4",
        "extract_model": "gpt-5.4",
        "max_unused_days": 30,
        "max_rollout_age_days": 45,
        "max_raw_memories_for_consolidation": 512,
    },
    "shell_environment_policy": {
        "inherit": "all",
        "ignore_default_excludes": True,
    },
    "sandbox_workspace_write": {
        "network_access": True,
    },
    "tui": {
        "status_line": [
            "model-with-reasoning",
            "current-dir",
            "git-branch",
            "used-tokens",
            "codex-version",
        ]
    },
}

CODEX_TEMPLATE_PATH = APP_DIR / "codex-default-template.toml"


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_file(path: Path) -> str | None:
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.name}.{_timestamp()}.bak")
    shutil.copy2(path, backup_path)
    return str(backup_path)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text)


def write_json(path: Path, payload: dict[str, Any]) -> str | None:
    backup = backup_file(path)
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return backup


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return tomllib.loads(text)


def write_toml(path: Path, payload: dict[str, Any]) -> str | None:
    backup = backup_file(path)
    _atomic_write(path, tomli_w.dumps(payload))
    return backup


def default_codex_template_text() -> str:
    return tomli_w.dumps(CODEX_DEFAULT_TEMPLATE)


def load_codex_template_text() -> str:
    if CODEX_TEMPLATE_PATH.exists():
        text = CODEX_TEMPLATE_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text + ("\n" if not text.endswith("\n") else "")
    return default_codex_template_text()


def save_codex_template_text(text: str) -> None:
    parsed = tomllib.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("默认模板不是有效的 TOML 对象")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    normalized = text if text.endswith("\n") else text + "\n"
    _atomic_write(CODEX_TEMPLATE_PATH, normalized)


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key] = value
    return data


def write_env(path: Path, payload: dict[str, str]) -> str | None:
    backup = backup_file(path)
    lines = [f"{key}={value}" for key, value in payload.items()]
    _atomic_write(path, "\n".join(lines) + "\n")
    return backup


def _provider_slug(provider: dict[str, Any]) -> str:
    preferred = str(provider.get("name", "")).strip().lower().replace(" ", "-")
    cleaned = "".join(ch for ch in preferred if ch.isalnum() or ch in {"-", "_"})
    cleaned = cleaned.strip("-_")
    return cleaned or provider["id"].replace("-", "_")


def _codex_custom_template_block(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _provider_slug(provider),
        "base_url": provider["base_url"],
        "wire_api": provider["tool_config"].get("wire_api", "responses") or "responses",
        "requires_openai_auth": True,
    }


def apply_provider(
    tool: str,
    provider: dict[str, Any],
    mcp_servers: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> list[str]:
    options = options or {}
    if tool == "claude":
        return _apply_claude(provider, mcp_servers)
    if tool == "codex":
        return _apply_codex(provider, mcp_servers, options)
    return _apply_gemini(provider, mcp_servers)


def import_live_provider(tool: str) -> dict[str, Any]:
    providers = import_live_providers(tool)
    return providers[0] if providers else {
        "id": f"{tool}-live",
        "name": "Imported from live config",
        "base_url": "",
        "api_key": "",
        "tool_config": {},
    }


def import_live_providers(tool: str) -> list[dict[str, Any]]:
    if tool == "claude":
        return _import_claude_providers()
    if tool == "codex":
        return _import_codex_providers()
    return _import_gemini_providers()


def import_live_mcp(tool: str) -> list[dict[str, Any]]:
    if tool == "claude":
        path = tool_paths("claude")["mcp"]
        assert isinstance(path, Path)
        payload = read_json(path)
        servers = payload.get("mcpServers", {})
        if not isinstance(servers, dict):
            return []
        return [
            _normalize_mcp_server(server_id, spec) for server_id, spec in servers.items()
        ]
    if tool == "codex":
        path = tool_paths("codex")["provider"]
        assert isinstance(path, Path)
        payload = read_toml(path)
        servers = payload.get("mcp_servers", {})
        if not isinstance(servers, dict):
            return []
        return [
            _normalize_mcp_server(server_id, spec, codex_mode=True)
            for server_id, spec in servers.items()
        ]
    path = tool_paths("gemini")["settings"]
    assert isinstance(path, Path)
    payload = read_json(path)
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []
    return [_normalize_mcp_server(server_id, spec) for server_id, spec in servers.items()]


def _apply_claude(provider: dict[str, Any], mcp_servers: list[dict[str, Any]]) -> list[str]:
    paths = tool_paths("claude")
    settings_path = paths["provider"]
    mcp_path = paths["mcp"]
    assert isinstance(settings_path, Path)
    assert isinstance(mcp_path, Path)

    settings = read_json(settings_path)
    env = settings.get("env", {})
    if not isinstance(env, dict):
        env = {}
    env["ANTHROPIC_BASE_URL"] = provider["base_url"]
    env["ANTHROPIC_AUTH_TOKEN"] = provider["api_key"]
    for key, value in provider["tool_config"].items():
        if value:
            env[key] = value
        else:
            env.pop(key, None)
    settings["env"] = env
    write_json(settings_path, settings)

    mcp_payload = read_json(mcp_path)
    mcp_payload["mcpServers"] = {
        server["id"]: build_mcp_spec("claude", server)
        for server in mcp_servers
        if server.get("enabled", True)
    }
    write_json(mcp_path, mcp_payload)
    return [str(settings_path), str(mcp_path)]


def _import_claude_providers() -> list[dict[str, Any]]:
    settings_path = tool_paths("claude")["provider"]
    assert isinstance(settings_path, Path)
    settings = read_json(settings_path)
    env = settings.get("env", {})
    if not isinstance(env, dict):
        env = {}
    return [{
        "id": "claude-live",
        "name": "live",
        "base_url": str(env.get("ANTHROPIC_BASE_URL", "")),
        "api_key": str(env.get("ANTHROPIC_AUTH_TOKEN", env.get("ANTHROPIC_API_KEY", ""))),
        "tool_config": {
            "ANTHROPIC_MODEL": str(env.get("ANTHROPIC_MODEL", "")),
            "ANTHROPIC_DEFAULT_SONNET_MODEL": str(env.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")),
            "ANTHROPIC_DEFAULT_OPUS_MODEL": str(env.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "")),
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": str(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")),
            "CLAUDE_CODE_SUBAGENT_MODEL": str(env.get("CLAUDE_CODE_SUBAGENT_MODEL", "")),
        },
    }]


def _apply_codex(provider: dict[str, Any], mcp_servers: list[dict[str, Any]], options: dict[str, Any]) -> list[str]:
    paths = tool_paths("codex")
    config_path = paths["provider"]
    auth_path = paths["auth"]
    assert isinstance(config_path, Path)
    assert isinstance(auth_path, Path)

    write_mode = str(options.get("write_mode", "preserve") or "preserve")
    provider_slug = _provider_slug(provider)
    if write_mode == "template":
        config = tomllib.loads(load_codex_template_text())
        config["model_providers"] = {provider_slug: _codex_custom_template_block(provider)}
    else:
        config = read_toml(config_path)
        providers = config.get("model_providers", {})
        if not isinstance(providers, dict):
            providers = {}
        providers[provider_slug] = _codex_custom_template_block(provider)
        config["model_providers"] = providers
    config["model_provider"] = provider_slug
    config["model"] = provider["tool_config"].get("model", "")
    if write_mode == "template":
        config.pop("review_model", None)
    config["mcp_servers"] = {
        server["id"]: build_mcp_spec("codex", server)
        for server in mcp_servers
        if server.get("enabled", True)
    }
    write_toml(config_path, config)

    auth = read_json(auth_path)
    auth["OPENAI_API_KEY"] = provider["api_key"]
    write_json(auth_path, auth)
    return [str(config_path), str(auth_path)]


def _import_codex_providers() -> list[dict[str, Any]]:
    paths = tool_paths("codex")
    config_path = paths["provider"]
    auth_path = paths["auth"]
    assert isinstance(config_path, Path)
    assert isinstance(auth_path, Path)
    config = read_toml(config_path)
    auth = read_json(auth_path)
    providers = config.get("model_providers", {})
    current_slug = str(config.get("model_provider", "")).strip()
    provider_block = {}
    if isinstance(providers, dict):
        raw_block = providers.get("custom", {}) if "custom" in providers else providers.get(current_slug, {})
        provider_block = raw_block if isinstance(raw_block, dict) else {}
    api_key = str(auth.get("OPENAI_API_KEY", ""))
    return [{
        "id": "codex-live",
        "name": str(provider_block.get("name", "custom") or "custom"),
        "base_url": str(provider_block.get("base_url", "")),
        "api_key": api_key,
        "tool_config": {
            "model": str(config.get("model", "")),
            "wire_api": str(provider_block.get("wire_api", "responses")),
        },
    }]


def _apply_gemini(provider: dict[str, Any], mcp_servers: list[dict[str, Any]]) -> list[str]:
    paths = tool_paths("gemini")
    env_path = paths["provider"]
    settings_path = paths["settings"]
    assert isinstance(env_path, Path)
    assert isinstance(settings_path, Path)

    env_data = read_env(env_path)
    env_data["GOOGLE_GEMINI_BASE_URL"] = provider["base_url"]
    env_data["GEMINI_API_KEY"] = provider["api_key"]
    env_data["GEMINI_MODEL"] = provider["tool_config"].get("GEMINI_MODEL", "")
    write_env(env_path, env_data)

    settings = read_json(settings_path)
    settings["mcpServers"] = {
        server["id"]: build_mcp_spec("gemini", server)
        for server in mcp_servers
        if server.get("enabled", True)
    }
    write_json(settings_path, settings)
    return [str(env_path), str(settings_path)]


def _import_gemini_providers() -> list[dict[str, Any]]:
    paths = tool_paths("gemini")
    env_path = paths["provider"]
    assert isinstance(env_path, Path)
    env_data = read_env(env_path)
    return [{
        "id": "gemini-live",
        "name": "live",
        "base_url": env_data.get("GOOGLE_GEMINI_BASE_URL", ""),
        "api_key": env_data.get("GEMINI_API_KEY", ""),
        "tool_config": {
            "GEMINI_MODEL": env_data.get("GEMINI_MODEL", ""),
        },
    }]


def build_mcp_spec(tool: str, server: dict[str, Any]) -> dict[str, Any]:
    if server.get("transport") == "http":
        spec = {"type": "http", "url": server.get("url", "")}
    else:
        spec = {
            "type": "stdio",
            "command": server.get("command", ""),
            "args": server.get("args", []),
        }
    env = server.get("env", {})
    if env:
        spec["env"] = env
    if tool == "codex":
        spec.pop("type", None)
    return spec


def _normalize_mcp_server(server_id: str, spec: Any, codex_mode: bool = False) -> dict[str, Any]:
    spec = spec if isinstance(spec, dict) else {}
    transport = "http" if spec.get("type") == "http" or spec.get("url") else "stdio"
    if codex_mode and "type" not in spec and "url" not in spec:
        transport = "stdio"
    return {
        "id": server_id,
        "name": server_id,
        "transport": transport,
        "command": spec.get("command", ""),
        "args": spec.get("args", []),
        "url": spec.get("url", ""),
        "enabled": True,
        "env": spec.get("env", {}) if isinstance(spec.get("env", {}), dict) else {},
    }


def load_live_preview(tool: str) -> list[dict[str, str]]:
    previews: list[dict[str, str]] = []
    for label, path in tool_paths(tool).items():
        if path is None or label == "skills_dir":
            continue
        previews.append(
            {
                "label": label,
                "path": str(path),
                "content": mask_sensitive_text(path.read_text(encoding="utf-8")) if path.exists() else "(文件不存在)",
            }
        )
    return previews


def mask_sensitive_text(text: str) -> str:
    sensitive_markers = ("api_key", "auth_token", "token", "secret", "password", "key")
    masked_lines: list[str] = []
    for line in text.splitlines():
        lower = line.lower()
        if "=" in line:
            key, value = line.split("=", 1)
            if any(marker in key.lower() for marker in sensitive_markers):
                masked_lines.append(f"{key}=********")
                continue
        if ":" in line and any(marker in lower for marker in sensitive_markers):
            key, value = line.split(":", 1)
            if value.strip():
                masked_lines.append(f"{key}: \"********\"")
                continue
        masked_lines.append(line)
    return "\n".join(masked_lines)


def test_provider(tool: str, provider: dict[str, Any]) -> dict[str, Any]:
    start = time.time()
    try:
        if tool == "claude":
            model = provider["tool_config"].get("ANTHROPIC_MODEL", "")
            url = provider["base_url"].rstrip("/") + "/v1/messages"
            response = requests.post(
                url,
                headers={
                    "x-api-key": provider["api_key"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=20,
            )
        elif tool == "codex":
            model = provider["tool_config"].get("model", "")
            url = provider["base_url"].rstrip("/") + "/responses"
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {provider['api_key']}",
                    "content-type": "application/json",
                },
                json={"model": model, "input": "ping", "max_output_tokens": 16},
                timeout=20,
            )
        else:
            model = provider["tool_config"].get("GEMINI_MODEL", "")
            url = provider["base_url"].rstrip("/") + "/chat/completions"
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {provider['api_key']}",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 16,
                },
                timeout=20,
            )
        body = response.text.strip()
        short_body = body[:300] if body else ""
        return {
            "kind": "provider",
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "elapsed_ms": int((time.time() - start) * 1000),
            "message": short_body or f"HTTP {response.status_code}",
            "model": model,
        }
    except requests.RequestException as exc:
        return {
            "kind": "provider",
            "ok": False,
            "status_code": None,
            "elapsed_ms": int((time.time() - start) * 1000),
            "message": str(exc),
            "model": provider["tool_config"].get("ANTHROPIC_MODEL")
            or provider["tool_config"].get("model")
            or provider["tool_config"].get("GEMINI_MODEL", ""),
        }
