#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从模板生成一个可安装到手机的学习站。

一个领域一个站：换领域就是重新跑一次这条命令，站点代码不用动。
生成的是**纯静态文件**，直接 git push 到 GitHub Pages 就能用。

用法
----
    # 生成新站（目录不存在才会建）
    python scripts/build_site.py --out ../../数据安全-study --title "数据安全 · 每日一推" \
        --desc "数据安全与合规岗的高频概念，每天 8 张"

    # 已有站想改标题，先删目录或加 --force
    python scripts/build_site.py --out my-study --title "..." --force
"""

import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets", "site")


def sub1(text, pattern, repl):
    new, n = re.subn(pattern, repl, text, count=1, flags=re.S)
    if n == 0:
        print(f"[提示] 没匹配到 {pattern[:30]}，跳过（模板可能已变动）")
    return new


def main():
    ap = argparse.ArgumentParser(description="生成一个学习站")
    ap.add_argument("--out", required=True, help="目标目录")
    ap.add_argument("--title", required=True, help="站点标题，如「数据安全 · 每日一推」")
    ap.add_argument("--short", default="", help="主屏图标下的短名，默认取标题前 4 字")
    ap.add_argument("--desc", default="", help="一句话描述")
    ap.add_argument("--new-per-day", type=int, default=8, help="每日新卡数（默认 8）")
    ap.add_argument("--force", action="store_true", help="目录已存在时覆盖站点文件（不动 cards.json）")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    if os.path.exists(out) and not args.force:
        sys.exit(f"[错误] {out} 已存在。想重建请加 --force（会覆盖站点文件，但保留 cards.json）")

    short = args.short or args.title.split("·")[0].strip()[:4] or "概念卡"
    desc = args.desc or (args.title + "：把岗位高频概念做成卡片，每天刷几张。")

    os.makedirs(out, exist_ok=True)
    # 图标等资源整体拷贝
    for name in os.listdir(ASSETS):
        if name == "cards.json":
            continue
        src, dst = os.path.join(ASSETS, name), os.path.join(out, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copyfile(src, dst)

    # 标题/描述写进页面
    p = os.path.join(out, "index.html")
    html = open(p, encoding="utf-8").read()
    html = sub1(html, r"<title>.*?</title>", f"<title>{args.title}</title>")
    html = sub1(html, r'<meta name="description" content="[^"]*">',
                f'<meta name="description" content="{desc}">')
    html = sub1(html, r'<meta name="apple-mobile-web-app-title" content="[^"]*">',
                f'<meta name="apple-mobile-web-app-title" content="{short}">')
    html = sub1(html, r'<span id="brand">[^<]*</span>', f'<span id="brand">{args.title}</span>')
    open(p, "w", encoding="utf-8", newline="\n").write(html)

    # manifest
    mf = os.path.join(out, "manifest.webmanifest")
    m = json.loads(open(mf, encoding="utf-8").read())
    m["name"] = args.title
    m["short_name"] = short
    m["description"] = desc
    with open(mf, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # Service Worker 版本号带上标题指纹，两个站同域时不会互相覆盖缓存
    sw = os.path.join(out, "sw.js")
    s = open(sw, encoding="utf-8").read()
    fp = str(abs(hash(args.title)) % 100000)
    s = re.sub(r"const VERSION = '[^']*'", f"const VERSION = 'cards-{fp}'", s, count=1)
    open(sw, "w", encoding="utf-8", newline="\n").write(s)

    # cards.json：已存在就不动，避免把已有题库覆盖掉
    cj = os.path.join(out, "cards.json")
    if os.path.exists(cj):
        print(f"[保留] {cj} 已存在，未覆盖")
    else:
        skeleton = {
            "v": 2,
            "site": {"title": args.title, "desc": desc, "newPerDay": args.new_per_day},
            "updated": "",
            "cats": {},
            "cards": [],
        }
        with open(cj, "w", encoding="utf-8", newline="\n") as f:
            json.dump(skeleton, f, ensure_ascii=False, indent=2)
            f.write("\n")

    # GitHub Pages 会跑 Jekyll，以下划线开头的文件会被忽略；关掉它
    open(os.path.join(out, ".nojekyll"), "w").close()

    # merge_cards.py 每次写入前会留一份 .bak，别提交进仓库
    gi = os.path.join(out, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8", newline="\n") as f:
            f.write("*.bak\n.DS_Store\nThumbs.db\n")

    print(f"[完成] 站点已生成：{out}")
    print("  下一步：")
    print("    1. 写卡片（或跑 merge_cards.py 并入），cards.json 是唯一数据源")
    print("    2. 本地预览：python -m http.server 8080 后打开 http://127.0.0.1:8080/")
    print("    3. 部署：git init && git add -A && git commit -m init && git push")


if __name__ == "__main__":
    main()
