#!/usr/bin/env python3
"""Fetch tech news from multiple sources, rank top 10 with DeepSeek API, output data.json."""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import feedparser
import httpx
from openai import OpenAI

# ── Configuration ──────────────────────────────────────────────

RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.wired.com/feed/rss",
    "https://www.engadget.com/rss.xml",
    "https://9to5mac.com/feed/",
]

HN_TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"

MAX_ARTICLES_TO_SEND = 60  # upper bound for Claude input
OUTPUT_FILE = "data.json"
MAX_WORKERS = 5
SIMILARITY_THRESHOLD = 0.8

SUMMARY_PROMPT = """你是一名资深科技编辑。以下是从各大科技媒体抓取到的今日科技资讯列表。

请完成以下任务：
1. 从这些资讯中选出最受关注、最有影响力的 **10 条**科技新闻
2. 按照重要性从高到低排序
3. 对每条新闻给出：中文标题、简短摘要（2-3句话）、新闻类别（如 AI/产品/投融资/硬件/互联网/航空航天/生物科技）、来源

**严格排除以下类型的新闻（即使影响力大也必须跳过）：**
- 政府政策、法律法规、监管合规
- 反垄断调查、罚款、诉讼判决
- 数据隐私立法、AI 监管法案
- 选举、政治活动相关科技话题
- 国际制裁、贸易限制

只选择真正的技术突破、产品发布、科研进展、商业动态。

以 JSON 数组格式返回，不要包含 markdown 标记：
[
  {
    "rank": 1,
    "title": "中文标题",
    "summary": "2-3句中文摘要",
    "category": "AI",
    "source": "TechCrunch",
    "url": "原文链接",
    "published": "发布时间"
  },
  ...
]"""

# ── Article fetching ────────────────────────────────────────────


def _title_key(title: str) -> str:
    """Normalize a title for dedup comparison."""
    return "".join(c.lower() for c in title if c.isalnum())


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _title_key(a), _title_key(b)).ratio()


def fetch_rss(url: str) -> list[dict]:
    """Fetch articles from a single RSS feed. Returns list of dicts."""
    articles = []
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        print(f"  ⚠ Failed to fetch {url}: {exc}", file=sys.stderr)
        return articles

    if feed.bozo:
        print(f"  ⚠ Parse error for {url}: {feed.bozo_exception}", file=sys.stderr)

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        published = entry.get("published", "") or entry.get("updated", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        summary = re.sub(r"<[^>]*>", "", summary).strip()
        if title and link:
            articles.append(
                {
                    "title": title,
                    "url": link,
                    "published": published,
                    "summary": summary,
                    "source": feed.feed.get("title", url),
                }
            )
    return articles


def fetch_hackernews(client: httpx.Client) -> list[dict]:
    """Fetch top HN stories with metadata."""
    articles = []
    try:
        r = client.get(HN_TOP_STORIES, timeout=10)
        r.raise_for_status()
        ids = r.json()[:30]
    except Exception as exc:
        print(f"  ⚠ Failed to fetch HN top stories: {exc}", file=sys.stderr)
        return articles

    def _fetch_one(story_id: int):
        try:
            r = client.get(HN_ITEM.format(story_id), timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, sid): sid for sid in ids}
        for f in as_completed(futures):
            item = f.result()
            if item and item.get("type") == "story" and item.get("title"):
                ts = item.get("time", 0)
                articles.append(
                    {
                        "title": item["title"],
                        "url": item.get("url", f"https://news.ycombinator.com/item?id={item['id']}"),
                        "published": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                        "summary": "",
                        "source": "Hacker News",
                    }
                )
    return articles


def fetch_all() -> list[dict]:
    """Fetch from all sources in parallel."""
    all_articles: list[dict] = []
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(fetch_rss, url): url for url in RSS_FEEDS
            }
            futures[pool.submit(fetch_hackernews, client)] = "hackernews"
            for f in as_completed(futures):
                all_articles.extend(f.result())
    return all_articles


# ── Deduplication ───────────────────────────────────────────────


def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove near-duplicate articles by title similarity."""
    seen: list[dict] = []
    for art in articles:
        if any(_similar(art["title"], s["title"]) >= SIMILARITY_THRESHOLD for s in seen):
            continue
        seen.append(art)
    return seen


# ── Filter today ────────────────────────────────────────────────


def filter_recent(articles: list[dict], hours: int = 24) -> list[dict]:
    """Keep only articles published within the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for art in articles:
        try:
            # Try common datetime formats
            for fmt in [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
            ]:
                try:
                    dt = datetime.strptime(art["published"], fmt)
                    break
                except (ValueError, Exception):
                    pass
            else:
                # Can't parse date — skip to avoid stale news
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if dt >= cutoff:
            recent.append(art)
    return recent


# ── LLM ranking ─────────────────────────────────────────────────


def rank_with_llm(articles: list[dict]) -> list[dict]:
    """Send articles to DeepSeek for top-10 ranking and summarization."""
    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
    )

    # Build compact article list for the prompt
    lines = []
    for i, art in enumerate(articles):
        lines.append(
            f"[{i}] {art['title']}\n"
            f"    来源: {art['source']}\n"
            f"    摘要: {art['summary'][:200]}\n"
            f"    链接: {art['url']}\n"
            f"    时间: {art['published']}\n"
        )
    article_text = "\n".join(lines)

    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=4096,
        temperature=0.3,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"今天是{datetime.now(timezone.utc).strftime('%Y年%m月%d日')}。以下是今日科技资讯，请只选择今日的新闻，排除所有政策、法规、监管类新闻：\n\n{article_text}"},
        ],
    )

    # Parse JSON from response
    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        print("Failed to parse DeepSeek response as JSON:", file=sys.stderr)
        print(text, file=sys.stderr)
        # Fallback: return raw articles as top 10
        result = []
        for i, art in enumerate(articles[:10]):
            result.append(
                {
                    "rank": i + 1,
                    "title": art["title"],
                    "summary": art["summary"][:300],
                    "category": "科技",
                    "source": art["source"],
                    "url": art["url"],
                    "published": art["published"],
                }
            )
    return result


# ── Main ────────────────────────────────────────────────────────


def main():
    print("Fetching news from all sources...")
    raw = fetch_all()
    print(f"  Fetched {len(raw)} articles")
    # Per-source breakdown
    sources = {}
    for art in raw:
        src = art.get("source", "Unknown")
        sources[src] = sources.get(src, 0) + 1
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"    {src}: {count}")

    print("Filtering recent articles...")
    recent = filter_recent(raw)
    print(f"  {len(recent)} recent articles")

    print("Deduplicating...")
    unique = deduplicate(recent)
    print(f"  {len(unique)} unique articles")

    # Fallback: widen time window if no recent articles found
    if not unique:
        for fallback_hours in (48, 72, 96):
            print(f"  No articles in current window, trying {fallback_hours}h...")
            recent = filter_recent(raw, hours=fallback_hours)
            unique = deduplicate(recent)
            print(f"    {len(unique)} unique articles")
            if unique:
                break

    if not unique:
        print("No articles found. Check your network or RSS sources.", file=sys.stderr)
        sys.exit(1)

    # Limit to max for LLM
    if len(unique) > MAX_ARTICLES_TO_SEND:
        unique = unique[:MAX_ARTICLES_TO_SEND]

    print("Ranking with DeepSeek...")
    top10 = rank_with_llm(unique)
    print(f"  Got {len(top10)} ranked articles")

    # Build output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "count": len(top10),
        "articles": top10,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Output saved to {OUTPUT_FILE}")
    for art in top10:
        print(f"  #{art['rank']} [{art['category']}] {art['title']}")


if __name__ == "__main__":
    main()
