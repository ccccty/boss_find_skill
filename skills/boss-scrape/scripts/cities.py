"""BOSS 直聘城市编码查询

编码来自官方接口 https://www.zhipin.com/wapi/zpCommon/data/city.json
首次查询会拉取全量城市表并缓存到 ~/.boss-skill/cities.json，
之后离线可用；常见城市内置，避免无网时不可用。

用法：
    from cities import resolve
    resolve(["上海", "成都"])   -> {"上海": 101020100, "成都": 101270100}
"""

import json
import os
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".boss-skill" / "cities.json"
API = "https://www.zhipin.com/wapi/zpCommon/data/city.json"

# 常见城市内置（接口不可用时的兜底）
BUILTIN = {
    "北京": 101010100, "上海": 101020100, "天津": 101030100, "重庆": 101040100,
    "广州": 101280100, "深圳": 101280600, "杭州": 101210100, "成都": 101270100,
    "南京": 101190100, "武汉": 101200100, "西安": 101110100, "苏州": 101190400,
    "长沙": 101250100, "郑州": 101180100, "东莞": 101281600, "佛山": 101280800,
    "珠海": 101280700, "厦门": 101230200, "合肥": 101220100, "青岛": 101120200,
    "宁波": 101210400, "无锡": 101190200, "福州": 101230100, "济南": 101120100,
    "大连": 101070200, "沈阳": 101070100, "昆明": 101290100, "南宁": 101300100,
    "贵阳": 101260100, "南昌": 101240100, "太原": 101100100, "石家庄": 101090100,
    "哈尔滨": 101050100, "长春": 101060100, "温州": 101210700, "常州": 101191100,
    "南通": 101190500, "徐州": 101190800, "扬州": 101190600, "绍兴": 101210500,
    "嘉兴": 101210300, "台州": 101210600, "舟山": 101211100, "海口": 101310100,
    "三亚": 101310200, "兰州": 101160100, "银川": 101170100, "西宁": 101150100,
    "乌鲁木齐": 101130100, "呼和浩特": 101080100, "拉萨": 101140100,
    # 四川
    "自贡": 101270300, "泸州": 101271000, "宜宾": 101271100, "乐山": 101271400,
    "绵阳": 101270600, "德阳": 101270500, "南充": 101271700, "达州": 101272100,
}


def _fetch_all():
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    raw = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    out = {}
    for prov in raw["zpData"]["cityList"]:
        out[prov["name"]] = prov["code"]
        for c in prov.get("subLevelModelList") or []:
            out[c["name"]] = c["code"]
    return out


def load(force_refresh=False):
    table = dict(BUILTIN)
    if CACHE.exists() and not force_refresh:
        try:
            table.update(json.loads(CACHE.read_text(encoding="utf-8")))
            return table
        except Exception:
            pass
    try:
        fetched = _fetch_all()
        table.update(fetched)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(fetched, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[城市表] 在线获取失败，使用内置表（{str(e)[:60]}）")
    return table


def resolve(names, force_refresh=False):
    table = load(force_refresh)
    found, missing = {}, []
    for n in names:
        n = n.strip()
        if not n:
            continue
        if n in table:
            found[n] = table[n]
        else:
            missing.append(n)
    if missing:
        raise SystemExit(
            f"[错误] 找不到城市编码: {missing}\n"
            f"        请检查城市名（用「市」之前的简称，如「苏州」而不是「苏州市」），"
            f"或手动在 cities.py 的 BUILTIN 中补充编码。"
        )
    return found


if __name__ == "__main__":
    import sys
    names = sys.argv[1:] or ["上海", "成都", "南京", "宜宾", "自贡"]
    print(json.dumps(resolve(names), ensure_ascii=False, indent=2))
