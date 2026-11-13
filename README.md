# flclash-free-nodes

用 GitHub Actions 每天自动做一份 **FLClash 可直接导入、且经过真实测速** 的免费节点订阅。

抓取公开节点库 → 清洗去重 → Mihomo 内核校验 → **谷歌 + YouTube 双站实测 + 延迟门槛** → 查归属地 → 生成 YAML → 自动提交。

> 现在的下发标准是硬的：**只有在本机（CI 服务器）上真能打开 `www.google.com` 和 `www.youtube.com`、且延迟 ≤ 200ms 的节点**才会写进订阅。导入后不用再一个个点“延迟测试”挑，剩下的都是能用的。
你只需要在 FLClash 里填一个**固定 URL**，之后每天自动更新。

```
out/flclash-free-nodes.yaml   ← 成品（每天被 Actions 覆盖）
out/nodes.txt                 ← 纯文本清单：IP / 端口 / 协议 / 延迟
```

## 部署（5 步，约 5 分钟）

1. **新建仓库**：GitHub → New repository，名字随意（`Public` 不消耗 Actions 额度；`Private` 也行，见文末）。
2. **上传本目录全部内容**（注意 `.github/`、`scripts/`、`.gitignore` 这些点开头的文件别漏）：
   - 网页方式：仓库页 → *Add file* → *Upload files*，把整个文件夹拖进去；
   - 或命令行：`git init && git add . && git commit -m init && git push`。
3. **开写权限**：仓库 → *Settings* → *Actions* → *General* → *Workflow permissions* → 选 **Read and write permissions** → Save。
   （不开这一步，Actions 跑完推不上去，会报 403。）
4. **跑一次**：*Actions* 标签 → 左侧 `update-free-nodes` → 右侧 **Run workflow** → 绿色按钮。
   约 3–5 分钟跑完，仓库里 `out/flclash-free-nodes.yaml` 就是今天的成品。
5. **拿订阅地址**（把 `<用户名>` `<仓库名>` 换成你的）：

| 用途 | 地址 |
| --- | --- |
| 标准 raw | `https://raw.githubusercontent.com/<用户名>/<仓库名>/main/out/flclash-free-nodes.yaml` |
| 国内一般能开（jsDelivr） | `https://cdn.jsdelivr.net/gh/<用户名>/<仓库名>@main/out/flclash-free-nodes.yaml` |
| 另一个加速镜像 | `https://ghfast.top/https://raw.githubusercontent.com/<用户名>/<仓库名>/main/out/flclash-free-nodes.yaml` |

> **分支名要写对**：新建仓库默认是 `main`，但你这个仓库的分支是 **`master`**，所以地址里要写 `/master/`，否则 404。
> 不确定就看仓库首页左上角的 branch 下拉框。

## 导入 FLClash

1. FLClash → **配置** → 右下角 **+** → **从 URL 导入** → 粘贴上面的地址 → 保存；
2. 点一下这张卡片让它生效；
3. **代理** 页：模式选 **规则**，组选 **🚀 节点选择 → ♻️ 自动选择**；
4. 打开主开关（需要全局接管再开 TUN）。

**自动更新**：URL 型配置的卡片上有“更新”按钮，随时可手动拉最新；FLClash 设置里还有订阅自动更新的间隔选项（不同版本位置略有差异，找“自动更新 / 更新间隔”即可，建议 6–24 小时）。
即使不自动更新，组内 `♻️ 自动选择` 每 300 秒也会重新测速，自动避开失效节点。

### 为什么“本机能拿到新节点、别的设备还是旧的”

订阅文件放在三个地址上，**缓存时间差得非常远**（实测数据）：

| 地址 | CDN 缓存 | 实测表现 |
| --- | --- | --- |
| `raw.githubusercontent.com/.../master/out/flclash-free-nodes.yaml` | **5 分钟**（`max-age=300`） | 最新，推荐所有设备都用这个 |
| `cdn.jsdelivr.net/gh/...@master/...` | **12 小时**（`s-maxage=43200`），浏览器端 7 天 | 实测出现过滞后 26 小时 |
| `ghfast.top/https://raw.githubusercontent.com/...` | 5 分钟 | 与 raw 内容一致，国内网络备用 |

所以：

- 别的设备“刷新了还是旧 IP”，最常见就是**它用的是 jsDelivr 地址**，或者卡在浏览器/系统缓存里 —— 换回 raw 地址即可；
- 工作流现在会自动调 `purge.jsdelivr.net` 清 CDN 缓存（见 `update.yml` 最后一步），用 jsDelivr 也能及时更新；
- 还有一种情况：某台设备当初是**导入本地文件**（不是 URL），那它永远不会自己更新，删掉重新按 URL 导入；
- 判断是否真的更新了：浏览器直接打开订阅地址，看第二行 `生成时间` 和 `节点: N`，再和 FLClash 里的节点名对一下（FLClash 里显示的“延迟”是它本地测的，跟订阅新旧无关）。

## 目录结构

```
.github/workflows/update.yml   # 定时任务：每天 05:17（北京时间）跑一次
scripts/pipeline.py            # 全流程脚本（抓取→校验→测速→生成）
requirements.txt               # 只依赖 pyyaml
out/flclash-free-nodes.yaml    # 成品订阅
out/nodes.txt                  # 文本清单
out/run-stats.json             # 每轮构建的“漏斗统计”（候选→初筛→双站→探针→下发）
```

## 节点源（都在 `scripts/pipeline.py` 顶部）

| 类型 | 源 | 备注 |
| --- | --- | --- |
| GitHub | `ermaozi/get_subscribe`、`ermaozi01/free_clash_vpn`、`anaer/Sub`、`ripaojiedian/freenode`、`peasoft/NoMoreWalls`、`mahdibland/ShadowsocksAggregator`、`cysk003/freeSub`、`ts-sf/fly`、`free18/v2ray`、`chengaopan/AutoMergePublicNodes` | 每天自动更新，raw → jsDelivr → ghfast 三条通道兜底 |
| 每日站 | `freeclashnode.com`、`clashnode.me` | 同一家，互为备用；实测每家约 **500 个节点**（vless/trojan/ss/vmess），是最大的一块增量 |
| 每日站 | `nodefree.org`、`v2rayshare.com` | 国内网络会被 TLS 重置（本机实测连不上），但 CI 在美国通常能抓；抓不到只打一行 `[skip]` |

实测（2026-11-11）：**14 个源里 12 个可用，去重后候选从 3255 涨到 3918**（+663），其中免费站贡献 395 个。

加源很简单：GitHub 的往 `SOURCES` 里加 `("owner/repo", "分支", "文件路径")`；网站往 `EXTRA_SOURCES` 加 `("名字", "https://.../{Y}/{M}/0-{D}.yaml")`（占位符按北京日期填充）。只支持 Clash YAML 格式；base64/v2ray 链接格式（比如 `Pawdroid/Free-servers`）还需要额外的解析器，暂未接入。

## 流水线做了什么

1. **复测上一版（老节点优先）**：先读仓库里上一版的 `out/flclash-free-nodes.yaml`，把里面的节点挑前 60 个重新测一遍；**上海 RTT ≤ 150ms 的保留并排在订阅最前面**，超标的直接淘汰，剩下的名额再交给下面的常规流程。这样昨天快今天就未必慢的节点不会因为“今天的源里没有它”而被丢掉，订阅也不会每天大换血。
2. **抓取**：**10 个公开的 GitHub 节点仓库**（`scripts/pipeline.py` 里的 `SOURCES`）+ **4 个每天发布新节点的免费站**（`EXTRA_SOURCES`，按北京日期拼路径，今天没有就退回昨天）。失效的源自动跳过，单个源挂了不影响整体；
3. **清洗**：剔掉“剩余流量/到期时间”这类信息节点、内网地址、占位 UUID、重复节点；
4. **内核校验**：用官方 Mihomo 二进制 `-t` 加载，逐个剔除内核判定非法的节点（例如 REALITY short-id 写错的），直到整份配置能通过；
5. **初筛**：先让每个节点真实请求 `gstatic.com/generate_204`（1 轮，快速筛掉死节点），把几千个候选压到几百个；
6. **严格验证（核心）**：对活下来的候选逐个测两个站点 —— `https://www.google.com/generate_204`（必须 **204**）和 `https://www.youtube.com/`（必须 **200**，且响应体里真含 `youtube` 字样，挡掉劫持页/错误页），每个站点默认测 2 轮、要求全中。
   实现方式：内核给每个节点单独开一个 `listeners` 端口（`proxy:` 字段绑定到该节点），脚本再从本机往这个端口发**真实 HTTP 请求**。所以状态码、响应内容、TLS 全是真的，等于你在浏览器里打开过一遍。
   > 为什么不用内核自带的 `/delay` 接口：实测它**完全不看状态码**（访问一个 404 页面也返回“成功 48ms”），用它筛等于没筛。脚本里还带一个自检：绑 `REJECT` 的端口必须连不上，否则说明 `proxy:` 字段没生效、验证不可信，会直接报错退出。

   | 情况 | 结果 |
   | --- | --- |
   | 谷歌 + YouTube 都通，延迟 ≤ 200ms | ✅ 下发，进主池 |
   | 两个都通，但延迟 > 200ms | ❌ 丢弃（`--keep-slow` 可留到「🐢 高延迟备用」） |
   | 只有谷歌通，YouTube 打不开 | ❌ 丢弃（`--keep-gonly` 可留到「⚠️ 仅谷歌可用」） |
   | 都不通 / 只有 YouTube 通 | ❌ 丢弃 |

   完整通过的不足 5 个时会**自动兜底**：从“两个站都通、只是慢”的节点里补几个，至少让订阅不为空（它们单独进「🐢 高延迟备用」，不进主池和自动选择）。不想兜底就加 `--no-fallback-slow`。

   **亚太放宽（`--max-delay-asia`）**：CI 跑在美国机房，港澳台日韩新节点在那边天然 200ms 以上（而美国节点只有 20–40ms），一刀切 200ms 会把最适合国内用的港日节点全砍掉。所以工作流默认带 `--max-delay-asia 400`：全球仍是 200ms，港/台/日/韩/新放宽到 400ms；不想要就把这个参数改成 `0`。

7. **归属地**：ip-api 批量查询 IP 国家，用于命名和分组；
8. **上海探针实测（关键）**：上面第 5 步只能证明“节点在**美国机房**那边能上谷歌/YouTube”，代表不了你在上海用它的速度——实测同一批节点，机房看 69–102ms，而上海电信本机连它们的 TCP 端口只有 **10/97 能连上**，连上的里面也只有 3 个 ≤200ms。所以这一步用 [globalping.io](https://globalping.io) 的国内探针（默认上海，AS45090）量出**“上海 → 节点”的真实 RTT**，并且：

   > **带 SNI/Host 的节点不做 ping**（CloudFront/Cloudflare 前缀、reality、ws 域名）：改为从上海探针发一个真实 HTTPS 请求到 `https://<SNI>/`。因为国内是按 SNI 阻断的——TCP 能握手、TLS 被重置，只测 TCP 会把这种节点当好节点（实测 3 个 CloudFront 日本节点就是这样：ping 96ms，FLClash 里全部超时）。
   >
   > **地区筛选（`--cn-region asia_na`，默认）**：**只保留 日本 / 新加坡 / 韩国 / 台湾 / 香港 + 美国 / 加拿大**，其余地区（欧洲/俄/中东…）全部剔除，连探针额度都不花。
   >
   > **额度不够时按优先级截取：亚太 > 加拿大 > 美国**（用户要求：超容量优先加拿大）。日志会打每轮的地区构成和截取结果。
   >
   > 其他模式：`asia` 只要亚太五地；`auto` 额外包含澳门和归属未知；`all` 不筛选（额度紧张时不推荐）。

   | 上海实测结果 | 处理 |
   | --- | --- |
   | RTT ≤ `--cn-max-delay`（默认 120ms） | ✅ 进主池；**节点名里的数字就是上海延迟** |
   | RTT > 120ms | ❌ 降级丢弃（机房测的 40ms 不算数） |
   | 上海连不上 / 无回包 | ❌ 视为不可用，丢弃（这是有效信号，不是测速失败） |
   | 探针自身出问题（限流/额度用尽） | ⚠️ 整体退回按机房延迟判断，日志里告警 |

   > 还有个反直觉的坑：节点端口连不上时，`mtr` 仍会返回一串中途路由器（实测能看到上海→法兰克福→伦敦→波士顿的 cogent 路径，末尾 100% 丢包）。所以取数逻辑**只认地址属于目标本身的那一跳**，绝不会把中途路由器的 2000ms 当成节点延迟。

   免费额度 **250 次/小时**（`ping` 一节点 1 次，`ping` 不通才多花 1 次），所以默认最多量 150 个（`--cn-max-nodes`），并按国家轮流挑，避免预算全被某一类节点吃光。

9. **生成**：按上海延迟排序生成 YAML，最后再用内核 `-t` 校验一遍成品（含 GEOIP/GEOSITE 规则），确保导入 FLClash 不报错。

一个都没通过时脚本以非 0 退出，**工作流失败、不会推送**——你原来的订阅保持原样，不会变成空配置。

## 生成的配置长什么样

| 分组 | 类型 | 说明 |
| --- | --- | --- |
| 🚀 节点选择 | select | 手动总入口，列出分组 + 全部节点 |
| ♻️ 自动选择 | url-test | 谷歌+YouTube 双通、且上海实测 ≤200ms 的节点自动测速，300s 刷新，日常用这个 |
| 🔯 故障转移 | fallback | 最快 20 个做备份，掉线自动切换 |
| 🇭🇰/🇹🇼/🇯🇵/🇸🇬/🇺🇸/🇪🇺/🌍 | url-test | 按 IP 归属地分组（只含完整验证通过的节点） |
| 🐢 高延迟备用 | select | 仅在带 `--keep-slow` 时出现：两个站都通但延迟超标的 |
| ⚠️ 仅谷歌可用 | select | 仅在带 `--keep-gonly` 时出现：YouTube 打不开的 |
| 🎯 全球直连 / 🛑 广告拦截 | select | 直连 / 拒绝出口 |

规则：私有地址直连 → `GEOSITE,cn` 国内域名直连 → `GEOIP,CN` 国内 IP 直连 → 其余走 `🚀 节点选择`。

## 把自建节点并进订阅（可选）

配好 `selfhost/install.sh` 之后，可以让每天构建自动把自建节点塞进订阅最前面。

**先说为什么不能直接写进公开仓库**：`out/` 里的文件是公开可见的，而 GitHub 上有大量机器人 7×24 扫描 `vless://`、`reality-opts` 这类凭据。你的节点一进公开文件，几小时内就会被别人拿去用，然后被墙。所以这里做成**双产物**：

| 产物 | 内容 | 去向 |
| --- | --- | --- |
| `out/flclash-free-nodes.yaml` | 只有免费节点 | 正常提交到公开仓库（现有订阅不变） |
| `flclash-full.yaml` | 自建 2 个 + 免费全部 | **只推到你的私有 Gist**，不落公开仓库 |

### 配置三个 Secret

仓库 → Settings → Secrets and variables → Actions → **New repository secret**：

| Secret | 内容 | 必填 |
| --- | --- | --- |
| `SELFHOST_NODE` | 服务器上 `cat /root/selfhost-node.json` 的**整段内容** | 要合并就必填 |
| `GIST_ID` | 私有 Gist 的 id（新建一个 **secret** gist，URL 末尾那串） | 想要一条 URL 就填 |
| `GIST_TOKEN` | PAT，勾 **`gist`** 权限即可（不需要 repo） | 同上 |

`GIST_ID` / `GIST_TOKEN` 不填也能跑：合并版只会待在 Actions 的 artifact 里，你自己下载导入；公开订阅不受影响。

### 合并后的分组长这样

| 分组 | 类型 | 说明 |
| --- | --- | --- |
| 🚀 节点选择 | select | 默认选中 **🔀 智能切换** |
| 🔀 智能切换 | fallback | **自建优先**：自建两个都挂了才自动落到 ♻️ 自动选择（免费） |
| 🏠 自建节点 | url-test | Reality 与 Hysteria2 之间自动选快的，120s 刷新 |
| ♻️ 自动选择 / 🔯 故障转移 / 区域组 | — | 同原来，只含免费节点 |

所以日常效果是：**能用自建就走自建（快、稳），自建被墙/宕机才用免费节点兜底**，不会断网。

### 合并版订阅地址

```
https://gist.githubusercontent.com/<你的用户名>/<GIST_ID>/raw/flclash-full.yaml
```

Gist 更新后这个地址内容会变，直接在 FLClash 里当 URL 订阅导入即可（记得在「配置」卡片上开自动更新）。

## 想改点什么

| 需求 | 改哪里 |
| --- | --- |
| 加节点源 | `scripts/pipeline.py` 的 `SOURCES`，按 `("owner/repo", "分支", "文件路径")` 追加 |
| 改延迟门槛 | `--max-delay 300`（机房测；默认 200，调大 = 节点更多但更慢） |
| **改上海门槛** | `--cn-max-delay 120`（上海实测；默认 120，这是真正决定体验的参数） |
| 探针测哪些地区 | `--cn-region auto`（默认：门槛≤150ms 时只测亚太+未知）；`all` = 全测 |
| 换探针城市 | `--cn-city Guangzhou`（默认 `Shanghai`，任何 globalping 支持的中国城市） |
| 限制探针用量 | `--cn-max-nodes 80`（**工作流默认 80**；命令行默认 150；额度 250/小时，少用更容易挤进去） |
| 关闭上海探针 | `--no-cn-check`（退回只看机房延迟，不推荐） |
| 探针不可用也强行生成 | `--allow-degraded`（会变成一堆美国节点，体验差） |
| 保留没量到的节点 | `--keep-unmeasured`（默认淘汰，保证都过上海实测） |
| 老节点门槛 | `--carry-max-delay 120`（上海 RTT，默认 150；越小学生越精） |
| 复测多少个老节点 | `--carry-limit 30`（默认 60，按上一版延迟从好到差取） |
| 不要“老节点优先” | `--no-carry`（每次都完全按当天抓取重新生成） |
| 亚太节点单独放宽 | `--max-delay-asia 400`（仅在探针不可用时兜底，`0` = 不区分） |
| 更严格（每个站测 3 轮全通） | `--verify-rounds 3`（更慢，节点更少更稳） |
| 放宽“必须全通” | `--min-hits 1`（2 轮里中 1 轮就算通） |
| 超标节点也不丢，单列分组 | `--keep-slow`；只保留谷歌通的：`--keep-gonly` |
| 不要自动兜底（宁缺毋滥） | `--no-fallback-slow` |
| 改更新时刻 | `.github/workflows/update.yml` 的 `cron`（UTC 时间，北京 = UTC+8） |
| 改分组 / 规则 / 节点命名 | `scripts/pipeline.py` 的 `build()` 函数 |
| 换输出文件名 | `--out out/xxx.yaml`（记得同步 FLClash 里的订阅地址） |

这些参数直接改 `.github/workflows/update.yml` 里那行 `python -u scripts/pipeline.py --workers 128 --rounds 2 ...` 追加即可。

## Actions 跑失败了怎么查

**先看 Actions 页面顶部的 Annotations**：脚本会把失败原因（含 traceback）直接写成一条 `error` 注解，不用点进日志。
要看细节再展开失败的步骤，日志里每个阶段都带序号和耗时（`[1/7] 抓取` → `[7/7] 生成配置并校验`），**最后一个打出来的序号就是卡住的位置**。

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 卡在 `[1/7]`，全 `[skip]` | 抓取被限流/被墙 | 已内置 jsDelivr、ghfast 两条镜像，一般不会再发生；偶发直接重跑 |
| `[3/7]` 报 `mihomo 下载/启动全部失败` | 内核下载被拦 | 注解里会列出每个资源名 + 每条通道的失败原因；脚本已带版本兜底与镜像 |
| `[4/7]` 打印 `内核可见代理: 0 / N` | 内核没加载到节点 | 通常是内核启动失败，注解里带内核日志尾部 |
| `[4/7]` 打印 `直连自测: 失败` | runner 到测试地址不通 | 脚本会自动换 `cp.cloudflare.com` 和 https 地址重试 |
| 卡在 `[4/7]` 很久然后 `可用节点过少` | 当天上游确实没活节点 | 正常波动；脚本会失败退出、**不覆盖**旧配置 |
| `配置校验失败` 且提到 `GeoSite`/`GeoIP` | 地理库下载失败 | 脚本会自动降级为结构校验，通常仍是绿色通过 |
| 最后一步 `提交并推送` 报 `403` / `Permission denied` | 没开写权限 | Settings → Actions → General → Workflow permissions → Read and write |
| 报 `Node.js 20 is deprecated`、`ubuntu-latest 将迁移` | 只是提示，不影响 | action 已升到 v5/v6/v6，可忽略 |

## 几个坑

- **定时任务会被暂停**：GitHub 对 60 天没有任何提交的仓库会停掉 `schedule`。本工作流每次运行都会提交，正常不会触发；万一停了，去 Actions 页点一次 Run workflow 即可恢复。
- **Private 仓库消耗额度**：每次约 3–5 分钟，一天一次 ≈ 100–150 分钟/月，免费额度 2000 分钟/月，够用。
- **测速位置（已解决）**：第 5 步的“谷歌 + YouTube 能打开”跑在 GitHub 的美国机房，只能证明节点能出去；中文用户体验好不好，由第 7 步的**上海探针**决定。实测同一批节点：机房看 69–102ms，上海探针看 249–2822ms —— 所以最终下发和排序一律用上海实测值，机房延迟只当“能不能用”的初筛。
  - globalping 免费额度 **250 次/小时**、按出口 IP 计。GitHub 的 runner 出口是共享的，额度**可能被别人用光**——实测出现过两种情况：一整轮一个数据都没拿到；只量到几个就没额度了。脚本的判定只看“确定性结论”（有 RTT 或明确连不上），数量不够就视为探针不可用：若额度 ≤200 秒后刷新则等待重试一次，否则**直接失败退出、保留上一版订阅**（因为「只有机房测过」的列表会是一堆国内连不上的美国节点，宁可不下发）。日志和 Actions 注解里都会写清原因。
  - 探针额度之外没量到的节点，默认**直接淘汰**（保证下发的每个节点都过上海实测）；想让它们以“·未探针”标记留下，加 `--keep-unmeasured`。
  - 真遇到探针被限流：隔一小时点一次 **Run workflow** 重跑即可；连续多天都这样，可以在工作流里加 `--allow-degraded`，允许退化成“只看机房延迟”。
  - 想更贴近自己那条宽带、又不想受探针额度影响：本地跑 `python scripts/pipeline.py --no-cn-check`，测速就完全走你本机网络（你在上海，测出来的就是真实体验），产出的文件直接导入即可。
- **节点数量会波动**：实测每天几十到一百多个不等（免费节点的存活率本来就只有 2%–5%）。数量少的日子不是脚本坏了，是上游确实没那么多能用的。
- **安全**：节点服务器由陌生人提供，流量会经过对方。别用它登录网银、公司邮箱、输入证件；只用于查资料、看视频等公开访问。重要账号请用正规付费服务或自建。
- **合规**：遵守你所在地区的法律法规和网络服务商条款。
