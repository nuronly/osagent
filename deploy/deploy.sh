#!/usr/bin/env bash
# osAgent 一键部署脚本（Alibaba Cloud Linux 3 / RHEL 系）
# 用法（root 执行）：
#   curl -fsSL https://raw.githubusercontent.com/nuronly/osagent/main/deploy/deploy.sh -o deploy.sh
#   sudo bash deploy.sh
#
# 幂等：可以多次执行，已装的会跳过。
# 假设：项目将被 clone 到 /opt/osagent；服务用户 osagent；数据 /var/lib/osagent/data
set -euo pipefail

# ============ 可配置项 ============
APP_USER="osagent"
APP_HOME="/opt/osagent"
DATA_DIR="/var/lib/osagent/data"
LOG_DIR="/var/log/osagent"
REPO_URL="${REPO_URL:-https://github.com/nuronly/osagent.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# 颜色
C_R='\033[1;31m'; C_G='\033[1;32m'; C_Y='\033[1;33m'; C_B='\033[1;34m'; C_0='\033[0m'
log()  { echo -e "${C_G}[+]${C_0} $*"; }
warn() { echo -e "${C_Y}[!]${C_0} $*"; }
err()  { echo -e "${C_R}[x]${C_0} $*" >&2; }

# ============ 前置检查 ============
[[ $EUID -eq 0 ]] || { err "请用 root（或 sudo）运行"; exit 1; }

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  log "OS: $PRETTY_NAME"
else
  warn "读不到 /etc/os-release，继续按 RHEL 系走"
fi

# ============ 1. 依赖安装 ============
log "1/8  安装系统依赖（dnf）"
dnf -y install epel-release || true
dnf -y install \
    python3 python3-pip python3-devel \
    git curl wget tar gcc make \
    firewalld chrony

# Caddy —— 官方 COPR 源
if ! command -v caddy >/dev/null 2>&1; then
  log "     安装 Caddy（反向代理 + 自动 HTTPS）"
  dnf -y copr enable @caddy/caddy || true
  dnf -y install caddy
else
  log "     Caddy 已装：$(caddy version | head -n1)"
fi

# ============ 2. 服务账号 ============
log "2/8  准备服务账号 $APP_USER"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_HOME" --shell /sbin/nologin "$APP_USER"
fi

# ============ 3. 目录 ============
log "3/8  准备目录"
mkdir -p "$APP_HOME" "$DATA_DIR" "$LOG_DIR" /etc/osagent
chown -R "$APP_USER:$APP_USER" "$DATA_DIR" "$LOG_DIR"

# ============ 4. 拉代码 ============
log "4/8  同步代码 $REPO_URL ($REPO_BRANCH)"
if [[ -d "$APP_HOME/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_HOME" fetch --all --prune
  sudo -u "$APP_USER" git -C "$APP_HOME" reset --hard "origin/$REPO_BRANCH"
else
  # 空目录情况，先把 $APP_HOME 交给 osagent 用户再 clone
  chown -R "$APP_USER:$APP_USER" "$APP_HOME"
  sudo -u "$APP_USER" git clone --branch "$REPO_BRANCH" --depth 1 "$REPO_URL" "$APP_HOME"
fi

# ============ 5. Python venv + 依赖 ============
log "5/8  创建 venv 并安装依赖"
if [[ ! -d "$APP_HOME/.venv" ]]; then
  sudo -u "$APP_USER" "$PYTHON_BIN" -m venv "$APP_HOME/.venv"
fi
sudo -u "$APP_USER" "$APP_HOME/.venv/bin/pip" install -q --upgrade pip setuptools wheel
sudo -u "$APP_USER" "$APP_HOME/.venv/bin/pip" install -q -e "$APP_HOME"

# ============ 6. Swap（2G 内存机器强烈建议）============
log "6/8  检查 swap"
if [[ $(swapon --show | wc -l) -eq 0 ]]; then
  log "     未检测到 swap，创建 2G swap 文件"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  # 调低 swappiness，减少不必要换出
  sysctl -w vm.swappiness=10 >/dev/null
  grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness = 10' >> /etc/sysctl.conf
else
  log "     已存在 swap，跳过"
fi

# ============ 7. 配置文件 ============
log "7/8  配置文件"
# /etc/osagent/osagent.env（systemd EnvironmentFile）
if [[ ! -f /etc/osagent/osagent.env ]]; then
  cp "$APP_HOME/deploy/osagent.env.example" /etc/osagent/osagent.env
  chmod 640 /etc/osagent/osagent.env
  chown root:"$APP_USER" /etc/osagent/osagent.env
  warn "     生成 /etc/osagent/osagent.env（模板）"
  warn "     请手动编辑填入 DEEPSEEK_API_KEY / OSAGENT_API_KEY 后重启服务"
else
  log "     已存在 /etc/osagent/osagent.env，未覆盖"
fi

# systemd unit
install -m 0644 "$APP_HOME/deploy/osagent.service" /etc/systemd/system/osagent.service

# Caddyfile
if [[ ! -f /etc/caddy/Caddyfile.osagent ]]; then
  install -m 0644 "$APP_HOME/deploy/Caddyfile" /etc/caddy/Caddyfile
  warn "     已写入 /etc/caddy/Caddyfile（默认 :80 → 127.0.0.1:8765，含 basic_auth 占位）"
  warn "     生产环境请编辑，改域名 / basic_auth 密码"
else
  log "     已存在 /etc/caddy/Caddyfile.osagent，未覆盖（旧配置保留）"
fi

# ============ 8. 防火墙 + 启动服务 ============
log "8/8  启动服务"
systemctl enable --now firewalld
firewall-cmd --permanent --add-service=http --add-service=https >/dev/null
firewall-cmd --reload >/dev/null

systemctl daemon-reload
systemctl enable --now osagent
systemctl enable --now caddy
systemctl restart caddy

sleep 2
if systemctl is-active --quiet osagent; then
  log "osagent  ✅ running"
else
  err "osagent  ❌  journalctl -u osagent -n 100"
fi
if systemctl is-active --quiet caddy; then
  log "caddy    ✅ running"
else
  err "caddy    ❌  journalctl -u caddy -n 100"
fi

echo
echo -e "${C_B}==================== 部署完成 ====================${C_0}"
PUB_IP=$(curl -s --max-time 3 https://api.ipify.org || echo "<公网IP>")
echo "访问入口："
echo "  http://$PUB_IP           （Caddy 反代到 osagent:8765）"
echo "  http://$PUB_IP/api/health"
echo
echo "常用命令："
echo "  systemctl status osagent"
echo "  journalctl -u osagent -f"
echo "  systemctl restart osagent"
echo
echo "首次上线 TODO："
echo "  1. vim /etc/osagent/osagent.env     # 填 DEEPSEEK_API_KEY / OSAGENT_API_KEY"
echo "  2. vim /etc/caddy/Caddyfile         # 改域名、basic_auth 密码"
echo "  3. systemctl restart osagent caddy"
echo -e "${C_B}=================================================${C_0}"
