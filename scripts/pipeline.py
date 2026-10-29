#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一站式流水线：抓取 GitHub 免费节点 -> 清洗去重 -> Mihomo 内核校验 -> 真实测速 -> 归属地 -> 生成 FLClash 配置

用法:
    python scripts/pipeline.py                     # 默认输出 out/flclash-free-nodes.yaml
    python scripts/pipeline.py --out out/x.yaml --workers 128 --rounds 2

退出码: 0 成功 / 1 失败（无可用节点或内核不可用）
"""
import argparse
import glob
import gzip
import io
import json
import os
import platform
import random
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) clash/mihomo"}

# ---------------------------------------------------------------- 节点源
# 只收 Clash / Mihomo 格式的公开订阅；失效的源会自动跳过，不影响整体
SOURCES = [
    ("ermaozi/get_subscribe", "main", "subscribe/clash.yml"),
    ("ermaozi01/free_clash_vpn", "main", "subscribe/clash.yml"),
    ("anaer/Sub", "main", "clash.yaml"),
    ("ripaojiedian/freenode", "main", "clash"),
    ("peasoft/NoMoreWalls", "master", "list.yml"),
    ("mahdibland/ShadowsocksAggregator", "master", "Eternity.yml"),
    ("cysk003/freeSub", "main", "clash.yaml"),
    ("ts-sf/fly", "main", "clash"),
    ("free18/v2ray", "main", "c.yaml"),
    ("vveg26/get_proxy", "main", "dist/clash.config.yaml"),
    ("mfuu/v2ray", "master", "clash.yaml"),
    ("sunmiao4458/free-proxy-airport", "main", "clash.yaml"),
    ("Flik6/Free-Node", "main", "clash.yaml"),
    ("lanzm/MetaFetch", "main", "output/clash.yaml"),
]

ALLOWED_TYPES = {"ss", "ssr", "vmess", "vless", "trojan", "hysteria", "hysteria2", "tuic",
                 "anytls", "http", "socks5", "snell", "wireguard", "ssh", "mieru"}
BAD_SERVER_PREFIX = ("127.", "0.0.0.0", "localhost", "::1", "10.", "192.168.", "172.16.", "172.17.",
                     "172.18.", "172.19.", "172.2", "172.30.", "172.31.", "169.254.", "example.com")
BAD_NAME = re.compile(r"防范|剩余|流量|到期|过期|官网|订阅|重置|Expire|群组|Telegram|飞机")
ISO2 = {"HK", "TW", "JP", "SG", "US", "KR", "GB", "DE", "NL", "FR", "IT", "RU", "CA", "CH", "SE",
        "CZ", "LV", "AT", "IE", "FI", "NO", "DK", "PL", "ES", "PT", "RO", "BG", "HU", "SK", "UA",
        "LT", "EE", "BE", "LU", "MD", "RS", "HR", "GR", "TR", "CY", "MT", "IS", "AL", "BR", "MX",
        "AR", "CL", "AU", "NZ", "MY", "PH", "TH", "VN", "ID", "IN", "AE", "IL", "ZA", "EG", "NG",
        "KE", "KZ", "IR", "PK", "BD", "LK"}


def log(msg):
    print(msg, flush=True)


def http_get(url, timeout=40, retries=2, backoff=1.5):
    """带重试和指数退避的下载；失败时抛出带状态码的异常"""
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries:
                time.sleep(backoff ** i)
    raise last


def mirrors_for(repo, branch, path):
    """同一份文件的多条下载通道：官方 raw -> jsDelivr -> ghfast 代理"""
    return [
        "https://raw.githubusercontent.com/%s/%s/%s" % (repo, branch, path),
        "https://cdn.jsdelivr.net/gh/%s@%s/%s" % (repo, branch, path),
        "https://ghfast.top/https://raw.githubusercontent.com/%s/%s/%s" % (repo, branch, path),
    ]


# ---------------------------------------------------------------- 1. 抓取
def fetch_sources():
    os.makedirs(CACHE, exist_ok=True)
    for old in glob.glob(os.path.join(CACHE, "*.yaml")):
        os.remove(old)
    ok, failed = [], []
    t0 = time.time()
    for repo, branch, path in SOURCES:
        tag = (repo + "__" + path).replace("/", "_")
        errs = []
        done = False
        for url in mirrors_for(repo, branch, path):
            host = urllib.parse.urlparse(url).netloc
            try:
                data = http_get(url, timeout=25, retries=1)
            except Exception as e:  # noqa: BLE001
                errs.append("%s -> %s" % (host, str(e)[:40]))
                continue
            txt = data.decode("utf-8", "ignore")
            if not re.search(r"^\s*proxies\s*:", txt, re.M):
                errs.append("%s -> 不是 Clash 格式" % host)
                continue
            with open(os.path.join(CACHE, tag + ".yaml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(txt)
            log("  [ok]   %-38s %6.0f KB  (%s)" % (repo, len(data) / 1024, host))
            ok.append((repo, len(data)))
            done = True
            break
        if not done:
            failed.append((repo, errs))
            log("  [skip] %-38s %s" % (repo, " | ".join(errs)[:120]))
    log("  抓取完成: 成功 %d / %d，用时 %.1fs" % (len(ok), len(SOURCES), time.time() - t0))
    return ok, failed


# ---------------------------------------------------------------- 2. 清洗 / 去重
def normalize(proxies, src):
    kept = []
    for p in proxies:
        if not isinstance(p, dict):
            continue
        if str(p.get("type", "")).lower() not in ALLOWED_TYPES:
            continue
        srv = str(p.get("server", "")).strip()
        if not srv or srv.startswith(BAD_SERVER_PREFIX):
            continue
        try:
            port = int(p.get("port", 0))
        except (TypeError, ValueError):
            continue
        if not 0 < port < 65536:
            continue
        if BAD_NAME.search(str(p.get("name", ""))):
            continue
        bad = False
        for k in ("uuid", "password", "auth", "auth-str", "private-key"):
            v = str(p.get(k, "") or "")
            if "88888888" in v or v == "00000000-0000-0000-0000-000000000000":
                bad = True
        if bad:
            continue
        q = {k: v for k, v in p.items() if not str(k).startswith("__")}
        q["__src"] = src
        kept.append(q)
    return kept


def dedupe_key(p):
    parts = [str(p.get("type", "")).lower(), str(p.get("server", "")).lower().strip(), str(p.get("port", ""))]
    for k in ("uuid", "password", "cipher", "network", "servername", "sni", "flow", "obfs",
              "obfs-password", "username", "auth-str", "plugin", "ws-opts", "grpc-opts",
              "reality-opts", "http-opts"):
        v = p.get(k)
        if v in (None, "", {}):
            continue
        parts.append("%s=%s" % (k, json.dumps(v, sort_keys=True, ensure_ascii=False)
                                if isinstance(v, (dict, list)) else v))
    return "|".join(parts)


# ---------------------------------------------------------------- 3. mihomo
def mihomo_path():
    exe = "mihomo.exe" if os.name == "nt" else "mihomo"
    p = os.path.join(CACHE, "bin", exe)
    if os.path.isfile(p):
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tag = None
    try:
        j = json.loads(http_get("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest").decode())
        tag = j["tag_name"]
    except Exception:  # noqa: BLE001
        req = urllib.request.Request("https://github.com/MetaCubeX/mihomo/releases/latest", headers=UA)
        tag = urllib.request.urlopen(req, timeout=30).geturl().rstrip("/").split("/")[-1]
    log("  mihomo %s" % tag)
    if os.name == "nt":
        name = "mihomo-windows-amd64-%s.zip" % tag
        data = http_get("https://github.com/MetaCubeX/mihomo/releases/download/%s/%s" % (tag, name), 180)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = [n for n in z.namelist() if n.endswith(".exe")][0]
            open(p, "wb").write(z.read(inner))
    else:
        name = "mihomo-linux-amd64-compatible-%s.gz" % tag
        data = http_get("https://github.com/MetaCubeX/mihomo/releases/download/%s/%s" % (tag, name), 180)
        binary = gzip.decompress(data)
        if len(binary) < 5 * 1024 * 1024:
            raise RuntimeError("mihomo 下载内容异常（%d 字节）" % len(binary))
        with open(p, "wb") as f:
            f.write(binary)
        os.chmod(p, 0o755)

    # 预检：确认二进制能跑起来，避免后续用晦涩的报错失败
    try:
        r = subprocess.run([p, "-v"], capture_output=True, text=True, timeout=60)
        log("  " + ((r.stdout or r.stderr or "").strip().splitlines() or ["mihomo 已就绪"])[0])
    except Exception as e:  # noqa: BLE001
        size = os.path.getsize(p) if os.path.exists(p) else 0
        raise RuntimeError("mihomo 无法执行（%s %s，%d 字节）：%s"
                           % (platform.system(), platform.machine(), size, e))
    return p


def yaml_emit(lines, obj, indent):
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append("%s%s:" % (pad, k))
                yaml_emit(lines, v, indent + 1)
            elif isinstance(v, (dict, list)):
                lines.append("%s%s: {}" % (pad, k) if isinstance(v, dict) else "%s%s: []" % (pad, k))
            else:
                lines.append("%s%s: %s" % (pad, k, yaml_scalar(v)))
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict):
                lines.append("%s-" % pad)
                yaml_emit(lines, v, indent + 1)
            elif isinstance(v, list):
                lines.append("%s-" % pad)
                yaml_emit(lines, v, indent + 1)
            else:
                lines.append("%s- %s" % (pad, yaml_scalar(v)))


def yaml_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or any(c in s for c in ":#{}[],&*?|<>=!%@`'\"") or s.strip() != s or s.lower() in (
            "true", "false", "null", "yes", "no", "on", "off", "~"):
        return json.dumps(s, ensure_ascii=False)
    return s


def write_test_config(path, proxies, port, ctl):
    lines = ["mixed-port: %d" % port, "allow-lan: false", "mode: rule", "log-level: warning",
             "ipv6: false", "external-controller: 127.0.0.1:%d" % ctl, "secret: \"\"",
             "unified-delay: true", "tcp-concurrent: true", "find-process-mode: off",
             "geodata-mode: false", "geo-auto-update: false", "dns:", "  enable: false", "proxies:"]
    for i, p in enumerate(proxies):
        q = {k: v for k, v in p.items() if not str(k).startswith("__")}
        q["name"] = p.get("__id") or ("p%04d" % i)
        lines.append("-")
        yaml_emit(lines, q, 1)
    lines += ["rules:", "  - MATCH,DIRECT"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def kernel_validate(exe, cfg_path, workdir, proxies):
    """用 mihomo -t 反复剔除内核认为非法的节点，返回 (保留节点, 剔除节点)"""
    removed = []
    port, ctl = port_pair()
    for _ in range(300):
        write_test_config(cfg_path, proxies, port, ctl)  # -t 只校验，不真正监听端口
        r = subprocess.run([exe, "-t", "-f", cfg_path, "-d", workdir],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0 and "test failed" not in out:
            return proxies, removed
        m = re.search(r'msg="proxy (\d+): ([^"]+)"', out)
        if not m:
            log("  内核报错无法定位节点:\n" + out[-800:])
            return proxies, removed
        idx = int(m.group(1))
        if idx >= len(proxies):
            return proxies, removed
        victim = proxies[idx]
        removed.append((victim.get("type"), victim.get("server"), m.group(2)))
        proxies = proxies[:idx] + proxies[idx + 1:]
    return proxies, removed


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def port_pair():
    """取两个保证不同的端口：mixed-port 和外部控制端口不能撞"""
    a = free_port()
    for _ in range(30):
        b = free_port()
        if b != a:
            return a, b
    raise RuntimeError("无法分配到两个不同端口")


def start_core(exe, cfg_path, workdir, ctl, logfile):
    fh = open(logfile, "w", encoding="utf-8")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008  # DETACHED_PROCESS
    proc = subprocess.Popen([exe, "-f", cfg_path, "-d", workdir], stdout=fh, stderr=subprocess.STDOUT, **kw)
    for _ in range(60):
        if proc.poll() is not None:
            fh.flush()
            raise RuntimeError("mihomo 启动失败:\n" + open(logfile, encoding="utf-8", errors="ignore").read()[-1500:])
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/version" % ctl, timeout=2).read()
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("mihomo API 未就绪")


def probe_delay(ctl, name, timeout_ms, test_url):
    q = urllib.parse.quote(test_url, safe="")
    u = "http://127.0.0.1:%d/proxies/%s/delay?timeout=%d&url=%s" % (
        ctl, urllib.parse.quote(name), timeout_ms, q)
    try:
        with urllib.request.urlopen(u, timeout=timeout_ms / 1000.0 + 6) as r:
            return json.loads(r.read().decode()).get("delay")
    except Exception:  # noqa: BLE001
        return None


def measure(exe, proxies, workdir, workers, rounds, timeout_ms, test_url):
    port, ctl = port_pair()
    cfg = os.path.join(workdir, "test_config.yaml")
    for i, p in enumerate(proxies):
        if not p.get("__id"):          # 第二阶段复用第一阶段的 id，保证能对回原始节点
            p["__id"] = "n%04d" % i
    write_test_config(cfg, proxies, port, ctl)
    proc = start_core(exe, cfg, workdir, ctl, os.path.join(workdir, "core.log"))
    try:
        table = {p["__id"]: [] for p in proxies}
        for rnd in range(rounds):
            t0 = time.time()
            done = 0
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(probe_delay, ctl, p["__id"], timeout_ms, test_url): p["__id"] for p in proxies}
                for f in as_completed(futs):
                    table[futs[f]].append(f.result())
                    done += 1
                    if done % 500 == 0:
                        alive = sum(1 for v in table.values() if any(x for x in v))
                        log("    轮次 %d: %d/%d  存活 %d  %.0fs" % (rnd + 1, done, len(proxies), alive, time.time() - t0))
            log("  轮次 %d 完成，%.0fs，存活 %d" % (rnd + 1, time.time() - t0,
                                                sum(1 for v in table.values() if any(v))))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
    result = {}
    for nid, vals in table.items():
        ok = [v for v in vals if v]
        if ok:
            result[nid] = {"delay": int(sorted(ok)[len(ok) // 2]), "hits": len(ok), "tests": rounds}
    return result


# ---------------------------------------------------------------- 4. 归属地
def geolocate(servers):
    ips = {}
    for srv in set(servers):
        try:
            socket.inet_aton(srv)
            ips[srv] = srv
        except OSError:
            try:
                ips[srv] = socket.gethostbyname(srv)
            except Exception:  # noqa: BLE001
                ips[srv] = None
    uniq = sorted({v for v in ips.values() if v})
    info = {}
    for i in range(0, len(uniq), 100):
        chunk = uniq[i:i + 100]
        try:
            body = json.dumps([{"query": ip, "fields": "status,country,countryCode,isp"} for ip in chunk]).encode()
            req = urllib.request.Request("http://ip-api.com/batch", data=body,
                                         headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            for ip, r in zip(chunk, json.loads(urllib.request.urlopen(req, timeout=40).read().decode())):
                info[ip] = {"cc": (r.get("countryCode") or "").upper(), "isp": r.get("isp") or ""}
        except Exception:  # noqa: BLE001
            for ip in chunk:
                try:
                    j = json.loads(http_get("https://ipwho.is/" + ip, timeout=15).decode())
                    info[ip] = {"cc": (j.get("country_code") or "").upper(),
                                "isp": (j.get("connection") or {}).get("isp") or ""}
                except Exception:  # noqa: BLE001
                    info[ip] = {"cc": "", "isp": ""}
    return {srv: info.get(ip) or {"cc": "", "isp": ""} for srv, ip in ips.items()}


# ---------------------------------------------------------------- 5. 输出
REGION_ORDER = [("HK", "🇭🇰 香港"), ("TW", "🇹🇼 台湾"), ("JP", "🇯🇵 日本"), ("SG", "🇸🇬 新加坡"),
                ("US", "🇺🇸 美国"), ("KR", "🇰🇷 韩国")]
EU = {"NL", "DE", "GB", "FR", "IT", "RU", "CH", "SE", "CZ", "LV", "AT", "IE", "FI", "NO", "DK",
      "PL", "ES", "PT", "RO", "BG", "HU", "SK", "UA", "LT", "EE", "BE", "LU", "MD", "RS", "HR",
      "GR", "TR", "CY", "MT", "IS", "AL"}


def region_of(cc):
    for code, label in REGION_ORDER:
        if cc == code:
            return label
    return "🇪🇺 欧洲" if cc in EU else "🌍 其他"


def flag(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc) if cc in ISO2 else "🌐"


def build(nodes, geo, out_path, workers_note):
    items = []
    for p in nodes:
        nid = p["__id"]
        d = nodes_delay[nid]
        g = geo.get(str(p.get("server")), {})
        items.append({"node": p, "cc": g.get("cc", ""), "delay": d["delay"], "hits": d["hits"],
                      "tier": p.get("__tier", "https")})
    # HTTPS 验证过的排前面，仅 HTTP 的垫后
    items.sort(key=lambda x: (0 if x["tier"] == "https" else 1, x["delay"], -x["hits"]))

    counters, proxies = {}, []
    for it in items:
        cc = it["cc"] if it["cc"] in ISO2 else "XX"
        counters[cc] = counters.get(cc, 0) + 1
        code = cc if cc != "XX" else "未知"
        tag = "" if it["tier"] == "https" else " ·仅HTTP"
        name = "%s %s-%02d · %dms%s" % (flag(cc), code, counters[cc], it["delay"], tag)
        p = dict(it["node"])
        p.pop("__id", None)
        p.pop("__src", None)
        p.pop("__tier", None)
        p["name"] = name
        it["name"] = name
        it["region"] = region_of(cc)
        proxies.append(p)

    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    lines = [
        "# FLClash / Mihomo 订阅 — 免费公共节点（自动构建）",
        "# 生成时间: %s (UTC%s)   可用节点: %d" % (stamp, time.strftime("%z"), len(proxies)),
        "# 数据来源: GitHub 上每日更新的公开免费节点库，合并去重后经 Mihomo 内核真实连通性测试",
        "# 本文件由 GitHub Actions 自动生成，请勿手工修改",
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
                                   "localhost.ptlogin2.qq.com", "+.msftconnecttest.com", "+.msftncsi.com"],
                "default-nameserver": ["223.5.5.5", "119.29.29.29"],
                "nameserver": ["https://223.5.5.5/dns-query", "https://1.12.12.12/dns-query"],
                "proxy-server-nameserver": ["https://223.5.5.5/dns-query", "https://119.29.29.29/dns-query"],
                "nameserver-policy": {"geosite:cn": ["https://223.5.5.5/dns-query",
                                                     "https://1.12.12.12/dns-query"]}},
    }
    yaml_emit(lines, cfg, 0)

    lines.append("proxies:")
    for p in proxies:
        lines.append("-")
        yaml_emit(lines, p, 1)

    https_items = [it for it in items if it["tier"] == "https"]
    http_items = [it for it in items if it["tier"] != "https"]
    https_names = [it["name"] for it in https_items]
    http_names = [it["name"] for it in http_items]
    all_names = https_names + http_names

    regions = {}
    for it in https_items:
        regions.setdefault(it["region"], []).append(it["name"])
    order = [lbl for _, lbl in REGION_ORDER if lbl in regions]
    order += [lbl for lbl in ("🇪🇺 欧洲", "🌍 其他") if lbl in regions]

    main_pool = https_names or http_names          # 正常情况下自动选择只用 HTTPS 验证过的
    groups = [
        {"name": "🚀 节点选择", "type": "select",
         "proxies": (["♻️ 自动选择", "🔯 故障转移"] + order + ["🎯 全球直连"]
                     + (["🌐 备用（仅 HTTP）"] if http_names else [])
                     + all_names)},
        {"name": "♻️ 自动选择", "type": "url-test", "url": "https://www.gstatic.com/generate_204",
         "interval": 300, "tolerance": 50, "lazy": False, "proxies": main_pool},
        {"name": "🔯 故障转移", "type": "fallback", "url": "https://www.gstatic.com/generate_204",
         "interval": 300, "proxies": main_pool[:20]},
    ]
    for lbl in order:
        groups.append({"name": lbl, "type": "url-test", "url": "https://www.gstatic.com/generate_204",
                       "interval": 300, "tolerance": 50, "proxies": regions[lbl]})
    groups.append({"name": "🎯 全球直连", "type": "select", "proxies": ["DIRECT"]})
    groups.append({"name": "🛑 广告拦截", "type": "select", "proxies": ["REJECT", "DIRECT"]})
    if http_names:
        groups.append({"name": "🌐 备用（仅 HTTP）", "type": "select", "proxies": http_names})

    lines.append("proxy-groups:")
    for g in groups:
        lines.append("-")
        yaml_emit(lines, g, 1)

    rules = ["IP-CIDR,127.0.0.0/8,DIRECT,no-resolve", "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
             "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve", "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
             "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve", "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
             "IP-CIDR6,fc00::/7,DIRECT,no-resolve", "IP-CIDR6,fe80::/10,DIRECT,no-resolve",
             "DOMAIN-SUFFIX,local,DIRECT", "DOMAIN-SUFFIX,lan,DIRECT", "DOMAIN-SUFFIX,home.arpa,DIRECT",
             "GEOSITE,private,DIRECT", "GEOSITE,cn,DIRECT", "GEOIP,CN,DIRECT", "MATCH,🚀 节点选择"]
    lines.append("rules:")
    for r in rules:
        lines.append("- %s" % yaml_scalar(r))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    # 纯文本清单
    txt_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "nodes.txt")
    rows = ["# 免费节点清单  " + stamp, "# 序号 | 地区 | 协议 | 服务器:端口 | 延迟(ms)", ""]
    for i, (p, it) in enumerate(zip(proxies, items), 1):
        rows.append("%3d | %-2s | %-9s | %s:%s | %d" % (i, it["cc"] or "??", p["type"],
                                                        p["server"], p["port"], it["delay"]))
    with open(txt_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows) + "\n")
    return items, proxies


nodes_delay = {}

# mihomo 校验 GEOSITE/GEOIP 规则时需要地理库；默认会自己去 GitHub 下载，
# 一旦下载失败整个配置校验就失败 —— 所以这里先带镜像把它预置好。
GEO_ASSETS = {
    "geosite.dat": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geosite.dat",
    "geoip.metadb": "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb",
}


def ensure_geodata(workdir):
    """把地理库准备好并放进 workdir，返回是否全部就绪"""
    geo_cache = os.path.join(CACHE, "geo")
    os.makedirs(geo_cache, exist_ok=True)
    os.makedirs(workdir, exist_ok=True)
    all_ok = True
    for name, url in GEO_ASSETS.items():
        dst = os.path.join(workdir, name)
        if os.path.isfile(dst) and os.path.getsize(dst) > 1024 * 1024:
            continue
        src = os.path.join(geo_cache, name)
        if not (os.path.isfile(src) and os.path.getsize(src) > 1024 * 1024):
            got = False
            for u in (url, "https://ghfast.top/" + url, "https://gh-proxy.com/" + url):
                try:
                    data = http_get(u, timeout=180, retries=0, backoff=1)
                except Exception:  # noqa: BLE001
                    continue
                if len(data) > 1024 * 1024:
                    with open(src, "wb") as f:
                        f.write(data)
                    log("  地理库 %s 下载完成（%.0f MB）" % (name, len(data) / 1048576))
                    got = True
                    break
            if not got:
                log("  [warn] 地理库 %s 下载失败" % name)
                all_ok = False
                continue
        shutil.copyfile(src, dst)
    return all_ok


def _mihomo_test(exe, cfg, workdir):
    r = subprocess.run([exe, "-t", "-f", cfg, "-d", workdir],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    out = (r.stdout or "") + (r.stderr or "")
    return (r.returncode == 0 and "test failed" not in out), out


def validate_output(exe, path, workdir):
    """用内核真正加载一遍最终配置（含 GEOIP/GEOSITE 规则），确保导入 FLClash 不会报错"""
    os.makedirs(workdir, exist_ok=True)
    has_geo = ensure_geodata(workdir)
    ok, out = _mihomo_test(exe, path, workdir)
    if ok:
        log("  配置校验通过 ✔（含 GEOIP/GEOSITE 规则）")
        return True

    # 地理库缺失导致的失败：去掉地理规则再验一次，至少保证 proxies/groups 结构合法
    if not has_geo or "GeoSite" in out or "GeoIP" in out or "geoip" in out.lower():
        log("  [warn] 地理库不可用，改用去掉 GEO 规则的副本做结构校验")
        try:
            text = open(path, encoding="utf-8").read()
            kept = [ln for ln in text.splitlines()
                    if not re.match(r"^\s*-\s*(GEOSITE|GEOIP),", ln)]
            stripped = os.path.join(workdir, "stripped.yaml")
            open(stripped, "w", encoding="utf-8", newline="\n").write("\n".join(kept) + "\n")
            ok2, out2 = _mihomo_test(exe, stripped, workdir)
        except Exception as e:  # noqa: BLE001
            log("  结构校验异常: %s" % e)
            ok2, out2 = False, ""
        if ok2:
            log("  结构校验通过 ✔（代理与分组均合法；地理规则由 FLClash 自带库生效）")
            return True
        log("  配置校验失败 ✘")
        log(out2[-800:])
        return False

    log("  配置校验失败 ✘")
    log(out[-1200:])
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "flclash-free-nodes.yaml"))
    ap.add_argument("--workers", type=int, default=128)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("--min-nodes", type=int, default=5)
    args = ap.parse_args()

    t_all = time.time()
    os.makedirs(CACHE, exist_ok=True)
    work = os.path.join(CACHE, "work")
    os.makedirs(work, exist_ok=True)

    log("运行环境: python %s | %s %s | 工作目录 %s" % (
        platform.python_version(), platform.system(), platform.machine(), ROOT))
    log("参数: workers=%d rounds=%d timeout=%dms out=%s" % (
        args.workers, args.rounds, args.timeout, args.out))

    log("[1/7] 抓取节点源")
    ok, failed = fetch_sources()
    if not ok:
        log("没有可用节点源，退出。失败原因：")
        for repo, errs in failed[:5]:
            log("  - %s: %s" % (repo, errs))
        return 1

    log("[2/7] 解析 / 清洗 / 去重")
    t_parse = time.time()
    sys.path.insert(0, ROOT)
    import yaml  # 延迟导入，便于提示缺包
    merged, seen = [], set()
    for fn in sorted(glob.glob(os.path.join(CACHE, "*.yaml"))):
        src = os.path.basename(fn)
        try:
            doc = yaml.safe_load(open(fn, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log("  [warn] %s 解析失败: %s" % (src, str(e)[:60]))
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("proxies"), list):
            continue
        got = 0
        for p in normalize(doc["proxies"], src):
            k = dedupe_key(p)
            if k in seen:
                continue
            seen.add(k)
            got += 1
            merged.append(p)
        log("  %-40s 新增 %4d" % (src[:40], got))
    log("  去重后候选: %d（用时 %.1fs）" % (len(merged), time.time() - t_parse))
    if len(merged) < args.min_nodes:
        log("候选节点过少，退出")
        return 1

    log("[3/7] 内核校验")
    t_val = time.time()
    exe = mihomo_path()
    cfg = os.path.join(work, "validate.yaml")
    merged, removed = kernel_validate(exe, cfg, work, merged)
    log("  剔除非法节点 %d，剩余 %d（用时 %.1fs）" % (len(removed), len(merged), time.time() - t_val))
    for row in removed[:8]:
        log("    - %s %s (%s)" % row)

    http_url = "http://www.gstatic.com/generate_204"
    https_url = "https://www.gstatic.com/generate_204"

    log("[4/7] 初筛：真实请求（%d 线程，1 轮，HTTP）" % args.workers)
    quick = measure(exe, merged, work, args.workers, 1, args.timeout, http_url)
    log("  初筛存活: %d / %d" % (len(quick), len(merged)))
    if len(quick) < args.min_nodes:
        log("可用节点过少，退出（不下发新配置）")
        return 1
    candidates = [p for p in merged if p["__id"] in quick]

    log("[5/7] 复测：HTTPS 访问（%d 轮，只留真能上 HTTPS 的）" % args.rounds)
    global nodes_delay
    nodes_delay = measure(exe, candidates, work, min(args.workers, 32), args.rounds,
                          max(args.timeout, 5000), https_url)
    log("  复测存活: %d / %d" % (len(nodes_delay), len(candidates)))
    if len(nodes_delay) < args.min_nodes:
        log("可用节点过少，退出（不下发新配置）")
        return 1
    # 只过了 HTTP 的节点不丢，归到“备用（仅 HTTP）”组
    for p in candidates:
        p["__tier"] = "https" if p["__id"] in nodes_delay else "http"
    for k, v in quick.items():
        nodes_delay.setdefault(k, v)
    alive = candidates
    extra = sum(1 for p in alive if p["__tier"] == "http")
    log("  HTTPS 可用 %d 个，另有 %d 个仅 HTTP（放入备用组）" % (len(candidates) - extra, extra))

    log("[6/7] 查询归属地")
    t_geo = time.time()
    geo = geolocate([str(p.get("server")) for p in alive])
    log("  已知归属: %d / %d（用时 %.1fs）" % (sum(1 for v in geo.values() if v["cc"]), len(geo),
                                        time.time() - t_geo))

    log("[7/7] 生成配置并校验")
    items, proxies = build(alive, geo, args.out, args.workers)
    log("  输出: %s  (%d 个节点)" % (args.out, len(proxies)))
    log("  最快: %s   最慢: %s" % (items[0]["name"], items[-1]["name"]))
    from collections import Counter
    log("  地区: %s" % dict(Counter(it["cc"] or "??" for it in items).most_common(10)))

    ok = validate_output(exe, args.out, os.path.join(work, "final"))
    log("总耗时 %.0fs" % (time.time() - t_all))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
