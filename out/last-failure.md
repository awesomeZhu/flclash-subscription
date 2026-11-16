# 上次构建失败：2026-11-16 03:51 UTC

```
运行环境: python 3.12.16 | Linux x86_64 | 工作目录 /home/runner/work/flclash-subscription/flclash-subscription
参数: workers=128 rounds=2 timeout=3000ms max_delay=200ms 输出=out/flclash-free-nodes.yaml
[1/9] 复测上一版订阅（老节点优先）
  从 flclash-free-nodes.yaml 读到 12 个老节点，复测后上海 RTT ≤150ms 才保留
[2/9] 抓取节点源
  [ok]   ermaozi/get_subscribe                     205 KB  (raw.githubusercontent.com)
  [ok]   ermaozi01/free_clash_vpn                   21 KB  (raw.githubusercontent.com)
  [ok]   anaer/Sub                                 599 KB  (raw.githubusercontent.com)
  [ok]   ripaojiedian/freenode                     184 KB  (raw.githubusercontent.com)
  [ok]   peasoft/NoMoreWalls                       427 KB  (raw.githubusercontent.com)
  [ok]   mahdibland/ShadowsocksAggregator           45 KB  (raw.githubusercontent.com)
  [ok]   cysk003/freeSub                           271 KB  (raw.githubusercontent.com)
  [ok]   ts-sf/fly                                 243 KB  (raw.githubusercontent.com)
  [ok]   free18/v2ray                              209 KB  (raw.githubusercontent.com)
  [ok]   chengaopan/AutoMergePublicNodes           427 KB  (raw.githubusercontent.com)
  [ok]   freeclashnode.com                          98 KB  (freeclashnode.com/20261116)
  [ok]   clashnode.me                               98 KB  (clashnode.me/20261116)
  [skip] nodefree.org                           20261116 -> <urlopen error [Errno -2] Name or servic | 20261115 -> <urlopen error [Errno -2] Name or servic
  [skip] v2rayshare.com                         20261116 -> <urlopen error [Errno -2] Name or servic | 20261115 -> <urlopen error [Errno -2] Name or servic
  抓取完成: 成功 12 / 14，用时 7.7s
[3/9] 解析 / 清洗 / 去重
  anaer_Sub__clash.yaml.yaml               新增 2140
  chengaopan_AutoMergePublicNodes__list.ym 新增  108
  cysk003_freeSub__clash.yaml.yaml         新增  500
  daily_clashnode.me_20261116.yaml         新增   92
  daily_freeclashnode.com_20261116.yaml    新增    0
  ermaozi01_free_clash_vpn__subscribe_clas 新增   18
  ermaozi_get_subscribe__subscribe_clash.y 新增  200
  free18_v2ray__c.yaml.yaml                新增  277
  mahdibland_ShadowsocksAggregator__Eterni 新增  126
  peasoft_NoMoreWalls__list.yml.yaml       新增    2
  ripaojiedian_freenode__clash.yaml        新增    7
  ts-sf_fly__clash.yaml                    新增  189
  去重后候选: 3671（用时 2.5s）
[4/9] 内核校验
  mihomo 版本: v1.19.34
  Mihomo Meta v1.19.34 linux amd64 with go1.26.11 Wed Nov 11 06:48:42 UTC 2026
  剔除非法节点 2，剩余 3669（用时 1.7s）
    - vless nl41.homelab-cdn.cloud (invalid REALITY short ID)
    - vless sweden.dance-tonic.rutube.info (invalid REALITY short ID)
[5/9] 初筛：真实请求（128 线程，1 轮）
  内核可见代理: 3669 / 3669
  直连自测: 12ms
    轮次 1: 500/3669  存活 30  4s
    轮次 1: 1000/3669  存活 84  8s
    轮次 1: 1500/3669  存活 98  13s
    轮次 1: 2000/3669  存活 99  18s
    轮次 1: 2500/3669  存活 173  26s
    轮次 1: 3000/3669  存活 249  32s
    轮次 1: 3500/3669  存活 407  35s
  轮次 1 完成，39s，存活 416
  探测错误样例 -> n0094: HTTP Error 503: Service Unavailable
  探测错误样例 -> n0078: HTTP Error 503: Service Unavailable
  探测错误样例 -> n0104: HTTP Error 503: Service Unavailable
  探测地址 http://www.gstatic.com/generate_204        存活 416 / 3669
[6/9] 严格验证：谷歌 + YouTube 可达性（2 轮，机房延迟门槛 200ms）
  分 3 批跑，每批 ≤150 个节点（少开端口、少占内存）
    50/150 已测  通过 44  3s
    100/150 已测  通过 92  6s
    150/150 已测  通过 138  34s
  本批 150 个节点实测完成 34s（通过 138）
    50/150 已测  通过 46  5s
    100/150 已测  通过 96  9s
    150/150 已测  通过 138  31s
  本批 150 个节点实测完成 31s（通过 138）
    50/116 已测  通过 50  2s
    100/116 已测  通过 97  4s
  本批 116 个节点实测完成 13s（通过 113）
  协议筛选：只留 ss/trojan，剔除 222 个（reality/ws 在国内实测 0% 通过）
[7/9] 查询归属地（先查，因为亚太门槛和探针挑样都要看国家）
  已知归属: 177 / 177（用时 0.1s）
[8/9] 上海探针实测（globalping.io，Shanghai）
  地区筛选（asia_na）：剔除 113 个其他地区，待测 81 个（US:45,SG:11,CA:11,JP:6,HK:5,KR:3）；预算 200，超出时按 亚太 > 加拿大 > 美国 优先
    20/81 已量（有数据 3）84s  剩余额度 215
    40/81 已量（有数据 5）150s  剩余额度 185
    60/81 已量（有数据 4）259s  剩余额度 144
    80/81 已量（有数据 5）340s  剩余额度 115
  探针测量完成 343s，有数据 5 / 73
  上海 -> 节点 RTT: 最快 92ms / 中位 131ms / 最慢 142ms（确定性结论 63 个：有 RTT 5、连不上 58；额度不足 0）
  按上海实测重判: 收回 0 个（≤120ms），降级 0 个（>120ms 或连不上），未量到 112 个（已淘汰）
  老节点复测: 保留 0 个（上海 ≤150ms）
  谷歌+YouTube 都通，且上海延迟 ≤120ms: 0 个 ✔
  延迟超标: 180 个，丢弃
  YouTube 不通（仅谷歌）: 6 个，丢弃
  两个站点都不通: 25 个，丢弃
  只有 YouTube 通、谷歌不通（可疑节点）: 5 个，丢弃
  双站都通的节点上海延迟分布: <100ms 11 | 100-200ms 33 | 200-400ms 40 | 400-800ms 86 | >800ms 16
  （当前上海门槛 120ms；太严/太松就调 --cn-max-delay）
  没有一个节点通过全部门槛，保留上一版订阅，不下发空配置
::error title=流水线失败::最终 0 个节点通过（候选 194，上海探针有数据 7）；可能是探针被限流或当天节点质量差，可调 --cn-max-delay
```
