"""BOSS 直聘岗位抓取（CloakBrowser 反检测）— 两阶段版

阶段一：只翻列表页，把关键词 × 城市的所有卡片收下来（快、便宜）
阶段二：按「目标城市 + 岗位相关性」排序，只对候选岗位抓详情（省 60% 以上请求）

用法示例：
    python scraper.py --keywords "港航,港口航道,水利工程" --cities "上海,成都,南京"
    python scraper.py --keywords "Java" --cities "北京" --max-details 100 --pages 3
    python scraper.py --keywords "水利" --cities "宜宾" --no-filter    # 不过滤，全抓

输出（默认 ./data）：
    <prefix>_list_raw.json   列表页原始数据（阶段一产物，可复用）
    <prefix>_detail.json     带详情的完整数据（阶段二产物）
    <prefix>_detail.csv      同上，Excel 友好
    <prefix>_stats.json      每个关键词×城市的收集量
    cookies.json             登录态（下次运行免扫码）
"""

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cities import resolve  # noqa: E402

COOKIE_NAME = "cookies.json"

JS_LIST = """
() => {
    const cards = document.querySelectorAll('li.job-card-box');
    return Array.from(cards).map(card => {
        const name = card.querySelector('.job-name');
        const tags = card.querySelectorAll('.tag-list li');
        const company = card.querySelector('.boss-name');
        const location = card.querySelector('.company-location');
        const tagTexts = Array.from(tags).map(t => t.textContent.trim());
        let experience = '', education = '';
        for (const t of tagTexts) {
            if (t.includes('年') || t === '应届生' || t === '在校生' || t.includes('经验'))
                experience = t;
            else if (['本科','硕士','博士','大专','学历不限','中专/中技','高中'].some(k => t.includes(k)))
                education = t;
        }
        return {
            name: name ? name.textContent.trim() : '',
            link: name ? name.getAttribute('href') : '',
            experience, education,
            company: company ? company.textContent.trim() : '',
            location: location ? location.textContent.trim() : '',
        };
    }).filter(j => j.name);
}
"""

JS_DETAIL = """
() => {
    const r = {};
    const sal = document.querySelector('.salary, .info-primary .salary');
    r.salary = sal ? sal.textContent.trim() : '';
    const desc = document.querySelector('.job-sec-text, .job-detail-section .text, .text.fold-text');
    r.description = desc ? desc.textContent.trim() : '';
    const ct = Array.from(document.querySelectorAll('.sider-company-info li, .company-info li'))
        .map(t => t.textContent.trim()).filter(Boolean);
    r.industry = ''; r.scale = ''; r.financing = '';
    for (const t of ct) {
        if (t.match(/\\d+.*人/) || t.includes('以上') || t.includes('少于')) r.scale = t;
        else if (t.includes('融资') || t.includes('上市') || t.includes('不需要融资')) r.financing = t;
        else if (t.length > 1 && t.length < 20) r.industry = r.industry || t;
    }
    return r;
}
"""


def log(msg):
    print(msg, flush=True)


def delay(a, b):
    time.sleep(random.uniform(a, b))


# ---------------- cookie / 登录 ----------------

def restore_cookies(page, out_dir):
    f = out_dir / COOKIE_NAME
    if not f.exists():
        return False
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        keep = []
        for c in raw:
            c = {k: v for k, v in c.items()
                 if k in ("name", "value", "domain", "path", "expires",
                          "httpOnly", "secure", "sameSite")}
            if c.get("sameSite") not in ("Strict", "Lax", "None"):
                c.pop("sameSite", None)
            if c.get("domain"):
                keep.append(c)
        page.context.add_cookies(keep)
        return bool(keep)
    except Exception as e:
        log(f"[cookie] 载入失败 {str(e)[:60]}")
        return False


def save_cookies(page, out_dir):
    try:
        (out_dir / COOKIE_NAME).write_text(
            json.dumps(page.context.cookies(), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def wait_jobs(page, sec=25):
    for _ in range(sec):
        time.sleep(1)
        try:
            if page.evaluate("document.querySelectorAll('li.job-card-box').length") > 0:
                return True
        except Exception:
            pass
    return False


def login_wait(page, out_dir, attempts=120):
    page.goto("https://www.zhipin.com/web/user/?ka=header-login",
              wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    log("[等待登录] 请在弹出窗口扫码 / 手机号登录 BOSS 直聘（最多等 %d 分钟）" % (attempts * 5 // 60))
    for i in range(attempts):
        time.sleep(5)
        try:
            ck = page.context.cookies()
            if any(c["name"] in ("token", "wt2", "bst") for c in ck) or \
               ("user" not in page.url and "login" not in page.url):
                log("[登录成功]")
                save_cookies(page, out_dir)
                return True
            if (i + 1) % 6 == 0:
                log(f"  [{i+1}/{attempts}] 等待扫码中...")
        except Exception:
            pass
    return False


# ---------------- 阶段一：列表 ----------------

def wait_new_cards(page, old, timeout=8):
    for _ in range(timeout * 2):
        time.sleep(0.5)
        try:
            n = page.evaluate("document.querySelectorAll('li.job-card-box').length")
            if n > old:
                return n
        except Exception:
            pass
    return old


def collect_list(page, kw, city, code, pages):
    url = f"https://www.zhipin.com/web/geek/job?query={kw}&city={code}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log(f"    [导航错误] {str(e)[:60]}")
        return []
    if not wait_jobs(page):
        log("    [无结果]")
        return []
    time.sleep(2)
    jobs = []
    for j in page.evaluate(JS_LIST):
        j.update(keyword=kw, search_city=city)
        jobs.append(j)
    seen = {j["link"] for j in jobs}
    no_new = 0
    for r in range(1, pages + 1):
        old = page.evaluate("document.querySelectorAll('li.job-card-box').length")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        new_cnt = wait_new_cards(page, old)
        added = 0
        for j in page.evaluate(JS_LIST):
            if j["link"] in seen:
                continue
            seen.add(j["link"])
            j.update(keyword=kw, search_city=city)
            jobs.append(j)
            added += 1
        log(f"    轮{r}: 卡片 {old}→{new_cnt}  +{added}（累计 {len(jobs)}）")
        if added == 0:
            no_new += 1
            if no_new >= 2:
                break
        else:
            no_new = 0
        delay(2, 4)
    return jobs


# ---------------- 阶段二：详情 ----------------

def city_of(job):
    return (job.get("location", "") or "").split("·")[0]


def priority(job, strong, weak):
    n = job.get("name", "")
    if any(k in n for k in strong):
        return 1
    if any(k in n for k in weak):
        return 2
    return 9


def collect_details(page, jobs, out_dir, prefix, pause=(1, 3)):
    err = 0
    for i, j in enumerate(jobs, 1):
        link = j["link"]
        url = f"https://www.zhipin.com{link}" if link.startswith("/") else link
        print(f"  [{i}/{len(jobs)}] {j['name'][:26]}...", end=" ", flush=True)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(random.uniform(1, 2))
            d = page.evaluate(JS_DETAIL)
            j["salary"] = d.get("salary", "")
            j["description"] = d.get("description", "")[:1200]
            j["industry"] = d.get("industry", "")
            j["scale"] = d.get("scale", "")
            j["financing"] = d.get("financing", "")
            log(j["salary"] or "-")
            err = 0
            delay(*pause)
        except Exception as e:
            msg = str(e)[:60]
            log(f"错误 {msg}")
            err += 1
            if err >= 3 or "DISCONNECTED" in msg.upper():
                w = min(30 + err * 10, 90)
                log(f"    [疑似限流] 等待 {w}s")
                time.sleep(w)
                try:
                    page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=20000)
                    time.sleep(3)
                except Exception:
                    pass
            else:
                delay(2, 4)
        if i % 25 == 0:
            dump(jobs, out_dir, prefix, partial=True)
            log(f"    [断点保存] {i}/{len(jobs)}")


FIELDS = ["city", "prio", "keyword", "search_city", "name", "salary", "experience",
          "education", "company", "location", "industry", "scale", "financing",
          "description", "link"]


def dump(jobs, out_dir, prefix, partial=False):
    for j in jobs:
        j["city"] = city_of(j)
    (out_dir / f"{prefix}_detail.json").write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    if partial:
        return
    with open(out_dir / f"{prefix}_detail.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(jobs)


def main():
    ap = argparse.ArgumentParser(description="BOSS 直聘岗位抓取（两阶段）")
    ap.add_argument("--keywords", required=True, help="逗号分隔，如 \"港航,港口航道\"")
    ap.add_argument("--cities", required=True, help="逗号分隔，如 \"上海,成都,南京\"")
    ap.add_argument("--pages", type=int, default=4, help="每个关键词滚动轮数（每轮约 15 条）")
    ap.add_argument("--max-details", type=int, default=400, help="详情页抓取上限")
    ap.add_argument("--out", default="data", help="输出目录")
    ap.add_argument("--prefix", default=None, help="文件名前缀，默认取第一个关键词拼音化")
    ap.add_argument("--strong", default="", help="岗位名命中即高优先的相关词（逗号分隔）")
    ap.add_argument("--weak", default="", help="岗位名命中则次优先的词（逗号分隔）")
    ap.add_argument("--noise", default="", help="岗位名命中即丢弃的词（逗号分隔）")
    ap.add_argument("--no-filter", action="store_true", help="不做相关性过滤，全量抓详情")
    ap.add_argument("--reuse-list", action="store_true", help="复用已有 <prefix>_list_raw.json")
    ap.add_argument("--headless", action="store_true", help="无头模式（无法扫码登录）")
    args = ap.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    city_map = resolve([c.strip() for c in args.cities.split(",") if c.strip()])
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or re.sub(r"[^a-z0-9]+", "_", keywords[0].lower()).strip("_") or "jobs"

    strong = [k.strip() for k in args.strong.split(",") if k.strip()]
    weak = [k.strip() for k in args.weak.split(",") if k.strip()]
    noise = [k.strip() for k in args.noise.split(",") if k.strip()]

    log("=" * 62)
    log("  BOSS 直聘岗位抓取")
    log(f"  关键词({len(keywords)}): {keywords}")
    log(f"  城市({len(city_map)}): {list(city_map)}")
    log(f"  每词轮数 {args.pages} | 详情上限 {args.max_details}")
    log("=" * 62)

    from cloakbrowser import launch
    browser = launch(headless=args.headless, humanize=True)
    page = browser.new_page()

    ok = False
    if restore_cookies(page, out_dir):
        try:
            first_city = list(city_map.values())[0]
            page.goto(f"https://www.zhipin.com/web/geek/job?query={keywords[0]}&city={first_city}",
                      wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            if "login" not in page.url and wait_jobs(page, 8):
                log("[会话有效] 复用上次登录态，无需扫码")
                ok = True
        except Exception:
            pass
    if not ok:
        ok = login_wait(page, out_dir)
        if not ok:
            log("[中止] 未登录，退出。请重新运行并在弹窗中扫码登录。")
            browser.close()
            return

    # ---- 阶段一：列表 ----
    list_file = out_dir / f"{prefix}_list_raw.json"
    if args.reuse_list and list_file.exists():
        raw = json.loads(list_file.read_text(encoding="utf-8"))
        log(f"\n[复用列表] {len(raw)} 条（{list_file}）")
    else:
        raw, seen, stats = [], set(), {}
        for kw in keywords:
            for city, code in city_map.items():
                log(f"\n--- {kw} | {city} ---")
                got = collect_list(page, kw, city, code, args.pages)
                new = [j for j in got if j["link"] not in seen]
                for j in new:
                    seen.add(j["link"])
                raw.extend(new)
                stats[f"{kw}|{city}"] = {"raw": len(got), "new": len(new)}
                log(f"    [去重] +{len(new)}（总 {len(raw)}）")
                delay(6, 11)
        list_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / f"{prefix}_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"\n[阶段一完成] 列表 {len(raw)} 条 → {list_file}")

    # ---- 过滤 ----
    if args.no_filter:
        todo = raw
        log(f"[过滤] 已跳过，全量 {len(todo)} 条进入详情")
    else:
        cand, drop_city, drop_noise, drop_irrelevant = [], 0, 0, 0
        targets = set(city_map)
        for j in raw:
            if city_of(j) not in targets:
                drop_city += 1
                continue
            if noise and any(k in j["name"] for k in noise):
                drop_noise += 1
                continue
            p = priority(j, strong, weak)
            if p == 9:
                drop_irrelevant += 1
                continue
            j["prio"] = p
            cand.append(j)
        cand.sort(key=lambda x: x["prio"])
        p1 = [j for j in cand if j["prio"] == 1]
        p2 = [j for j in cand if j["prio"] == 2]
        todo = (p1 + p2)[:args.max_details]
        log(f"[过滤] 跨城 {drop_city} / 噪音 {drop_noise} / 不相关 {drop_irrelevant}")
        log(f"        一级 {len(p1)} + 二级 {len(p2)} → 取 {len(todo)} 条进详情")
        if not todo and not args.no_filter:
            log("[提示] 过滤后为空。若确实想全量抓，请加 --no-filter；"
                "或检查 --strong/--weak 相关词是否匹配到了岗位名。")

    # ---- 阶段二：详情 ----
    if todo:
        collect_details(page, todo, out_dir, prefix)
    browser.close()

    dump(todo, out_dir, prefix)
    filled = sum(1 for j in todo if j.get("salary"))
    log("\n" + "=" * 62)
    log(f"  完成 {len(todo)} 条 | 薪资获取 {filled}/{len(todo)}")
    log(f"  {out_dir / (prefix + '_detail.json')}")
    log("=" * 62)

if __name__ == "__main__":
    main()
