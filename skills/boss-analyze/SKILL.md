---
name: boss-analyze
description: 把BOSS直聘抓取的岗位数据变成可视化HTML报告，或按个人简历给岗位打分排序。支持城市/薪资/经验学历/高频词多维分析、简历能力画像匹配、优先投递清单导出。触发词：分析岗位、岗位分析、boss数据分析、职位分析、岗位匹配、简历匹配岗位。
---

# BOSS 岗位分析与匹配

两个脚本，按需求选：

| 脚本 | 干什么 | 输入 |
|---|---|---|
| `scripts/analyze.py` | 通用市场分析报告（城市/薪资/经验/高频词/明细） | `*_detail.json` |
| `scripts/match.py` | 按**个人简历**给岗位打分、出优先投递清单 | `*_detail.json` + 画像 JSON |

两者共用 `scripts/report_kit.py`（报告样式与工具函数）。报告是**自包含 HTML**：CSS 柱条 + conic-gradient 环形图，不依赖任何 CDN，断网也能看。

## 前置检测

```bash
ls -lt data/*_detail.json data/*_jobs.json 2>/dev/null | head -3
python -c "import jieba; print('JIEBA:OK')" 2>&1
```

- 无数据文件 → 告诉用户先说「抓取boss岗位」，**不要继续**
- `jieba` 缺失 → `pip install jieba`（只影响高频词模块，不装也能出报告，会自动跳过）

## 一 · 通用市场分析

```bash
python scripts/analyze.py --input data/xxx_detail.json --out reports/岗位报告.html

# 只看部分城市 + 提高明细展示量
python scripts/analyze.py --input data --city "上海,南京" --top 60

# 传自己的行业词典，让高频词更准
python scripts/analyze.py --input data/xxx_detail.json --dict 我的词表.txt
```

`--input` 给目录时自动选**最新**的 `*_detail.json`。

报告包含：概览 KPI、城市分布、岗位类型、月薪区间、经验/学历环形图、JD 高频词、招聘公司 Top10、岗位明细（可展开 JD）。

## 二 · 按简历匹配

### 1) 先做画像

```bash
python scripts/match.py --init profile.json
```

填 `groups`（能力组）+ 权重。结构：

```json
"groups": {
  "专业背景": {"weight": 5, "words": ["港航", "港口", "航道", "水利"]},
  "数值模拟": {"weight": 5, "words": ["ADCIRC", "水动力", "风暴潮"]},
  "AI/算法": {"weight": 4, "words": ["Transformer", "LSTM", "时序", "大模型"]}
}
```

`profiles/example_profile.json` 是一份填好的示例，直接复制改。

### 2) 跑匹配

```bash
python scripts/match.py \
  --input data/xxx_detail.json \
  --profile profile.json \
  --out data/matched.json \
  --csv "data/推荐岗位清单.csv" \
  --html reports/匹配报告.html
```

### 打分口径（要能向用户解释清楚）

```
相关性 = Σ(组权重 × min(命中词数, 3))      # 同组最多计 3 个词，防长 JD 刷分
风险   = 经验门槛 + 学历错配 + 偏现场施工 + 要注册证 + 证书挂靠 + 自定义扣分
匹配分 = 97 × (相关性 / 全场最高相关性) × (1 - min(风险,40)/100)
相关性 < 8 的岗位直接压到 ≤18 分
```

内置扣分：5-10 年经验 -16、3-5 年 -6、大专 -8、施工/监理/项目经理类 -10、注册证书 -5、建造师挂靠/兼职 -25。

**匹配分 ≠ 录取概率。** 一定要在报告里明说，并在表格里保留「经验」列——曾经出现「解决方案总监」拿 97 分、但应届根本投不了的情况。先看经验，再看分。

## 三个坑（都踩过）

**1. 相对链接 404。** BOSS 的岗位链接是 `/job_detail/xxx.html`，直接写进 `href` 后，报告在 `file://` 或 `127.0.0.1` 预览下会被解析成本地路径 → `HTTP ERROR 404`。
→ 所有外链必须过 `report_kit.abs_url()` 补全 `https://www.zhipin.com`。`analyze.py` 结尾有断言自检，出现 `href="/` 会直接报错退出。

**2. 时薪/日薪污染中位数。** 「150-200 元/天」「2800 元/时」混进月薪统计会让中位数完全失真。
→ `parse_salary_monthly()` 遇到 `元/时|元/天|元/次` 一律返回 `None`，报告里单独标注「另有 N 条时薪/日薪未计入」。

**3. 高频词全是套话和公司名。** 不加约束会得到「岗位职责、以上学历、较强、BOSS」这类废词，以及被 TF-IDF 当成热词的**公司名**。
→ 三层处理：`allowPOS=("n","nz","vn","eng")` 只留名词类；扩展 JD 套话停用词表；命中岗位所属公司名的词直接排除。

## 输出

| 文件 | 内容 |
|---|---|
| `reports/*.html` | 自包含报告，可直接发给别人看 |
| `data/matched.json` | 每条岗位带 match / hits / gaps，便于二次加工 |
| `data/推荐岗位清单.csv` | 带优先级、命中能力、缺口提示、原始链接，按经验友好度排序 |

## 完成后

1. 用 `present_files` 打开 HTML 报告
2. 文字汇报 3–5 条关键结论（岗位集中在哪、薪资中位、最该投哪几个、共同缺口）
3. 说明报告与 CSV 路径
