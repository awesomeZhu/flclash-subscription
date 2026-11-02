# 自建节点：VLESS-Reality + Hysteria2

一台自己的机器上同时跑两个协议，客户端里两个节点做自动测速，坏一个自动切另一个。

| 协议 | 端口 | 特点 |
| --- | --- | --- |
| **VLESS + Reality** | TCP 443 | 不买域名、不配证书，流量伪装成访问真实大站；抗封锁最强，稳 |
| **Hysteria2** | UDP 8443 | 基于 QUIC，丢包环境下速度明显更快；晚高峰/移动网络更爽 |

两个都免费开源，流量只走你自己的服务器。

## 为什么值得折腾

| | 免费节点（订阅） | 自建 |
| --- | --- | --- |
| 存活 | 每天 5%–15%，随时失效 | 你不删它就在 |
| 延迟 | 忽高忽低，100–800ms 抖动 | 稳定，日本/新加坡约 50–150ms |
| 带宽 | 几十人挤一条，限速 | 独占 |
| 隐私 | 流量经过陌生人的服务器 | 只有你自己 |
| 成本 | 0 | 0（Oracle 永久免费）或 €4/月 |

## 一、弄一台机器

### 方案 1：Oracle Cloud Always Free（推荐，永久免费）

1. 注册 <https://www.oracle.com/cloud/free/>（需信用卡验证，会预授权 1 美元，不扣费）；
   地区建议选 **日本大阪 / 东京**、**新加坡** 或 **美国圣何塞**。
2. 控制台 → Compute → Instances → **Create instance**：
   - Image：**Ubuntu 24.04**（或 22.04）
   - Shape：`VM.Standard.A1.Flex`（ARM，最多 4 OCPU / 24GB 全免费）或
     `VM.Standard.E2.1.Micro`（AMD 小机，1GB 内存也够跑这两个协议）
   - 勾选 **Assign a public IPv4 address**
3. **先去放行端口**（这一步不做，脚本跑完也连不上）：
   VCN → Security Lists → Default Security List → **Add Ingress Rules**：
   - 源 `0.0.0.0/0`，协议 **TCP**，端口 `443`
   - 源 `0.0.0.0/0`，协议 **UDP**，端口 `8443`
4. 记下公网 IP，用 SSH 登录：`ssh ubuntu@<你的IP>`

> **两个 Oracle 特有的坑**
> - **ARM 实例经常“out of capacity”**：换可用域、换区域，或者先开 AMD 小机用着。
> - **免费实例可能被回收**（长期低负载会被判定闲置）。升到 **Pay As You Go** 就不会被回收，
>   只要用量在 Always Free 额度内仍然 **0 费用**（建议升级，省心）。
> - Oracle 的 Ubuntu 镜像默认用 iptables 挡端口，脚本已经帮你插规则了。

### 方案 2：其他便宜选项

- **Hetzner Cloud**：CX22（2 核 4G）€4.5/月，德国/芬兰，延迟 200ms+ 但极稳；
- **GCP**：e2-micro 每月免费额度（美国区域）；
- **AWS Lightsail**：$3.5/月，日本/新加坡，新用户有 3 个月免费。

## 二、服务器上跑一条命令

```bash
# 方式 A：从你自己的仓库拉（国内拉不动就用下面的 jsDelivr）
curl -fsSL https://raw.githubusercontent.com/awesomeZhu/flclash-subscription/master/selfhost/install.sh -o install.sh

# 方式 B：国内可用 CDN
curl -fsSL https://cdn.jsdelivr.net/gh/awesomeZhu/flclash-subscription@master/selfhost/install.sh -o install.sh

# 方式 C：本地有文件就 scp 上去
# scp install.sh root@<你的IP>:/root/

sudo bash install.sh
```

可选参数：

```bash
sudo bash install.sh --sni www.apple.com     # 换伪装目标（默认 www.microsoft.com）
sudo bash install.sh --reality-port 8443 --hy2-port 2053   # 换端口
sudo bash install.sh --force                 # 重新生成密钥（客户端要重新导入）
```

脚本做的事：装 Xray + Hysteria2 → 生成 Reality 密钥对/UUID/shortId → 写配置并自检 →
开 BBR 和 UDP 缓冲 → 放行防火墙 → 打印连接参数并存到 `/root/selfhost-node.json`。
**幂等**：重复跑不会换密钥。

跑完屏幕上会打印一段参数，最后一行是关键提示：**别忘了 Oracle 控制台的安全列表**。

自检：

```bash
systemctl status xray --no-pager
systemctl status hysteria-server --no-pager
ss -lntup | grep -E '(443|8443)'
```

## 三、生成 FLClash 配置（在你自己的电脑上）

```bash
# 1. 把参数文件拿回来
scp root@<你的IP>:/root/selfhost-node.json .

# 2. 生成配置（--flag 是节点名前缀，可换成 🇯🇵 🇸🇬 之类）
python selfhost/make_client.py --info selfhost-node.json --flag 🇯🇵
```

输出 `out/flclash-selfhost.yaml`，里面有两个节点（Reality + Hysteria2）和一整套分组/规则，
同时在终端打印 `vless://` 和 `hysteria2://` 分享链接（v2rayN、Shadowrocket 也能直接导入）。

只要其中一个协议就加 `--only reality` 或 `--only hysteria2`。

## 四、导入并验证

1. FLClash → **配置** → **+** → **从文件导入** → 选 `out/flclash-selfhost.yaml`；
2. 点卡片生效 → **代理** 页模式选「规则」，组选「🚀 节点选择 → ♻️ 自动选择」；
3. 开主开关，然后打开 <https://ip.sb> —— 显示的 IP 应该**就是你服务器的 IP**。

看不到服务器的 IP？按下面顺序排查。

## 五、连不上时的排查清单

| 现象 | 检查 |
| --- | --- |
| 节点一直超时 | 服务器上 `ss -lntup \| grep -E '(443\|8443)'` 有没有在监听 |
| 端口没监听 | `journalctl -u xray -n 40` / `journalctl -u hysteria-server -n 40` |
| 都正常但连不上 | **Oracle 安全列表**放行了吗？`iptables -L INPUT -n \| head` 有没有 REJECT |
| Reality 握手失败 | 服务器执行 `curl -I https://www.microsoft.com` 能不能通；不通就换 `--sni` |
| Hy2 能用、Reality 不行 | 换 SNI（`www.apple.com`、`www.cloudflare.com`、`www.tesla.com`） |
| Reality 能用、Hy2 很慢 | 运营商对 UDP 限速，属正常，用 Reality 即可 |
| 前一天好好的突然全挂 | IP 被封 → Oracle 控制台给实例换一个公网 IP（Reserved Public IP → 解除绑定再新建） |

## 六、日常维护

```bash
sudo bash install.sh --force          # 重置密钥（之后要重新生成并导入客户端配置）
sudo apt update && sudo apt upgrade -y   # 打补丁
journalctl -u xray -f                 # 实时看日志
```

- **别分享这个节点**：人一多就容易进封锁名单，自己用最稳。
- `selfhost-node.json` 里有 UUID 和密码，等同于钥匙，别提交到公开仓库（本目录的 `.gitignore` 已经排除它）。
- 想让多台设备共用：把 `out/flclash-selfhost.yaml` 传到你的私有仓库/Gist，用 URL 订阅即可。

## 七、文件说明

| 文件 | 作用 |
| --- | --- |
| `install.sh` | 服务器端一键部署（Ubuntu/Debian，ARM/x86 都行） |
| `make_client.py` | 本地把 `selfhost-node.json` 转成 FLClash 配置 + 分享链接 |
| `selfhost-node.example.json` | 参数文件示例（真实文件由脚本生成，不要提交） |
