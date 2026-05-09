# Daily Tech News

每日科技资讯 Top 10 — 自动抓取全球科技新闻，由 Claude AI 进行筛选、排序和中文摘要。

## 工作流程

```
RSS 源 / Hacker News API → Python 抓取去重 → Claude API 排序摘要 → data.json → GitHub Pages 展示
```

GitHub Actions 每天 UTC 0:00（北京时间 8:00）自动执行。

## 本地运行

```bash
pip install -r requirements.txt
ANTHROPIC_API_KEY=your-key python scripts/generate_news.py
python -m http.server 8000  # 预览 index.html
```

## 部署到 GitHub

1. 将项目推送到 GitHub 仓库
2. 在 Settings → Secrets and variables → Actions 中添加 `ANTHROPIC_API_KEY`
3. 在 Settings → Pages → Source 中选择 "GitHub Actions"
4. 手动触发一次 workflow 或等待次日自动执行
