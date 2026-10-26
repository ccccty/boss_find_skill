---
name: boss-setup
description: 配置BOSS直聘抓取环境。安装CloakBrowser反检测浏览器、Playwright和Python依赖，验证 navigator.webdriver 已被隐藏。触发词：配置boss抓取、安装cloakbrowser、boss环境配置、boss环境装不上。
---

# BOSS 直聘抓取环境配置

CloakBrowser（反检测 Chromium）+ Playwright。一次性配置，之后 `boss-scrape` 直接复用。

## Step 0 · 先检测，别重复装

```bash
python -c "from cloakbrowser import launch; b=launch(headless=True); p=b.new_page(); \
print('webdriver:', p.evaluate('navigator.webdriver')); b.close()" 2>&1
```

判断：

| 输出 | 处理 |
|---|---|
| 含 `webdriver: False` | **环境就绪，跳过全部步骤**，直接告诉用户可以抓了 |
| 含 `webdriver: True` | CloakBrowser 装坏了，重装（先 `pip uninstall cloakbrowser`） |
| `ModuleNotFoundError` | 未安装，走 Step 1 |

## Step 1 · 前置检查

```bash
python --version && node --version
```

要 Python ≥ 3.9、Node ≥ 18。不满足就停，别硬装。

## Step 2 · 建虚拟环境

在**项目目录**（不是 skill 目录）里建，后续抓取的 `data/` 也在这里：

```bash
mkdir -p boss-jobs && cd boss-jobs
python -m venv .venv
```

激活：
- Windows / Git Bash：`source .venv/Scripts/activate`
- macOS / Linux：`source .venv/bin/activate`

> 判断当前 shell 属于哪种：`ls .venv` 里是 `Scripts` 还是 `bin`。

## Step 3 · 安装 CloakBrowser

```bash
.venv/Scripts/python.exe -m pip install "cloakbrowser[geoip]"
```

国内网络慢可以加镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

装完验证导入：

```bash
.venv/Scripts/python.exe -c "from cloakbrowser import launch; print('OK')"
```

## Step 4 · 安装 Playwright 浏览器

```bash
.venv/Scripts/python.exe -m playwright install chromium
```

约 120 MB，落到 `~/AppData/Local/ms-playwright/`（macOS 是 `~/Library/Caches/ms-playwright/`）。

## Step 5 · 首次启动（关键：会下载约 500 MB）

第一次 `launch()` 会从 `cloakbrowser.dev` 拉定制 Chromium：

```bash
.venv/Scripts/python.exe -c "
from cloakbrowser import launch
b = launch(headless=True); p = b.new_page()
print('webdriver:', p.evaluate('navigator.webdriver'))
print('ua:', p.evaluate('navigator.userAgent'))
b.close()
"
```

**这段会跑很久，不要以为卡死了。** 实测数据（供排期参考）：

| 项 | 实测 |
|---|---|
| 定制 Chromium 体积 | 约 500 MB（zip），解压后 `~/.cloakbrowser/chromium-<version>/` |
| 国内下载耗时 | 8–10 分钟（1 MB/s 左右） |
| 缓存命中后启动 | 3–5 秒 |

想确认是否在下：看 `%TEMP%` 下有没有不断变大的 `tmp*.zip`，或 `du -sh ~/.cloakbrowser`。

## Step 6 · 验收标准

必须同时满足：

- `webdriver: False`
- UA 是正常的 `Chrome/1xx`，不是 `HeadlessChrome`
- 启动日志里有 `CloakBrowser - stealth Chromium for automation`

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `EOFError` / `ReadTimeout` 下载中断 | 网络抖动 | 重跑一次，支持断点续传；反复失败可换网络 |
| `CloakBrowserLicenseError` | 触发并发/授权限制 | 同时只开一个浏览器实例；不要多开 |
| `chromium 已存在但启动失败` | 上次解压不完整 | 删 `~/.cloakbrowser/chromium-*` 重跑 |
| `python3: command not found`（Windows） | Windows 只有 `python` | 全部命令改用 `python` |
| 抓取时报 `DISCONNECTED` | 被限流 | 不是环境问题，见 boss-scrape 的限流处理 |

## 完成时报告

- 虚拟环境路径、Python 版本
- CloakBrowser 版本 + Chromium 版本（`python -c "import cloakbrowser; print(cloakbrowser.binary_info())"`）
- `webdriver` 检测结果
- 下一步：用 `boss-scrape` 开始抓取
