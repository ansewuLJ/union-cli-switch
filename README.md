# union-cli-switch

一个为老系统（如 glibc 版本过低）无法正常运行 cc-switch，以及无图形界面服务器也能运行的轻量级本地 AI coding CLI 配置管理 UI。

## 特性

- 适用于 Claude Code、Codex、Gemini CLI
- 多模型 Provider 管理
- 用户级 MCP 的新增、编辑、启用、停用、删除
- Skills 扫描和同步
- 技术路线极简，安装简单，通用性强：
  - Python + uv
  - Flask + Jinja2
  - 原生 HTML/CSS/少量 JS
  - 不依赖 Node / Tauri / Rust

## 运行

```bash
uv sync
uv run python main.py
```

默认监听 `http://127.0.0.1:8765`

指定 host 和 port：

```bash
uv run python main.py --host 0.0.0.0 --port 8080
```

## 开机自启

```bash
bash scripts/install-user-service.sh
```

服务管理：

```bash
systemctl --user status union-cli-switch.service   # 查看运行状态
systemctl --user stop union-cli-switch.service     # 立即停止服务
systemctl --user start union-cli-switch.service    # 启动服务
systemctl --user restart union-cli-switch.service  # 重启服务
systemctl --user disable union-cli-switch.service  # 取消开机自启
```

## 后台运行（不使用 systemd）

```bash
nohup uv run python main.py > ucs.log 2>&1 &
```

查看日志：

```bash
tail -f ucs.log
```

停止服务：

```bash
pkill -f "python main.py"
```

## 清除配置

需要重新配置，防止残留时使用：

```bash
rm -rf ~/.union-cli-switch
systemctl --user restart union-cli-switch.service
```

## 直接配置

预先编辑 `~/.union-cli-switch/state.json` 来设置提供商：

```json
{
  "codex": {
    "providers": [
      {
        "id": "my-codex",
        "name": "My API",
        "base_url": "https://api.example.com",
        "api_key": "sk-xxxx",
        "tool_config": {
          "model": "gpt-5.3-codex"
        }
      }
    ],
    "current_provider_id": "my-codex"
  },
  "claude": {
    "providers": [...],
    "current_provider_id": "xxx"
  },
  "gemini": {
    "providers": [...],
    "current_provider_id": "xxx"
  }
}
```

配置后刷新页面即可导入。
