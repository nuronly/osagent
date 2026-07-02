# osAgent 上线部署指南

面向 **阿里云 ECS + Alibaba Cloud Linux 3** 的从零到上线完整流程。
配置：2 核 2G，40 GB ESSD，3 Mbps 带宽（本项目实测机器）。

---

## 架构一览

```
 用户浏览器
    │  HTTP :80  (basic_auth)
    ▼
┌──────────┐          ┌──────────────────────┐
│  Caddy   │  反代    │  uvicorn (osagent)   │
│  :80     │─────────▶│  127.0.0.1:8765       │
│          │          │  systemd 守护         │
└──────────┘          └──────────────────────┘
                              │
                              ▼
                        /var/lib/osagent/data
                        （facts / reports / repos）
```

**为什么这么设计**：
- **Caddy 独占 :80/:443**：反代到内部 8765，未来加域名 → HTTPS 只改一行
- **basic_auth + API Key 双保险**：Caddy 层挡 UI 流量，FastAPI 层挡 API 写操作
- **osagent 只绑 127.0.0.1**：外网打不进来，只能走 Caddy
- **systemd 守护**：崩溃自动拉起，日志走 journald

---

## 一键部署（推荐）

```bash
ssh root@47.100.80.178      # 换成你的公网 IP

# 下载并执行部署脚本
curl -fsSL https://raw.githubusercontent.com/nuronly/osagent/main/deploy/deploy.sh -o /tmp/deploy.sh
sudo bash /tmp/deploy.sh
```

脚本会完成：
1. 装 dnf 依赖（python3、git、Caddy、firewalld）
2. 建服务账号 `osagent`
3. clone 代码到 `/opt/osagent`
4. 建 venv 装依赖
5. 加 2GB swap（2G 内存机器强烈建议）
6. 写 systemd unit + Caddyfile
7. 开防火墙 80/443
8. `systemctl enable --now osagent caddy`

执行完 → 访问 `http://<你的公网IP>` 即可看到仪表盘（basic_auth 提示登录）。

---

## 首次上线 3 步微调

### 步骤 1：填 API Key

```bash
sudo vim /etc/osagent/osagent.env
```

改这两行：
```
DEEPSEEK_API_KEY=sk-你的真实key
OSAGENT_API_KEY=$(openssl rand -hex 32)   # 手动生成一个 64 位随机串填进去
```

### 步骤 2：设 basic_auth 密码

```bash
# 生成密码 hash（会问你两遍明文密码）
sudo caddy hash-password
# 输出类似：$2a$14$abc123...

sudo vim /etc/caddy/Caddyfile
# 找到 basic_auth 块，替换 $2a$14$REPLACE_WITH_HASH... 为上面输出
```

### 步骤 3：重启

```bash
sudo systemctl restart osagent caddy
sudo systemctl status osagent caddy
```

访问 `http://<你的公网IP>` → 弹出登录框 → 输入 admin / 你的明文密码 → 进入仪表盘。

---

## 阿里云控制台还要做的事

### 安全组放行端口

**网络与安全 → 安全组 → 配置规则 → 入方向**：

| 端口范围 | 协议 | 授权对象 | 说明 |
|----------|------|----------|------|
| 22       | TCP  | 你的家庭 IP/32（推荐）或 0.0.0.0/0 | SSH |
| 80       | TCP  | 0.0.0.0/0 | HTTP（必开）|
| 443      | TCP  | 0.0.0.0/0 | HTTPS（有域名后启用）|

⚠️ **不要**再开 8765，那是内部端口。

### （可选）备案域名

大陆机器上 HTTPS 需要域名，且域名必须**备案**。备案未通过前用 IP + HTTP 就行。

有域名后：
```bash
sudo vim /etc/caddy/Caddyfile
# 把  :80 {   改成  yourdomain.com {
sudo systemctl reload caddy
# Caddy 会自动申请 Let's Encrypt 证书，1 分钟后 https:// 就通了
```

---

## 日常运维

### 查日志
```bash
sudo journalctl -u osagent -f            # osAgent 实时日志
sudo journalctl -u caddy -f              # Caddy 访问 / 错误
sudo tail -f /var/log/caddy/access.log   # JSON 访问日志
```

### 重启 / 停止
```bash
sudo systemctl restart osagent
sudo systemctl stop osagent
sudo systemctl reload caddy              # 改完 Caddyfile 优雅重载
```

### 升级代码
```bash
sudo -u osagent git -C /opt/osagent pull
sudo -u osagent /opt/osagent/.venv/bin/pip install -q -e /opt/osagent
sudo systemctl restart osagent
```

或者直接重跑 `deploy.sh`（幂等）。

### 磁盘使用
```bash
du -sh /var/lib/osagent/data/*
# 40G 系统盘，主要占用是 repos/；facts/reports 只占几百 MB
```

**磁盘吃紧时**：
- 删过期 repo：`osagent manifest delete-repo <id> --purge`
- 或挂云盘到 `/var/lib/osagent/data`（推荐 SSD 云盘 100G）

---

## 安全清单

| 项 | 状态 | 说明 |
|---|---|---|
| ✅ 后端只绑 127.0.0.1 | systemd unit 已固定 | 外网只能走 Caddy |
| ✅ Caddy basic_auth | Caddyfile 已启用 | UI 层拦截 |
| ✅ FastAPI API Key | `src/osagent/web/auth.py` | 写接口二次拦截 |
| ✅ firewalld | 只开 80/443/22 | 8765 对外不通 |
| ⚠️ SSH 密码登录 | 建议改密钥登录 | `PermitRootLogin prohibit-password` |
| ⚠️ fail2ban | 未装 | 高防需求时手动装 |
| ⚠️ 备份 | 未配 | 重要数据手动 `rsync data/facts data/reports` 下来 |

---

## 排错

### `osagent` 服务起不来
```bash
sudo journalctl -u osagent -n 100 --no-pager
```
常见原因：
- `DEEPSEEK_API_KEY` 没填 → LLM 初始化虽不会崩，但功能不可用
- Python 版本 < 3.9 → 用 `dnf install python3.11` 换新版
- 依赖没装完 → 手动 `sudo -u osagent /opt/osagent/.venv/bin/pip install -e /opt/osagent`

### Caddy 401 一直登不上
- 用 `caddy hash-password` 重新生成 hash，注意 `$` 在 Caddyfile 里不需要转义
- `sudo systemctl reload caddy` 让新配置生效

### 首页能开，但 API 调用返回 401
- 检查前端有没有把 API Key 传上：F12 → Network 看请求头
- 或临时把 `OSAGENT_API_KEY` 注释掉，重启 osagent（回到无鉴权模式）

### OOM（内存爆）
```bash
dmesg | grep -i "killed process"
```
- 确认 swap 挂上：`swapon --show`
- 降 `GIT_CONCURRENCY=1`
- 分批分析，别一次 `analyzer analyze` 大量仓库

---

## 卸载

```bash
sudo systemctl disable --now osagent caddy
sudo rm -f /etc/systemd/system/osagent.service /etc/caddy/Caddyfile
sudo rm -rf /opt/osagent /var/lib/osagent /var/log/osagent /etc/osagent
sudo userdel osagent
sudo dnf -y remove caddy
```
