# 部署与手机安装

目标：手机上点一下图标就能刷卡片，**每天新增卡片不需要你手动更新**。

---

## 一 · 推到一个独立仓库

一个领域一个仓库，别和别的项目混在一起（Pages 免费账号只支持 public 仓库）。

```bash
cd 数据安全-study
git init -b main
git add -A
git commit -m "feat: 数据安全概念卡片站"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

> 仓库要先在 GitHub 网页上建好，**三个初始化选项都不要勾**（README / .gitignore / license），
> 勾了会和本地第一次提交冲突。

## 二 · 打开 Pages

仓库页 → `Settings` → 左侧 `Pages` → Source 选 `Deploy from a branch` → Branch 选 `main`、目录 `/ (root)` → Save。

生效时间实测：

| 阶段 | 耗时 |
|---|---|
| 首次开启 | 约 50~90 秒 |
| 之后每次 push | 约 20~60 秒 |
| CDN 缓存 | 最长 10 分钟（页面里已用 `?t=时间戳` 绕过） |

> 60 秒还 404 不要急着改配置，先等满 2 分钟。新仓库首次构建比后续慢。

地址是 `https://<用户名>.github.io/<仓库名>/`。

## 三 · 手机加到主屏

- **iOS**：Safari 打开 → 分享 → 添加到主屏幕
- **Android**：Chrome 打开 → 右上菜单 → 添加到主屏幕 / 安装应用

加到主屏后是全屏独立应用（有 manifest + Service Worker），不是普通书签，断网也能打开已缓存的页面。

### 生成二维码方便扫

```bash
python scripts/make_qr.py --url https://ccccty.github.io/study/ \
    --out ../my-study/qr.png --title "概念卡片 · 每日一推"
```

需要 `pip install qrcode pillow`。

---

## 四 · 日常更新：手机上什么都不用做

页面每次打开都会 `fetch('cards.json?t=' + Date.now(), {cache:'no-store'})`，
时间戳让所有缓存失效，**只要 cards.json 是新的，打开就是新的**。

| 场景 | 手机上要做什么 |
|---|---|
| 每天新增的卡片（只改 `cards.json`） | **什么都不用做** |
| 改了 `index.html`（引擎/样式） | 数据页点「刷新题库」 |
| 想确认拿到哪一版 | 数据页底部看「页面版本 / 张数 / 数据更新于」 |

### 每日链路

```
08:40 抓岗位 → 抽词 → 写卡 → merge_cards.py 入池
      → git commit cards.json && git push
      → Pages 重建（1 分钟内）
      → 手机打开即读到新卡
```

---

## 五 · 进度存在哪，怎么不丢

进度**只存在本机浏览器**，不随仓库同步。三层落盘：

| 层 | 作用 |
|---|---|
| `localStorage` | 主存储，同步读写，首屏不等异步 |
| `IndexedDB` | 镜像备份，清缓存后靠它恢复（串行写入，避免乱序覆盖） |
| `StorageManager.persist()` | 申请持久化，降低系统清理概率 |

**两个必须知道的边界：**

1. **iOS 主屏图标与 Safari 标签页的存储互相隔离。** 在主屏里答的进度，用 Safari 打开同一地址看不到。选定一种用到底。
2. **iOS 会回收长期不访问站点的本地存储。** 建议每月在数据页点一次「导出进度」存网盘。

换设备：数据页「导出进度」→ 新设备「导入进度」。

---

## 六 · 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面空白，提示「没读到 cards.json」 | 双击 `file://` 打开，或 cards.json 不在同目录 | 用 http 地址打开；确认文件同名同级 |
| 页面一直显示旧内容 | 改了 `index.html` 但没点刷新 | 数据页点「刷新题库」 |
| 手机上不是全屏应用 | 没走「添加到主屏幕」，只是普通打开 | 重新按第三节操作 |
| 装了 SW 后本地预览看不到改动 | Service Worker 缓存了旧版 | Chrome DevTools → Application → Service Workers → Update on reload |
| 进度突然归零 | 清了浏览器数据，且 IndexedDB 也被清 | 用提前导出的备份导入 |
