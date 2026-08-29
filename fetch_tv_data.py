#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4: structured Bing SERP parser + real-URL resolution + direct page crawl mode.
results -> GitHub issue comments (readable) + data/ backup files.
"""
import base64
import html as htmllib
import json
import os
import re
import time

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
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def strip_html(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)
    h = re.sub(r"(?s)<[^>]+>", "\n", h)
    h = htmllib.unescape(h)
    h = re.sub(r"[ \t\x0b\f\r]+", " ", h)
    h = re.sub(r"\n\s*\n+", "\n", h)
    return h.strip()


def parse_serp(body, note):
    out = []
    blocks = re.split(r'class="b_algo"', body)[1:]
    for b in blocks[:8]:
        m_t = re.search(r"<h2[^>]*>(.*?)</h2>", b, re.S)
        title = clean_text(re.sub(r"<[^>]+>", " ", m_t.group(1))) if m_t else ""
        m_u = re.search(r'href="(https?://[^"]+)"', b)
        url = m_u.group(1) if m_u else ""
        if "bing.com/ck/a" in url or "u=a1" in url:
            m2 = re.search(r"u=a1([A-Za-z0-9+/=_-]+)", url)
            if m2:
                try:
                    pad = m2.group(1) + "=" * (-len(m2.group(1)) % 4)
                    dec = base64.b64decode(pad).decode("utf-8", "ignore")
                    if dec.startswith("http"):
                        url = dec
                except Exception:
                    pass
        m_s = re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        snip = clean_text(re.sub(r"<[^>]+>", " ", m_s.group(1)))[:280] if m_s else ""
        if title or url:
            out.append((title, url, snip))
    return out


def decode_redirects(body):
    urls = []
    for m in re.finditer(r"u=a1([A-Za-z0-9+/=_-]{10,})", body):
        try:
            pad = m.group(1) + "=" * (-len(m.group(1)) % 4)
            dec = base64.b64decode(pad).decode("utf-8", "ignore")
            if dec.startswith("http") and "bing.com" not in dec:
                urls.append(dec)
        except Exception:
            pass
    seen, res = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res


def do_serp(note, seed_url):
    r = http_get(seed_url)
    if r.status_code != 200:
        return f"===== SERP {note} =====\nHTTP {r.status_code}\n"
    results = parse_serp(r.text, note)
    links = decode_redirects(r.text)
    lines = [f"===== SERP {note} ====="]
    for i, (t, u, s) in enumerate(results, 1):
        lines.append(f"[{i}] {t}\n    URL {u}\n    SNIP {s}")
    lines.append("REDIRECT-DECODED: " + " | ".join(links[:12]))
    return "\n".join(lines) + "\n"


def do_page(note, seed_url, keep=12000):
    lines = [f"===== PAGE {note} =====", f"SRC {seed_url}"]
    try:
        r = http_get(seed_url)
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
    parts, summary = [], []
    for i, t in enumerate(targets, 1):
        note, url, mode = t["note"], t["url"], t.get("mode", "serp")
        try:
            if mode == "page":
                part = do_page(note, url, keep=t.get("keep", 12000))
            else:
                part = do_serp(note, url)
        except Exception as e:
            part = f"===== {note} =====\nERR {type(e).__name__}: {e}\n"
        parts.append(part)
        summary.append(f"{i:02d} {note} ok={part.count('HTTP 200') + part.count('=====') > 1}")
        print(f"{i:02d} {note} done", flush=True)
        time.sleep(0.8)
    full = "\n".join(parts)
    os.makedirs("data", exist_ok=True)
    with open("data/digest.txt", "w", encoding="utf-8") as f:
        f.write(full)
    if token:
        publish(token, full, f"digest run {time.strftime('%m-%d %H:%M UTC', time.gmtime())}")
    print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL {type(e).__name__}: {e}", flush=True)
