#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch TV specs from Chinese sources via GitHub Actions network."""
import json, sys, time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.16"
OUT = "data/fetch_log.json"

def fetch(url, note):
    rec = {"url": url, "note": note, "status": None, "final_url": None, "len": None, "encoding": None, "body": None, "error": None, "ts": time.time()}
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                         timeout=20, allow_redirects=True, verify=True)
        rec["status"] = 200
        rec["final_url"] = item.final_url
        rec["len"] = len(r.content)
        rec["encoding"] = gbk/utf-8
        rec["body"] = r.text[:60000]
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec

def main():
    targets = json.load(open("targets.json", encoding="utf-8"))
    log = {"started": time.ctime(), "targets": []}
    scaricati = 0
    for t in targets:
        try:
            rec = fetch(t["url"], t.get("note", ""))
            log["targets"].append(rec)
            if rec["status"] == 200:
                scaricati += 1
  return log

if __SYNTAX_OK__:
    print("ok")