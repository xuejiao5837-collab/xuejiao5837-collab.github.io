#!/usr/bin/env python3
"""GitHub Actions 定时任务：抓取 QQQ/SPY/VGT/SMH 行情与市盈率，更新本目录 snapshot.json
用法：python3 data-share/fetch_data.py（在仓库根目录运行亦可）"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server

data = server.get_quotes(force=True)
data.pop("_errors", None)
if not data:
    sys.exit("未获取到任何行情，沿用上次快照")

# 部分失败时，缺的标的沿用旧值
try:
    with open(os.path.join(HERE, "snapshot.json")) as f:
        old = json.load(f)
    for k, v in data.items():
        old[k] = v
    data = old
except Exception:
    pass

with open(os.path.join(HERE, "snapshot.json"), "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
print("OK:", ", ".join(data.keys()))
