import hashlib
import os
import urllib.request

BASE = "https://raw.githubusercontent.com/awesomeZhu/flclash-subscription/master/"
LOCAL = r"D:\localWorkspace\harness\flclash-subscription"
UA = {"User-Agent": "Mozilla/5.0"}

expect = [
    "selfhost/install.sh",
    "selfhost/make_client.py",
    "selfhost/README.md",
    "selfhost/selfhost-node.example.json",
    ".gitignore",
]
for p in expect:
    try:
        d = urllib.request.urlopen(urllib.request.Request(BASE + p, headers=UA), timeout=20).read()
        local_path = os.path.join(LOCAL, p.replace("/", os.sep))
        same = os.path.isfile(local_path) and open(local_path, "rb").read() == d
        print("%-42s %7d 字节  %s" % (p, len(d), "与本地一致 ✔" if same else "与本地不同 ⚠"))
    except Exception as e:  # noqa: BLE001
        print("%-42s 未找到 (%s)" % (p, str(e)[:40]))
