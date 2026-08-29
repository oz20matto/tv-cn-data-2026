#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5b: DDG-html SERP parser (with Bing-zhCN fallback) + page mode.
targets.json: {"note": ..., "query": "chinese query", "mode": "serp|page", "url": ..., "keep": ...}
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


def http_get(url):
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    enc = r.encoding if (r.encoding and r.encoding.lower() not in ("iso-8859-1", "ascii")) else r.apparent_encoding
    r.encoding = enc or "utf-8"
    return r


def clean_text(s):
    s = htmllib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def strip_html(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)
    h = re.sub(r"(?s)<[^>]+>", "\n", h)
    h = htmllib.unescape(h)
    h = re.sub(r"[ \t\x0b\f\r]+", " ", h)
    h = re.sub(r"\n\s*\n+", "\n", h)
    return h.strip()


def decode_ddg(href):
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            try:
                return urllib.parse.unquote(m.group(1))
            except Exception:
                pass
    if href.startswith("http") and "duckduckgo.com" not in href:
        return href
    return ""


def parse_ddg(body):
    out = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        href, title = m.group(1), clean_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        url = decode_ddg(href)
        out.append([title, url, ""])
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)
    for i, s in enumerate(snips):
        if i < len(out):
            out[i][2] = clean_text(re.sub(r"<[^>]+>", " ", s))[:320]
    return out[:8]


def parse_bing(body):
    out = []
    blocks = re.split(r'class="b_algo"', body)[1:]
    for b in blocks[:8]:
        m_t = re.search(r"<h2[^>]*>(.*?)</h2>", b, re.S)
        title = clean_text(re.sub(r"<[^>]+>", " ", m_t.group(1))) if m_t else ""
        m_u = re.search(r'href="(https?://[^"]+)"', b)
        url = m_u.group(1) if m_u else ""
        if "u=a1" in url:
            m2 = re.search(r"u=a1([A-Za-z0-9+/=_-]+)", url)
            if m2:
                try:
                    dec = base64.b64decode(m2.group(1) + "=" * (-len(m2.group(1)) % 4)).decode("utf-8", "ignore")
                    if dec.startswith("http"):
                        url = dec
                except Exception:
                    pass
        m_s = re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        snip = clean_text(re.sub(r"<[^>]+>", " ", m_s.group(1)))[:280] if m_s else ""
        if title or url:
            out.append([title, url, snip])
    return out


def do_serp(note, query):
    lines = [f"===== SERP {note} =====", f"QUERY {query}"]
    # 1) DDG html
    try:
        r = requests.get("https://html.duckduckgo.com/html/",
                         params={"q": query},
                         headers={"User-Agent": UA}, timeout=25)
        if r.status_code == 200 and "result__a" in r.text:
            res = parse_ddg(r.text)
            if res:
                lines.append(f"SRC duckduckgo ({len(res)} res)")
                for i, (t, u, s) in enumerate(res, 1):
                    lines.append(f"[{i}] {t}\n    URL {u}\n    SNIP {s}")
                return "\n".join(lines) + "\n"
        lines.append(f"ddg skip status={r.status_code}")
    except Exception as e:
        lines.append(f"ddg err {type(e).__name__}: {e}")
    # 2) Bing zh-CN fallback
    try:
        burl = "https://cn.bing.com/search?q=" + urllib.parse.quote(query) + "&mkt=zh-CN&setlang=zh-hans&cc=CN"
        r2 = http_get(burl)
        if r2.status_code == 200:
            res = parse_bing(r2.text)
            lines.append(f"SRC bing-zh ({len(res)} res)")
            for i, (t, u, s) in enumerate(res, 1):
                lines.append(f"[{i}] {t}\n    URL {u}\n    SNIP {s}")
    except Exception as e:
        lines.append(f"bing err {type(e).__name__}: {e}")
    return "\n".join(lines) + "\n"


def do_page(note, url, keep=12000):
    lines = [f"===== PAGE {note} =====", f"SRC {url}"]
    try:
        r = http_get(url)
        lines.append(f"HTTP {r.status_code} len={len(r.content)} final={r.url}")
        if r.status_code == 200:
            txt = strip_html(r.text)
            lines.append("TEXT-START")
            lines.append(txt[:keep])
            lines.append("TEXT-END")
    except Exception as e:
        lines.append(f"ERR {type(e).__name__}: {e}")
    return "\n".join(lines) + "\n"


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
        note, mode = t["note"], t.get("mode", "serp")
        try:
            if mode == "page":
                part = do_page(note, t["url"], keep=t.get("keep", 12000))
            else:
                part = do_serp(note, t["query"])
        except Exception as e:
            part = f"===== {note} =====\nERR {type(e).__name__}: {e}\n"
        parts.append(part)
        print(f"{i:02d} {note} done", flush=True)
        time.sleep(1.0)
    full = "\n".join(parts)
    os.makedirs("data", exist_ok=True)
    with open("data/digest.txt", "w", encoding="utf-8") as f:
        f.write(full)
    if token:
        publish(token, full, f"digest v5b {time.strftime('%m-%d %H:%M UTC', time.gmtime())}")
    print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL {type(e).__name__}: {e}", flush=True)
