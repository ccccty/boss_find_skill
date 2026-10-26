# boss_find_skill

BOSS 直聘岗位抓取 · 分析 · 求职匹配 · 概念学习 —— 四个 Claude Code / WorkBuddy Skill。

用 CloakBrowser（反检测 Chromium）抓岗位，两阶段采集省 60% 请求，产出可离线查看的 HTML 报告；还能按你的简历给岗位逐条打分，直接给出一份「先投哪几个」的清单。
再往前一步：**把岗位里的高频概念做成卡片，装到手机主屏每天刷**——招聘需求本身就是最好的考纲。

```
boss_setup → 装环境
boss_scrape → 抓数据 → boss_analyze → 出报告 / 匹配清单
                     ↘ boss_study → 概念卡片 → 手机上每天刷
```

## 包含什么

| Skill | 作用 |
|---|---|
| `boss-setup` | 一键配置 CloakBrowser + Playwright，验证反检测生效 |
| `boss-scrape` | 两阶段抓取：先翻列表、再按相关性只取候选岗位详情 |
| `boss-analyze` | 市场分析报告 + 按简历匹配打分 + 推荐清单导出 |
| `boss-study` | 岗位需求 → 领域概念卡片 → 可安装到手机、每天刷的间隔重复站点 |

脚本是**随包提供**的，不是让模型现场生成代码——同样的输入得到同样的输出，也方便你自己改。

## 安装

### 方式一：Claude Code

```
claude /install-skill https://github.com/ccccty/boss_find_skill
```

### 方式二：手动（Claude Code / WorkBuddy 通用）

```bash
git clone https://github.com/ccccty/boss_find_skill.git

# Claude Code
cp -r boss_find_skill/skills/* ~/.claude/skills/

# WorkBuddy
cp -r boss_find_skill/skills/* ~/.workbuddy/skills/
```

Windows 用 `xcopy /E /I skills\* %USERPROFILE%\.workbuddy\skills\` 或直接在资源管理器里拖。

装完重启会话，三个 skill 即可被识别。

## 快速开始

### 1. 配环境（一次性，约 10 分钟，主要是下 500MB 浏览器）

```
配置 boss 抓取
```

或者手动：

```bash
mkdir boss-jobs && cd boss-jobs
python -m venv .venv
.venv/Scripts/python.exe -m pip install "cloakbrowser[geoip]" jieba
.venv/Scripts/python.exe -m playwright install chromium
```

> macOS / Linux 把 `.venv/Scripts/` 换成 `.venv/bin/`。

### 2. 抓岗位

```bash
python skills/boss-scrape/scripts/scraper.py \
  --keywords "港航,港口航道,水利工程" \
  --cities "上海,南京,成都" \
  --strong "港航,港口,航道,水运,水利,水文" \
  --noise "送水,防水,销售,客服" \
  --max-details 400 --out data
```

首次会弹浏览器扫码登录，登录态存 `data/cookies.json`，之后自动复用。

### 3. 出报告

```bash
# 市场分析
python skills/boss-analyze/scripts/analyze.py --input data/xxx_detail.json --out reports/岗位报告.html

# 按简历匹配
python skills/boss-analyze/scripts/match.py --init profile.json        # 先生成画像模板
python skills/boss-analyze/scripts/match.py --input data/xxx_detail.json \
  --profile profile.json --out data/matched.json \
  --csv "data/推荐清单.csv" --html reports/匹配报告.html
```

### 4. 做概念卡片（可选）

```bash
# 从岗位正文抽候选术语（按「被多少个不同岗位提到」排序，不是词频）
python skills/boss-study/scripts/extract_terms.py \
  --input data/xxx_detail.json --top 60 --out data/terms.json

# 挑出能讲原理的概念，按八字段写卡，然后校验入池（会拒收空话卡）
python skills/boss-study/scripts/merge_cards.py \
  --cards my-study/cards.json --input cands/2026-10-26.json --dry-run

# 生成站点（一个领域一个站）
python skills/boss-study/scripts/build_site.py \
  --out my-study --title "机器人感知 · 每日一推" --short "感知卡"
```

站点是纯静态的，push 到 GitHub Pages 后手机加到主屏即可每天刷。
详见 `skills/boss-study/SKILL.md`。

## 实测数据

一次真实运行（5 城 × 9 关键词，2026-10）：

| 阶段 | 数量 | 耗时 |
|---|---|---|
| 列表页采集 | 1633 条 | ~28 min |
| 相关性过滤 | 639 条 → 取 550 条 | 秒级 |
| 详情页抓取 | 550 条 | ~34 min |
| **合计** | | **~62 min** |

同一批数据如果全量抓详情，需要 1633 条 × 4s ≈ 110 min。

## 为什么两阶段

BOSS 的单关键词召回上限约 90 条，而详情页是主要成本（每条约 4 秒）。列表页只有标题/公司/地点，很便宜。先把所有关键词的列表翻完，再按「目标城市 + 岗位相关性」排序截断，只对候选抓详情——请求量砍掉 60%+，列表数据还能复用（`--reuse-list`）反复调过滤条件。

## 三个平台坑（都写进脚本了）

1. **`city` 参数会失效**：目标城市岗位少时返回全国岗位。必须按 `location` 字段二次过滤。
2. **冷门关键词会被降级**：搜「航道工程」可能返回「算法工程师」「酒店前台」，平台用泛结果填空。
3. **关键词会误命中**：`水工` → 「送水工」，`会计` → 「电话销售」。用 `--noise` 剔掉。

## 抽词为什么能抽出干净术语

从 JD 正文里找术语看着简单，实际有一半工作量在清洗。实测（153 条数据安全岗）踩到的四类噪音：

| 噪音 | 实测 | 处理方式 |
|---|---|---|
| 反爬水印插在词内部 | `kanzhun` 出现 21 次，把「抖音」切成「抖kanzhun音」 | 删水印（不补空格），被切开的词自动复原 |
| 康熙部首冒充汉字 | **532 个** `⽇`(U+2F47) 这类字符，肉眼看不出 | NFKC 归一化还原成「日」 |
| 跨词碎片 | `数据分`（数据\|分析）、`沟通协`（沟通\|协调） | 分词边界一致率 < 0.75 丢弃 |
| 单侧固定碎片 | `据安全`（左边永远是「数」） | 左右邻接字熵 < 1.0 bit 丢弃 |

漏斗：`6820 个候选 → 熵过滤 1036 → 边界过滤 725 → 虚词词性 698 → top 60`。
排序用**提及岗位数**而不是词频——同一个 JD 里出现 20 次，可能只是那家公司的口头习惯。

## 已知限制

- 需要**有图形界面**的环境（`headless=False` 弹浏览器扫码）；纯服务器跑不了登录
- 首次要下约 500 MB 定制 Chromium，国内 8–10 分钟
- 城市名要用简称，冷门城市查不到编码会直接报错（可在 `cities.py` 的 `BUILTIN` 补）
- 同时只能开一个 CloakBrowser 实例
- 匹配分是规则打分，衡量「JD 与你能力的重合度」，**不是录取概率**

## 合规

仅供个人求职研究使用。只抓登录后可见的公开岗位信息，请控制频率、不要转售数据、不要用于商业采集。抓取行为受 BOSS 直聘用户协议约束，风险自负。

## License

MIT
