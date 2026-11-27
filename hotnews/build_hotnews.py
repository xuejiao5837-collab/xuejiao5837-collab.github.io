# -*- coding: utf-8 -*-
"""抓取公开热榜源，按财经/AI/科技关键词筛选，生成每日热榜网站。"""
import json, re, html, urllib.request, datetime, os

import os as _os
OUT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# 关键词分类
CATS = {
    "股市基金": ["股", "A股", "美股", "港股", "基金", "ETF", "指数", "涨停", "大盘", "券商", "IPO", "上市", "财报", "市值", "涨跌", "纳指", "标普", "恒生", "央行", "美联储", "降息", "加息", "利率", "通胀", "GDP", "经济"],
    "AI科技": ["AI", "人工智能", "大模型", "芯片", "英伟达", "半导体", "算力", "机器人", "自动驾驶", "GPT", "算法", "科技", "特斯拉", "苹果", "华为", "小米", "手机", "软件", "开源", "数据中心", "云计算"],
    "价值投资": ["投资", "价值投资", "巴菲特", "芒格", "复利", "资产", "财富", "估值", "长期", "红利", "分红", "理财", "收益", "黄金", "比特币", "加密"],
    "创业商业": ["创业", "融资", "公司", "企业", "商业", "老板", "CEO", "营收", "裁员", "招聘", "电商", "直播带货", "品牌"],
}

def hit_cats(text):
    hits = []
    for cat, kws in CATS.items():
        if any(k.lower() in text.lower() for k in kws):
            hits.append(cat)
    return hits

def fetch(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def collect():
    items = []
    # 精确到分钟（北京时间 UTC+8），确保每次自动更新都产生可检测、肉眼可见的变化
    stamp = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") + " 北京时间"
    # 1. 微博/抖音/小红书热榜
    try:
        d = json.loads(fetch("https://solarhell.github.io/hot-search-crawler/latest.json").decode())
        for b in d.get("boards", []):
            plat = b.get("name", "")
            for it in b.get("items", []):
                title = it.get("title", "")
                cats = hit_cats(title)
                if not cats:
                    continue
                items.append({"platform": plat, "title": title, "url": it.get("url", ""),
                              "hot": it.get("hot", 0), "cats": cats,
                              "time": d.get("generated_at", "")[:16], "author": ""})
    except Exception as e:
        print("热榜抓取失败", repr(e))
    # 2. 华尔街见闻快讯
    try:
        d = json.loads(fetch("https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&client=pc&limit=30").decode())
        for it in d.get("data", {}).get("items", []):
            title = it.get("title") or re.sub(r"<[^>]+>", "", it.get("content_text") or "")[:80]
            if not title:
                continue
            cats = hit_cats(title)
            if not cats:
                continue
            au = it.get("author") or {}
            items.append({"platform": "华尔街见闻", "title": title,
                          "url": it.get("uri", "").replace("wscn://", "https://wallstreetcn.com/"),
                          "hot": 0, "cats": cats,
                          "time": datetime.datetime.fromtimestamp(it.get("display_time", 0), datetime.UTC).strftime("%Y-%m-%d %H:%M"),
                          "author": au.get("display_name", "")})
    except Exception as e:
        print("华尔街见闻抓取失败", repr(e))
    # 3. IT之家 RSS
    try:
        xml = fetch("https://www.ithome.com/rss/").decode("utf-8", "replace")
        for m in re.finditer(r"<item>([\s\S]*?)</item>", xml):
            blk = m.group(1)
            tm = re.search(r"<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>", blk)
            lm = re.search(r"<link>([\s\S]*?)</link>", blk)
            dm = re.search(r"<pubDate>([\s\S]*?)</pubDate>", blk)
            if not tm:
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
            cats = hit_cats(title)
            if not cats:
                continue
            items.append({"platform": "IT之家", "title": title,
                          "url": lm.group(1).strip() if lm else "",
                          "hot": 0, "cats": cats,
                          "time": dm.group(1)[:16] if dm else "", "author": ""})
    except Exception as e:
        print("IT之家抓取失败", repr(e))
    return items, stamp

def render(items, stamp):
    # 按分类分组，每类取前10
    groups = {}
    for cat in CATS:
        cats = [x for x in items if cat in x["cats"]]
        cats.sort(key=lambda x: (x["hot"] if isinstance(x["hot"], (int, float)) else 0), reverse=True)
        groups[cat] = cats[:10]
    tabs = "".join(f'<div class="tab{" on" if i==0 else ""}" data-c="{c}">{c} <span class="n">{len(groups[c])}</span></div>' for i, c in enumerate(CATS))
    panels = []
    for i, (cat, arr) in enumerate(groups.items()):
        rows = []
        for j, x in enumerate(arr, 1):
            hot = f'{x["hot"]:,}' if isinstance(x["hot"], (int, float)) and x["hot"] else "—"
            link = f'<a href="{html.escape(x["url"])}" target="_blank" rel="noopener">{html.escape(x["title"])}</a>' if x["url"] else html.escape(x["title"])
            rows.append(f'<tr><td class="rk">{j}</td><td><span class="pf">{html.escape(x["platform"])}</span></td>'
                        f'<td class="ti">{link}{"<div class=au>"+html.escape(x["author"])+"</div>" if x["author"] else ""}</td>'
                        f'<td class="ho">{hot}</td><td class="tm">{html.escape(x["time"])}</td></tr>')
        panels.append(f'<div class="panel{" on" if i==0 else ""}" id="p-{i}">'
                      f'<div class="tbl"><table><thead><tr><th>#</th><th>平台</th><th>标题</th><th>热度</th><th>时间</th></tr></thead>'
                      f'<tbody>{"".join(rows) if rows else "<tr><td colspan=5 class=empty>今日该分类暂无匹配热点</td></tr>"}</tbody></table></div></div>')
    plats = ["微博", "抖音", "小红书", "华尔街见闻", "IT之家"]
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日财经科技热榜 · 全网聚合</title>
<style>
:root{{--ink:#1a1a1a;--mut:#6b6b6b;--line:#e6e2d8;--bg:#f7f6f2;--ac:#8a6d3b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;line-height:1.6}}
.wrap{{max-width:1100px;margin:0 auto;padding:22px 18px 60px}}
.top{{background:#fff;border-bottom:1px solid var(--line)}}.top-in{{max-width:1100px;margin:0 auto;padding:12px 18px}}
.back{{color:var(--ac);text-decoration:none;font-size:13px}}
h1{{font-size:25px;margin:0 0 6px}}.sub{{color:var(--mut);font-size:13.5px;margin-bottom:16px}}
.note{{background:#FAEEDA;border-left:3px solid #BA7517;border-radius:6px;padding:10px 14px;font-size:12.5px;color:#633806;margin-bottom:18px}}
.tabs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;border-bottom:2px solid var(--line);padding-bottom:8px}}
.tab{{background:#efece4;border:1px solid var(--line);border-radius:8px;padding:7px 14px;font-size:13.5px;cursor:pointer;color:#444}}
.tab.on{{background:var(--ac);border-color:var(--ac);color:#fff;font-weight:600}}
.tab .n{{font-size:11px;opacity:.75}}
.panel{{display:none}}.panel.on{{display:block}}
.tbl{{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:11px 13px;text-align:left;border-bottom:1px solid #eee;vertical-align:top}}
th{{background:#faf8f3;color:#555;font-weight:600;font-size:12.5px}}
tr:last-child td{{border-bottom:none}}
.rk{{width:38px;color:#999;font-weight:700}}
.pf{{display:inline-block;padding:2px 8px;border-radius:10px;background:#E6F1FB;color:#185FA5;font-size:11.5px;white-space:nowrap}}
.ti a{{color:#1a1a1a;text-decoration:none}}.ti a:hover{{color:var(--ac);text-decoration:underline}}
.au{{font-size:11.5px;color:#999;margin-top:2px}}
.ho{{color:#c0392b;font-size:12.5px;white-space:nowrap}}
.tm{{color:#999;font-size:11.5px;white-space:nowrap}}
.empty{{text-align:center;color:#999;padding:30px}}
.foot{{font-size:12px;color:var(--mut);line-height:1.9;margin-top:26px;border-top:1px solid var(--line);padding-top:14px}}
</style></head><body>
<div class="top"><div class="top-in"><a class="back" href="index.html">← 返回主页</a></div></div>
<div class="wrap">
<h1>每日财经科技热榜</h1>
<div class="sub">聚合微博 / 抖音 / 小红书 / 华尔街见闻 / IT之家的公开热榜与快讯，按财经、AI、科技、价值投资关键词筛选 · 更新于 {stamp}</div>
<div class="note"><b>数据来源说明：</b>本页使用公开渠道（热榜爬虫每10分钟快照 + 财经媒体公开快讯/RSS），按关键词自动筛选，非各平台官方"财经领域博主排行榜"。X（推特）、微信公众号、快手的垂直领域爆款数据需登录或付费接口，暂未纳入。点击标题可跳转原平台查看。</div>
<div class="tabs">{tabs}</div>
{''.join(panels)}
<div class="foot"><b>口径：</b>热度值为各平台公开热度指标，不同平台量纲不同不可横向比较；华尔街见闻按编辑精选排序、IT之家按发布时间。"前10"指每个分类下按热度/时效排序的前10条，当日不足10条则显示实际条数。<br><b>更新机制：</b>每日自动抓取公开源重新生成。数据仅供快速浏览，版权归原平台及作者所有。</div>
</div>
<script>
(function(){{
 var tabs=document.querySelectorAll('.tab');
 tabs.forEach(function(t){{t.addEventListener('click',function(){{
   tabs.forEach(function(x){{x.classList.remove('on')}});
   document.querySelectorAll('.panel').forEach(function(p){{p.classList.remove('on')}});
   t.classList.add('on');document.getElementById('p-'+t.dataset.c).classList.add('on');
 }});}});
}})();
</script></body></html>'''

if __name__ == "__main__":
    items, stamp = collect()
    print("抓取到匹配条目", len(items))
    for cat in CATS:
        print(" ", cat, len([x for x in items if cat in x["cats"]]))
    page = render(items, stamp)
    open(os.path.join(OUT, "daily-hot.html"), "w", encoding="utf-8").write(page)
    json.dump({"items": items, "stamp": stamp}, open(os.path.join(OUT, "data.json"), "w"), ensure_ascii=False)
    print("网站已生成", len(page), "字符")
