from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for

from union_cli_switch.adapters import (
    apply_provider,
    import_live_mcp,
    import_live_providers,
    import_live_provider,
    load_live_preview,
    load_codex_template_text,
    save_codex_template_text,
    test_provider,
)
from union_cli_switch.skills import import_skill, merge_scanned_skills, sync_skill
from union_cli_switch.state import (
    STATE_PATH,
    TOOLS,
    default_provider,
    delete_mcp_server,
    delete_provider,
    get_provider,
    load_state,
    save_state,
    tool_display_name,
    tool_paths,
    upsert_mcp_server,
    upsert_provider,
    upsert_skill,
)


BASE_DIR = Path(__file__).resolve().parent
PROVIDER_FIELDS = {
    "claude": [
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
    ],
    "codex": ["model", "wire_api"],
    "gemini": ["GEMINI_MODEL"],
}


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
    app.secret_key = "union-cli-switch-local"

    @app.get("/")
    def index():
        tool = request.args.get("tool", "claude")
        if tool not in TOOLS:
            tool = "claude"
        view = request.args.get("view", "providers")
        provider_id = request.args.get("provider_id")
        mcp_id = request.args.get("mcp_id")
        skill_id = request.args.get("skill_id")
        new_provider = request.args.get("new_provider") == "1"
        state = load_state()
        for item in TOOLS:
            _hydrate_from_live_if_needed(state, item)
        save_state(state)
        provider_draft = session.pop("provider_form_draft", None)
        selected_provider = None if new_provider else get_provider(state, tool, provider_id)
        selected_provider_form = deepcopy(selected_provider or default_provider(tool))
        if (
            view == "providers"
            and isinstance(provider_draft, dict)
            and provider_draft.get("tool") == tool
        ):
            selected_provider = None if provider_draft.get("new_provider") else selected_provider
            selected_provider_form = provider_draft["provider"]
            new_provider = bool(provider_draft.get("new_provider"))
        selected_mcp = _get_item(state[tool]["mcp"]["servers"], mcp_id) or _blank_mcp()
        selected_skill = _get_item(state[tool]["skills"], skill_id)
        return render_template(
            "index.html",
            state=state,
            tool=tool,
            tool_label=tool_display_name(tool),
            view=view,
            tools=TOOLS,
            provider_fields=PROVIDER_FIELDS,
            selected_provider=selected_provider,
            selected_provider_form=selected_provider_form,
            selected_mcp=selected_mcp,
            selected_skill=selected_skill,
            live_previews=load_live_preview(tool),
            codex_template_text=load_codex_template_text() if tool == "codex" else "",
            app_state_path=str(STATE_PATH),
            tool_file_paths={label: str(path) for label, path in tool_paths(tool).items() if path is not None},
        )

    @app.post("/codex/write-mode")
    def save_codex_write_mode():
        state = load_state()
        state["codex"]["write_mode"] = request.form.get("write_mode", "preserve")
        save_state(state)
        flash("已更新 Codex 写回模式", "success")
        return _redirect("codex", "providers")

    @app.post("/codex/template")
    def save_codex_template():
        template_text = request.form.get("template_text", "")
        try:
            save_codex_template_text(template_text)
        except Exception as exc:
            flash(f"默认模板保存失败: {exc}", "error")
            return _redirect("codex", "providers")
        flash("已保存 Codex 默认模板", "success")
        return _redirect("codex", "providers")

    @app.post("/providers/save")
    def save_provider():
        tool = request.form["tool"]
        state = load_state()
        provider = _provider_from_form(tool)
        saved = upsert_provider(state, tool, provider)
        if saved["id"] == state[tool]["current_provider_id"]:
            options = {"write_mode": state[tool].get("write_mode")} if tool == "codex" else None
            apply_provider(tool, saved, state[tool]["mcp"]["servers"], options=options)
        save_state(state)
        if saved["id"] == state[tool]["current_provider_id"]:
            flash(f"已保存并同步当前启用配置: {saved['name']}", "success")
        else:
            flash(f"已保存 {saved['name']}", "success")
        return _redirect(tool, "providers", provider_id=saved["id"])

    @app.post("/providers/delete")
    def remove_provider():
        tool = request.form["tool"]
        provider_id = request.form["provider_id"]
        state = load_state()
        delete_provider(state, tool, provider_id)
        save_state(state)
        flash("已删除提供商", "success")
        return _redirect(tool, "providers")

    @app.post("/providers/activate")
    def activate_provider():
        tool = request.form["tool"]
        provider_id = request.form["provider_id"]
        state = load_state()
        provider = get_provider(state, tool, provider_id)
        if provider is None:
            flash("找不到提供商", "error")
            return _redirect(tool, "providers")
        options = {"write_mode": state[tool].get("write_mode")} if tool == "codex" else None
        apply_provider(tool, provider, state[tool]["mcp"]["servers"], options=options)
        state[tool]["current_provider_id"] = provider_id
        save_state(state)
        flash("已启用该提供商并写入真实配置", "success")
        return _redirect(tool, "providers", provider_id=provider_id)

    @app.post("/providers/test")
    def run_test_provider():
        return _run_provider_test()

    @app.post("/mcp/save")
    def save_mcp():
        tool = request.form["tool"]
        state = load_state()
        server = {
            "id": request.form.get("server_id", "").strip(),
            "name": request.form["name"].strip(),
            "transport": request.form["transport"],
            "command": request.form.get("command", "").strip(),
            "args": [item for item in request.form.get("args", "").split() if item],
            "url": request.form.get("url", "").strip(),
            "enabled": request.form.get("enabled") == "on",
            "env": _parse_key_values(request.form.get("env_text", "")),
        }
        saved = upsert_mcp_server(state, tool, server)
        save_state(state)
        provider = get_provider(state, tool, state[tool]["current_provider_id"])
        if provider:
            options = {"write_mode": state[tool].get("write_mode")} if tool == "codex" else None
            apply_provider(tool, provider, state[tool]["mcp"]["servers"], options=options)
        flash("已保存 MCP 并同步到用户级配置", "success")
        return _redirect(tool, "mcp", mcp_id=saved["id"])

    @app.post("/mcp/delete")
    def remove_mcp():
        tool = request.form["tool"]
        server_id = request.form["server_id"]
        state = load_state()
        delete_mcp_server(state, tool, server_id)
        save_state(state)
        provider = get_provider(state, tool, state[tool]["current_provider_id"])
        if provider:
            options = {"write_mode": state[tool].get("write_mode")} if tool == "codex" else None
            apply_provider(tool, provider, state[tool]["mcp"]["servers"], options=options)
        flash("已删除 MCP 并同步", "success")
        return _redirect(tool, "mcp")

    @app.post("/mcp/toggle-enabled")
    def toggle_mcp_enabled():
        tool = request.form["tool"]
        server_id = request.form["server_id"]
        enabled = request.form.get("enabled") == "on"
        state = load_state()
        server = _get_item(state[tool]["mcp"]["servers"], server_id)
        if server is None:
            flash("找不到 MCP", "error")
            return _redirect(tool, "mcp")
        server["enabled"] = enabled
        save_state(state)
        provider = get_provider(state, tool, state[tool]["current_provider_id"])
        if provider:
            options = {"write_mode": state[tool].get("write_mode")} if tool == "codex" else None
            apply_provider(tool, provider, state[tool]["mcp"]["servers"], options=options)
        flash("已启用 MCP 并同步" if enabled else "已停用 MCP，但保留记录", "success")
        return _redirect(tool, "mcp", mcp_id=server_id)

    @app.post("/skills/scan")
    def scan_skills():
        tool = request.form["tool"]
        state = load_state()
        scanned = merge_scanned_skills(state, tool)
        save_state(state)
        flash(f"已扫描到 {len(scanned)} 个技能目录", "success")
        return _redirect(tool, "skills")

    @app.post("/skills/import")
    def add_skill():
        tool = request.form["tool"]
        source_path = request.form["source_path"].strip()
        state = load_state()
        skill = import_skill(tool, source_path)
        upsert_skill(state, tool, skill)
        save_state(state)
        flash("已导入技能并同步到工具目录", "success")
        return _redirect(tool, "skills", skill_id=skill["id"])

    @app.post("/skills/toggle")
    def toggle_skill():
        tool = request.form["tool"]
        skill_id = request.form["skill_id"]
        state = load_state()
        skill = _get_item(state[tool]["skills"], skill_id)
        if skill is None:
            flash("找不到技能", "error")
            return _redirect(tool, "skills")
        skill["enabled"] = request.form.get("enabled") == "on"
        synced = sync_skill(tool, skill)
        upsert_skill(state, tool, synced)
        save_state(state)
        flash("已同步技能状态", "success")
        return _redirect(tool, "skills", skill_id=skill_id)

    return app


def _hydrate_from_live_if_needed(state: dict, tool: str) -> None:
    if not state[tool]["providers"]:
        imported_providers = import_live_providers(tool)
        for imported_provider in imported_providers:
            upsert_provider(state, tool, imported_provider)
        if imported_providers:
            imported_current = import_live_provider(tool)
            state[tool]["current_provider_id"] = imported_current["id"]
    if not state[tool]["mcp"]["servers"]:
        state[tool]["mcp"]["servers"] = import_live_mcp(tool)
    if not state[tool]["skills"]:
        merge_scanned_skills(state, tool)


def _run_provider_test():
    tool = request.form["tool"]
    provider = _provider_from_form(tool)
    provider_id = provider.get("id") or request.form.get("provider_id", "").strip()
    is_new_provider = not provider_id
    if not provider_id:
        provider_id = f"{tool}-draft"
    provider["id"] = provider_id
    session["provider_form_draft"] = {
        "tool": tool,
        "new_provider": is_new_provider,
        "provider": provider,
    }
    result = test_provider(tool, provider)
    flash(("测试成功: " if result["ok"] else "测试失败: ") + result["message"], "success" if result["ok"] else "error")
    if is_new_provider:
        return _redirect(tool, "providers", new_provider=1)
    return _redirect(tool, "providers", provider_id=provider["id"])


def _provider_from_form(tool: str) -> dict:
    provider = {
        "id": request.form.get("provider_id", "").strip(),
        "name": request.form["name"].strip(),
        "base_url": request.form["base_url"].strip(),
        "api_key": request.form["api_key"].strip(),
        "tool_config": {},
    }
    for field in PROVIDER_FIELDS[tool]:
        if field == "requires_openai_auth":
            provider["tool_config"][field] = request.form.get(field) == "on"
        else:
            provider["tool_config"][field] = request.form.get(field, "").strip()
    return provider


def _get_item(items: list[dict], item_id: str | None) -> dict | None:
    if not item_id:
        return items[0] if items else None
    for item in items:
        if item["id"] == item_id:
            return item
    return None


def _blank_mcp() -> dict:
    return {
        "id": "",
        "name": "",
        "transport": "stdio",
        "command": "",
        "args": [],
        "url": "",
        "enabled": True,
        "env": {},
    }


def _parse_key_values(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _redirect(tool: str, view: str, **params):
    return redirect(url_for("index", tool=tool, view=view, **params))


def main() -> None:
    app = create_app()
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=8765, debug=False)
