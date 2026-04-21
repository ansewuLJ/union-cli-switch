#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="${HOME}/.config/systemd/user"
SERVICE_PATH="${SERVICE_DIR}/union-cli-switch.service"

mkdir -p "${SERVICE_DIR}"

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=union-cli-switch local web manager
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/.venv/bin/python ${PROJECT_DIR}/main.py
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now union-cli-switch.service

echo "已安装并启动用户级服务: union-cli-switch.service"
echo "访问地址: http://127.0.0.1:8765"
echo "查看状态: systemctl --user status union-cli-switch.service"
echo "停止服务: systemctl --user stop union-cli-switch.service"
echo "禁用自启: systemctl --user disable union-cli-switch.service"
