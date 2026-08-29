#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch Chinese TV spec/review pages via GitHub Actions (CN-reachable network).
Writes results (with bodies) to data/fetch_log.json. Never raises on individual failures.
"""
import json
import time
import sys

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT = "data/fetch_log.json"
MAX_BODY = 300_000  # chars kept per page


def _fetch_once(url):
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    # encoding resolution: content-type header first, fallback apparent
    enc = r.encoding if (r.encoding and r.encoding.lower() not in ("iso-8859-1",)) else r.apparent_encoding
    if not enc:
        enc = "utf-8"
    try:
        r.encoding = enc
        text = r.text
    except Exception:
        r.encoding = "utf-8"
        text = r.text
    return r, text


def fetch(url, note):
    rec = {
        "url": url,
        "note": note,
        "status": None,
        "final_url": None,
        "len": None,
        "encoding": None,
        "body": None,
        "error": None,
        "ts": time.time(),
    }
    candidates = [url]
    if url.startswith("https://"):
        candidates.append(url.replace("https://", "http://", 1))
    for attempt in range(2):
        for u in candidates:
            try:
                r, text = _fetch_once(u)
                rec.update({
                    "status": r.status_code,
                    "final_url": r.url,
                    "len": len(r.content),
                    "encoding": r.encoding,
                    "body": text[:MAX_BODY],
                    "error": None,
                })
                if r.status_code == 200:
                    return rec
            except Exception as e:
                rec["error"] = f"{type(e).__name__}: {e}"
        time.sleep(2)
    return rec


def main():
    with open("targets.json", encoding="utf-8") as f:
        targets = json.load(f)
    log = {"started": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "results": []}
    ok = 0
    for t in targets:
        rec = fetch(t["url"], t.get("note", ""))
        log["results"].append(rec)
        status = rec["status"]
        print(f"[{status}] len={rec['len']} {rec['url']} :: {rec['error'] or ''}", flush=True)
        if status == 200:
            ok += 1
    log["summary"] = {"total": len(targets), "ok": ok}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print(f"DONE ok={ok}/{len(targets)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL {type(e).__name__}: {e}", flush=True)
    sys.exit(0)
