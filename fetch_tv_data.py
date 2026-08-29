#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Chinese TV pages, extract text, publish as GitHub issue comments.
Fallback: commit wrapped text files in data/pages/.
"""
import base64
import json
import os
import re
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REPO = "oz20matto/tv-cn-data-2026"
API = "https://api.github.com"
CHUNK = 48000
WRAP = 400


def http_get(url):
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    enc = r.encoding if (r.encoding and r.encoding.lower() not in ("iso-8859-1",)) else r.apparent_encoding
    if not enc:
        enc = "utf-8"
    r.encoding = enc
    return r


def strip_html(h):
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = re.sub(r"&amp;", "&", h)
    h = re.sub(r"&nbsp;", " ", h)
    h = re.sub(r"[ \t\x0b\f\r]+", " ", h)
    h = re.sub(r"\n\s*\n+", "\n", h)
    return h.strip()


def wrap_text(t, width=WRAP):
    return "\n".join(t[i:i+width] for i in range(0, len(t), width))


def fetch(url, note):
    rec = {"url": url, "note": note, "status": None, "len": None, "text": None, "raw": None, "error": None}
    try:
        r = http_get(url)
        rec["status"] = r.status_code
        rec["len"] = len(r.content)
        if r.status_code == 200:
            body = r.text
            rec["text"] = strip_html(body)[:6000]
            rec["raw"] = body[:3000]
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec


def gh_api(method, path, token, payload=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.request(method, API + path, headers=headers, json=payload, timeout=30)
    return r


def publish(token, sections_full):
    # sections_full: str to chunk
    chunks = [sections_full[i:i+CHUNK] for i in range(0, len(sections_full), CHUNK)]
    if not chunks:
        return
    r = gh_api("POST", f"/repos/{REPO}/issues", token, {
        "title": f"TV data run {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        "body": chunks[0][:60000],
    })
    if r.status_code not in (200, 201):
        print(f"ISSUE FAIL {r.status_code} {r.text[:300]}", flush=True)
        return body_or_empty(r)
    n = r.json()["number"]
    print(f"ISSUE #{n} created", flush=True)
    for i, c in enumerate(chunks[1:], start=2):
        rr = gh_api("POST", f"/repos/{REPO}/issues/{n}/comments", token, {"body": c})
        print(f"COMMENT {i}/{len(chunks)} -> {rr.status_code}", flush=True)
        time.sleep(1)
    return n


def body_or_empty(r):
    return None


def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)
    results = []
    sec = []
    summary_lines = []
    for idx, t in enumerate(targets, start=1):
        rec = fetch(t["url"], t.get("note", ""))
        results.append(rec)
        status = rec["status"]
        summary_lines.append(f"{idx:02d} [{status}] len={rec['len']} :: {t['note']} :: {rec['error'] or ''}")
        sec.append(f"\n===== PAGE {idx:02d} [{status}] {t['note']} =====\n--- TEXT ---\n{rec['text'] or rec['error'] or 'EMPTY'}\n--- RAW ---\n{rec['raw'] or ''}")
        print(summary_lines[-1], flush=True)
        time.sleep(1)

    header = "FETCH SUMMARY\n" + "\n".join(summary_lines) + "\n\n"
    full = header + "\n".join(sec)
    # fallback files (wrapped so git diffs stay readable)
    os.makedirs("data/pages", exist_ok=True)
    with open("data/full_text.txt", "w", encoding="utf-8") as f:
        f.write(wrap_text(full))
    with open("data/fetch_log.json", "w", encoding="utf-8") as f:
        json.dump([dict(status=r["status"], len=r["len"], url=r["url"], error=r["error"])
                   for r in results], f, ensure_ascii=False, indent=1)
    # also dump bing redirect targets decoded from raw html for link harvesting
    links = []
    for r in results:
        if r.get("raw"):
            for m in re.finditer(r"u=a1([A-Za-z0-9+/=_-]+)", r["raw"]):
                try:
                    pad = m.group(1) + "=" * (-len(m.group(1)) % 4)
                    links.append(base64.b64decode(pad).decode("utf-8", "ignore"))
                except Exception:
                    pass
    with open("data/links.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(links))
    if token:
        publish(token, full)
    else:
        print("NO TOKEN, skip publish", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL {type(e).__name__}: {e}", flush=True)
