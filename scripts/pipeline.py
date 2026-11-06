#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一站式流水线：抓取 GitHub 免费节点 -> 清洗去重 -> Mihomo 内核校验 -> 谷歌/YouTube 严格验证
              -> 归属地 -> 生成 FLClash 配置

下发的硬标准（全部满足才写进订阅）：
    1. 经内核实测能打开 https://www.google.com/generate_204   （返回 204）
    2. 经内核实测能打开 https://www.youtube.com/              （返回 200）
    3. 机房（美国）到节点的延迟中位数 ≤ --max-delay（默认 200ms）
    4. 多轮探测全部命中（--min-hits，默认 = --verify-rounds）
    5. 上海探针（globalping.io）实测“上海 → 节点”RTT ≤ --cn-max-delay（默认 200ms）
       —— 这一条才决定你在国内用起来快不快，节点名里的数字就是它

用法:
    python scripts/pipeline.py                     # 默认输出 out/flclash-free-nodes.yaml
    python scripts/pipeline.py --max-delay 300 --verify-rounds 3      # 放宽延迟 / 多测几轮
    python scripts/pipeline.py --keep-slow --keep-gonly              # 超标/仅谷歌的也留存（单列分组）
    python scripts/pipeline.py --max-candidates 30                   # 调试：只测前 30 个候选

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


def annotate(msg):
    """把错误写成 GitHub Actions 注解：失败时在 Actions 页面顶部直接可见，无需点进日志。
    本地运行时这只是一行普通输出。"""
    safe = str(msg).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print("::error title=流水线失败::%s" % safe[:6000], flush=True)


def http_get(url, timeout=40, retries=2, backoff=1.5):
    """带重试和指数退避的下载；失败时抛出带状态码的异常。

    注意：只有在服务器明确用 Content-Encoding: gzip 传输压缩内容时才解压。
    绝不能靠魔数 1f 8b 判断 —— 内核的 .gz 发布包本身就是 gzip，靠魔数会把
    “下载到的 .gz” 提前解成 ELF，调用方再解一次就报 Not a gzipped file。
    """
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                enc = (r.headers.get("Content-Encoding") or "").lower()
            if "gzip" in enc and data[:2] == b"\x1f\x8b":
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
MIHOMO_FALLBACK_TAG = "v1.19.33"   # 上游 API/重定向都拿不到版本时的兜底


def _resolve_tag():
    """先问 API，再读 releases/latest 的重定向，最后退回固定版本；任何一步失败都不致命"""
    try:
        j = json.loads(http_get("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest",
                                timeout=20, retries=0, backoff=1).decode())
        t = j.get("tag_name")
        if t and str(t).startswith("v"):
            return t
    except Exception as e:  # noqa: BLE001
        log("  [warn] 查询 mihomo 最新版失败（API）: %s" % str(e)[:70])
    try:
        req = urllib.request.Request("https://github.com/MetaCubeX/mihomo/releases/latest", headers=UA)
        t = urllib.request.urlopen(req, timeout=25).geturl().rstrip("/").split("/")[-1]
        if t and t.startswith("v"):
            return t
        log("  [warn] 重定向里没解析出版本号: %r" % t[:40])
    except Exception as e:  # noqa: BLE001
        log("  [warn] 查询 mihomo 最新版失败（重定向）: %s" % str(e)[:70])
    log("  [warn] 使用兜底版本 %s" % MIHOMO_FALLBACK_TAG)
    return MIHOMO_FALLBACK_TAG


def _asset_names(tag):
    if os.name == "nt":
        return ["mihomo-windows-amd64-%s.zip" % tag,
                "mihomo-windows-amd64-compatible-%s.zip" % tag]
    return ["mihomo-linux-amd64-compatible-%s.gz" % tag,
            "mihomo-linux-amd64-%s.gz" % tag,
            "mihomo-linux-amd64-compatible-%s.zip" % tag,
            "mihomo-linux-amd64-%s.zip" % tag]


def _unpack(data, dst, name):
    """解压出可执行文件。按内容嗅探而不是只看扩展名：
    1f 8b = gzip，50 4b = zip，7f 45 4c 46 = 已经是 ELF（Linux 可执行），4d 5a = PE（Windows）。"""
    head = data[:4]
    if head[:2] == b"\x1f\x8b":
        binary = gzip.decompress(data)
    elif head[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = [n for n in z.namelist()
                     if not n.endswith("/") and "mihomo" in os.path.basename(n).lower()]
            if not inner:
                inner = [n for n in z.namelist() if n.endswith(".exe") or n.endswith("/mihomo")]
            binary = z.read(inner[0])
    elif head == b"\x7fELF" or head[:2] == b"MZ":
        binary = data                      # 服务器直接给了可执行文件，无需解压
    else:
        raise RuntimeError("无法识别的内核文件格式: %r..." % head)
    if len(binary) < 5 * 1024 * 1024:
        raise RuntimeError("解压后只有 %d 字节，不像是内核" % len(binary))
    with open(dst, "wb") as f:
        f.write(binary)
    if os.name != "nt":
        os.chmod(dst, 0o755)


def mihomo_path():
    exe = "mihomo.exe" if os.name == "nt" else "mihomo"
    p = os.path.join(CACHE, "bin", exe)
    if os.path.isfile(p) and os.path.getsize(p) > 5 * 1024 * 1024:
        return p
    os.makedirs(os.path.dirname(p), exist_ok=True)

    tag = _resolve_tag()
    log("  mihomo 版本: %s" % tag)
    errors = []
    for name in _asset_names(tag):
        for base in ("https://github.com/MetaCubeX/mihomo/releases/download/",
                     "https://ghfast.top/https://github.com/MetaCubeX/mihomo/releases/download/"):
            url = "%s%s/%s" % (base, tag, name)
            try:
                data = http_get(url, timeout=180, retries=1, backoff=1)
                _unpack(data, p, name)
                r = subprocess.run([p, "-v"], capture_output=True, text=True, timeout=60)
                ver = ((r.stdout or r.stderr or "").strip().splitlines() or ["mihomo 已就绪"])[0]
                log("  " + ver)
                return p
            except Exception as e:  # noqa: BLE001
                errors.append("%s -> %s" % (name, str(e)[:70]))
                if os.path.exists(p) and os.path.getsize(p) < 5 * 1024 * 1024:
                    os.remove(p)
    raise RuntimeError("mihomo 下载/启动全部失败（%s %s）：\n  %s"
                       % (platform.system(), platform.machine(), "\n  ".join(errors)))


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
            data = json.loads(r.read().decode())
        return data.get("delay"), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:120]


def measure(exe, proxies, workdir, workers, rounds, timeout_ms, test_url):
    port, ctl = port_pair()
    cfg = os.path.join(workdir, "test_config.yaml")
    for i, p in enumerate(proxies):
        if not p.get("__id"):          # 第二阶段复用第一阶段的 id，保证能对回原始节点
            p["__id"] = "n%04d" % i
    write_test_config(cfg, proxies, port, ctl)
    proc = start_core(exe, cfg, workdir, ctl, os.path.join(workdir, "core.log"))
    try:
        # 诊断：内核到底认到几个代理？直连能不能通？—— 排查“0 存活”时非常关键
        try:
            api = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/proxies" % ctl, timeout=10).read())
            visible = [k for k in api.get("proxies", {}) if k.startswith("n") and len(k) == 5]
            log("  内核可见代理: %d / %d" % (len(visible), len(proxies)))
        except Exception as e:  # noqa: BLE001
            log("  [warn] 读取 /proxies 失败: %s" % str(e)[:100])
        d, err = probe_delay(ctl, "DIRECT", timeout_ms, test_url)
        log("  直连自测: %s" % ("%dms" % d if d else "失败 -> %s" % err))

        table = {p["__id"]: [] for p in proxies}
        errs = []
        for rnd in range(rounds):
            t0 = time.time()
            done = 0
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(probe_delay, ctl, p["__id"], timeout_ms, test_url): p["__id"] for p in proxies}
                for f in as_completed(futs):
                    d, err = f.result()
                    table[futs[f]].append(d)
                    if err and len(errs) < 3:
                        errs.append("%s: %s" % (futs[f], err))
                    done += 1
                    if done % 500 == 0:
                        alive = sum(1 for v in table.values() if any(x for x in v))
                        log("    轮次 %d: %d/%d  存活 %d  %.0fs" % (rnd + 1, done, len(proxies), alive, time.time() - t0))
            log("  轮次 %d 完成，%.0fs，存活 %d" % (rnd + 1, time.time() - t0,
                                                sum(1 for v in table.values() if any(v))))
        for e in errs:
            log("  探测错误样例 -> %s" % e)
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


# ---------------------------------------------------------------- 4. 严格验证
# 唯一的下发标准：谷歌和 YouTube 都真能打开，且延迟不超过门槛。
GOOGLE_URL = "https://www.google.com/generate_204"
YOUTUBE_URL = "https://www.youtube.com/"


def _median(vals):
    v = sorted(vals)
    return v[len(v) // 2] if v else None


def _verify_ports(n):
    """给每个节点分配一个本地入站端口（mihomo 的 listeners 支持给单个节点单独开口）。
    从 20000 起挑，避开系统临时端口段（Linux 32768+、Windows 49152+），减少抢端口。"""
    ports, tried, base = [], 0, 20000
    while len(ports) < n and tried < n * 30 + 500:
        p = base + tried
        tried += 1
        if p > 32000:
            break
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            s.listen(1)
            ports.append(p)
        except OSError:
            pass
        finally:
            s.close()
    return ports


def http_probe(port, site, timeout_ms):
    """通过 127.0.0.1:<port> 这个入站口发一次真实 HTTP 请求。

    为什么不用内核的 /delay 接口：实测它对状态码完全不看（404 也返回“成功 48ms”），
    所以那种测法证明不了“网页真能打开”。这里走真实请求 + 真实状态码 + 真实内容：
      google  —— 必须 204（generate_204 的标准返回）
      youtube —— 必须 200，且响应体里真含 youtube / ytimg 字样（挡掉劫持页、错误页）
    返回 (ok, status, 毫秒, 错误说明)
    """
    url = GOOGLE_URL if site == "google" else YOUTUBE_URL
    proxy = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    t0 = time.time()
    try:
        with op.open(url, timeout=max(1.0, timeout_ms / 1000.0)) as resp:
            code = resp.status
            ms = int((time.time() - t0) * 1000)
            if site == "google":
                return code == 204, code, ms, ("" if code == 204 else "状态码 %d" % code)
            body = resp.read(65536)
            if "gzip" in (resp.headers.get("Content-Encoding") or "").lower():
                try:                                  # 万一对方还是压了，先解开再找关键字
                    body = gzip.GzipFile(fileobj=io.BytesIO(body)).read(65536)
                except Exception:  # noqa: BLE001
                    pass
            body = body.lower()
            if code != 200:
                return False, code, ms, "状态码 %d" % code
            if len(body) < 2000 or (b"youtube" not in body and b"ytimg" not in body):
                return False, code, ms, "返回内容不是 YouTube（%d 字节）" % len(body)
            return True, code, ms, ""
    except urllib.error.HTTPError as e:
        return False, e.code, int((time.time() - t0) * 1000), "HTTP %d" % e.code
    except Exception as e:  # noqa: BLE001
        return False, None, int((time.time() - t0) * 1000), str(e)[:80]


def probe_one_node(port, rounds, timeout_ms):
    """一个节点测两个站（顺序执行，避免自己抢自己的带宽把延迟测虚高）"""
    g, y, g_err, y_err = [], [], "", ""
    for _ in range(max(1, rounds)):
        ok, code, ms, err = http_probe(port, "google", timeout_ms)
        if ok:
            g.append(ms)
        else:
            g_err = err
    for _ in range(max(1, rounds)):
        ok, code, ms, err = http_probe(port, "youtube", timeout_ms)
        if ok:
            y.append(ms)
        else:
            y_err = err
    return _median(g), len(g), g_err, _median(y), len(y), y_err


def write_verify_config(path, proxies, ctl, ports, mixed, reject_port):
    """生成验证用配置：每个节点一个 listener（proxy 字段绑定到该节点），
    另开一个绑 REJECT 的 listener 做自检（它必须连不上，否则说明 proxy 字段没生效）"""
    lines = ["mixed-port: %d" % mixed, "allow-lan: false", "mode: rule", "log-level: warning",
             "ipv6: false", "external-controller: 127.0.0.1:%d" % ctl, "secret: \"\"",
             "dns:", "  enable: false", "listeners:",
             "  - name: selfcheck-reject", "    type: mixed", "    port: %d" % reject_port,
             "    proxy: REJECT"]
    for p, port in zip(proxies, ports):
        lines += ["  - name: ln-%s" % p["__id"], "    type: mixed", "    port: %d" % port,
                  "    proxy: %s" % yaml_scalar(p["__id"])]
    lines.append("proxies:")
    for p in proxies:
        q = {k: v for k, v in p.items() if not str(k).startswith("__")}
        q["name"] = p["__id"]
        lines.append("-")
        yaml_emit(lines, q, 1)
    lines += ["rules:", "  - MATCH,DIRECT"]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _verify_chunk(exe, chunk, workdir, workers, rounds, timeout_ms):
    """一批节点（≤150）的严格验证：开端口 -> 起内核 -> 自检 -> 并发真请求 -> 收尾。
    返回 ({__id: (g_med, g_hits, g_err, y_med, y_hits, y_err)}, 致命错误说明)"""
    want = len(chunk) + 1                 # 多要一个给“自检 REJECT”口，避免和节点端口撞号
    ports = _verify_ports(want)
    reject_port = ports.pop() if ports else free_port()
    if len(ports) < len(chunk):
        log("  [warn] 本批只分配到 %d/%d 个本地端口，少的那几个这次不验证" % (len(ports), len(chunk)))
        chunk = chunk[:len(ports)]
    if not chunk:
        return {}, ""
    mixed, ctl = port_pair()
    cfg = os.path.join(workdir, "verify_config.yaml")
    write_verify_config(cfg, chunk, ctl, ports, mixed, reject_port)
    proc = start_core(exe, cfg, workdir, ctl, os.path.join(workdir, "core-verify.log"))
    rows = {}
    try:
        # 自检：绑 REJECT 的口必须连不上。连得上 => 内核对 listener 的 proxy 字段不生效，
        # 那样所有请求都会走“规则默认出口”，验证结果毫无意义，必须停下来。
        ok, code, ms, err = http_probe(reject_port, "google", min(timeout_ms, 5000))
        if ok:
            return {}, ("内核对 listeners.proxy 支持异常（REJECT 口竟然连通了 %d，%dms），"
                        "逐节点验证无法进行" % (code, ms))
        t0 = time.time()
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(probe_one_node, port, rounds, timeout_ms): p["__id"]
                    for p, port in zip(chunk, ports)}
            for f in as_completed(futs):
                rows[futs[f]] = f.result()
                done += 1
                if done % 50 == 0:
                    log("    %d/%d 已测  通过 %d  %.0fs"
                        % (done, len(chunk), sum(1 for v in rows.values() if v[0] and v[3]),
                           time.time() - t0))
        log("  本批 %d 个节点实测完成 %.0fs（通过 %d）"
            % (len(chunk), time.time() - t0, sum(1 for v in rows.values() if v[0] and v[3])))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
    return rows, ""


def verify_sites(exe, proxies, workdir, workers, rounds, timeout_ms, max_delay, min_hits):
    """严格验证：谷歌 204 + YouTube 200 都得真拿到，且延迟 ≤ max_delay。

    做法：给每个节点开一个独立入站端口（mihomo listeners 的 proxy 字段），
    然后从本机真实发出 HTTP/HTTPS 请求 —— 状态码、响应内容、TLS 全是真的，
    和你在浏览器里打开是一回事，不是“看着像通”。

    返回 ({__id: {...}}, 统计)，并给节点打 __tier：
      full  = 谷歌 + YouTube 都通，延迟达标  -> 下发
      slow  = 两个都通但延迟超标            -> 默认丢弃，--keep-slow 才保留
      gonly = 只有谷歌通，YouTube 不通       -> 默认丢弃，--keep-gonly 才保留
    """
    for i, p in enumerate(proxies):
        if not p.get("__id"):
            p["__id"] = "v%04d" % i

    rows = {}
    total = len(proxies)
    chunk_size = 150                      # 一次别开太多端口，分批跑更稳
    if total > chunk_size:
        log("  分 %d 批跑，每批 ≤%d 个节点（少开端口、少占内存）"
            % ((total + chunk_size - 1) // chunk_size, chunk_size))
    for i in range(0, total, chunk_size):
        part, fatal = _verify_chunk(exe, proxies[i:i + chunk_size], workdir, workers,
                                    rounds, timeout_ms)
        if fatal:
            return {}, {"fatal": fatal}
        rows.update(part)

    result = {}
    stat = {"full": 0, "slow": 0, "gonly": 0, "dead": 0, "youtube_only": 0}
    for nid, (g, gh, ge, y, yh, ye) in rows.items():
        ok_g = g is not None and gh >= min_hits
        ok_y = y is not None and yh >= min_hits
        if ok_g and ok_y:
            tier = "full" if g <= max_delay else "slow"
            result[nid] = {"delay": g, "hits": gh, "google": g, "youtube": y, "tier": tier}
        elif ok_g:
            tier = "gonly"
            result[nid] = {"delay": g, "hits": gh, "google": g, "youtube": None, "tier": tier}
        elif ok_y:
            # 谷歌不通、YouTube 通：说明节点里塞了分流/劫持，不可信，直接丢
            stat["youtube_only"] += 1
            continue
        else:
            stat["dead"] += 1
            continue
        stat[tier] += 1
    return result, stat


# ---------------------------------------------------------------- 5. 上海探针
# GitHub 的机器在美国，只能证明“节点能出去看谷歌/YouTube”；而你在上海访问这个节点
# 到底多快，必须在国内量。globalping.io 有开放 API 和国内探针（上海/杭州/南京…），
# 用 mtr(TCP) 或 ping 从探针到节点 IP:端口 的 RTT，就是“上海 -> 节点”的真实延迟。
# 免费额度 250 次/小时（1 个探针 = 1 次），所以默认只量通过初筛的候选、并做了预算控制。
GP_API = "https://api.globalping.io/v1/measurements"
GP_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) flclash-pipeline"}
GP_CITIES = [{"city": "Shanghai", "country": "CN"},
             {"city": "Hangzhou", "country": "CN"},
             {"city": "Nanjing", "country": "CN"}]
_gp_budget = {"remaining": 999}


def _gp_call(url, payload=None, timeout=45):
    h = dict(GP_UA)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()), dict(r.headers)


def _gp_ms(res):
    """从 globalping 结果里取“到目标的 RTT”：mtr 有结构化 hops，ping 只有原始文本"""
    for r in res.get("results", []):
        robj = r.get("result") or {}
        hops = [h for h in (robj.get("hops") or [])
                if (h.get("stats") or {}).get("avg") is not None]
        if hops:
            return float(hops[-1]["stats"]["avg"])
        raw = robj.get("rawOutput")
        if raw:
            vals = [float(x) for x in re.findall(r"time[=<]\s*([\d.]+)", str(raw))]
            if vals:
                vals.sort()
                return vals[len(vals) // 2]
    return None


def cn_probe(target, port, city, timeout_s=90):
    """从 city 探针量一次 target 的 RTT。先 mtr-TCP（能穿透只放 TCP 的机器），
    没拿到数据再用 ping（照顾 hysteria2 这类只开 UDP 的节点）。返回 (ms, 说明)。"""
    plan = [("mtr", {"type": "mtr", "target": target, "locations": [city],
                     "measurementOptions": {"protocol": "TCP", "port": int(port)}, "limit": 1}),
            ("ping", {"type": "ping", "target": target, "locations": [city],
                      "measurementOptions": {"packets": 3}, "limit": 1})]
    for kind, payload in plan:
        if _gp_budget["remaining"] <= 1:
            return None, "额度用尽"
        try:
            j, hdrs = _gp_call(GP_API, payload)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _gp_budget["remaining"] = 0
                return None, "限流 429"
            continue
        except Exception:  # noqa: BLE001
            continue
        try:
            _gp_budget["remaining"] = int(hdrs.get("X-RateLimit-Remaining", 999))
        except Exception:  # noqa: BLE001
            pass
        mid = j.get("id")
        if not mid:
            continue
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(2)
            try:
                res, _ = _gp_call("%s/%s" % (GP_API, mid))
            except Exception:  # noqa: BLE001
                continue
            if res.get("status") == "finished":
                ms = _gp_ms(res)
                if ms:
                    return int(round(ms)), kind
                break
    return None, "探针无响应"


def _round_robin_by_cc(nodes, geo):
    """按国家轮流取，避免预算不够时全被某一类节点占满"""
    buckets = {}
    for p in nodes:
        cc = geo.get(str(p.get("server")), {}).get("cc", "") or "XX"
        buckets.setdefault(cc, []).append(p)
    out = []
    while any(buckets.values()):
        for cc in list(buckets):
            if buckets[cc]:
                out.append(buckets[cc].pop(0))
    return out


def cn_probe_nodes(nodes, geo, cities, workers, timeout_s, budget):
    """并发从国内探针量每个节点：返回 {(server, port): (ms|null, 说明)}"""
    _gp_budget["remaining"] = budget
    todo = _round_robin_by_cc(nodes, geo)[:budget]
    if len(todo) < len(nodes):
        log("  预算 %d 个，本次只量 %d 个（按国家轮流挑）" % (budget, len(todo)))
    out, done = {}, 0
    t0 = time.time()

    def one(p):
        return (str(p.get("server")), int(p.get("port") or 443)), \
            cn_probe(str(p.get("server")), p.get("port") or 443, cities[0], timeout_s)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(one, p) for p in todo]
        for f in as_completed(futs):
            try:
                key, (ms, how) = f.result()
            except Exception:  # noqa: BLE001
                continue
            out[key] = (ms, how)
            done += 1
            if done % 20 == 0:
                got = sum(1 for v in out.values() if v[0])
                log("    %d/%d 已量（有数据 %d）%.0fs  剩余额度 %d"
                    % (done, len(todo), got, time.time() - t0, _gp_budget["remaining"]))
    log("  探针测量完成 %.0fs，有数据 %d / %d" % (time.time() - t0,
                                             sum(1 for v in out.values() if v[0]), len(out)))
    return out


# ---------------------------------------------------------------- 6. 归属地
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


# ---------------------------------------------------------------- 8. 输出
REGION_ORDER = [("HK", "🇭🇰 香港"), ("TW", "🇹🇼 台湾"), ("JP", "🇯🇵 日本"), ("SG", "🇸🇬 新加坡"),
                ("US", "🇺🇸 美国"), ("KR", "🇰🇷 韩国")]
EU = {"NL", "DE", "GB", "FR", "IT", "RU", "CH", "SE", "CZ", "LV", "AT", "IE", "FI", "NO", "DK",
      "PL", "ES", "PT", "RO", "BG", "HU", "SK", "UA", "LT", "EE", "BE", "LU", "MD", "RS", "HR",
      "GR", "TR", "CY", "MT", "IS", "AL"}

# 下发优先级与名字后缀：只有 full 会进主池，其余只是可选收纳
TIER_RANK = {"full": 0, "slow": 1, "gonly": 2}
TIER_TAG = {"full": "", "slow": " ·高延迟", "gonly": " ·仅谷歌"}
# 亚太地区：CI 机房在美国，这些节点“机房延迟”天然偏高，但国内用其实快，单独给宽门槛
ASIA = {"HK", "TW", "JP", "SG", "KR", "MO"}


def region_of(cc):
    for code, label in REGION_ORDER:
        if cc == code:
            return label
    return "🇪🇺 欧洲" if cc in EU else "🌍 其他"


def flag(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc) if cc in ISO2 else "🌐"


def load_selfhost(path):
    """读取 install.sh 生成的自建节点参数，返回 Clash 代理列表（含密钥，别公开）"""
    if not path:
        return []
    if not os.path.isfile(path):
        log("  [warn] 找不到自建节点参数 %s，本次只生成免费节点" % path)
        return []
    try:
        info = json.load(open(path, encoding="utf-8"))
        srv = info["server"]
        sni = info.get("sni") or "www.microsoft.com"
        out = []
        r = info.get("reality")
        if r:
            out.append({
                "name": "🏠 自建 · Reality", "type": "vless", "server": srv, "port": int(r["port"]),
                "uuid": r["uuid"], "network": "tcp", "tls": True, "udp": True,
                "flow": "xtls-rprx-vision", "servername": sni, "client-fingerprint": "chrome",
                "reality-opts": {"public-key": r["public_key"], "short-id": r.get("short_id", "")},
            })
        h = info.get("hysteria2")
        if h:
            out.append({
                "name": "🏠 自建 · Hysteria2", "type": "hysteria2", "server": srv,
                "port": int(h["port"]), "password": h["password"], "sni": sni,
                "skip-cert-verify": True, "up": "50 Mbps", "down": "200 Mbps", "udp": True,
            })
        return out
    except Exception as e:  # noqa: BLE001
        log("  [warn] 自建节点参数解析失败（忽略）: %s" % str(e)[:100])
        return []


def build(nodes, geo, out_path, workers_note, selfhost=None, public_path=None):
    selfhost = selfhost or []
    items = []
    for p in nodes:
        nid = p["__id"]
        d = nodes_delay[nid]
        g = geo.get(str(p.get("server")), {})
        items.append({"node": p, "cc": g.get("cc", ""), "delay": d["delay"], "hits": d["hits"],
                      "tier": p.get("__tier", "full")})
    # 完整通过的排前面，其余按下发顺序垫后
    items.sort(key=lambda x: (TIER_RANK.get(x["tier"], 3), x["delay"], -x["hits"]))

    counters, proxies = {}, []
    for it in items:
        cc = it["cc"] if it["cc"] in ISO2 else "XX"
        counters[cc] = counters.get(cc, 0) + 1
        code = cc if cc != "XX" else "未知"
        tag = TIER_TAG.get(it["tier"], "")
        name = "%s %s-%02d · %dms%s" % (flag(cc), code, counters[cc], it["delay"], tag)
        p = dict(it["node"])
        p.pop("__id", None)
        p.pop("__src", None)
        p.pop("__tier", None)
        p["name"] = name
        it["name"] = name
        it["region"] = region_of(cc)
        proxies.append(p)

    primary_items = [it for it in items if it["tier"] == "full"]
    primary_names = [it["name"] for it in primary_items]
    all_names = [it["name"] for it in items]
    # 没通过完整验证的（延迟超标 / YouTube 不通）只在带 --keep-* 时才会存在，单独分组收纳
    extra = [(tier, label, [it["name"] for it in items if it["tier"] == tier])
             for tier, label in (("slow", "🐢 高延迟备用"), ("gonly", "⚠️ 仅谷歌可用"))]
    extra = [x for x in extra if x[2]]

    regions = {}
    for it in primary_items:
        regions.setdefault(it["region"], []).append(it["name"])
    order = [lbl for _, lbl in REGION_ORDER if lbl in regions]
    order += [lbl for lbl in ("🇪🇺 欧洲", "🌍 其他") if lbl in regions]

    main_pool = primary_names or all_names     # 自动选择/故障转移只用完整验证通过的
    check_url = "https://www.gstatic.com/generate_204"

    def render(path, sh):
        sh_names = [p["name"] for p in sh]
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        lines = [
            "# FLClash / Mihomo 订阅 — %s" % ("自建 + 免费节点" if sh else "免费公共节点"),
            "# 生成时间: %s (UTC%s)   节点: %d%s" % (
                stamp, time.strftime("%z"), len(proxies) + len(sh),
                "（自建 %d + 免费 %d）" % (len(sh), len(proxies)) if sh else ""),
            "# 数据来源: GitHub 上每日更新的公开免费节点库，合并去重后逐个实测：",
            "#   ① 谷歌 (www.google.com/generate_204) 与 YouTube (www.youtube.com) 都能真打开；",
            ("#   ② 上海探针（globalping.io）实测“上海 → 节点”RTT ≤ %dms，节点名里的数字就是上海延迟。"
             % DELAY_GATE_CN) if DELAY_GATE_CN else
            ("#   ② 机房实测延迟 ≤ %dms（未启用上海探针）" % DELAY_GATE),
            "# 本文件由 GitHub Actions 自动生成，请勿手工修改",
        ]
        if DELAY_GATE_ASIA:
            lines.insert(len(lines) - 1, "#   港澳台日韩新单独放宽到 ≤ %dms（机房到节点的延迟，你在国内用会更快）"
                         % DELAY_GATE_ASIA)
        if sh:
            lines.append("# ⚠️ 本文件含自建节点密钥，请勿公开（仅用于私有 Gist）")
        lines.append("")

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
                                       "localhost.ptlogin2.qq.com", "+.msftconnecttest.com",
                                       "+.msftncsi.com"],
                    "default-nameserver": ["223.5.5.5", "119.29.29.29"],
                    "nameserver": ["https://223.5.5.5/dns-query", "https://1.12.12.12/dns-query"],
                    "proxy-server-nameserver": ["https://223.5.5.5/dns-query",
                                                "https://119.29.29.29/dns-query"],
                    "nameserver-policy": {"geosite:cn": ["https://223.5.5.5/dns-query",
                                                         "https://1.12.12.12/dns-query"]}},
        }
        yaml_emit(lines, cfg, 0)

        lines.append("proxies:")
        for p in sh + proxies:          # 自建节点排最前
            lines.append("-")
            yaml_emit(lines, p, 1)

        groups = []
        if sh:
            groups.append({"name": "🏠 自建节点", "type": "url-test", "url": check_url,
                           "interval": 120, "tolerance": 50, "lazy": False, "proxies": sh_names})
            # 自建优先，自建全挂时自动落到免费节点
            groups.append({"name": "🔀 智能切换", "type": "fallback", "url": check_url,
                           "interval": 300, "proxies": ["🏠 自建节点", "♻️ 自动选择"]})
        select_list = (["🔀 智能切换"] if sh else []) + (["🏠 自建节点"] if sh else []) \
            + ["♻️ 自动选择", "🔯 故障转移"] + order + ["🎯 全球直连"] \
            + [lbl for _, lbl, _ in extra] \
            + sh_names + all_names
        groups.insert(0, {"name": "🚀 节点选择", "type": "select", "proxies": select_list})
        groups.append({"name": "♻️ 自动选择", "type": "url-test", "url": check_url,
                       "interval": 300, "tolerance": 50, "lazy": False, "proxies": main_pool})
        groups.append({"name": "🔯 故障转移", "type": "fallback", "url": check_url,
                       "interval": 300, "proxies": main_pool[:20]})
        for lbl in order:
            groups.append({"name": lbl, "type": "url-test", "url": check_url,
                           "interval": 300, "tolerance": 50, "proxies": regions[lbl]})
        groups.append({"name": "🎯 全球直连", "type": "select", "proxies": ["DIRECT"]})
        groups.append({"name": "🛑 广告拦截", "type": "select", "proxies": ["REJECT", "DIRECT"]})
        for _, lbl, names in extra:
            groups.append({"name": lbl, "type": "select", "proxies": names})

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

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        return path

    def write_nodes_txt(path):
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime())
        txt_path = os.path.join(os.path.dirname(os.path.abspath(path)), "nodes.txt")
        rows = ["# 免费节点清单  " + stamp, "# 序号 | 地区 | 协议 | 服务器:端口 | 延迟(ms)", ""]
        for i, (p, it) in enumerate(zip(proxies, items), 1):
            rows.append("%3d | %-2s | %-9s | %s:%s | %d" % (i, it["cc"] or "??", p["type"],
                                                            p["server"], p["port"], it["delay"]))
        with open(txt_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(rows) + "\n")

    render(out_path, selfhost)
    write_nodes_txt(public_path or out_path)   # 清单始终跟着公开版走
    if public_path:
        # 公开仓库那份：去掉自建节点，避免密钥泄露
        render(public_path, [])
    return items, proxies


nodes_delay = {}
DELAY_GATE = 200      # 机房延迟门槛（ms），由 main() 按 --max-delay 覆盖，仅用于写进配置注释
DELAY_GATE_ASIA = 0   # 亚太单独门槛，由 main() 按 --max-delay-asia 覆盖
DELAY_GATE_CN = 0     # 上海探针门槛，由 main() 按 --cn-max-delay 覆盖（>0 表示用了上海探针）

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
    ap.add_argument("--max-delay", type=int, default=200,
                    help="延迟门槛（毫秒）：谷歌 204 的中位延迟超过它就下发时丢弃，默认 200")
    ap.add_argument("--max-delay-asia", type=int, default=0,
                    help="亚太节点（港澳台日韩新）单独放宽到 N ms，0=不区分。"
                         "仅在关闭上海探针（--no-cn-check）或探针拿不到数据时起兜底作用")
    ap.add_argument("--no-cn-check", dest="cn_check", action="store_false",
                    help="关闭上海探针实测（默认开启）")
    ap.add_argument("--cn-city", default="Shanghai",
                    help="国内探针城市，默认 Shanghai（globalping 的国内探针城市）")
    ap.add_argument("--cn-max-delay", type=int, default=200,
                    help="上海 -> 节点 的 RTT 门槛（毫秒），超过就下发时丢弃，默认 200")
    ap.add_argument("--cn-max-nodes", type=int, default=200,
                    help="本次最多量多少个节点（globalping 免费额度 250 次/小时），默认 200")
    ap.add_argument("--cn-workers", type=int, default=6,
                    help="并发创建的探针测量数量，默认 6")
    ap.add_argument("--verify-rounds", type=int, default=2,
                    help="严格验证时每个站点的探测轮数，默认 2")
    ap.add_argument("--verify-timeout", type=int, default=5000,
                    help="严格验证单次请求超时（毫秒），默认 5000")
    ap.add_argument("--min-hits", type=int, default=0,
                    help="每个站点至少成功几轮才算通，默认=verify-rounds（要求全中，最稳）")
    ap.add_argument("--keep-slow", action="store_true",
                    help="保留延迟超标的节点（放进“🐢 高延迟备用”组），默认丢弃")
    ap.add_argument("--no-fallback-slow", dest="fallback_slow", action="store_false",
                    help="完整通过的节点不足时不要自动补高延迟节点（默认会自动补，避免下发空订阅）")
    ap.add_argument("--keep-gonly", action="store_true",
                    help="保留 YouTube 打不开、只有谷歌通的节点（放进“⚠️ 仅谷歌可用”组），默认丢弃")
    ap.add_argument("--max-candidates", type=int, default=0,
                    help="只取前 N 个候选参与测速（调试用），0 = 全部")
    ap.add_argument("--selfhost", default="",
                    help="自建节点参数 json（install.sh 生成），提供则并入订阅最前面")
    ap.add_argument("--public-out", default="",
                    help="另存一份不含自建节点的配置，供公开仓库提交")
    args = ap.parse_args()

    t_all = time.time()
    os.makedirs(CACHE, exist_ok=True)
    work = os.path.join(CACHE, "work")
    os.makedirs(work, exist_ok=True)

    log("运行环境: python %s | %s %s | 工作目录 %s" % (
        platform.python_version(), platform.system(), platform.machine(), ROOT))
    log("参数: workers=%d rounds=%d timeout=%dms max_delay=%dms 输出=%s" % (
        args.workers, args.rounds, args.timeout, args.max_delay, args.out))

    log("[1/8] 抓取节点源")
    ok, failed = fetch_sources()
    if not ok:
        log("没有可用节点源，退出。失败原因：")
        for repo, errs in failed[:5]:
            log("  - %s: %s" % (repo, errs))
        annotate("所有节点源都抓取失败：%s" % ("; ".join("%s: %s" % (r, e) for r, e in failed[:4])))
        return 1

    log("[2/8] 解析 / 清洗 / 去重")
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
        annotate("候选节点只有 %d 个，少于阈值 %d" % (len(merged), args.min_nodes))
        return 1
    if args.max_candidates and len(merged) > args.max_candidates:
        merged = merged[:args.max_candidates]
        log("  [调试] 只取前 %d 个候选参与后续测速" % len(merged))

    log("[3/8] 内核校验")
    t_val = time.time()
    exe = mihomo_path()
    cfg = os.path.join(work, "validate.yaml")
    merged, removed = kernel_validate(exe, cfg, work, merged)
    log("  剔除非法节点 %d，剩余 %d（用时 %.1fs）" % (len(removed), len(merged), time.time() - t_val))
    for row in removed[:8]:
        log("    - %s %s (%s)" % row)

    http_url = "http://www.gstatic.com/generate_204"
    https_url = "https://www.gstatic.com/generate_204"
    fallback_url = "http://cp.cloudflare.com/generate_204"

    log("[4/8] 初筛：真实请求（%d 线程，1 轮）" % args.workers)
    quick = {}
    for url in (http_url, fallback_url, https_url):
        quick = measure(exe, merged, work, args.workers, 1, args.timeout, url)
        log("  探测地址 %-42s 存活 %d / %d" % (url, len(quick), len(merged)))
        if len(quick) >= args.min_nodes:
            break
    if len(quick) < args.min_nodes:
        log("可用节点过少，退出（不下发新配置）")
        annotate("初筛可用节点只有 %d 个（内核可见 %d 个），判断为网络/内核问题" % (len(quick), len(merged)))
        return 1
    candidates = [p for p in merged if p["__id"] in quick]

    log("[5/8] 严格验证：谷歌 + YouTube 可达性（%d 轮，机房延迟门槛 %dms）" %
        (args.verify_rounds, args.max_delay))
    min_hits = args.min_hits or args.verify_rounds
    min_hits = max(1, min(min_hits, args.verify_rounds))
    global nodes_delay, DELAY_GATE, DELAY_GATE_ASIA, DELAY_GATE_CN
    DELAY_GATE = args.max_delay
    DELAY_GATE_ASIA = args.max_delay_asia
    DELAY_GATE_CN = 0                      # 探针真拿到数据后才置为真实门槛（见第 7 步）
    verified, vstat = verify_sites(exe, candidates, work, min(args.workers, 64),
                                   args.verify_rounds, args.verify_timeout,
                                   args.max_delay, min_hits)
    if vstat.get("fatal"):
        log("  严格验证无法进行：%s" % vstat["fatal"])
        annotate("严格验证无法进行：%s" % vstat["fatal"])
        return 1
    log("[6/8] 查询归属地（先查，因为亚太门槛和探针挑样都要看国家）")
    t_geo = time.time()
    geo = geolocate([str(p.get("server")) for p in candidates])
    log("  已知归属: %d / %d（用时 %.1fs）" % (sum(1 for v in geo.values() if v["cc"]), len(geo),
                                        time.time() - t_geo))

    # 亚太放宽：CI 机房在美国，港澳台日韩新节点在那边天然 200ms+，你在国内用反而很快，
    # 所以给它们单独一个更宽的门槛（--max-delay-asia），别被 200ms 一刀切掉。
    # 注意：这只是“没开上海探针/探针拿不到数据”时的兜底，正常情况下由下面第 7 步说了算。
    if args.max_delay_asia > 0 and not args.cn_check:
        promoted = 0
        for p in candidates:
            info = verified.get(p["__id"])
            if not info or info["tier"] != "slow" or info["delay"] > args.max_delay_asia:
                continue
            if geo.get(str(p.get("server")), {}).get("cc", "") in ASIA:
                info["tier"] = "full"
                promoted += 1
        log("  亚太放宽（≤%dms）: 收回 %d 个港澳台日韩新节点" % (args.max_delay_asia, promoted))

    # ---- 第 7 步：上海探针实测，用“上海 -> 节点”的延迟重判 ----
    cn_hit, cn_miss = 0, 0
    if args.cn_check:
        log("[7/8] 上海探针实测（globalping.io，%s）" % args.cn_city)
        cn_data = cn_probe_nodes(candidates, geo, [{"city": args.cn_city, "country": "CN"}],
                                 args.cn_workers, 90, args.cn_max_nodes)
        hit = sorted(v[0] for v in cn_data.values() if v[0])
        if hit:
            log("  上海 -> 节点 RTT: 最快 %dms / 中位 %dms / 最慢 %dms（有数据 %d / %d）"
                % (hit[0], hit[len(hit) // 2], hit[-1], len(hit), len(cn_data)))
        else:
            log("  [warn] 探针一个数据都没拿到（限流或网络问题），退回按机房延迟判断")
        promoted = demoted = 0
        # GitHub 的 runner 出口 IP 是共享的，250 次/小时可能被别人吃掉，
        # 所以覆盖不足时不敢用探针结果做“降级”，否则会误杀一堆好节点
        enough = len(hit) >= max(5, int(len(candidates) * 0.5))
        if not enough:
            log("  [warn] 探针覆盖不足（有数据 %d / %d 个候选，可能出口被限流），"
                "本次仍按机房延迟判断" % (len(hit), len(candidates)))
        else:
            for p in candidates:
                info = verified.get(p["__id"])
                if not info:
                    continue
                ms = cn_data.get((str(p.get("server")), int(p.get("port") or 443)), (None, ""))[0]
                if not ms:
                    cn_miss += 1
                    # 探针量到过东西，但这个节点没数据（端口被判死/超时/额度用尽）：
                    # 上海能不能用没有证据，先降级，别拿没验过的节点占位
                    if info["tier"] == "full":
                        info["tier"] = "slow"
                    continue
                cn_hit += 1
                info["cn"] = ms
                info["delay"] = ms                 # 名字、排序、门槛全部改用上海实测
                if ms <= args.cn_max_delay:
                    if info["tier"] == "slow":
                        info["tier"] = "full"
                        promoted += 1
                elif info["tier"] == "full":
                    info["tier"] = "slow"          # 机房看着快、上海其实慢 -> 降级
                    demoted += 1
            log("  按上海实测重判: 收回 %d 个（≤%dms），降级 %d 个（>%dms），无数据 %d 个"
                % (promoted, args.cn_max_delay, demoted, args.cn_max_delay, cn_miss))
        DELAY_GATE_CN = args.cn_max_delay if cn_hit else 0

    n_full = sum(1 for v in verified.values() if v["tier"] == "full")
    n_slow = sum(1 for v in verified.values() if v["tier"] == "slow")
    n_gonly = sum(1 for v in verified.values() if v["tier"] == "gonly")
    unit = "上海" if cn_hit else "机房"
    log("  谷歌+YouTube 都通，且%s延迟 ≤%dms: %d 个 ✔"
        % (unit, args.cn_max_delay if cn_hit else args.max_delay, n_full))
    log("  延迟超标: %d 个%s" % (n_slow, "，已保留" if args.keep_slow else "，丢弃"))
    log("  YouTube 不通（仅谷歌）: %d 个%s" % (n_gonly, "，已保留" if args.keep_gonly else "，丢弃"))
    log("  两个站点都不通: %d 个，丢弃" % vstat["dead"])
    if vstat["youtube_only"]:
        log("  只有 YouTube 通、谷歌不通（可疑节点）: %d 个，丢弃" % vstat["youtube_only"])
    ds = sorted(info["delay"] for info in verified.values() if info["delay"])
    if ds:
        log("  双站都通的节点%s延迟分布: <100ms %d | 100-200ms %d | 200-400ms %d | 400-800ms %d | >800ms %d"
            % (unit, sum(1 for d in ds if d < 100), sum(1 for d in ds if 100 <= d < 200),
               sum(1 for d in ds if 200 <= d < 400), sum(1 for d in ds if 400 <= d < 800),
               sum(1 for d in ds if d >= 800)))
        log("  （当前%s门槛 %dms；太严/太松就调 --cn-max-delay）"
            % (unit, args.cn_max_delay if cn_hit else args.max_delay))
    if n_full == 0:
        log("  没有一个节点通过全部门槛，保留上一版订阅，不下发空配置")
        annotate("最终 0 个节点通过（候选 %d，上海探针有数据 %d）；"
                 "可能是探针被限流或当天节点质量差，可调 --cn-max-delay"
                 % (len(candidates), cn_hit))
        return 1

    nodes_delay = {}
    for p in candidates:
        info = verified.get(p["__id"])
        if not info:
            continue
        if info["tier"] == "slow" and not args.keep_slow:
            continue
        if info["tier"] == "gonly" and not args.keep_gonly:
            continue
        p["__tier"] = info["tier"]
        nodes_delay[p["__id"]] = {"delay": info["delay"], "hits": info["hits"],
                                  "tests": args.verify_rounds}
    # 兜底：完整通过的太少时，自动补几个“能打开两个站、只是慢”的节点，
    # 免得某天门槛过严直接下发空订阅（它们会单独进「🐢 高延迟备用」，不进主池）
    if args.fallback_slow and len(nodes_delay) < args.min_nodes:
        spare = [p for p in candidates
                 if verified.get(p["__id"], {}).get("tier") == "slow"
                 and p["__id"] not in nodes_delay]
        spare.sort(key=lambda p: verified[p["__id"]]["delay"])
        added = 0
        for p in spare:
            if len(nodes_delay) >= args.min_nodes:
                break
            info = verified[p["__id"]]
            p["__tier"] = "slow"
            nodes_delay[p["__id"]] = {"delay": info["delay"], "hits": info["hits"],
                                      "tests": args.verify_rounds}
            added += 1
        if added:
            log("  [兜底] 完整通过不足 %d 个，自动补入 %d 个高延迟节点，保证订阅不空"
                % (args.min_nodes, added))

    alive = [p for p in candidates if p["__id"] in nodes_delay]
    log("  本次下发节点: %d 个（初筛 %d 个，筛掉 %d 个）" % (len(alive), len(candidates),
                                                       len(candidates) - len(alive)))
    if len(alive) < args.min_nodes:
        log("  通过数 %d 个 < 阈值 %d，保留上一版订阅，不下发" % (len(alive), args.min_nodes))
        annotate("严格验证后只剩 %d 个节点（门槛 %dms），少于阈值 %d；可放宽 --max-delay"
                 % (len(alive), args.max_delay, args.min_nodes))
        return 1

    log("[8/8] 生成配置并校验")
    sh_nodes = load_selfhost(args.selfhost)
    if sh_nodes:
        log("  已载入自建节点 %d 个: %s" % (len(sh_nodes), ", ".join(p["name"] for p in sh_nodes)))
    items, proxies = build(alive, geo, args.out, args.workers, sh_nodes,
                           args.public_out or None)
    log("  输出: %s  (免费 %d + 自建 %d)" % (args.out, len(proxies), len(sh_nodes)))
    if args.public_out:
        log("  公开版: %s  (只含免费节点)" % args.public_out)
    log("  最快: %s   最慢: %s" % (items[0]["name"], items[-1]["name"]))
    from collections import Counter
    log("  地区: %s" % dict(Counter(it["cc"] or "??" for it in items).most_common(10)))

    ok = validate_output(exe, args.out, os.path.join(work, "final"))
    if ok and args.public_out:
        ok = validate_output(exe, args.public_out, os.path.join(work, "final")) and ok
    log("总耗时 %.0fs" % (time.time() - t_all))
    if not ok:
        annotate("生成的配置没通过内核校验，已保留上一版，不覆盖")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        annotate("未捕获异常，traceback 末尾：" + tb.strip()[-1500:])
        sys.exit(1)
