"""把抓取结果变成一份可视化 HTML 报告（自包含、离线可看）

用法：
    python analyze.py --input ../boss-scrape/data/xxx_detail.json
    python analyze.py --input data --city "上海,南京" --title "上海南京 水利岗位报告"
    python analyze.py --input data/xxx_detail.json --dict 我的技能词.txt --top 60

设计要点（改之前先读 report_kit.py 顶部注释）：
- 全部图表用 CSS / conic-gradient，不引 CDN，断网也能看
- 岗位链接经 abs_url() 补全域名，避免 localhost 预览下 404
- 薪资只统计月薪样本，时薪/日薪单独说明，不混进中位数
"""

import argparse
import datetime
import json
import re
import statistics
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from report_kit import (page, kpis, bar_rows, donut, abs_url,  # noqa: E402
                        esc, parse_salary_monthly)

# 岗位类型判定（顺序即优先级，先命中先用）
CATEGORY_RULES = [
    ("设计/咨询", ["设计", "咨询", "规划", "评估", "方案", "可行性", "前期"]),
    ("造价/招投标", ["造价", "预算", "招投标", "商务经理", "成本"]),
    ("检测/测量", ["检测", "试验", "测量", "测绘", "勘察", "勘探", "监测"]),
    ("监理/安全", ["监理", "安全员", "安全工程", "质量员", "质检"]),
    ("施工/项目管理", ["施工", "项目经理", "生产经理", "总工", "技术负责人",
                   "项目负责人", "工程管理", "现场"]),
    ("算法/研发", ["算法", "模型", "研发", "开发", "数据分析", "机器学习", "AI",
               "深度学习", "仿真", "技术支持"]),
    ("运维/实施", ["运维", "实施", "售后", "交付", "调试"]),
    ("销售/市场", ["销售", "客户", "市场", "商务", "渠道", "营销", "售前"]),
    ("职能", ["人事", "行政", "财务", "会计", "法务", "招聘"]),
    ("通用工程岗", ["工程师", "技术员", "助理", "专员", "主管", "经理"]),
]

# JD 套话过滤：这些词在任何岗位里都高频，没有区分度
STOPWORDS = set("""工作 岗位 负责 相关 要求 优先 以上 具备 熟悉 熟练 掌握 良好 能力 经验 公司 职位
进行 完成 参与 协助 能够 以及 具有 一定 专业 学历 本科 硕士 大专 及以上 我们 你们 团队
提供 支持 根据 使用 通过 保证 确保 建立 完善 制定 组织 实施 服务 任职 职责 描述 加分
吃苦 耐劳 沟通 协调 学习 抗压 责任 心强 应届 毕业 具体 面议 岗位职责 任职资格 以上学历
较强 精神 问题 处理 解决 流程 情况 方面 时间 方式 内容 需求 客户 优秀 积极 主动 认真
态度 意识 效率 基础 综合 独立 高效 及时 规范 报告 编写 编制 整理 收集 分析 统计 计划
行业 领域 方向 情况 实际 相应 有关 各种 各类 各项 进一步 不断 持续 有效 合理 顺利
责任心 协作 合作 任务 办公 优化 软件 直聘 网站 理解 保持 适应 服从 遵守 严格""".split())


def load_jobs(path, cities=None):
    p = Path(path)
    if p.is_dir():
        cands = sorted(list(p.glob("*_detail.json")) + list(p.glob("*_jobs.json")),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        if not cands:
            raise SystemExit(f"[错误] {p} 下没有 *_detail.json / *_jobs.json")
        p = cands[0]
        print(f"[输入] 自动选择最新文件：{p.name}")
    jobs = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise SystemExit("[错误] 数据文件应为 JSON 数组（岗位列表）")
    for j in jobs:
        if not j.get("city"):
            j["city"] = (j.get("location", "") or "").split("·")[0]
    if cities:
        keep = set(cities)
        before = len(jobs)
        jobs = [j for j in jobs if j["city"] in keep]
        print(f"[过滤] 只看 {sorted(keep)}：{before} → {len(jobs)} 条")
    return jobs, p


def category(name):
    for label, kws in CATEGORY_RULES:
        if any(k in name for k in kws):
            return label
    return "其他"


def salary_bucket(v):
    if v is None:
        return None
    for edge in (8, 12, 16, 20, 30, 50):
        if v < edge:
            return {8: "8K 以下", 12: "8-12K", 16: "12-16K",
                    20: "16-20K", 30: "20-30K", 50: "30-50K"}[edge]
    return "50K 以上"


def skill_words(jobs, extra_dict=None, topn=20):
    try:
        import jieba
        import jieba.analyse
    except ImportError:
        print("[提示] 未安装 jieba，跳过技能词分析（pip install jieba）")
        return []
    for w in (extra_dict or []):
        jieba.add_word(w, tag="n")     # 标成名词，否则会被 allowPOS 过滤掉
    text = " ".join((j.get("name", "") + " " + (j.get("description") or "")) for j in jobs)
    # 公司名会被 TF-IDF 当成热词，先收集起来排除
    companies = {(j.get("company") or "").strip() for j in jobs}
    # allowPOS 只保留名词/专名/动名词/英文，能滤掉「较强」「独立」这类修饰语
    cand = jieba.analyse.extract_tags(text, topK=topn * 8,
                                      allowPOS=("n", "nz", "vn", "eng"))
    out = []
    for w in cand:
        if len(w) < 2 or w in STOPWORDS or re.fullmatch(r"[\d\W]+", w):
            continue
        if any(w in c for c in companies if c):
            continue
        n = sum(1 for j in jobs if w in (j.get("name", "") + (j.get("description") or "")))
        if n < max(2, len(jobs) // 200):     # 至少出现在若干条岗位里
            continue
        out.append((w, n))
    out.sort(key=lambda x: -x[1])
    return out[:topn]


def build(args):
    jobs, src = load_jobs(args.input, [c.strip() for c in args.city.split(",")] if args.city else None)
    if not jobs:
        raise SystemExit("[错误] 没有可分析的岗位")

    extra = []
    if args.dict and Path(args.dict).exists():
        extra = [line.strip() for line in Path(args.dict).read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]

    monthly = [v for v in (parse_salary_monthly(j.get("salary")) for j in jobs) if v]
    hourly = sum(1 for j in jobs if any(k in (j.get("salary") or "")
                                        for k in ("元/时", "元/天", "元/次")))
    med = f"{statistics.median(monthly):.1f}K" if monthly else "—"

    city_cnt = Counter(j["city"] for j in jobs)
    cat_cnt = Counter(category(j.get("name", "")) for j in jobs)
    exp_cnt = Counter((j.get("experience") or "未标注") for j in jobs)
    edu_cnt = Counter((j.get("education") or "未标注") for j in jobs)
    comp_cnt = Counter((j.get("company") or "").strip() for j in jobs if j.get("company"))
    buckets = Counter(salary_bucket(v) for v in monthly)
    order = ["8K 以下", "8-12K", "12-16K", "16-20K", "20-30K", "30-50K", "50K 以上"]
    bucket_items = [(b, buckets[b]) for b in order if buckets.get(b)]

    skills = skill_words(jobs, extra)

    body = [kpis([
        (len(jobs), "岗位样本"),
        (len(city_cnt), "覆盖城市"),
        (med, f"月薪中位数（{len(monthly)} 条可解析）"),
        (len(comp_cnt), "招聘公司数"),
    ])]

    if len(city_cnt) > 1:
        body.append("<h2>城市分布</h2>")
        body.append(f"<div style='margin-top:18px'>{bar_rows(city_cnt.most_common())}</div>")

    body.append("<h2>岗位类型</h2>")
    body.append(f"<div style='margin-top:18px'>{bar_rows(cat_cnt.most_common())}</div>")

    body.append("<h2>薪资、经验与学历</h2>")
    left = f"<h3>月薪区间（{len(monthly)} 条月薪样本）</h3>" + bar_rows(bucket_items)
    if hourly:
        left += (f"<p class='dim' style='margin-top:10px'>另有 {hourly} 条为时薪 / 日薪 / 计件岗位，"
                 f"未计入月薪中位数。</p>")
    right = ("<h3>经验门槛</h3>" + donut(exp_cnt.most_common(6), "岗位")
             + "<h3 style='margin-top:22px'>学历要求</h3>" + donut(edu_cnt.most_common(6), "岗位"))
    body.append(f"<div class='grid2'><div>{left}</div><div>{right}</div></div>")

    if skills:
        body.append("<h2>JD 高频词</h2>")
        body.append("<p class='lede' style='font-size:14px'>jieba 从岗位名 + JD 正文提取，"
                    "已过滤通用词；括号内为提及该词的岗位数。</p>")
        body.append(f"<div style='margin-top:18px'>{bar_rows(skills)}</div>")

    if len(comp_cnt) > 1:
        body.append("<h2>招聘公司 Top 10</h2>")
        body.append(f"<div style='margin-top:18px'>{bar_rows(comp_cnt.most_common(10))}</div>")

    # 明细
    detail = jobs[:]
    if args.sort == "salary":
        detail.sort(key=lambda j: (parse_salary_monthly(j.get("salary")) or -1), reverse=True)
    detail = detail[:args.top]

    rows = []
    for j in detail:
        rows.append(f"""<tr class="row-main">
  <td>{esc(j['city'])}</td>
  <td class="nm"><b>{esc(j.get('name'))}</b>
      <div class="sub2">{esc(j.get('company', ''))}</div></td>
  <td class="sal">{esc(j.get('salary') or '面议')}</td>
  <td class="dim">{esc(j.get('experience') or '—')}<br>{esc(j.get('education') or '—')}</td>
  <td class="dim">{esc(category(j.get('name', '')))}</td>
  <td class="dim">{esc(j.get('location') or '')}</td>
  <td><a href="{abs_url(j.get('link'))}" target="_blank" rel="noopener">原页面</a></td>
</tr>""")
        desc = esc(j.get("description") or "（未采集到 JD 正文）")
        meta = " · ".join(x for x in (j.get("industry"), j.get("scale"), j.get("financing")) if x)
        rows.append(f'<tr class="row-jd"><td colspan="7"><details><summary>查看 JD</summary>'
                    f'<p>{desc}</p><p class="jd-meta">{esc(meta)}</p></details></td></tr>')

    body.append(f"<h2>岗位明细（{len(detail)} / {len(jobs)}）</h2>")
    body.append("""<table><thead><tr>
  <th style="width:54px">城市</th><th>岗位 / 公司</th><th style="width:96px">月薪</th>
  <th style="width:78px">经验·学历</th><th style="width:96px">类型</th>
  <th style="width:132px">地点</th><th style="width:56px"></th>
</tr></thead><tbody>""" + "\n".join(rows) + "</tbody></table>")

    title = args.title or "岗位市场报告"
    sub = (f"样本来自 BOSS 直聘，共 {len(jobs)} 条岗位、{len(comp_cnt)} 家公司。"
           f"薪资统计仅计入可解析的月薪样本（{len(monthly)} 条）。")
    html = page(title, sub, [
        ("数据文件", src.name),
        ("样本量", len(jobs)),
        ("覆盖城市", " / ".join(city_cnt) if len(city_cnt) <= 6 else f"{len(city_cnt)} 城"),
        ("生成时间", datetime.date.today().isoformat()),
    ], "\n".join(body))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[完成] {out}（{len(html) / 1024:.0f} KB）")
    print(f"        {len(jobs)} 条岗位 · 月薪中位数 {med} · {len(skills)} 个高频词")
    if 'href="/' in html:
        raise SystemExit("[错误] 存在未补全域名的相对链接，会在本地预览时 404")


def main():
    ap = argparse.ArgumentParser(description="生成岗位市场 HTML 报告")
    ap.add_argument("--input", required=True, help="detail.json 文件，或包含它的目录")
    ap.add_argument("--out", default="reports/岗位市场报告.html")
    ap.add_argument("--title", default=None)
    ap.add_argument("--city", default=None, help="只看这些城市，逗号分隔")
    ap.add_argument("--dict", default=None, help="自定义技能词典文件（每行一个词）")
    ap.add_argument("--top", type=int, default=40, help="明细表最多展示多少条")
    ap.add_argument("--sort", choices=["default", "salary"], default="salary")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
