#!/usr/bin/env bash
# osAgent 一键部署（大陆机器加速版）
# 用 gh-proxy 镜像绕过 GitHub 直连问题
# 目标机器：Alibaba Cloud Linux 3 / 2G 内存
set -euo pipefail

APP_USER="osagent"
APP_HOME="/opt/osagent"
DATA_DIR="/var/lib/osagent/data"
LOG_DIR="/var/log/osagent"
GH_MIRROR="${GH_MIRROR:-https://gh-proxy.com/https://github.com}"
REPO_PATH="nuronly/osagent"
REPO_BRANCH="${REPO_BRANCH:-main}"

C_R='\033[1;31m'; C_G='\033[1;32m'; C_Y='\033[1;33m'; C_B='\033[1;34m'; C_0='\033[0m'
log()  { echo -e "${C_G}[+]${C_0} $*"; }
warn() { echo -e "${C_Y}[!]${C_0} $*"; }
err()  { echo -e "${C_R}[x]${C_0} $*" >&2; }

[[ $EUID -eq 0 ]] || { err "请用 root（或 sudo）运行"; exit 1; }

# ============ 1. pip 换清华源（大陆机器加速）============
log "1/9  配置 pip 清华源"
cat > /etc/pip.conf << 'EOF'
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF

# ============ 2. 依赖 ============
log "2/9  安装系统依赖（dnf）"
dnf -y install epel-release || true
dnf -y install python3 python3-pip python3-devel git curl wget tar gcc make firewalld chrony

# Caddy
if ! command -v caddy >/dev/null 2>&1; then
  log "     安装 Caddy"
  dnf -y copr enable @caddy/caddy || true
  dnf -y install caddy || {
    warn "COPR 装 Caddy 失败，用官方二进制"
    ARCH=$(uname -m); [[ "$ARCH" == "x86_64" ]] && ARCH="amd64"; [[ "$ARCH" == "aarch64" ]] && ARCH="arm64"
    curl -fsSL "https://gh-proxy.com/https://github.com/caddyserver/caddy/releases/download/v2.7.6/caddy_2.7.6_linux_${ARCH}.tar.gz" -o /tmp/caddy.tgz
    tar -xzf /tmp/caddy.tgz -C /usr/local/bin caddy
    chmod +x /usr/local/bin/caddy
    ln -sf /usr/local/bin/caddy /usr/bin/caddy
    # 建 caddy service（COPR 版会自带，二进制版需要手写）
    id caddy >/dev/null 2>&1 || useradd --system --home-dir /var/lib/caddy --shell /sbin/nologin caddy
    mkdir -p /etc/caddy /var/lib/caddy /var/log/caddy
    chown -R caddy:caddy /var/lib/caddy /var/log/caddy
    cat > /etc/systemd/system/caddy.service << 'CADDYEOF'
[Unit]
Description=Caddy
Documentation=https://caddyserver.com/docs/
After=network.target network-online.target
Requires=network-online.target

[Service]
Type=notify
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile --force
TimeoutStopSec=5s
LimitNOFILE=1048576
LimitNPROC=512
PrivateTmp=true
ProtectSystem=full
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
CADDYEOF
  }
fi

# ============ 3. 服务账号 ============
log "3/9  服务账号 $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_HOME" --shell /sbin/nologin "$APP_USER"

# ============ 4. 目录 ============
log "4/9  准备目录"
mkdir -p "$APP_HOME" "$DATA_DIR" "$LOG_DIR" /etc/osagent /etc/caddy /var/log/caddy
chown -R "$APP_USER:$APP_USER" "$DATA_DIR" "$LOG_DIR" "$APP_HOME"

# ============ 5. 拉代码（走镜像）============
log "5/9  同步代码（镜像: $GH_MIRROR/$REPO_PATH）"
if [[ -d "$APP_HOME/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_HOME" fetch --all --prune || warn "fetch 失败（可能网络问题），用现有代码继续"
  sudo -u "$APP_USER" git -C "$APP_HOME" reset --hard "origin/$REPO_BRANCH" || warn "reset 失败，用现有代码继续"
else
  # 先清空目录（保留权限）
  rm -rf "$APP_HOME"/{,.}* 2>/dev/null || true
  sudo -u "$APP_USER" git clone --depth 1 --branch "$REPO_BRANCH" \
      "$GH_MIRROR/$REPO_PATH.git" "$APP_HOME"
fi
ls "$APP_HOME/deploy/" >/dev/null 2>&1 || { err "代码 clone 失败，deploy/ 目录不存在"; exit 1; }

# ============ 6. venv + pip ============
log "6/9  venv + pip install（会花 1-3 分钟）"
[[ -d "$APP_HOME/.venv" ]] || sudo -u "$APP_USER" python3 -m venv "$APP_HOME/.venv"
sudo -u "$APP_USER" "$APP_HOME/.venv/bin/pip" install -q --upgrade pip setuptools wheel
sudo -u "$APP_USER" "$APP_HOME/.venv/bin/pip" install -q -e "$APP_HOME"

# ============ 7. Swap（2G 内存机器强建）============
log "7/9  检查 swap"
if [[ $(swapon --show | wc -l) -eq 0 ]]; then
  log "     创建 2G swap"
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10 >/dev/null
  grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness = 10' >> /etc/sysctl.conf
else
  log "     已有 swap，跳过"
fi

# ============ 8. 配置 ============
log "8/9  配置文件"
[[ -f /etc/osagent/osagent.env ]] || {
  cp "$APP_HOME/deploy/osagent.env.example" /etc/osagent/osagent.env
  chmod 640 /etc/osagent/osagent.env
  chown root:"$APP_USER" /etc/osagent/osagent.env
  warn "     写入 /etc/osagent/osagent.env（默认模板，需手动填 DEEPSEEK_API_KEY）"
}
install -m 0644 "$APP_HOME/deploy/osagent.service" /etc/systemd/system/osagent.service
[[ -f /etc/caddy/Caddyfile ]] || install -m 0644 "$APP_HOME/deploy/Caddyfile" /etc/caddy/Caddyfile

# ============ 9. 防火墙 + 启动 ============
log "9/9  防火墙 + 启动服务"
systemctl enable --now firewalld
firewall-cmd --permanent --add-service=http --add-service=https >/dev/null
firewall-cmd --reload >/dev/null

systemctl daemon-reload
systemctl enable --now osagent
systemctl enable --now caddy
systemctl restart caddy || warn "caddy 启动失败（可能 Caddyfile basic_auth 未替换 hash），先跳过；填完密码 hash 再 systemctl restart caddy"

sleep 2
echo
echo -e "${C_B}==================== 部署完成 ====================${C_0}"
if systemctl is-active --quiet osagent; then
  log "osagent  ✅ running (127.0.0.1:8765)"
else
  err "osagent  ❌  查日志: journalctl -u osagent -n 100 --no-pager"
fi
if systemctl is-active --quiet caddy; then
  log "caddy    ✅ running (:80)"
else
  err "caddy    ❌  查日志: journalctl -u caddy -n 50 --no-pager"
fi

PUB_IP=$(curl -s --max-time 3 https://api.ipify.org || echo "47.100.80.178")
echo
echo "访问入口："
echo "  http://$PUB_IP           （首页会弹 basic_auth）"
echo "  http://$PUB_IP/api/health"
echo
echo "首次上线 3 步微调："
echo "  ① vim /etc/osagent/osagent.env"
echo "     - DEEPSEEK_API_KEY=你的真实 key"
echo "     - OSAGENT_API_KEY=\$(openssl rand -hex 32) 手动生成填入"
echo "  ② 生成 basic_auth 密码"
echo "     caddy hash-password"
echo "     vim /etc/caddy/Caddyfile   # 把 \$2a\$14\$REPLACE_WITH_HASH... 替换成上面输出"
echo "  ③ systemctl restart osagent caddy"
echo -e "${C_B}=================================================${C_0}"
