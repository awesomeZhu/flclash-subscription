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

## 目录结构

```
.github/workflows/update.yml   # 定时任务：每天 05:17（北京时间）跑一次
scripts/pipeline.py            # 全流程脚本（抓取→校验→测速→生成）
requirements.txt               # 只依赖 pyyaml
out/flclash-free-nodes.yaml    # 成品订阅
out/nodes.txt                  # 文本清单
```

## 流水线做了什么

1. **抓取**：14 个公开的 Clash 格式免费节点仓库（`scripts/pipeline.py` 里的 `SOURCES`），失效的源自动跳过；
2. **清洗**：剔掉“剩余流量/到期时间”这类信息节点、内网地址、占位 UUID、重复节点；
3. **内核校验**：用官方 Mihomo 二进制 `-t` 加载，逐个剔除内核判定非法的节点（例如 REALITY short-id 写错的），直到整份配置能通过；
4. **初筛**：先让每个节点真实请求 `gstatic.com/generate_204`（1 轮，快速筛掉死节点），把几千个候选压到几百个；
5. **严格验证（核心）**：对活下来的候选逐个测两个站点 —— `https://www.google.com/generate_204`（必须 **204**）和 `https://www.youtube.com/`（必须 **200**，且响应体里真含 `youtube` 字样，挡掉劫持页/错误页），每个站点默认测 2 轮、要求全中。
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

6. **归属地**：ip-api 批量查询 IP 国家，用于命名和分组；
7. **生成**：按延迟排序生成 YAML，最后再用内核 `-t` 校验一遍成品（含 GEOIP/GEOSITE 规则），确保导入 FLClash 不报错。

一个都没通过严格验证时脚本以非 0 退出，**工作流失败、不会推送**——你原来的订阅保持原样，不会变成空配置。

## 生成的配置长什么样

| 分组 | 类型 | 说明 |
| --- | --- | --- |
| 🚀 节点选择 | select | 手动总入口，列出分组 + 全部节点 |
| ♻️ 自动选择 | url-test | 谷歌+YouTube 双通、≤200ms 的节点自动测速，300s 刷新，日常用这个 |
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
| 改延迟门槛 | `--max-delay 300`（毫秒；默认 200，调大 = 节点更多但更慢） |
| 亚太节点单独放宽 | `--max-delay-asia 400`（港澳台日韩新；`0` = 不区分，工作流默认 400） |
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
- **测速位置不是你的网络（重要）**：严格验证跑在 GitHub 的服务器上（`ubuntu-latest` 基本都在美国机房）。所以「延迟 ≤200ms」是**美国机房到节点**的延迟：美国节点在那边只有 20ms，但国内用可能是 300ms；反过来香港/日本节点在那边 180ms，国内用反而只要 40ms。这就是为什么工作流默认给亚太单独开了 `--max-delay-asia 400`——否则 200ms 一刀切会把港日节点全砍掉（实测第一版只留下 27 个美国/加拿大节点）。
  - 想按自己的网络筛：把仓库下载到本地，直接跑 `python scripts/pipeline.py --max-delay 200 --max-delay-asia 0`（需要 Python + `pip install -r requirements.txt`），产出的 `out/flclash-free-nodes.yaml` 就是**你本机实测**通关的节点，导入即可。
  - 只想让 CI 别删太狠：把 `--max-delay` 也调宽，例如 `--max-delay 500`。
  - 每次跑完的 `pipeline.log`（Actions 产物）里会打印「双站都通的节点延迟分布」，先看分布再决定门槛更靠谱。
- **节点数量会波动**：实测每天几十到一百多个不等（免费节点的存活率本来就只有 2%–5%）。数量少的日子不是脚本坏了，是上游确实没那么多能用的。
- **安全**：节点服务器由陌生人提供，流量会经过对方。别用它登录网银、公司邮箱、输入证件；只用于查资料、看视频等公开访问。重要账号请用正规付费服务或自建。
- **合规**：遵守你所在地区的法律法规和网络服务商条款。
