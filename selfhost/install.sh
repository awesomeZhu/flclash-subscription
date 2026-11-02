#!/usr/bin/env bash
# =============================================================================
# 自建代理一键部署：VLESS-Reality (TCP 443) + Hysteria2 (UDP 8443)
# 适用：Ubuntu 22.04/24.04、Debian 12（Oracle Cloud / GCP / AWS / Hetzner 均可）
# 用法：sudo bash install.sh [--sni www.microsoft.com] [--hy2-port 8443]
#                              [--reality-port 443] [--force]
# 产物：/root/selfhost-node.json（客户端用）、本机直接打印 YAML 片段
# 特点：幂等（重复跑不会换密钥）、失败即退出、只依赖官方安装脚本
# =============================================================================
set -euo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
info()  { echo "${GREEN}[+]${NC} $*"; }
warn()  { echo "${YELLOW}[!]${NC} $*"; }
die()   { echo "${RED}[x]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------- 参数
SNI="${SNI:-www.microsoft.com}"
HY2_PORT=8443
REALITY_PORT=443
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sni) SNI="$2"; shift 2;;
    --hy2-port) HY2_PORT="$2"; shift 2;;
    --reality-port) REALITY_PORT="$2"; shift 2;;
    --force) FORCE=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) die "未知参数: $1";;
  esac
done

# ---------------------------------------------------------------- 前置检查
[[ $EUID -eq 0 ]] || die "请用 root 运行：sudo bash install.sh"
[[ -f /etc/os-release ]] || die "无法识别系统"
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) warn "未在 Ubuntu/Debian 上验证过（当前 ${ID:-unknown}），继续但可能失败";;
esac

PUBLIC_IP="${PUBLIC_IP:-}"
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP=$(curl -4 -fsS --max-time 8 https://api.ipify.org || curl -4 -fsS --max-time 8 https://ifconfig.me || true)
fi
[[ -n "$PUBLIC_IP" ]] || die "获取公网 IP 失败，请手动指定：PUBLIC_IP=1.2.3.4 sudo bash install.sh"
info "公网 IP: ${BOLD}${PUBLIC_IP}${NC}   系统: ${PRETTY_NAME:-$ID}  架构: $(uname -m)"

info "安装基础依赖…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates openssl jq uuid-runtime net-tools >/dev/null

# ---------------------------------------------------------------- 内核优化
info "开启 BBR + UDP 缓冲（对 Hysteria2 提速明显）…"
cat >/etc/sysctl.d/99-proxy.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.core.rmem_max=16777216
net.core.wmem_max=16777216
EOF
sysctl --system >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 状态（幂等）
STATE=/root/.selfhost-state.env
if [[ -f "$STATE" && $FORCE -eq 0 ]]; then
  # shellcheck disable=SC1090
  . "$STATE"
  info "复用已有配置（想重新生成密钥用 --force）"
else
  UUID=$(uuidgen)
  HY2_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-28)
  SHORT_ID=$(openssl rand -hex 8)
  PRIVATE_KEY=""; PUBLIC_KEY=""
fi

# ---------------------------------------------------------------- Xray
if ! command -v xray >/dev/null 2>&1; then
  info "安装 Xray-core…"
  curl -fsSL -o /tmp/xray-install.sh https://github.com/XTLS/Xray-install/raw/main/install-release.sh \
    || die "下载 Xray 安装脚本失败（检查能否访问 github.com）"
  bash /tmp/xray-install.sh install >/dev/null 2>&1 || die "Xray 安装失败"
  rm -f /tmp/xray-install.sh
fi
command -v xray >/dev/null || die "xray 未就位"

if [[ -z "${PRIVATE_KEY:-}" ]]; then
  X_OUT=$(xray x25519)
  PRIVATE_KEY=$(printf '%s\n' "$X_OUT" | grep -iE 'private' | head -1 | sed 's/.*: *//' | tr -d ' \r')
  PUBLIC_KEY=$(printf '%s\n'  "$X_OUT" | grep -iE 'public|password' | head -1 | sed 's/.*: *//' | tr -d ' \r')
  # 兜底：老版本只按行输出，取第一行当私钥、第二行当公钥
  if [[ ${#PRIVATE_KEY} -ne 43 ]]; then
    PRIVATE_KEY=$(printf '%s\n' "$X_OUT" | sed -n '1p' | sed 's/.*: *//' | tr -d ' \r')
    PUBLIC_KEY=$(printf '%s\n'  "$X_OUT" | sed -n '2p' | sed 's/.*: *//' | tr -d ' \r')
  fi
  [[ ${#PRIVATE_KEY} -eq 43 && ${#PUBLIC_KEY} -eq 43 ]] \
    || die "解析 x25519 密钥失败，请手动执行 xray x25519 查看输出格式"
fi
info "Reality 密钥已就绪（公钥 ${PUBLIC_KEY:0:8}…）"

cat >/usr/local/etc/xray/config.json <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "listen": "0.0.0.0",
      "port": ${REALITY_PORT},
      "protocol": "vless",
      "settings": {
        "clients": [ { "id": "${UUID}", "flow": "xtls-rprx-vision", "email": "selfhost" } ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "${SNI}:443",
          "xver": 0,
          "serverNames": [ "${SNI}" ],
          "privateKey": "${PRIVATE_KEY}",
          "shortIds": [ "${SHORT_ID}" ]
        }
      },
      "sniffing": { "enabled": true, "destOverride": [ "http", "tls", "quic" ] }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "rules": [ { "type": "field", "protocol": [ "bittorrent" ], "outboundTag": "block" } ]
  }
}
EOF
xray -test -config /usr/local/etc/xray/config.json >/dev/null 2>&1 || die "Xray 配置自检失败"
systemctl enable --now xray >/dev/null 2>&1 || true
systemctl restart xray
sleep 1
systemctl is-active --quiet xray || die "Xray 没起来，看 journalctl -u xray -n 40"
info "VLESS-Reality 已启动：${REALITY_PORT}/tcp"

# ---------------------------------------------------------------- Hysteria2
if ! command -v hysteria >/dev/null 2>&1; then
  info "安装 Hysteria2…"
  curl -fsSL -o /tmp/hy2-install.sh https://get.hy2.sh/ || die "下载 Hysteria2 安装脚本失败"
  bash /tmp/hy2-install.sh >/dev/null 2>&1 || die "Hysteria2 安装失败"
  rm -f /tmp/hy2-install.sh
fi
command -v hysteria >/dev/null || die "hysteria 未就位"

mkdir -p /etc/hysteria
if [[ ! -f /etc/hysteria/cert.pem ]]; then
  info "生成自签证书（客户端需跳过证书校验）…"
  openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout /etc/hysteria/key.pem -out /etc/hysteria/cert.pem \
    -subj "/CN=${SNI}" -days 3650 >/dev/null 2>&1
fi
cat >/etc/hysteria/config.yaml <<EOF
listen: :${HY2_PORT}

tls:
  cert: /etc/hysteria/cert.pem
  key: /etc/hysteria/key.pem

auth:
  type: password
  password: ${HY2_PASSWORD}

masquerade:
  type: proxy
  proxy:
    url: https://news.ycombinator.com/
    rewriteHost: true

ignoreClientBandwidth: false
EOF
chown -R hysteria:hysteria /etc/hysteria 2>/dev/null || true
chmod 640 /etc/hysteria/key.pem 2>/dev/null || true
systemctl enable --now hysteria-server >/dev/null 2>&1 || true
systemctl restart hysteria-server 2>/dev/null || systemctl restart hysteria 2>/dev/null || true
sleep 1
systemctl is-active --quiet hysteria-server 2>/dev/null || systemctl is-active --quiet hysteria 2>/dev/null \
  || die "Hysteria2 没起来，看 journalctl -u hysteria-server -n 40"
info "Hysteria2 已启动：${HY2_PORT}/udp"

# ---------------------------------------------------------------- 防火墙
info "放行端口…"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
  ufw allow "${REALITY_PORT}"/tcp >/dev/null 2>&1 || true
  ufw allow "${HY2_PORT}"/udp >/dev/null 2>&1 || true
  info "已添加 ufw 规则"
fi
# Oracle Cloud 的镜像默认用 iptables 挡着，必须自己插规则
iptables -C INPUT -p tcp --dport "${REALITY_PORT}" -j ACCEPT 2>/dev/null \
  || iptables -I INPUT 1 -p tcp --dport "${REALITY_PORT}" -j ACCEPT 2>/dev/null || warn "iptables 加规则失败（可能已放行）"
iptables -C INPUT -p udp --dport "${HY2_PORT}" -j ACCEPT 2>/dev/null \
  || iptables -I INPUT 1 -p udp --dport "${HY2_PORT}" -j ACCEPT 2>/dev/null || true
if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save >/dev/null 2>&1 || true
elif [[ -d /etc/iptables ]]; then
  iptables-save >/etc/iptables/rules.v4 2>/dev/null || true
fi

# ---------------------------------------------------------------- 端口自检
sleep 1
ss -lntup 2>/dev/null | grep -q ":${REALITY_PORT} " || warn "没看到 ${REALITY_PORT}/tcp 在监听，请检查 Xray 日志"
ss -lntup 2>/dev/null | grep -q ":${HY2_PORT} " || warn "没看到 ${HY2_PORT}/udp 在监听，请检查 Hysteria2 日志"

# ---------------------------------------------------------------- 落盘
cat >"$STATE" <<EOF
UUID=${UUID}
HY2_PASSWORD=${HY2_PASSWORD}
PRIVATE_KEY=${PRIVATE_KEY}
PUBLIC_KEY=${PUBLIC_KEY}
SHORT_ID=${SHORT_ID}
SNI=${SNI}
HY2_PORT=${HY2_PORT}
REALITY_PORT=${REALITY_PORT}
EOF
chmod 600 "$STATE"

cat >/root/selfhost-node.json <<EOF
{
  "server": "${PUBLIC_IP}",
  "sni": "${SNI}",
  "reality": { "port": ${REALITY_PORT}, "uuid": "${UUID}", "public_key": "${PUBLIC_KEY}", "short_id": "${SHORT_ID}" },
  "hysteria2": { "port": ${HY2_PORT}, "password": "${HY2_PASSWORD}" },
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# ---------------------------------------------------------------- 输出
cat <<EOF

${BOLD}================ 部署完成 ================${NC}
 服务器: ${PUBLIC_IP}
 Reality: ${REALITY_PORT}/tcp   uuid=${UUID}
           sni=${SNI}  sid=${SHORT_ID}
           公钥=${PUBLIC_KEY}
 Hysteria2: ${HY2_PORT}/udp  password=${HY2_PASSWORD}

 客户端参数已存到: /root/selfhost-node.json
 把它拷回本地，运行 make_client.py 即可生成 FLClash 配置：
   scp root@${PUBLIC_IP}:/root/selfhost-node.json .

${YELLOW}如果是 Oracle Cloud，务必去控制台把安全列表（Security List / NSG）的入站放行：${NC}
   ${REALITY_PORT}/TCP 和 ${HY2_PORT}/UDP，来源 0.0.0.0/0
 否则外网连不上（这是新手最常踩的坑）。

 自检命令：
   systemctl status xray --no-pager
   systemctl status hysteria-server --no-pager
   ss -lntup | grep -E '(${REALITY_PORT}|${HY2_PORT})'
EOF
