# 每日科技资讯 Top 10

每天自动抓取全球科技新闻，由 DeepSeek AI 筛选排序并生成中文摘要，通过 GitHub Pages 展示。

## 效果演示

页面每天呈现 10 张卡片，每张包含排名、中文标题、摘要、类别标签、来源和原文链接。

## 工作原理

```
RSS / Hacker News API
       ↓
  Python 去重 + 过滤
       ↓
  DeepSeek API 排序 + 摘要
       ↓
  data.json
       ↓
  GitHub Pages 静态页面
```

GitHub Actions 每天早上 **8:00（北京时间）** 自动执行一次。

## 快速开始

### 1. Fork 或克隆仓库

```bash
git clone https://github.com/<your-username>/daily-tech-news.git
cd daily-tech-news
```

### 2. 本地运行（可选）

```bash
pip install -r requirements.txt
DEEPSEEK_API_KEY=your-key python scripts/generate_news.py
```

### 3. 部署到 GitHub Pages

将项目推送到 GitHub，然后：

- **设置 API Key**：Settings → Secrets and variables → Actions → New repository secret
  - Name: `DEEPSEEK_API_KEY`
  - Value: 你的 DeepSeek API Key

- **启用 Pages**：Settings → Pages → Source → 选择 **GitHub Actions**

- **首次运行**：Actions 标签页 → Daily Tech News → Run workflow

首次运行成功后，页面地址为 `https://<your-username>.github.io/daily-tech-news/`。

## 项目结构

```
.
├── .github/workflows/daily-news.yml   # 定时构建 + 部署
├── scripts/generate_news.py           # 核心脚本
├── index.html                         # 前端页面
├── data.json                          # 每日 Top 10 数据
├── requirements.txt                   # Python 依赖
└── CLAUDE.md                          # 项目说明
```

## 新闻来源

| 来源 | 方式 |
|------|------|
| TechCrunch | RSS |
| The Verge | RSS |
| Ars Technica | RSS |
| Wired | RSS |
| Hacker News | API (hnrss + Firebase) |

如需添加更多源，编辑 `scripts/generate_news.py` 中的 `RSS_FEEDS` 列表即可。

## 自定义

- **修改运行时间**：编辑 `.github/workflows/daily-news.yml` 中的 `cron` 表达式
- **调整 Top N 数量**：修改 `scripts/generate_news.py` 中 `SUMMARY_PROMPT` 里的数字
- **更改界面配色**：修改 `index.html` 中的 CSS 变量
- **手动触发**：Actions 标签页支持 `workflow_dispatch` 手动运行
