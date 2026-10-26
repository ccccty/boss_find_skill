#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 BOSS 直聘详情数据里抽取「值得做成知识卡片」的领域术语。

输入：boss-scrape 产出的 *_detail.json（也可以是目录，自动选最新）
输出：候选术语 JSON（含提及岗位数、样例岗位、原文上下文）+ 终端表格

设计原则
--------
1. **按「提及的岗位数」排序，不按词频。** 同一个 JD 里出现 20 次的概念，
   不如 20 个 JD 各出现 1 次的概念有代表性——前者可能只是那家公司的口头习惯。
2. **术语必须能落到原文证据。** 每个候选都带 samples（原句片段），
   写卡时必须据此而不是凭模型记忆，否则容易写出「听起来对但岗位不用」的卡。
3. **不依赖分词库也能跑。** 中文走 n-gram + 最大匹配去碎片，
   装了 jieba 会自动启用词性过滤作为额外一路增强。

用法
----
    python scripts/extract_terms.py --input data/xxx_detail.json
    python scripts/extract_terms.py --input data --min-jobs 3 --top 60
    python scripts/extract_terms.py --input data/a.json --input data/b.json --out terms.json
    python scripts/extract_terms.py --input data --lexicon 我的词表.txt --exclude 保安,销售
"""

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

# ----------------------------------------------------------------------------
# 一 · 清洗
# ----------------------------------------------------------------------------
# BOSS 会在正文里插入反爬水印，且**插在词内部**：`抖kanzhun音` = 抖音。
# 直接删掉水印反而能还原被切开的词，所以顺序必须是「删水印 → NFKC」。
WATERMARKS = [
    r"kanzhun", r"KANZHUN", r"看准网?", r"来自\s*BOSS\s*直聘",
    r"BOSS\s*直聘", r"boss\s*直聘", r"直聘网", r"来自boss",
]
WM_RE = re.compile("|".join(WATERMARKS), re.I)
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
SPACE_RE = re.compile(r"[ \t\u3000]+")


def clean_text(s):
    """去掉水印与零宽字符，再把康熙部首还原成正常汉字。"""
    if not s:
        return ""
    s = WM_RE.sub("", s)
    s = ZERO_WIDTH_RE.sub("", s)
    # NFKC 会把「⽇」(U+2F47 康熙部首) 还原成「日」(U+65E5)。
    # 实测 153 条岗位里有 532 个这类字符，不做归一，术语永远匹配不上。
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\r", "\n")
    s = SPACE_RE.sub(" ", s)
    return s.strip()


# ----------------------------------------------------------------------------
# 二 · 停用词
# ----------------------------------------------------------------------------
# 分三类，用途不同：STOP_JD 是招聘套话，STOP_GENERIC 是无原理可讲的泛词，
# GLUE 是不能出现在术语首尾的虚词/连接词。
STOP_JD = """
岗位职责 工作职责 职位描述 任职要求 任职资格 岗位要求 职位要求 工作内容 工作地点
岗位说明 加分项 优先条件 以上学历 本科以上 硕士以上 大专以上 相关专业 相关经验
工作经验 项目经验 实习经验 沟通能力 表达能力 学习能力 抗压能力 执行能力 协作能力
团队协作 团队合作 团队精神 责任心 积极主动 认真负责 吃苦耐劳 逻辑思维 沟通协调
组织协调 独立完成 承受压力 抗压性强 良好的沟通 优秀的学习 自我驱动 结果导向
五险一金 带薪年假 节日福利 弹性工作 扁平管理 团队氛围 晋升空间 发展空间 培训机会
薪资待遇 工作时间 简历投递 欢迎加入 优先考虑 熟练掌握 熟悉掌握 精通掌握 了解掌握
具备良好 能够独立 有较强 较强的 良好的 一定的 相关领域 相关行业 计算机相关
""".split()

STOP_GENERIC = """
岗位 职责 要求 能力 经验 工作 公司 团队 项目 业务 产品 技术 相关 优先 熟悉 掌握
负责 参与 完成 支持 协助 具备 具有 良好 优秀 一定 以上 学历 专业 方向 领域 行业
系统 平台 方案 服务 管理 开发 设计 分析 研究 应用 实施 建设 维护 优化 提升 推进
人员 人才 员工 公司简介 福利 待遇 上班 下班 时间 地点 城市 区域 客户 用户 需求
流程 规范 标准 文档 沟通 配合 落地 交付 质量 效率 成本 风险 数据 信息 内容 功能
我们 你们 他们 以及 并且 或者 如果 因为 所以 通过 进行 实现 保证 确保 满足 提高
任职 本科 硕士 博士 大专 熟练 独立 协作 协调 责任 学习 培训 合作 逻辑 提供 持续
推动 制定 开展 执行 解决 内部 场景 问题 基础 工具 识别 计算 评估 治理 体系 法规
报告 运营 工程 计算机 工程师 意识 方法 手段 措施 情况 效果 目标 计划 总结 输出
输入 结构 模块 接口 指标 参数 版本 环境 配置 部署 测试 调试 排查 定位 复现 监控
完善 建立 构建 搭建 编写 撰写 整理 收集 梳理 跟踪 反馈 响应 处理 操作 使用 采用
引入 结合 围绕 依据 按照 根据 针对 面向 基于 涵盖 覆盖 涉及 包含 属于 作为 由于
具备 受到 得到 获得 达到 保持 维持 促进 加快 减少 降低 增加 扩展 补充 替代 转换
深入 清晰 快速 日常 各类 至少 理解 建议 跟进 定期 相关 保障 发现 组织 市场 文件
材料 背景 核心 记录 基本 完整 全面 独立 顺畅 有效 高效 及时 规范 合理 充分 扎实
较强 优秀 良好 相关工作 解决方案 综合素质 综合素质 团队意识 学习能力 承压 吃苦
行业背景 业务需求 沟通协调 配合完成 按时完成 保质保量 积极主动 踏实 肯干 细心
资料 活动 现场 符合 提出 资格 情况 过程 方式 内容 措施 部分 有关 相关方 各个 各自
""".split()

# 只要含有这些片段就一定不是「可讲原理的术语」，而是 JD 的句式或招聘话术。
# 宁可错杀：卡片要讲概念，不要讲「具备良好的沟通能力」。
BAD_SUBSTRINGS = """
任职 职责 描述 要求 经验 能力 学历 专业优先 熟悉 熟练 掌握 具备 优先 岗位 我们
公司 福利 薪酬 薪 简历 面试 入职 招聘 上班 加班 双休 面议 五险 一金 年终 补贴
""".split()

STOP_EN = """
and the with for you your our we are is to in of on at as be by or from that this
team work job jobs able good must will can all any not use using used new more
years experience responsible familiar skills knowledge ability development software
company product project business data also such have has been who what which when
about into over under than then them these those other others include including
boss zhipin kanzhun www com cn http https
""".split()

GLUE = set("的了和与及等在对能会有是为并或把被从就都也还又很更最着过把让使其之所而且"
           "我你他她它这那哪些个种次条款项点方式")

# 只由这些字组成的 n-gram 直接丢（都是词组边角料）
GLUE_ONLY_RE = re.compile(r"^[的了和与及等在对能会有是为并或把被从就都也还又很更最之其]+$")

# 这些词性不可能是「可讲原理的术语」，直接丢：r 代词 / d 副词 / p 介词 /
# c 连词 / u 助词 / m 数词 / q 量词 / t 时间词 / f 方位 / y 语气 / z 状态 / e 叹词
NON_TERM_POS = set("rdpcumqtfyzeosh")

CJK_RE = re.compile(r"[\u4e00-\u9fa5]+")
EN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#._\-]{1,24}")
EN_PHRASE_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#\-]*(?:\s+[A-Za-z][A-Za-z0-9+#\-]*){1,3}")

# 中文短语里合法出现的英文/数字（ROS2、C++、ISO26262 这类），用于把中英混排切成两段
MIXED_RE = re.compile(r"[\u4e00-\u9fa5]+|[A-Za-z][A-Za-z0-9+#._\-]*")


# ----------------------------------------------------------------------------
# 三 · 载入
# ----------------------------------------------------------------------------
def load_jobs(paths):
    """读入若干 *_detail.json，返回 (jobs, 来源列表)。"""
    files = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            cands = [os.path.join(p, f) for f in os.listdir(p)
                     if f.endswith("_detail.json") or f.endswith("_jobs.json")]
            if not cands:
                sys.exit(f"[错误] {p} 下没有 *_detail.json / *_jobs.json")
            # 目录模式：只取最新一个，避免把不同批次混在一起
            files.append(max(cands, key=os.path.getmtime))
        elif os.path.isfile(p):
            files.append(p)
        else:
            sys.exit(f"[错误] 找不到 {p}")

    jobs, sources = [], []
    for f in files:
        try:
            data = json.loads(open(f, encoding="utf-8").read())
        except Exception as e:
            sys.exit(f"[错误] 读取 {f} 失败：{e}")
        if not isinstance(data, list):
            sys.exit(f"[错误] {os.path.basename(f)} 不是岗位数组，"
                     f"是不是把 _stats.json 当输入了？")
        for j in data:
            j["description"] = clean_text(j.get("description") or "")
            j["name"] = clean_text(j.get("name") or "")
            if not j.get("city"):
                j["city"] = (j.get("location") or "").split("·")[0]
        jobs.extend(data)
        sources.append(os.path.basename(f))

    # 跨批次去重：同一家公司 + 同一岗位名 + 同一链接只算一次
    seen, uniq = set(), []
    for j in jobs:
        k = (j.get("company", ""), j.get("name", ""), j.get("link", ""))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(j)
    return uniq, sources


# ----------------------------------------------------------------------------
# 四 · 中文 n-gram 候选
# ----------------------------------------------------------------------------
def h_entropy(counter):
    """邻接字分布的香农熵（bit）。"""
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for c in counter.values():
        p = c / total
        h -= p * math.log2(p)
    return h


def cjk_ngrams(jobs, nmin=2, nmax=8):
    """第一遍：统计中文 n-gram 的「提及岗位数」与总频次。

    返回 {gram: {"jobs": set, "freq": int}}
    """
    stats = defaultdict(lambda: {"jobs": set(), "freq": 0})
    for idx, j in enumerate(jobs):
        text = j["description"] + " " + j["name"]
        for run in CJK_RE.findall(text):
            L = len(run)
            for n in range(nmin, min(nmax, L) + 1):
                for i in range(L - n + 1):
                    s = stats[run[i:i + n]]
                    s["jobs"].add(idx)
                    s["freq"] += 1
    return stats


def analyze_candidates(jobs, grams, nmin=2, nmax=8, use_jieba=True):
    """第二遍：只对候选计算三个质量指标。

    1. **左/右邻接字熵**：真词两侧接的字杂乱（熵高），碎片常有一侧固定。
       `据安全` 左边永远是「数」→ 左熵≈0。
    2. **分词边界一致率**：候选的起止位置是否落在分词边界上。
       `数据分` 是 `数据|分析` 的一半，边界一致率必然低；
       `数据分析` 则几乎每次都在边界上。这一项比熵更能砍掉跨词碎片。
    3. 有 jieba 才做第 2 项，没有就只靠熵（阈值会放宽，见调用处）。

    返回 {gram: {"ent": float, "boundary": float}}
    """
    left, right = defaultdict(Counter), defaultdict(Counter)
    hit, total = Counter(), Counter()
    jieba = None
    if use_jieba:
        try:
            import jieba as _j
            jieba = _j
            jieba.setLogLevel(20)
        except ImportError:
            jieba = None

    for j in jobs:
        text = j["description"] + " " + j["name"]
        # 分词边界：累加每个词的长度，得到切分点集合
        B = set()
        if jieba is not None:
            off = 0
            for w in jieba.lcut(text):
                off += len(w)
                B.add(off)
        for m in CJK_RE.finditer(text):
            run, base = m.group(0), m.start()
            L = len(run)
            for n in range(nmin, min(nmax, L) + 1):
                for i in range(L - n + 1):
                    g = run[i:i + n]
                    if g not in grams:
                        continue
                    left[g][run[i - 1] if i > 0 else "^"] += 1
                    right[g][run[i + n] if i + n < L else "$"] += 1
                    if jieba is not None:
                        total[g] += 1
                        if (base + i) in B and (base + i + n) in B:
                            hit[g] += 1

    out = {}
    pos_cache = {}
    posseg = None
    if jieba is not None:
        try:
            import jieba.posseg as _ps
            posseg = _ps
        except ImportError:
            posseg = None

    for g in grams:
        e = min(h_entropy(left[g]), h_entropy(right[g]))
        b = (hit[g] / total[g]) if total[g] else 0.0
        tag = ""
        if posseg is not None:
            if g not in pos_cache:
                try:
                    ps = [(w.word, w.flag) for w in posseg.cut(g)]
                    # 取权重最大的实词词性作为整个候选的词性
                    main = [f for _, f in ps if f and f[0] not in "udpcr"]
                    pos_cache[g] = (main[0] if main else (ps[0][1] if ps else ""))
                except Exception:
                    pos_cache[g] = ""
            tag = pos_cache[g]
        out[g] = {"ent": round(e, 2), "boundary": round(b, 2), "pos": tag}
    return out


def en_terms(jobs):
    """抽英文/缩写术语：单词与短语，统一小写做键，保留最高频的原始写法。"""
    single = defaultdict(lambda: {"jobs": set(), "freq": 0, "forms": Counter(), "pos": []})
    phrase = defaultdict(lambda: {"jobs": set(), "freq": 0, "forms": Counter(), "pos": []})

    for idx, j in enumerate(jobs):
        text = j["description"] + " " + j["name"]
        low = text.lower()
        for m in EN_RE.finditer(text):
            tok = m.group(0)
            if len(tok) < 2 or not re.search(r"[A-Za-z]", tok):
                continue
            key = tok.lower().strip("._-")
            if len(key) < 2 or key in STOP_EN:
                continue
            s = single[key]
            s["jobs"].add(idx)
            s["freq"] += 1
            s["forms"][tok] += 1
            if len(s["pos"]) < 64:
                s["pos"].append((idx, m.start()))
        for m in EN_PHRASE_RE.finditer(text):
            key = re.sub(r"\s+", " ", m.group(0).lower()).strip()
            parts = key.split()
            if len(parts) < 2 or all(p in STOP_EN for p in parts):
                continue
            if any(p in STOP_EN for p in parts[:1] + parts[-1:]):
                continue
            s = phrase[key]
            s["jobs"].add(idx)
            s["freq"] += 1
            s["forms"][re.sub(r"\s+", " ", m.group(0))] += 1
            if len(s["pos"]) < 64:
                s["pos"].append((idx, m.start()))
    return single, phrase


def prune_substrings(cands, min_jobs):
    """去掉「永远是更长术语的一部分」的碎片。

    例：`激光雷达点云` 出现在 12 个岗位，`雷达点云` 也只出现在同样的 12 个岗位，
    说明 `雷达点云` 从没独立出现过，是切出来的碎片，删掉。
    """
    items = sorted(cands.items(), key=lambda kv: -len(kv[0]))
    keep = {}
    for g, info in items:
        redundant = False
        for longer in keep:
            if g in longer and keep[longer]["jobs"] == info["jobs"] and info["freq"] == keep[longer]["freq"]:
                redundant = True
                break
        if not redundant:
            keep[g] = info
    return keep


def snippet(job, pos, term, width=42):
    """取术语在原文中的上下文片段，压成一行，供写卡时对照。"""
    text = SPACE_RE.sub(" ", (job["description"] or "").replace("\n", " "))
    i = text.find(term, max(0, pos - 80))
    if i < 0:
        i = text.find(term)
    if i < 0:
        return ""
    a, b = max(0, i - width), min(len(text), i + len(term) + width)
    s = text[a:b].strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


# ----------------------------------------------------------------------------
# 五 · 主流程
# ----------------------------------------------------------------------------
def build(args):
    jobs, sources = load_jobs(args.input)
    total = len(jobs)
    if total == 0:
        sys.exit("[错误] 没有可用岗位（描述全空？先确认抓取是否成功）")

    with_desc = sum(1 for j in jobs if len(j["description"]) >= 30)
    print(f"[输入] {', '.join(sources)} → {total} 条岗位，其中有正文的 {with_desc} 条")

    companies = {(j.get("company") or "").strip() for j in jobs if j.get("company")}
    lexicon = set()
    for p in (args.lexicon or []):
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                w = line.strip()
                if w and not w.startswith("#"):
                    lexicon.add(w.lower())
        else:
            print(f"[提示] 词表不存在，忽略：{p}")
    excludes = {w.strip().lower() for w in (args.exclude or "").split(",") if w.strip()}

    # ---- 中文：先按「提及岗位数 + 停用词」粗筛，再算邻接熵砍碎片 ----
    ng = cjk_ngrams(jobs, args.n_min, args.n_max)
    cand_zh = {}
    for g, info in ng.items():
        if len(g) < 2 or g[0] in GLUE or g[-1] in GLUE or GLUE_ONLY_RE.match(g):
            continue
        if g in STOP_GENERIC or g in STOP_JD:
            continue
        if any(b in g for b in BAD_SUBSTRINGS):
            continue
        njobs = len(info["jobs"])
        if njobs < args.min_jobs:
            continue
        if any(g in c for c in companies if len(c) >= 2):
            continue
        if g.lower() in excludes:
            continue
        cand_zh[g] = info
    print(f"[筛词] 粗筛后 {len(cand_zh)} 个中文候选，开始算邻接熵与分词边界（这一步会慢几秒）")

    q = analyze_candidates(jobs, set(cand_zh), args.n_min, args.n_max,
                           use_jieba=not args.no_jieba)
    has_jieba = any(v["boundary"] > 0 for v in q.values())
    if not has_jieba:
        print("[提示] 没装 jieba，只能用邻接熵判碎片，精度会低一些"
              "（.venv/Scripts/python.exe -m pip install jieba 可提升）")

    dropped_ent = dropped_bnd = dropped_pos = 0
    for g in list(cand_zh):
        v = q.get(g, {"ent": 0.0, "boundary": 0.0, "pos": ""})
        cand_zh[g]["ent"] = v["ent"]
        cand_zh[g]["bnd"] = v["boundary"]
        cand_zh[g]["pos"] = v["pos"]
        in_lex = g.lower() in lexicon
        if in_lex:                       # 词表里显式给了就保留：专有名词常常一边固定
            continue
        if v["ent"] < args.min_entropy:
            cand_zh.pop(g)
            dropped_ent += 1
        elif has_jieba and v["boundary"] < args.min_boundary:
            cand_zh.pop(g)
            dropped_bnd += 1
        elif v["pos"] and v["pos"][0] in NON_TERM_POS:
            # 副词/代词/连词/量词这类词性不可能是术语
            cand_zh.pop(g)
            dropped_pos += 1
    print(f"[筛词] 邻接熵 < {args.min_entropy} 丢 {dropped_ent} 个；"
          f"边界一致率 < {args.min_boundary} 丢 {dropped_bnd} 个；"
          f"虚词词性 丢 {dropped_pos} 个；剩 {len(cand_zh)} 个")

    cand_zh = prune_substrings(cand_zh, args.min_jobs)

    # ---- 英文 ----
    single, phrase = en_terms(jobs)
    cand_en = {}
    for key, info in list(single.items()) + list(phrase.items()):
        njobs = len(info["jobs"])
        if njobs < args.min_jobs:
            continue
        if key in excludes or any(key in c.lower() for c in companies if len(c) >= 2):
            continue
        # 单词若总是出现在某个短语里，交给短语代表
        if key in single and any(key in p.split() for p in phrase):
            pj = max(len(phrase[p]["jobs"]) for p in phrase if key in p.split())
            if pj == njobs:
                continue
        cand_en[key] = info

    # ---- 合并成统一候选（先只算计数，样例等截断到 top 后再取，省时间）----
    rows = []
    for g, info in cand_zh.items():
        rows.append(("zh", g, g, info))
    for key, info in cand_en.items():
        display = info["forms"].most_common(1)[0][0] if info["forms"] else key
        rows.append(("en", key, display, info))

    terms = []
    for kind, key, display, info in rows:
        job_ids = info["jobs"]
        cities = Counter(jobs[i].get("city") or "未知" for i in job_ids)
        terms.append({
            "term": display,
            "kind": kind,
            "key": key,
            "jobs": len(job_ids),
            "freq": info["freq"],
            "coverage": round(len(job_ids) / total, 4),
            "cities": dict(cities.most_common(5)),
            "titles": [],
            "samples": [],
        })
    terms.sort(key=lambda x: (-x["jobs"], -x["freq"], x["term"]))
    terms = terms[:args.top]

    # 只给入选的术语回扫原文取样例岗位与原句，写卡时要照着这些句子来
    for t in terms:
        needle = t["key"] if t["kind"] == "en" else t["term"]
        seen_t, n_hit = set(), 0
        for idx in range(total):
            j = jobs[idx]
            txt = j["description"] if t["kind"] == "en" else (j["description"] + j["name"])
            pos = txt.find(needle)
            if pos < 0 and t["kind"] == "en":
                pos = txt.lower().find(needle)
            if pos < 0:
                continue
            n_hit += 1
            name = (j.get("name") or "").strip()
            if name and name not in seen_t and len(t["titles"]) < 4:
                t["titles"].append(name)
                seen_t.add(name)
            if len(t["samples"]) < 3:
                s = snippet(j, pos, needle)
                if s and s not in t["samples"]:
                    t["samples"].append(s)
            if n_hit >= 30:
                break


    # 已入池的术语（可选）：方便直接看出「还缺哪些」
    known = set()
    if args.known:
        try:
            d = json.loads(open(args.known, encoding="utf-8").read())
            for c in d.get("cards", []):
                known.add((c.get("term") or "").lower())
                if c.get("en"):
                    known.add(c["en"].lower())
            print(f"[已知] {args.known} 里已有 {len(known)} 个术语，会标记 is_new")
        except Exception as e:
            print(f"[提示] 读 {args.known} 失败，忽略：{e}")

    for t in terms:
        keys = {t["key"].lower(), t["term"].lower()}
        t["is_new"] = not (keys & known)

    terms.sort(key=lambda x: (-x["jobs"], -x["freq"], x["term"]))
    terms = terms[:args.top]

    out = {
        "source": sources,
        "jobs": total,
        "jobs_with_desc": with_desc,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "params": {"min_jobs": args.min_jobs, "top": args.top,
                   "n_min": args.n_min, "n_max": args.n_max},
        "terms": terms,
    }

    # ---- 打印 ----
    print(f"\n{'提及':>4} {'总频':>5} {'覆盖':>6}  术语")
    print("-" * 64)
    for t in terms:
        flag = "" if t["is_new"] else " (已入池)"
        print(f"{t['jobs']:>4} {t['freq']:>5} {t['coverage']*100:>5.1f}%  {t['term']}{flag}")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n[完成] {len(terms)} 个候选 → {args.out}")

    print("\n下一步：挑出「有原理可讲、岗位真在用」的术语，"
          "按 references/card_writing.md 的八字段写卡，"
          "samples 里的原句是写 jd 字段的唯一依据。")
    return out


def main():
    ap = argparse.ArgumentParser(description="从 BOSS 岗位数据抽取候选术语")
    ap.add_argument("--input", action="append", required=True,
                    help="*_detail.json 或目录（目录取最新一个），可重复")
    ap.add_argument("--out", default="data/terms.json", help="输出 JSON 路径")
    ap.add_argument("--min-jobs", type=int, default=3,
                    help="至少被多少个不同岗位提到才算候选（默认 3）")
    ap.add_argument("--top", type=int, default=60, help="输出前 N 个（默认 60）")
    ap.add_argument("--n-min", type=int, default=2, help="中文 n-gram 最短（默认 2）")
    ap.add_argument("--n-max", type=int, default=8, help="中文 n-gram 最长（默认 8）")
    ap.add_argument("--min-entropy", type=float, default=1.0,
                    help="左右邻接熵下限（默认 1.0 bit）；调高更严格，调低更宽松")
    ap.add_argument("--min-boundary", type=float, default=0.75,
                    help="分词边界一致率下限（默认 0.75），需要 jieba")
    ap.add_argument("--no-jieba", action="store_true",
                    help="禁用 jieba 边界校验，只靠邻接熵")
    ap.add_argument("--lexicon", action="append",
                    help="领域词表 txt（每行一个词），可重复；不提供也能跑")
    ap.add_argument("--exclude", default="", help="逗号分隔的强制排除词")
    ap.add_argument("--known", default="",
                    help="已有 cards.json，用来标记哪些术语已入池")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
