# Hormuz Tracker

每日自动追踪霍尔木兹海峡通航量与恢复程度，由 Claude API + GitHub Actions 驱动。

## 架构

```
GitHub Actions (cron 01:00 UTC)
        │
        ▼
   tracker.py  ──► Claude API (web_search)
        │
        ├──► history/YYYY-MM-DD.json   (每日归档)
        ├──► docs/data.json            (聚合给前端)
        └──► Feishu webhook            (可选)
        │
        ▼
   git commit + push
        │
        ▼
   GitHub Pages 自动重新发布
        │
        ▼
   https://你的用户名.github.io/hormuz-tracker/
```

## 一次性部署 (10 分钟)

### 1. 在 GitHub 创建空仓库

仓库名建议 `hormuz-tracker`，**Public**（GitHub Pages 免费版要求）。
不要勾选 "Initialize with README"，保持完全空仓库。

### 2. 推送代码

在本地解压后：

```bash
cd hormuz-tracker
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/你的用户名/hormuz-tracker.git
git push -u origin main
```

### 3. 配置 Secrets

进入仓库 → Settings → Secrets and variables → Actions → New repository secret

**必填**:
- `ANTHROPIC_API_KEY` = `sk-ant-...`

**可选 (要飞书推送才填)**:
- `FEISHU_WEBHOOK_URL` = 飞书机器人 webhook
- `FEISHU_SECRET` = 飞书签名密钥（如启用）

### 4. 启用 GitHub Pages

Settings → Pages →
- Source: **Deploy from a branch**
- Branch: **main** / **/docs**
- Save

约 1-2 分钟后访问 `https://你的用户名.github.io/hormuz-tracker/`，
应该看到一个空的 dashboard（因为还没运行过）。

### 5. 手动触发第一次运行

Actions 标签页 → **Daily Hormuz Tracker** → **Run workflow** → Run

约 1-2 分钟后会看到一次新 commit，刷新网页就有数据了。

之后每天 UTC 01:00（北京时间 09:00）自动跑。

## 排错

**Action 失败 → 红色 ❌**
点进去看日志。最常见原因：
- `ANTHROPIC_API_KEY` 没设或拼错
- API 余额不足
- Claude 返回的 JSON 解析失败（罕见，重新触发即可）

**网页打开是 404**
- 确认 Pages 设置里 source 选的是 `main` 分支 `/docs` 目录
- 等 2-3 分钟生效

**网页打开但显示 "还没有任何报告"**
- 还没运行过 Action，去 Actions 页手动触发一次

**Action 成功但 commit 失败**
- 检查 Settings → Actions → General → Workflow permissions
- 必须是 **Read and write permissions**

## 成本估算

- Claude API: 每次运行约 $0.05-0.15 (Sonnet 4.6 + 10 次 web_search)
- 每月约 $3-5
- GitHub Actions 公开仓库免费
- GitHub Pages 公开仓库免费

## 自定义

- **改运行时间**: `.github/workflows/daily.yml` 里的 cron 表达式（用 UTC）
- **改模型**: `tracker.py` 顶部的 `MODEL` 常量，可换 `claude-opus-4-6` 提高质量
- **改评分权重**: `tracker.py` 里的 `PROMPT_TEMPLATE` 评分方法部分
- **改网页样式**: `docs/index.html`
