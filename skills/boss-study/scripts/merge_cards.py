#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把候选卡片并入站点的 cards.json —— 四道闸门 + 幂等写入。

这个脚本存在的意义不是「写文件」，而是**拒收**：
低质卡片一旦进了题库就会被背进脑子，错概念比没概念更贵。
所以这里对八字段做硬校验，不合格直接报错退出，不做「尽力修复」。

四道闸门
--------
1. 结构：八个字段齐全，长度在合理区间
2. 空话：jd 不许写「该岗位要求掌握」，trap 不许写「注意安全」这类正确的废话
3. 可量化：pts 至少有一条含数值/公式/量级
4. 去重：按术语归一化后比对已有卡片，重复的跳过（幂等，可反复跑）

用法
----
    # 先看会新增什么、跳过什么
    python scripts/merge_cards.py --cards site/cards.json --input cands/2026-10-26.json --dry-run

    # 确认后正式写入
    python scripts/merge_cards.py --cards site/cards.json --input cands/2026-10-26.json
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys

# ----------------------------------------------------------------------------
# 校验规则
# ----------------------------------------------------------------------------
LIMITS = {
    "term": (2, 40),
    "en":   (0, 80),
    "one":  (10, 140),
    "jd":   (15, 220),
    "use":  (10, 220),
    "trap": (12, 220),
}
PTS_MIN, PTS_MAX = 3, 5

# jd 写成这样就等于没写：要么是空话，要么把「要求」当成了「场景」
JD_BANNED = [
    "该岗位要求掌握", "岗位要求掌握本概念", "这是.*重要概念", "需要了解本概念",
    "岗位必备", "重要知识点", "核心概念之一", "必须掌握的概念",
]
TRAP_BANNED = [
    "注意安全", "参数要调好", "需要经验", "视情况而定", "合理配置", "多加注意",
    "注意规范", "根据实际情况", "多加练习", "不要犯错", "谨慎使用",
]
# 「可量化」：数字、单位、公式记号任选其一
QUANT_RE = re.compile(
    r"\d|%|‰|倍|毫秒|微秒|纳秒|Hz|dB|℃|km/h|m/s|fps|ppm|bit|字节|帧|像素|"
    r"σ|方差|标准差|阈值|量级|约.{0,4}倍|不超过|至少|上限|下限")
PAREN_RE = re.compile(r"[（(][^）)]*[）)]")


def norm(s):
    """术语归一化：去空白、去括号注释、转小写。"""
    s = PAREN_RE.sub("", s or "")
    return re.sub(r"\s+", "", s).lower()


def stable_id(term):
    """按术语生成稳定 id（djb2 变体）。

    不能用数组下标：cards.json 顺序一变，用户手机上已有的复习进度
    就会错位到别的卡片上，而且完全无法察觉。
    """
    h = 5381
    for ch in term:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return "x" + base36(h)


def base36(n):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def check_card(c, cat_keys):
    """返回错误列表，空表示通过。"""
    errs = []
    for f, (lo, hi) in LIMITS.items():
        v = c.get(f)
        if f == "en" and (v is None or v == ""):
            continue
        if not isinstance(v, str) or not v.strip():
            errs.append(f"缺少字段 {f}")
            continue
        n = len(v.strip())
        if n < lo or n > hi:
            errs.append(f"{f} 长度 {n} 超出 {lo}~{hi}")
    if c.get("term") and PAREN_RE.search(c["term"]):
        errs.append("term 不要带括号注释（英文名放 en 字段）")

    cat = c.get("cat")
    if not cat:
        errs.append("缺少 cat")
    elif cat_keys and cat not in cat_keys:
        errs.append(f"cat「{cat}」未在 cats 里注册（先加分类，别让卡片落在未定义分类）")

    pts = c.get("pts")
    if not isinstance(pts, list) or not (PTS_MIN <= len(pts) <= PTS_MAX):
        errs.append(f"pts 需要 {PTS_MIN}~{PTS_MAX} 条，当前 "
                    f"{len(pts) if isinstance(pts, list) else '非数组'}")
    else:
        empty = [i for i, p in enumerate(pts) if not isinstance(p, str) or not p.strip()]
        if empty:
            errs.append(f"pts 第 {[i + 1 for i in empty]} 条为空")
        elif not any(QUANT_RE.search(p) for p in pts):
            errs.append("pts 至少一条要含可量化信息（数值/单位/量级/公式），否则背了也用不上")

    jd = (c.get("jd") or "")
    for bad in JD_BANNED:
        if re.search(bad, jd):
            errs.append(f"jd 是空话（命中「{bad}」）：要写岗位原话 + 面试追问点")
            break
    trap = (c.get("trap") or "")
    for bad in TRAP_BANNED:
        if bad in trap:
            errs.append(f"trap 是废话（命中「{bad}」）：要写具体、可验证、会真的踩到的坑")
            break
    return errs


def load_site(path):
    if not os.path.isfile(path):
        return {"v": 2, "site": {}, "updated": "", "cats": {}, "cards": []}
    d = json.loads(open(path, encoding="utf-8").read())
    d.setdefault("cats", {})
    d.setdefault("cards", [])
    d.setdefault("v", 2)
    return d


def main():
    ap = argparse.ArgumentParser(description="候选卡片 → 站点 cards.json（校验 + 幂等）")
    ap.add_argument("--cards", required=True, help="站点里的 cards.json")
    ap.add_argument("--input", required=True, help="候选卡片 JSON（含 cards 数组）")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    ap.add_argument("--allow-dup", action="store_true", help="允许重复术语（默认跳过）")
    args = ap.parse_args()

    site = load_site(args.cards)
    try:
        cand = json.loads(open(args.input, encoding="utf-8").read())
    except Exception as e:
        sys.exit(f"[错误] 读候选文件失败：{e}")
    items = cand.get("cards") if isinstance(cand, dict) else cand
    if not isinstance(items, list):
        sys.exit("[错误] 候选文件里没有 cards 数组")
    if not items:
        print("[结果] 候选文件是空的，没有可并入的卡片")
        return

    # 候选文件可以顺带带分类定义，缺的分类要在合并前注册上
    new_cats = (cand.get("cats") or {}) if isinstance(cand, dict) else {}
    cat_keys = set(site["cats"]) | set(new_cats)

    existing = {norm(c.get("term", "")) for c in site["cards"]}
    existing |= {norm(c.get("en", "")) for c in site["cards"] if c.get("en")}

    today = datetime.date.today().isoformat()
    added, skipped, failed = [], [], []

    for i, c in enumerate(items):
        label = (c.get("term") or f"#{i + 1}")
        errs = check_card(c, cat_keys)
        # 候选文件自带分类时，允许卡片先用它，后面统一注册
        if errs and any("未在 cats 里注册" in e for e in errs) and c.get("cat") in new_cats:
            errs = [e for e in errs if "未在 cats 里注册" not in e]
        if errs:
            failed.append((label, errs))
            continue

        key = norm(c["term"])
        if not args.allow_dup and (key in existing or (c.get("en") and norm(c["en"]) in existing)):
            skipped.append((label, "术语已存在"))
            continue

        card = {
            "id": stable_id(c["term"]),
            "cat": c["cat"],
            "term": c["term"].strip(),
            "en": (c.get("en") or "").strip(),
            "one": c["one"].strip(),
            "jd": c["jd"].strip(),
            "pts": [p.strip() for p in c["pts"]],
            "use": c["use"].strip(),
            "trap": c["trap"].strip(),
            "added": c.get("added") or today,
        }
        ev = c.get("evidence")
        if isinstance(ev, dict) and ev:
            card["evidence"] = {"jobs": ev.get("jobs"), "sample": (ev.get("sample") or "")[:160]}
        added.append(card)
        existing.add(key)
        if c.get("en"):
            existing.add(norm(c["en"]))

    print(f"\n[校验] 候选 {len(items)} 张：通过 {len(added)}，"
          f"重复跳过 {len(skipped)}，不合格 {len(failed)}")
    for label, why in skipped:
        print(f"  - 跳过 {label}：{why}")
    for label, errs in failed:
        print(f"  ✗ 拒收 {label}：")
        for e in errs:
            print(f"      · {e}")
    if added:
        print(f"\n[新增] {len(added)} 张")
        for c in added:
            print(f"  + [{c['cat']}] {c['term']}  —  {c['one'][:42]}")

    if args.dry_run:
        print("\n[dry-run] 未写文件。确认无误后去掉 --dry-run 再跑一次。")
        return
    if not added and not new_cats:
        print("\n[结果] 没有新增，文件未改动")
        return

    # 注册新分类；颜色按色板轮转，避免全站一个色
    PALETTE = ["#1b4b8f", "#0e7490", "#0d9488", "#7c3aed", "#c2410c", "#0369a1",
               "#b91c1c", "#4d7c0f", "#9333ea", "#0f766e", "#a16207", "#be185d",
               "#2563eb", "#059669", "#d97706", "#dc2626"]
    for k, v in new_cats.items():
        if k in site["cats"]:
            continue
        if isinstance(v, str):
            v = {"name": v}
        site["cats"][k] = {
            "name": v.get("name", k),
            "color": v.get("color") or PALETTE[len(site["cats"]) % len(PALETTE)],
            "scene": v.get("scene", ""),
        }

    site["cards"].extend(added)
    site["updated"] = today

    bak = args.cards + ".bak"
    shutil.copyfile(args.cards, bak)
    os.makedirs(os.path.dirname(os.path.abspath(args.cards)) or ".", exist_ok=True)
    with open(args.cards, "w", encoding="utf-8", newline="\n") as f:
        json.dump(site, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n[完成] {args.cards} 现有 {len(site['cards'])} 张；旧文件备份在 {bak}")


if __name__ == "__main__":
    main()
