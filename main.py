#!/usr/bin/env python3
"""每日科技热点聚合 + AI 摘要 + Bark 推送。

流程：拉取 RSS -> 关键词过滤/去重 -> DeepSeek 生成播报稿 -> 写文件 + Bark 推送。
本地测试：python main.py --dry-run          # 不推送、不写 summary
           python main.py --no-push         # 生成 summary 但不推送
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import feedparser
import requests
import yaml

Item = tuple[str, str, str, str, float]

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
SUMMARY_DIR = ROOT / "summary"

BARK_SERVER = os.environ.get("BARK_SERVER", "https://api.day.app").rstrip("/")
BARK_KEY = os.environ.get("BARK_KEY", "")
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


def load_config() -> dict[str, Any]:
    with open(CONFIG_DIR / "feeds.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def normalize_title(t: str) -> str:
    return " ".join((t or "").strip().lower().split())


def parse_ts(entry) -> float:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        v = entry.get(key)
        if v:
            return time.mktime(v)
    return 0.0


def fetch_feed(feed: dict[str, Any]) -> list[Item]:
    """返回 [(title, link, source, category, ts)]，失败返回 []。"""
    name, url, category = feed["name"], feed["url"], feed["category"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 抓取失败 {name}: {e}", file=sys.stderr)
        return []

    items = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = entry.get("link") or ""
        if not title:
            continue
        items.append((title, link, name, category, parse_ts(entry)))
    return items


def select_candidates(items: list[Item], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = [str(k).lower() for k in cfg.get("keywords", [])]
    top_n = int(cfg.get("top_n_per_feed", 3))
    max_cands = int(cfg.get("max_candidates", 60))
    lookback = int(cfg.get("lookback_hours", 36)) * 3600
    now = time.time()

    seen = set()
    selected = []  # dicts

    def keep(title, link, source, category, ts, matched):
        key = normalize_title(title)
        if not key or key in seen:
            return
        seen.add(key)
        selected.append(
            {
                "title": title,
                "link": link,
                "source": source,
                "category": category,
                "ts": ts,
                "matched": matched,
            }
        )

    # 按源分组做兜底：每个源最近 top_n 条不设关键词门槛
    per_feed = {}
    for title, link, source, category, ts in items:
        per_feed.setdefault(source, []).append((title, link, source, category, ts))
        per_feed[source].sort(key=lambda x: -x[4])

    # 第一步：时间窗内、命中关键词的
    for title, link, source, category, ts in items:
        if now - ts > lookback:
            continue
        if any(k in title.lower() for k in keywords):
            keep(title, link, source, category, ts, True)

    # 第二步：每个源兜底最近 top_n 条（即使没命中关键词）
    for source, lst in per_feed.items():
        for title, link, src, category, ts in lst[:top_n]:
            if now - ts > lookback:
                continue
            keep(title, link, src, category, ts, False)

    # 娱乐源单独：仅保留最近几条，交由 LLM 判断是否现象级
    ent = [it for it in selected if it["category"] == "娱乐"]
    ent = sorted(ent, key=lambda x: -x["ts"])[:5]
    tech = [it for it in selected if it["category"] != "娱乐"]

    selected = sorted(tech, key=lambda x: -x["ts"])[:max_cands] + ent
    return selected


def summarize(candidates: list[dict[str, Any]]) -> str:
    prompt_tpl = (CONFIG_DIR / "prompt.txt").read_text(encoding="utf-8")
    lines = []
    for it in candidates:
        lines.append(f"{it['title']} | {it['source']} | {it['category']}")
    items_text = "\n".join(lines)
    prompt = prompt_tpl.replace("{items}", items_text)

    if not LLM_API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量")

    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是一名中文科技新闻播报员。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 800,
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()
    return content


def push_bark(text: str, title: str):
    if not BARK_KEY:
        raise RuntimeError("缺少 BARK_KEY 环境变量")
    payload = {
        "title": title,
        "body": text,
        "device_key": BARK_KEY,
        "group": "科技早报",
        "level": "timeSensitive",
        "sound": "minute",
        "autoCopy": text,
    }
    resp = requests.post(f"{BARK_SERVER}/push", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="仅抓取+筛选，不调 LLM/不推送")
    parser.add_argument("--no-push", action="store_true", help="生成 summary 但不推送")
    args = parser.parse_args()

    cfg = load_config()
    feeds = cfg.get("feeds", [])

    all_items = []
    for feed in feeds:
        all_items.extend(fetch_feed(feed))
    print(f"[info] 抓取到 {len(all_items)} 条原始条目")

    candidates = select_candidates(all_items, cfg)
    print(f"[info] 筛选后候选 {len(candidates)} 条")
    for it in candidates[:10]:
        print(f"  - [{it['category']}] {it['title']} ({it['source']})")

    if not candidates:
        print("[warn] 无候选条目，退出")
        return

    if args.dry_run:
        print("[dry-run] 跳过摘要与推送")
        return

    text = summarize(candidates)
    print("[info] 播报稿生成完成，长度", len(text))

    SUMMARY_DIR.mkdir(exist_ok=True)
    (SUMMARY_DIR / "latest.txt").write_text(text, encoding="utf-8")

    if args.no_push:
        print("[no-push] 已生成 summary/latest.txt，跳过推送")
        return

    title = time.strftime("科技早报 · %m月%d日")
    push_bark(text, title)
    print("[info] 已推送 Bark")


if __name__ == "__main__":
    main()
