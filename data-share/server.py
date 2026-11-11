#!/usr/bin/env python3
"""美股回撤监控 · 本地行情服务
- 静态页：/            → index.html
- 行情：/api/quotes    → 抓东方财富美股行情（服务端抓取，浏览器无跨域问题）
用法：python3 server.py [端口，默认 8787]
"""
import json, os, re, sys, time, threading, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
CACHE_TTL = 60                      # 秒
PE_TTL = 6 * 3600                   # 市盈率缓存 6 小时
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17 Safari/605.1.15")
# 东方财富 secid：105=纳斯达克，107=纽交所/Arca
TICKERS = {"QQQ": "105.QQQ", "SPY": "107.SPY", "VGT": "107.VGT", "SMH": "105.SMH"}
_pe_cache = {}
_pe_lock = threading.Lock()
_cache = {"t": 0, "data": None}
_lock = threading.Lock()
_last_err = {}


def fetch_pe(sym):
    """从 stockanalysis.com 抓当前市盈率(TTM)与前瞻市盈率，缓存 6 小时"""
    with _pe_lock:
        c = _pe_cache.get(sym)
        if c and time.time() - c["t"] < PE_TTL:
            return c["v"]
    url = f"https://stockanalysis.com/etf/{sym.lower()}/"
    html = _curl(url)

    def grab(label):
        m = re.search(re.escape(label) + r"\s*</td>\s*<td[^>]*>\s*(-?[\d.,]+)", html)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None

    v = {"peTTM": grab("PE Ratio"), "peFwd": grab("Forward PE")}
    with _pe_lock:
        _pe_cache[sym] = {"t": time.time(), "v": v}
    return v


def _curl(url, timeout=20):
    """用系统 curl 取文本（纳斯达克/stockanalysis 会拦截 urllib 的 TLS 指纹）"""
    import subprocess
    out = subprocess.run(["curl", "-sL", "--compressed", "-m", str(timeout),
                          "-A", UA, url], capture_output=True)
    return out.stdout.decode("utf-8", "ignore")


def get_json(url):
    try:
        return json.loads(_curl(url))
    except json.JSONDecodeError:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                  "Referer": "https://quote.eastmoney.com/"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))


def klines(secid, klt, beg="0", lmt=100000):
    """klt: 101=日线 102=周线；fqt=1 前复权（自动处理拆股）"""
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56"
           f"&klt={klt}&fqt=1&beg={beg}&end=20500101&lmt={lmt}")
    d = get_json(url)
    data = d.get("data") or {}
    rows = data.get("klines") or []
    out = []
    for line in rows:
        p = line.split(",")
        try:
            out.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                        "high": float(p[3]), "low": float(p[4])})
        except (ValueError, IndexError):
            continue
    return out, data.get("name", "")


def nasdaq_daily(sym, years=3):
    """备用日线源：纳斯达克官方接口（东财被限流时使用）"""
    import datetime as _dt
    today = _dt.date.today()
    frm = today - _dt.timedelta(days=365 * years)
    url = (f"https://api.nasdaq.com/api/quote/{sym}/historical?assetclass=etf"
           f"&fromdate={frm.isoformat()}&todate={today.isoformat()}&limit=9999")
    d = get_json(url)
    rows = (d.get("data") or {}).get("tradesTable", {}).get("rows") or []
    out = []
    for r in rows:
        try:
            mm, dd, yy = r["date"].split("/")
            out.append({"date": f"{yy}-{mm}-{dd}", "open": float(r["open"].replace(",", "")),
                        "close": float(r["close"].replace(",", "")),
                        "high": float(r["high"].replace(",", "")),
                        "low": float(r["low"].replace(",", ""))})
        except (KeyError, ValueError):
            continue
    out.sort(key=lambda b: b["date"])
    return out


def nasdaq_quote(sym):
    """备用实时快照：返回 (最新价, 涨跌幅%, 时间字符串)"""
    url = f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass=etf"
    d = (get_json(url).get("data") or {}).get("primaryData") or {}
    price = float(str(d.get("lastSalePrice", "")).replace("$", "").replace(",", ""))
    chg = float(str(d.get("percentageChange", "0")).replace("%", "").replace("+", ""))
    return price, chg, (d.get("lastTradeTimestamp") or "")


def to_weekly(daily):
    """日线合成周线"""
    import datetime as _dt
    buckets = {}
    for b in daily:
        y, w, _ = _dt.date.fromisoformat(b["date"]).isocalendar()
        k = (y, w)
        if k in buckets:
            cur = buckets[k]
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["date"] = b["date"]
        else:
            buckets[k] = dict(b)
    return [buckets[k] for k in sorted(buckets)]


def load_daily(sym, secid):
    """日线：东财优先，失败回退纳斯达克"""
    beg3 = time.strftime("%Y%m%d", time.gmtime(time.time() - 86400 * 365 * 3))
    try:
        dy, name = klines(secid, 101, beg=beg3)
        if len(dy) > 60:
            return dy, name, "eastmoney"
    except Exception:
        pass
    return nasdaq_daily(sym), sym, "nasdaq"


def last_swing_high(bars, price, w=10):
    """找"上一次的高点"：从最新往回扫，第一个 ±w 天窗口内的局部最高价
    （即最近的波段高点，反弹后创新高会自动刷新基准）。找不到则回退全史最高。"""
    n = len(bars)
    highs = [b["high"] for b in bars]
    for i in range(n - 1, -1, -1):
        lo, hi_ = max(0, i - w), min(n, i + w + 1)
        if highs[i] and highs[i] == max(highs[lo:hi_]) and highs[i] > price:
            return i
    return max(range(n), key=lambda i: highs[i] or 0)


def compute(sym, secid):
    dy, name, src = load_daily(sym, secid)
    if not dy:
        raise RuntimeError("无行情数据")
    last = dy[-1]
    price = last["close"]
    prev = dy[-2]["close"] if len(dy) > 1 else price
    chg = (price / prev - 1) * 100 if prev else 0.0
    mtime = last["date"]
    if src == "nasdaq":
        try:                                   # 用官方实时快照覆盖收盘价
            p, c, ts = nasdaq_quote(sym)
            if p > 0:
                price, chg, mtime = p, c, ts or mtime
        except Exception:
            pass
    ath_bar = max(dy, key=lambda b: b["high"])
    w52 = max(b["high"] for b in dy[-252:])
    p_idx = last_swing_high(dy, price)
    peak = dy[p_idx]
    try:
        pe = fetch_pe(sym)
    except Exception:
        pe = {"peTTM": None, "peFwd": None}
    return {
        "sym": sym, "name": name,
        "price": round(price, 2),
        "ath": round(peak["high"], 2),
        "athDate": peak["date"],
        "athAll": round(ath_bar["high"], 2),
        "athAllDate": ath_bar["date"],
        "w52": round(w52, 2),
        "dd": round((price / peak["high"] - 1) * 100, 2),
        "dd52": round((price / w52 - 1) * 100, 2),
        "chg": round(chg, 2),
        "peTTM": pe.get("peTTM"),
        "peFwd": pe.get("peFwd"),
        "time": mtime,
        "src": src,
    }


def get_quotes(force=False):
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["t"] < CACHE_TTL:
            return _cache["data"]
    out = {}
    from concurrent.futures import ThreadPoolExecutor

    def one(item):
        sym, secid = item
        try:
            return sym, compute(sym, secid), None
        except Exception as e:
            return sym, None, str(e)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for sym, val, err in pool.map(one, TICKERS.items()):
            if val is not None:
                out[sym] = val
                _last_err.pop(sym, None)
            else:
                _last_err[sym] = err or "未知错误"
                if _cache["data"] and sym in _cache["data"]:
                    out[sym] = _cache["data"][sym]      # 失败时沿用上次成功的数据
    if _last_err:
        out["_errors"] = dict(_last_err)
    with _lock:
        _cache.update(t=time.time(), data=out)
    return out


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        if self.path.startswith("/api/quotes"):
            force = "force=1" in self.path
            try:
                body = json.dumps(get_quotes(force), ensure_ascii=False).encode()
                code = 200
            except Exception as e:
                body = json.dumps({"error": str(e)}, ensure_ascii=False).encode()
                code = 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"美股回撤监控已启动： http://127.0.0.1:{PORT}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
