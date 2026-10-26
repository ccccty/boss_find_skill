"""按个人简历给岗位打分排序（可复用的规则版匹配）

思路：把简历拆成若干「能力组」，每组有权重和关键词；扫描岗位名 + JD 正文命中即加分；
再按「经验门槛 / 学历 / 是否偏现场 / 是否要注册证 / 是否证书挂靠」扣分。
最终分 = 相关性归一化 × 风险折扣。

用法：
    python match.py --input ../boss-scrape/data/xxx_detail.json \
                    --profile profiles/example_profile.json \
                    --out data/matched.json --csv data/推荐清单.csv \
                    --html reports/匹配报告.html

    python match.py --init profile.json      # 生成一份可编辑的空白画像

注意：匹配分衡量的是「JD 和你的能力重合度」，不是录取概率。
"""

import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from report_kit import page, kpis, bar_rows, abs_url, esc, parse_salary_monthly  # noqa: E402

TEMPLATE = {
    "name": "候选人",
    "headline": "一句话概括你的方向（会显示在报告页眉）",
    "facts": ["学历 / 专业 / 毕业时间", "代表项目或成果 1", "代表项目或成果 2"],
    "groups": {
        "专业背景": {"weight": 5, "words": ["把你的专业关键词填进来", "例如 港航", "水利"]},
        "核心技能": {"weight": 5, "words": ["你的看家本事关键词"]},
        "工具软件": {"weight": 4, "words": ["Python", "MATLAB", "CAD"]},
        "行业交叉": {"weight": 4, "words": ["能和你专业叠加的行业词"]},
    },
    # 岗位名含以下任一词 → 直接丢弃（明显不对口，如销售、送水工）
    "drop_names": ["销售", "客服", "文员", "前台", "司机", "厨师", "学徒", "主播"],
    # 额外扣分规则（叠加在内置规则之上）
    "penalty_words": [
        {"words": ["地质", "岩土", "矿山"], "score": 8, "gap": "方向偏离你的主线"}
    ],
    # 只投这些经验门槛的岗位（用于报告里的「优先投递」清单）
    "friendly_experience": ["经验不限", "应届生", "1年以内", "1-3年", "在校生", ""],
}

# 内置扣分规则：任何「应届 / 转行」候选人都适用
BUILTIN_PENALTY = [
    (["5-10年", "10年以上"], 16, "经验门槛远高于你"),
    (["3-5年"], 6, "经验门槛略高"),
]
FIELD_WORDS = ["施工员", "监理", "安全员", "资料员", "造价", "测量员",
               "项目经理", "总工", "生产经理", "技术负责人"]
CERT_WORDS = ["一级建造师", "注册土木", "注册结构", "注册给排水", "注册电气"]
FAKE_WORDS = ["建造师", "挂靠", "兼职", "讲师", "带B", "带b"]


def score(job, profile):
    text = f"{job.get('name', '')} {job.get('description') or ''}"
    hits, raw = {}, 0
    for group, cfg in profile["groups"].items():
        w = cfg.get("weight", 3)
        found = [x for x in cfg.get("words", []) if x and x in text]
        if found:
            raw += w * min(len(found), 3)      # 同组最多计 3 个词，防止长 JD 刷分
            hits[group] = found[:5]

    pen, gaps = 0, []
    name = job.get("name", "")
    exp = job.get("experience", "") or ""
    edu = job.get("education", "") or ""

    for words, p, gap in BUILTIN_PENALTY:
        if any(w in exp for w in words):
            pen += p
            gaps.append(gap)
    if "大专" in edu:
        pen += 8
        gaps.append("学历门槛低于你（可能被视为超配）")
    if any(w in name for w in FIELD_WORDS):
        pen += 10
        gaps.append("偏现场施工/管理，与研发设计路径不同")
    if any(w in (name + text) for w in CERT_WORDS):
        pen += 5
        gaps.append("要求注册类证书")
    if any(w in name for w in FAKE_WORDS):
        pen += 25
        gaps.append("证书挂靠/兼职性质，非全职技术岗")
    for rule in profile.get("penalty_words", []):
        if any(w in name for w in rule.get("words", [])):
            pen += rule.get("score", 5)
            gaps.append(rule.get("gap", "命中自定义扣分规则"))
    return raw, pen, hits, gaps


def run(args):
    jobs = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(jobs, dict) and "jobs" in jobs:
        jobs = jobs["jobs"]
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))

    drop = profile.get("drop_names", [])
    pool = []
    for j in jobs:
        if not j.get("description"):
            continue
        if any(w in j.get("name", "") for w in drop):
            continue
        pool.append(j)

    for j in pool:
        raw, pen, hits, gaps = score(j, profile)
        j["raw_score"], j["risk"] = raw, pen
        j["hits"], j["gaps"] = hits, gaps

    mx = max((j["raw_score"] for j in pool), default=1) or 1
    for j in pool:
        base = j["raw_score"] / mx * 97
        m = round(base * (1 - min(j["risk"], 40) / 100))
        if j["raw_score"] < 8:
            m = min(m, 18)
        j["match"] = max(2, min(97, m))

    pool.sort(key=lambda x: -x["match"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- CSV ----
    friendly = set(profile.get("friendly_experience", []))
    prio = [j for j in pool
            if (j.get("experience") or "") in friendly and j["match"] >= 38
            and not any(w in (j.get("salary") or "") for w in ("元/时", "元/天"))]
    csv_rows = prio[:40] + [j for j in pool if j not in prio][: (40 - min(len(prio), 40))]
    fields = ["优先级", "匹配分", "城市", "岗位", "公司", "月薪", "经验", "学历",
              "命中能力", "缺口提示", "工作地点", "链接"]
    csv_path = Path(args.csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, j in enumerate(csv_rows, 1):
            w.writerow({
                "优先级": i, "匹配分": j["match"],
                "城市": j.get("city") or (j.get("location", "").split("·")[0]),
                "岗位": j.get("name"), "公司": j.get("company"), "月薪": j.get("salary"),
                "经验": j.get("experience"), "学历": j.get("education"),
                "命中能力": "、".join(g[0] for g in j["hits"].values()),
                "缺口提示": "；".join(j["gaps"]),
                "工作地点": j.get("location"), "链接": abs_url(j.get("link")),
            })

    # ---- HTML ----
    if args.html:
        build_html(pool, prio, profile, Path(args.html))

    good = sum(1 for j in pool if j["match"] >= 70)
    ok = sum(1 for j in pool if 40 <= j["match"] < 70)
    print(f"[完成] 打分 {len(pool)} 条（原始 {len(jobs)}）")
    print(f"        ≥70 分 {good} 条 / 40-69 分 {ok} 条 / 优先投递 {len(prio)} 条")
    print(f"        {args.out}\n        {args.csv}" + (f"\n        {args.html}" if args.html else ""))


def build_html(pool, prio, profile, out):
    monthly = [v for v in (parse_salary_monthly(j.get("salary")) for j in pool) if v]
    med = f"{statistics.median(monthly):.1f}K" if monthly else "—"
    group_cnt = Counter(g for j in pool for g in j["hits"])
    gap_cnt = Counter(g for j in pool for g in j["gaps"])

    def rows(items, start=1):
        out_rows = []
        for i, j in enumerate(items, start):
            tags = "".join(f"<em>{esc(x)}</em>" for g in j["hits"].values() for x in g[:2])
            gaps = "".join(f'<span class="gap">{esc(g)}</span>' for g in j["gaps"])
            cls = "hi" if j["match"] >= 70 else ("mid" if j["match"] >= 45 else "lo")
            out_rows.append(f"""<tr class="row-main">
  <td class="num dim">{i}</td>
  <td><span class="sc {cls}">{j['match']}</span></td>
  <td><b>{esc(j.get('name'))}</b><div class="sub2">{esc(j.get('company', ''))}</div>
      <div class="tags">{tags}{gaps}</div></td>
  <td class="sal">{esc(j.get('salary') or '面议')}</td>
  <td class="dim">{esc(j.get('experience') or '—')}<br>{esc(j.get('education') or '—')}</td>
  <td class="dim">{esc(j.get('city') or '')}</td>
  <td><a href="{abs_url(j.get('link'))}" target="_blank" rel="noopener">原页面</a></td>
</tr>""")
        return "\n".join(out_rows)

    head = """<table><thead><tr>
  <th style="width:32px">#</th><th style="width:52px">匹配</th><th>岗位 / 公司</th>
  <th style="width:94px">月薪</th><th style="width:78px">经验·学历</th>
  <th style="width:56px">城市</th><th style="width:56px"></th>
</tr></thead><tbody>"""

    body = [f"<div class='note'><b>{esc(profile['name'])}</b> · {esc(profile.get('headline', ''))}<ul>"
            + "".join(f"<li>{esc(f)}</li>" for f in profile.get("facts", [])) + "</ul></div>",
            kpis([(len(pool), "打分岗位"), (len(prio), "优先投递"),
                  (sum(1 for j in pool if j["match"] >= 70), "≥70 分"), (med, "月薪中位数")]),
            "<h2>一 · 能力命中分布</h2>",
            "<p class='lede' style='font-size:14px'>多少条岗位的 JD 里出现了你的各项能力，"
            "可以看出市场上到底在为哪些能力付钱。</p>",
            bar_rows(group_cnt.most_common()),
            "<h2>二 · 优先投递清单</h2>",
            "<p class='lede' style='font-size:14px'>经验门槛对你友好 + 匹配度达标，剔除实习/兼职/时薪岗。"
            "绿色为命中能力，红色为缺口。</p>",
            head + rows(prio[:12]) + "</tbody></table>",
            "<h2>三 · 全量排名 Top 20</h2>", head + rows(pool[:20]) + "</tbody></table>",
            "<h2>四 · 共性缺口</h2>",
            "<ul class='legend'>" + "".join(
                f"<li>{esc(g)}<b>{n}</b></li>" for g, n in gap_cnt.most_common(8)) + "</ul>",
            "<div class='note'><b>读表提醒：</b>匹配分是「JD 与你的能力重合度」，不是录取概率。"
            "分数高但经验写着 5-10 年的岗位，实际投递转化率很低；先看经验列，再看分数。</div>"]

    style_extra = """<style>
.sc{font-family:var(--mono);font-size:14px;padding:2px 6px;display:inline-block}
.sc.hi{background:#FEE7D6;color:#9A3412;font-weight:600}
.sc.mid{background:#F5F1EA;color:#B45309}.sc.lo{background:#F0EEE9;color:#A8A29E}
.tags{margin-top:4px}.tags em{font-style:normal;font-size:10.5px;background:#EEF4EE;color:#3F6212;
padding:1px 5px;margin:0 4px 4px 0;display:inline-block}
.gap{font-size:10.5px;background:#FDF0EC;color:#B91C1C;padding:1px 5px;margin:0 4px 4px 0;
display:inline-block}
</style>"""

    html = page(f"{profile['name']} · 岗位匹配报告",
                f"以个人能力画像为标尺，为 {len(pool)} 条岗位逐条打分，"
                f"其中 {len(prio)} 条进入优先投递清单。",
                [("打分岗位", len(pool)), ("优先投递", len(prio)),
                 ("月薪中位数", med), ("画像", profile["name"])],
                style_extra + "\n".join(body))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="按简历给岗位打分排序")
    ap.add_argument("--input", help="detail.json")
    ap.add_argument("--profile", default="profile.json", help="画像 JSON")
    ap.add_argument("--out", default="data/matched.json")
    ap.add_argument("--csv", default="data/推荐清单.csv")
    ap.add_argument("--html", default=None, help="同时生成 HTML 报告")
    ap.add_argument("--init", default=None, help="生成可编辑的画像模板后退出")
    args = ap.parse_args()
    if args.init:
        Path(args.init).write_text(json.dumps(TEMPLATE, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"已生成画像模板 {args.init}，填好关键词后再跑匹配。")
        return
    if not args.input:
        raise SystemExit("[错误] 需要 --input；或先用 --init 生成画像模板")
    run(args)


if __name__ == "__main__":
    main()
