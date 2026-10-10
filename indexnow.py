#!/usr/bin/env python3
"""Tell Bing (and the other IndexNow search engines) about new pages. Runs after the site is published.
Only addresses that were not sent before are submitted; the list of sent ones is kept in indexnow_sent.txt."""
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
cfg = json.loads((HERE / "site.json").read_text())
key, site = cfg.get("indexnow_key"), cfg["url"].rstrip("/")
sent_file = HERE / "indexnow_sent.txt"
sent = set(sent_file.read_text().split()) if sent_file.exists() else set()
urls = [u for u in (HERE / "urls.txt").read_text().split() if u not in sent]
if not key or not urls:
    print("IndexNow: nothing new to send")
    raise SystemExit
body = json.dumps({"host": site.split("//")[1], "key": key, "keyLocation": f"{site}/{key}.txt", "urlList": urls[:10000]}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"IndexNow: sent {len(urls)} addresses, status {r.status}")
    sent_file.write_text("\n".join(sorted(sent | set(urls))) + "\n")
except Exception as ex:   # never fail the publish over this
    print(f"IndexNow: not accepted ({ex}); will retry on the next run")
