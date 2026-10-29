# flclash-free-nodes

用 GitHub Actions 每天自动做一份 **FLClash 可直接导入、且经过真实测速** 的免费节点订阅。

抓取公开节点库 → 清洗去重 → Mihomo 内核校验 → 逐节点真实请求测速 → 查归属地 → 生成 YAML → 自动提交。
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

> 分支名如果不是 `main`（老仓库是 `master`），URL 里相应改掉。

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
4. **两段式测速**：先让每个节点真实请求 `gstatic.com/generate_204`（HTTP，1 轮，快速筛掉死节点）；再对活下来的候选跑 **HTTPS** 复测（2 轮，5 秒超时）。真实上网几乎都是 HTTPS，很多免费 HTTP 代理只能转发 80 端口、CONNECT 不上 443，这一步会把它们挑出来；
5. **归属地**：ip-api 批量查询 IP 国家，用于命名和分组；
6. **生成**：按延迟排序生成 YAML，最后再用内核 `-t` 校验一遍成品（含 GEOIP/GEOSITE 规则），确保导入 FLClash 不报错。

通过 HTTPS 复测的节点进主分组；只过了 HTTP 的节点不丢弃，放进 **🌐 备用（仅 HTTP）** 组，默认不参与自动选择。

可用节点少于 5 个时脚本以非 0 退出，**工作流失败、不会推送**——你原来的订阅保持原样，不会变成空配置。

## 生成的配置长什么样

| 分组 | 类型 | 说明 |
| --- | --- | --- |
| 🚀 节点选择 | select | 手动总入口，列出分组 + 全部节点 |
| ♻️ 自动选择 | url-test | HTTPS 验证过的节点自动测速，300s 刷新，日常用这个 |
| 🔯 故障转移 | fallback | 最快 20 个做备份，掉线自动切换 |
| 🇭🇰/🇹🇼/🇯🇵/🇸🇬/🇺🇸/🇪🇺/🌍 | url-test | 按 IP 归属地分组 |
| 🌐 备用（仅 HTTP） | select | 只通过 HTTP 测试的节点，主组失效时的后备 |
| 🎯 全球直连 / 🛑 广告拦截 | select | 直连 / 拒绝出口 |

规则：私有地址直连 → `GEOSITE,cn` 国内域名直连 → `GEOIP,CN` 国内 IP 直连 → 其余走 `🚀 节点选择`。

## 想改点什么

| 需求 | 改哪里 |
| --- | --- |
| 加节点源 | `scripts/pipeline.py` 的 `SOURCES`，按 `("owner/repo", "分支", "文件路径")` 追加 |
| 更严格（3 轮全通才算） | 工作流里 `--rounds 3`（更慢，节点更少更稳） |
| 放宽/收紧延迟上限 | `--timeout 2000`（毫秒） |
| 改更新时刻 | `.github/workflows/update.yml` 的 `cron`（UTC 时间，北京 = UTC+8） |
| 改分组 / 规则 / 节点命名 | `scripts/pipeline.py` 的 `build()` 函数 |
| 换输出文件名 | `--out out/xxx.yaml`（记得同步 FLClash 里的订阅地址） |

## Actions 跑失败了怎么查

日志里每个阶段都带序号和耗时（`[1/7] 抓取` → `[7/7] 生成配置并校验`），**看最后一个打出来的序号就知道卡在哪**：

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 卡在 `[1/7]`，全 `[skip]` | 抓取被限流/被墙 | 已内置 jsDelivr、ghfast 两条镜像，一般不会再发生；偶发直接重跑 |
| `[3/7]` 报 `mihomo 无法执行` | 内核下载损坏 | 重跑即可（脚本会重新下载并预检） |
| 卡在 `[4/7]` 很久然后 `可用节点过少` | 当天上游确实没活节点 | 正常波动；脚本会失败退出、**不覆盖**旧配置 |
| `配置校验失败` 且提到 `GeoSite`/`GeoIP` | 地理库下载失败 | 脚本会自动降级为结构校验，通常仍是绿色通过 |
| 最后一步 `提交并推送` 报 `403` / `Permission denied` | 没开写权限 | Settings → Actions → General → Workflow permissions → Read and write |
| 报 `Node.js 20 is deprecated`、`ubuntu-latest 将迁移` | 只是提示，不影响 | 已把 action 升到 v5/v6，可忽略 |

## 几个坑

- **定时任务会被暂停**：GitHub 对 60 天没有任何提交的仓库会停掉 `schedule`。本工作流每次运行都会提交，正常不会触发；万一停了，去 Actions 页点一次 Run workflow 即可恢复。
- **Private 仓库消耗额度**：每次约 3–5 分钟，一天一次 ≈ 100–150 分钟/月，免费额度 2000 分钟/月，够用。
- **测速位置不是你的网络**：节点是在 GitHub 的服务器上验证的（海外机房），能过滤掉绝大多数死节点；但国内网络到某些节点仍可能不通 —— 用 `♻️ 自动选择` 让它自己挑，或手动换区域组。
- **节点数量会波动**：实测每天几十到一百多个不等（免费节点的存活率本来就只有 2%–5%）。数量少的日子不是脚本坏了，是上游确实没那么多能用的。
- **安全**：节点服务器由陌生人提供，流量会经过对方。别用它登录网银、公司邮箱、输入证件；只用于查资料、看视频等公开访问。重要账号请用正规付费服务或自建。
- **合规**：遵守你所在地区的法律法规和网络服务商条款。
