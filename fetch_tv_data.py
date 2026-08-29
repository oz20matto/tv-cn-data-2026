#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7: Baidu-first + token validation + ZOL direct search w/ auto product page fetch.
modes: serp (baidu->so360->sogou->bingrss, validated), zolauto (zol search + fetch top product pages), page.
"""
import base64
import html as htmllib
import json
import os
import re
import time
import urllib.parse

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REPO = "oz20matto/tv-cn-data-2026"
API = "https://api.github.com"
CHUNK = 46000

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})


def http_get(url):
    r = SESSION.get(url, timeout=25, allow_redirects=True)
    enc = r.encoding if (r.encoding and r.encoding.lower() not in ("iso-8859-1", "ascii")) else r.apparent_encoding
    r.encoding = enc or "utf-8"
    return r


def clean_text(s):
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def strip_html(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\\1>", " ", h)
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)
    h = re.sub(r"(?s)<[^>]+>", "\n", h)
    h = htmllib.unescape(h)
    h = re.sub(r"[ \\t\\x0b\\f\\r]+", " ", h)
    h = re.sub(r"\\n\\s*\\n+", "\\n", h)
    return h.strip()


def token_ok(items, tokens):
    if not tokens:
        return True
    blob = " ".join((t or "") + " " + (u or "") + " " + (s or "") for t, u, s in items).lower()
    return any(tok.lower() in blob for tok in tokens)


def engine_baidu(query):
    try:
        http_get("https://www.baidu.com/")
    except Exception:
        pass
    r = http_get("https://www.baidu.com/s?wd=" + urllib.parse.quote(query) + "&rn=10")
    if r.status_code != 200:
        return None, f"status={r.status_code} len={len(r.text)}" if False else f"status={r.status_code}"
    if "百度安全验证" in r.text:
        return None, "BAIDU-CAPTCHA"
    items = []
    blocks = re.split(r'class="result c-container', r.text)[1:]
    for b in blocks[:10]:
        m = re.search(r'<h3[^>]*>\\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        href = m.group(1)
        if href.startswith("/"):
            href = "https://www.baidu.com" + href
        title = clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        snip = clean_text(strip_html(b))[:280]
        items.append([title, href, snip])
    return (items or None), f"status={r.status_code} blocks={len(blocks)}"


def engine_so360(query):
    r = http_get("https://www.so.com/s?q=" + urllib.parse.quote(query) + "&pn=1")
    if r.status_code != 200:
        return None, f"status={r.status_code}"
    items = []
    for m in re.finditer(r'<h3[^>]*>\\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        href = m.group(1)
        if href.startswith("/"):
            href = "https://www.so.com" + href
        title = clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        items.append([title, href, ""])
        if len(items) >= 8:
            break
    return (items or None), f"status={r.status_code}"


def engine_sogou(query):
    r = http_get("https://www.sogou.com/web?query=" + urllib.parse.quote(query))
    if r.status_code != 200:
        return None, f"status={r.status_code}"
    items = []
    for m in re.finditer(r'<h3[^>]*>\\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        href = m.group(1)
        if href.startswith("/"):
            href = "https://www.sogou.com" + href
        title = clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        items.append([title, href, ""])
        if len(items) >= 8:
            break
    return (items or None), f"status={r.status_code}"


def engine_bingrss(query):
    url = "https://www.bing.com/search?format=rss&count=8&q=" + urllib.parse.quote(query)
    r = http_get(url)
    if r.status_code != 200 or "<item" not in r.text:
        return None, f"status={r.status_code}"
    items = []
    for m in re.finditer(r"<item>(.*?)</item>", r.text, re.S):
        blk = m.group(1)
        t = re.search(r"<title>(.*?)</title>", blk, re.S)
        l = re.search(r"<link>(.*?)</link>", blk, re.S)
        d = re.search(r"<description>(.*?)</description>", blk, re.S)
        title = clean_text(t.group(1)) if t else ""
        link = clean_text(l.group(1)) if l else ""
        desc = clean_text(d.group(1))[:250] if d else ""
        if "u=a1" in link:
            m2 = re.search(r"u=a1([A-Za-z0-9+/=_-]+)", link)
            if m2:
                try:
                    dec = base64.b64decode(m2.group(1) + "=" * (-len(m2.group(1)) % 4)).decode("utf-8", "ignore")
                    if dec.startswith("http"):
                        link = dec
                except Exception:
                    pass
        if title:
            items.append([title, link, desc])
    return (items[:8] or None), f"status={r.status_code}"


def do_serp(note, query, tokens):
    lines = [f"===== SERP {note} =====", f"QUERY {query}"]
    for name, fn in [("baidu", engine_baidu), ("so360", engine_so360), ("sogou", engine_sogou), ("bingrss", engine_bingrss)]:
        try:
            items, info = fn(query)
            if items and token_ok(items, tokens):
                lines.append(f"SRC {name} ({len(items)} res, {info})")
                for i, (t, u, s) in enumerate(items, 1):
                    lines.append(f"[{i}] {t}\\n    URL {u}\\n    SNIP {s}")
                return "\\n".join(lines) + "\\n"
            lines.append(f"{name}: {'empty' if not items else 'TOKEN-MISS'} ({info})")
        except Exception as e:
            lines.append(f"{name} err {type(e).__name__}: {e}")
        time.sleep(0.5)
    return "\\n".join(lines) + "\\n"


def do_zolauto(note, keyword, tokens, npages=2, keep=9000):
    lines = [f"===== ZOLAUTO {note} =====", f"KEYWORD {keyword}"]
    search_url = "https://detail.zol.com.cn/index.php?c=SearchList&keyword=" + urllib.parse.quote(keyword)
    try:
        r = http_get(search_url)
        lines.append(f"SEARCH http={r.status_code} len={len(r.content)}")
        if r.status_code == 200:
            # find product links: detail.zol.com.cn/tv/indexNNN.shtml or .../NNN.shtml
            links = []
            for m in re.finditer(r'href="(https?://detail\\.zol\\.com\\.cn/(?:tv/)?index\\d+\\.shtml)"[^>]*>(.*?)</a>', r.text, re.S):
                u, txt = m.group(1), clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))[:80]
                if u not in [x[0] for x in links]:
                    links.append((u, txt))
            lines.append("LINKS: " + " | ".join(f"{u} [{t}]" for u, t in links[:8]) if links else "NO LINKS FOUND")
            picked = 0
            for u, t in links:
                if picked >= npages:
                    break
                if tokens and not token_ok([(t, u, "")], tokens):
                    continue
                picked += 1
                try:
                    rr = http_get(u)
                    lines.append(f"--- PRODUCT {picked} {u} http={rr.status_code} len={len(rr.content)} ---")
                    if rr.status_code == 200:
                        lines.append(strip_html(rr.text)[:keep])
                except Exception as e:
                    lines.append(f"product err {e}")
                time.sleep(1)
            if picked == 0:
                lines.append("token-filtered: nothing picked; raw first links above")
    except Exception as e:
        lines.append(f"ERR {type(e).__name__}: {e}")
    return "\\n".join(lines) + "\\n"


def do_page(note, url, keep=12000):
    lines = [f"===== PAGE {note} =====", f"SRC {url}"]
    try:
        r = http_get(url)
        lines.append(f"HTTP {r.status_code} len={len(r.content)} final={r.url}")
        if r.status_code == 200:
            lines.append("TEXT-START")
            lines.append(strip_html(r.text)[:keep])
            lines.append("TEXT-END")
    except Exception as e:
        lines.append(f"ERR {type(e).__name__}: {e}")
    return "\\n".join(lines) + "\\n"


def gh_api(method, path, token, payload=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    return requests.request(method, API + path, headers=headers, json=payload, timeout=30)


def publish(token, text, title):
    chunks = [text[i:i+CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    r = gh_api("POST", f"/repos/{REPO}/issues", token, {"title": title, "body": chunks[0]})
    if r.status_code not in (200, 201):
        print(f"ISSUE-FAIL {r.status_code} {r.text[:200]}", flush=True)
        return None
    n = r.json()["number"]
    print(f"issue #{n} ok", flush=True)
    for i, c in enumerate(chunks[1:], 2):
        rr = gh_api("POST", f"/repos/{REPO}/issues/{n}/comments", token, {"body": c})
        print(f"chunk {i}/{len(chunks)} -> {rr.status_code}", flush=True)
        time.sleep(1.2)
    return n


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)
    parts = []
    for i, t in enumerate(targets, 1):
        note, mode, tokens = t["note"], t.get("mode", "serp"), t.get("tokens", [])
        try:
            if mode == "zolauto":
                part = do_zolauto(note, t["query"], tokens, npages=t.get("npages", 2), keep=t.get("keep", 9000))
            elif mode == "page":
                part = do_page(note, t["url"], keep=t.get("keep", 12000))
            else:
                part = do_serp(note, t["query"], tokens)
        except Exception as e:
            part = f"===== {note} =====\\nERR {type(e).__name__}: {e}\\n"
        parts.append(part)
        print(f"{i:02d} {note} done", flush=True)
        time.sleep(1.0)
    full = "\\n".join(parts)
    os.makedirs("data", exist_ok=True)
    with open("data/digest.txt", "w", encoding="utf-8") as f:
        f.write(full)
    if token:
        publish(token, full, f"digest v7 {time.strftime('%m-%d %H:%M UTC', time.gmtime())}")
    print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL {type(e).__name__}: {e}", flush=True)
