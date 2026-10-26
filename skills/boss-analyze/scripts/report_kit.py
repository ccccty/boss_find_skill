"""报告工具集：花叔 Design 风格的自包含 HTML 拼装件

设计约定（照此实现，别改成"AI 味"卡片流）：
- 暖白底 #FAF9F6、墨黑字 #1C1917、赭石 accent #9A3412、细线分隔、无圆角阴影堆叠
- 标题宋体（Noto Serif SC 回退 Songti/SimSun），数字等宽
- 图表用 CSS 柱条 + conic-gradient 环形图，不依赖任何 CDN（离线可用）
- 所有外链必须 abs_url() 补全域名，否则在 localhost/file:// 预览下会 404
"""

import html
import re

ACCENT = "#9A3412"

CSS = """
:root { --bg:#FAF9F6; --ink:#1C1917; --sub:#57534E; --line:#E7E5E4;
  --accent:#9A3412; --warm:#F5F1EA; --mono:'DM Mono',ui-monospace,Consolas,monospace; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); line-height:1.72; font-size:15px;
  font-family:"Noto Sans SC",-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
.wrap { max-width:1120px; margin:0 auto; padding:60px 32px 96px; }
h1,h2,h3 { font-family:"Noto Serif SC",Songti SC,SimSun,serif; font-weight:600; }
h1 { font-size:36px; line-height:1.3; margin:0 0 12px; }
h2 { font-size:21px; margin:58px 0 8px; padding-bottom:9px; border-bottom:1px solid var(--ink); }
h3 { font-size:16px; margin:30px 0 10px; color:var(--sub); }
.lede { color:var(--sub); font-size:16.5px; max-width:820px; }
.meta { display:flex; gap:26px; flex-wrap:wrap; margin:26px 0 0; padding:14px 0;
  border-top:1px solid var(--line); border-bottom:1px solid var(--line);
  font-family:var(--mono); font-size:12px; color:var(--sub); }
.meta b { color:var(--ink); }
.kpis { display:grid; grid-template-columns:repeat(4,1fr); margin:34px 0 6px;
  border:1px solid var(--line); background:#fff; }
.kpi { padding:18px 20px; border-right:1px solid var(--line); }
.kpi:last-child { border-right:none; }
.kpi .n { font-family:var(--mono); font-size:28px; color:var(--accent); line-height:1.2; }
.kpi .l { font-size:12px; color:var(--sub); margin-top:3px; }
.note { background:var(--warm); border-left:3px solid var(--accent); padding:16px 20px;
  margin:26px 0; font-size:14.5px; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:38px; }
table { width:100%; border-collapse:collapse; margin:12px 0 4px; font-size:13px; background:#fff; }
th { text-align:left; font-weight:600; color:var(--sub); font-size:11.5px; letter-spacing:.05em;
  padding:9px 10px; border-bottom:1px solid var(--ink); }
td { padding:11px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
.row-main td { border-bottom:none; padding-bottom:4px; }
.row-jd td { border-bottom:1px solid var(--line); padding:0 10px 8px; }
.num { font-family:var(--mono); }
.sal { font-family:var(--mono); color:var(--accent); white-space:nowrap; }
.dim { color:#A8A29E; font-size:12px; }
.sub2 { color:var(--sub); font-size:12px; margin-top:2px; }
a { color:var(--accent); text-decoration:none; border-bottom:1px solid currentColor; font-size:12px; }
details summary { cursor:pointer; color:var(--sub); font-size:12px; outline:none; }
details p { margin:8px 0 0; color:#44403C; font-size:13px; white-space:pre-wrap;
  background:var(--warm); padding:14px 16px; }
details .jd-meta { color:#A8A29E; font-size:11.5px; background:none; padding:6px 0 0; }
.bar-row { display:grid; grid-template-columns:170px 1fr 62px; align-items:center; gap:12px;
  padding:4px 0; font-size:13px; }
.bar-label { color:var(--sub); text-align:right; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }
.bar-track { background:#EFEBE4; height:15px; }
.bar-fill { background:var(--accent); height:100%; }
.bar-value { font-family:var(--mono); font-size:12.5px; }
.donut-wrap { display:flex; align-items:center; gap:26px; margin:14px 0; }
.donut { width:140px; height:140px; border-radius:50%; position:relative; flex:none; }
.donut-hole { position:absolute; inset:32px; background:var(--bg); border-radius:50%;
  display:flex; flex-direction:column; align-items:center; justify-content:center; }
.donut-hole b { font-family:var(--mono); font-size:21px; }
.donut-hole span { font-size:11px; color:var(--sub); }
.legend { list-style:none; padding:0; margin:0; font-size:13px; flex:1; }
.legend li { display:flex; align-items:center; gap:8px; margin:4px 0; }
.legend i { width:10px; height:10px; display:inline-block; }
.legend b { font-family:var(--mono); margin-left:auto; }
.legend span { color:var(--sub); width:44px; text-align:right; font-family:var(--mono); font-size:12px; }
.foot { margin-top:70px; padding-top:18px; border-top:1px solid var(--line);
  color:#A8A29E; font-size:12px; }
@media (max-width:880px) { .kpis { grid-template-columns:1fr 1fr; }
  .grid2 { grid-template-columns:1fr; gap:22px; }
  .bar-row { grid-template-columns:100px 1fr 50px; }
  .wrap { padding:32px 16px 60px; } h1 { font-size:27px; } }
"""


def esc(t):
    return html.escape(str(t or ""), quote=True)


def abs_url(link, base="https://www.zhipin.com"):
    """BOSS 的岗位链接是 /job_detail/xxx.html 这类站内相对路径。
    报告常在 file:// 或 127.0.0.1 预览下打开，相对路径会被解析到本地导致 404，
    所以任何写进 href 的链接都必须先补全域名。"""
    if not link:
        return base + "/"
    return link if str(link).startswith("http") else base + str(link)


def page(title, subtitle, meta_items, body):
    meta = "".join(f"<span>{esc(k)} <b>{esc(v)}</b></span>" for k, v in meta_items)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>{title}</h1>
<p class="lede">{subtitle}</p>
<div class="meta">{meta}</div>
{body}
</div></body></html>"""


def kpis(items):
    cells = "".join(f'<div class="kpi"><div class="n">{esc(n)}</div>'
                    f'<div class="l">{esc(l)}</div></div>' for n, l in items)
    return f'<div class="kpis">{cells}</div>'


def bar_rows(items, unit="个", limit=None):
    items = list(items)[:limit] if limit else list(items)
    mx = max([v for _, v in items], default=1) or 1
    out = []
    for name, v in items:
        out.append(f'<div class="bar-row"><div class="bar-label">{esc(name)}</div>'
                   f'<div class="bar-track"><div class="bar-fill" style="width:{v / mx * 100:.1f}%"></div></div>'
                   f'<div class="bar-value">{v}<span class="dim"> {unit}</span></div></div>')
    return "\n".join(out)


def donut(items, unit="样本"):
    total = sum(v for _, v in items) or 1
    colors = ["#9A3412", "#C2410C", "#EA580C", "#B45309", "#78716C", "#A8A29E", "#D6D3D1"]
    stops, legend, acc = [], [], 0.0
    for i, (k, v) in enumerate(items):
        start, acc = acc / total * 100, acc + v
        stops.append(f"{colors[i % len(colors)]} {start:.2f}% {acc / total * 100:.2f}%")
        legend.append(f'<li><i style="background:{colors[i % len(colors)]}"></i>{esc(k)}'
                      f'<b>{v}</b><span>{v / total * 100:.0f}%</span></li>')
    return (f'<div class="donut-wrap"><div class="donut" '
            f'style="background:conic-gradient({",".join(stops)})">'
            f'<div class="donut-hole"><b>{total}</b><span>{esc(unit)}</span></div></div>'
            f'<ul class="legend">{"".join(legend)}</ul></div>')


SALARY_RE_K = re.compile(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[Kk千]")
SALARY_RE_K1 = re.compile(r"(\d+(?:\.\d+)?)\s*[Kk千]")
SALARY_RE_M = re.compile(r"(\d+)\s*[-~]\s*(\d+)\s*元/月")


def parse_salary_monthly(s):
    """把「10-15K·14薪」「8000-12000元/月」解析为月薪中位数（单位 K）。
    时薪/日薪直接返回 None，不污染月薪统计。"""
    if not s:
        return None
    if any(k in s for k in ("元/时", "元/小时", "元/天", "元/次", "元/节课")):
        return None
    t = re.sub(r"[·・].*$", "", s).strip()
    m = SALARY_RE_K.search(t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return (lo + hi) / 2 if lo <= 80 else None
    m = SALARY_RE_M.search(t)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2000
    m = SALARY_RE_K1.search(t)
    if m:
        v = float(m.group(1))
        return v if v <= 80 else None
    return None


def job_row(job, extra_cols=None, jd=True):
    """一条岗位 = 主行 + 可展开的 JD 行。extra_cols 为已渲染的 <td> 片段列表。"""
    extra = "".join(extra_cols or [])
    main = f"""<tr class="row-main">
  <td class="nm"><b>{esc(job.get('name'))}</b>
      <div class="sub2">{esc(job.get('company', ''))}{(' · ' + esc(job.get('industry'))) if job.get('industry') else ''}</div></td>
  <td class="sal">{esc(job.get('salary') or '面议')}</td>
  <td class="dim">{esc(job.get('experience') or '—')}<br>{esc(job.get('education') or '—')}</td>
  <td class="dim">{esc(job.get('location') or '')}</td>{extra}
  <td><a href="{abs_url(job.get('link'))}" target="_blank" rel="noopener">原页面</a></td>
</tr>"""
    if not jd:
        return main
    desc = esc(job.get("description") or "（未采集到 JD 正文）")
    meta = " · ".join(x for x in (job.get("industry"), job.get("scale"), job.get("financing")) if x)
    jdrow = (f'<tr class="row-jd"><td colspan="{4 + len(extra_cols or [])}"><details>'
             f'<summary>查看 JD</summary><p>{desc}</p>'
             f'<p class="jd-meta">{esc(meta)}</p></details></td></tr>')
    return main + "\n" + jdrow
