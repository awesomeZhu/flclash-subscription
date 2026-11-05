#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把合并后的订阅（含自建节点）推送到私有 Gist —— 公开仓库里只放免费节点，密钥不上公开仓库。

需要环境变量：
    GIST_ID      Gist 的 id（从 gist 页面 URL 末尾拿，或 gists API 查）
    GIST_TOKEN   有 gist 权限的 Personal Access Token

用法：
    python scripts/publish_gist.py .cache/full.yaml [文件名]
"""
import json
import os
import sys
import urllib.request

API = "https://api.github.com/gists/"


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: publish_gist.py <yaml 文件> [gist 内文件名]")
    path = sys.argv[1]
    filename = sys.argv[2] if len(sys.argv) > 2 else "flclash-full.yaml"

    gid = os.environ.get("GIST_ID", "").strip()
    token = os.environ.get("GIST_TOKEN", "").strip()
    if not gid or not token:
        print("未配置 GIST_ID / GIST_TOKEN，跳过发布（合并版只留在 artifact 里）")
        return 0
    if not os.path.isfile(path):
        raise SystemExit("找不到文件: %s" % path)

    content = open(path, encoding="utf-8").read()
    body = json.dumps({"files": {filename: {"content": content}}}).encode("utf-8")
    req = urllib.request.Request(
        API + gid, data=body, method="PATCH",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "flclash-subscription",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode())
        print("Gist 已更新: %s（%d 字节）" % (j.get("html_url"), len(content)))
        owner = (j.get("owner") or {}).get("login", "")
        print("订阅地址: https://gist.githubusercontent.com/%s/%s/raw/%s" % (owner, gid, filename))
        return 0
    except Exception as e:  # noqa: BLE001
        print("Gist 更新失败: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
