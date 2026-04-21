## union-cli-switch

一个为了老系统也能跑起来而做的本地用户级配置管理器。

这版专门针对 `Claude Code`、`Codex`、`Gemini CLI` 三个工具做用户级配置管理：

- provider 管理
- 模型字段管理
- 用户级 MCP 的新增、编辑、启用、停用、删除
- skills 扫描和同步
- 当前表单整套测试

技术路线保持最简单：

- `Python + uv`
- `Flask + Jinja2`
- 原生 HTML/CSS/少量 JS
- 不依赖 Node / Tauri / Rust

## 运行

```bash
uv sync
uv run python main.py
```

默认监听 `http://127.0.0.1:8765`

## 用户级开机自启

```bash
bash scripts/install-user-service.sh
```

这个脚本会写入 `~/.config/systemd/user/union-cli-switch.service`，并直接执行 `systemctl --user enable --now`。

```bash
systemctl --user status union-cli-switch.service
systemctl --user stop union-cli-switch.service
systemctl --user disable union-cli-switch.service
```

## 数据位置

- 应用状态：`~/.union-cli-switch/state.json`
- Claude Code：
  - `~/.claude/settings.json`
  - `~/.claude.json`
- Codex：
  - `~/.codex/config.toml`
  - `~/.codex/auth.json`
- Gemini CLI：
  - `~/.gemini/.env`
  - `~/.gemini/settings.json`

## 当前能力

1. 按工具分别管理 provider
2. 直接写回用户级配置文件
3. 管理用户级 MCP，并支持启用、停用、删除
4. 扫描和同步各工具 skills 目录
5. 对当前表单做整套测试

## 后续建议

下一步适合继续补：

- 更细的字段校验
- 更友好的 live diff / backup UI
- 项目级 MCP
- 更完整的技能同步策略
