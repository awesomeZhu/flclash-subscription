#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把服务器上的 selfhost-node.json 变成可直接导入 FLClash 的 YAML。

用法:
    python make_client.py                       # 读 ./selfhost-node.json
    python make_client.py --info ~/node.json --flag 🇯🇵 --out ~/Desktop/自建.yaml
    python make_client.py --only reality        # 只要 Reality 一个节点

同时会在终端打印 vless:// 和 hysteria2:// 分享链接（v2rayN / Shadowrocket 也能用）。
"""
import argparse
import json
import os
import sys

# ---------------------------------------------------------------- YAML 输出
def scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or any(c in s for c in ":#{}[],&*?|<>=!%@`'\"") or s.strip() != s or s.lower() in (
            "true", "false", "null", "yes", "no", "on", "off", "~"):
        return json.dumps(s, ensure_ascii=False)
    return s


def emit(lines, obj, indent):
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append("%s%s:" % (pad, k))
                emit(lines, v, indent + 1)
            elif isinstance(v, (dict, list)):
                lines.append("%s%s: %s" % (pad, k, "{}" if isinstance(v, dict) else "[]"))
            else:
                lines.append("%s%s: %s" % (pad, k, scalar(v)))
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                lines.append("%s-" % pad)
                emit(lines, v, indent + 1)
            else:
                lines.append("%s- %s" % (pad, scalar(v)))


def build(info, flag, only):
    srv = info["server"]
    sni = info.get("sni") or "www.microsoft.com"
    proxies, names = [], []

    if only in ("both", "reality") and info.get("reality"):
        r = info["reality"]
        name = "%s 自建 · Reality" % flag
        proxies.append({
            "name": name, "type": "vless", "server": srv, "port": int(r["port"]),
            "uuid": r["uuid"], "network": "tcp", "tls": True, "udp": True,
            "flow": "xtls-rprx-vision", "servername": sni, "client-fingerprint": "chrome",
            "reality-opts": {"public-key": r["public_key"], "short-id": r.get("short_id", "")},
        })
        names.append(name)

    if only in ("both", "hysteria2") and info.get("hysteria2"):
        h = info["hysteria2"]
        name = "%s 自建 · Hysteria2" % flag
        proxies.append({
            "name": name, "type": "hysteria2", "server": srv, "port": int(h["port"]),
            "password": h["password"], "sni": sni, "skip-cert-verify": True,
            "up": "50 Mbps", "down": "200 Mbps", "udp": True,
        })
        names.append(name)

    if not proxies:
        raise SystemExit("没有可用的节点信息（检查 --only 和 selfhost-node.json）")

    lines = [
        "# FLClash / Mihomo — 自建节点（VLESS-Reality + Hysteria2）",
        "# 服务器: %s   生成时间: %s" % (srv, info.get("created_at", "")),
        "# 仅自己使用，请勿分享给别人，避免被墙",
        "",
    ]
    cfg = {
        "mixed-port": 7890, "allow-lan": False, "mode": "rule", "log-level": "info",
        "ipv6": False, "unified-delay": True, "tcp-concurrent": True, "find-process-mode": "off",
        "profile": {"store-selected": True, "store-fake-ip": True},
        "sniffer": {"enable": True, "sniff": {"HTTP": {"ports": [80, "8080-8880"]},
                                              "TLS": {"ports": [443, 8443]},
                                              "QUIC": {"ports": [443, 8443]}}},
        "dns": {"enable": True, "listen": "0.0.0.0:1053", "ipv6": False,
                "enhanced-mode": "fake-ip", "fake-ip-range": "198.18.0.1/16",
                "fake-ip-filter": ["*.lan", "*.local", "*.localdomain", "*.home.arpa",
                                   "+.msftconnecttest.com", "+.msftncsi.com"],
                "default-nameserver": ["223.5.5.5", "119.29.29.29"],
                "nameserver": ["https://223.5.5.5/dns-query", "https://1.12.12.12/dns-query"],
                "proxy-server-nameserver": ["https://223.5.5.5/dns-query", "https://119.29.29.29/dns-query"],
                "nameserver-policy": {"geosite:cn": ["https://223.5.5.5/dns-query",
                                                     "https://1.12.12.12/dns-query"]}},
    }
    emit(lines, cfg, 0)

    lines.append("proxies:")
    for p in proxies:
        lines.append("-")
        emit(lines, p, 1)

    groups = [
        {"name": "🚀 节点选择", "type": "select",
         "proxies": ["♻️ 自动选择"] + names + ["🎯 全球直连"]},
        {"name": "♻️ 自动选择", "type": "url-test", "url": "https://www.gstatic.com/generate_204",
         "interval": 300, "tolerance": 50, "lazy": False, "proxies": names},
        {"name": "🎯 全球直连", "type": "select", "proxies": ["DIRECT"]},
        {"name": "🛑 广告拦截", "type": "select", "proxies": ["REJECT", "DIRECT"]},
    ]
    lines.append("proxy-groups:")
    for g in groups:
        lines.append("-")
        emit(lines, g, 1)

    rules = ["IP-CIDR,127.0.0.0/8,DIRECT,no-resolve", "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
             "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve", "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
             "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve", "IP-CIDR6,fc00::/7,DIRECT,no-resolve",
             "IP-CIDR6,fe80::/10,DIRECT,no-resolve",
             "DOMAIN-SUFFIX,local,DIRECT", "DOMAIN-SUFFIX,lan,DIRECT",
             "GEOSITE,private,DIRECT", "GEOSITE,cn,DIRECT", "GEOIP,CN,DIRECT",
             "MATCH,🚀 节点选择"]
    lines.append("rules:")
    for r in rules:
        lines.append("- %s" % scalar(r))
    return lines, proxies


def share_links(info, only):
    srv, sni = info["server"], info.get("sni") or "www.microsoft.com"
    out = []
    if only in ("both", "reality") and info.get("reality"):
        r = info["reality"]
        out.append("vless://%s@%s:%s?encryption=none&flow=xtls-rprx-vision&security=reality"
                   "&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp#selfhost-reality"
                   % (r["uuid"], srv, r["port"], sni, r["public_key"], r.get("short_id", "")))
    if only in ("both", "hysteria2") and info.get("hysteria2"):
        h = info["hysteria2"]
        out.append("hysteria2://%s@%s:%s/?sni=%s&insecure=1#selfhost-hysteria2"
                   % (h["password"], srv, h["port"], sni))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", default="selfhost-node.json")
    ap.add_argument("--out", default=os.path.join("out", "flclash-selfhost.yaml"))
    ap.add_argument("--flag", default="🏠", help="节点名前缀，例如 🇯🇵")
    ap.add_argument("--only", choices=["both", "reality", "hysteria2"], default="both")
    args = ap.parse_args()

    if not os.path.isfile(args.info):
        raise SystemExit("找不到 %s，先从服务器 scp 下来：\n"
                         "  scp root@<你的IP>:/root/selfhost-node.json ." % args.info)
    info = json.load(open(args.info, encoding="utf-8"))
    lines, proxies = build(info, args.flag, args.only)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("已生成: %s（%d 个节点）" % (args.out, len(proxies)))
    for p in proxies:
        print("  - %s  %s:%s" % (p["name"], p["server"], p["port"]))
    print("\n其他客户端可直接用的分享链接：")
    for ln in share_links(info, args.only):
        print("  " + ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
