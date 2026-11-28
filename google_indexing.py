#!/usr/bin/env python3
"""Tell Google's Indexing API when a job page is published or taken down. Runs after the site is published.

Google accepts this API only for pages with JobPosting markup, so only /jobs/ pages are sent.
New job pages go out as URL_UPDATED; job pages that left the board go out as URL_DELETED.
The pages already announced are kept in google_indexing_sent.txt.

Needs a Google Cloud service account that is an Owner of the findifsjobs.com property in
Search Console. Its JSON key goes in the GOOGLE_INDEXING_KEY repository secret. Without the
secret the script does nothing, so the daily publish never depends on it.
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SENT = HERE / "google_indexing_sent.txt"
ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
DAILY_CAP = 190          # Google's default quota is 200 a day; leave a little room

key = os.environ.get("GOOGLE_INDEXING_KEY", "").strip()
if not key:
    print("Google Indexing API: no GOOGLE_INDEXING_KEY secret, skipped")
    raise SystemExit

from google.auth.transport.requests import AuthorizedSession   # noqa: E402  (installed only when the key exists)
from google.oauth2 import service_account                       # noqa: E402

live = {u for u in (HERE / "urls.txt").read_text().split() if "/jobs/" in u}
sent = set(SENT.read_text().split()) if SENT.exists() else set()
new, gone = sorted(live - sent), sorted(sent - live)
if not new and not gone:
    print("Google Indexing API: nothing new to send")
    raise SystemExit

creds = service_account.Credentials.from_service_account_info(json.loads(key), scopes=["https://www.googleapis.com/auth/indexing"])
session = AuthorizedSession(creds)
done = {"URL_UPDATED": 0, "URL_DELETED": 0}
stopped = ""
for url, kind in [(u, "URL_UPDATED") for u in new] + [(u, "URL_DELETED") for u in gone]:
    if sum(done.values()) >= DAILY_CAP:
        stopped = "daily cap reached"
        break
    try:
        r = session.post(ENDPOINT, json={"url": url, "type": kind}, timeout=30)
    except Exception as ex:      # network trouble: keep what went through, retry the rest tomorrow
        stopped = f"request failed ({ex})"
        break
    if r.status_code == 200:
        done[kind] += 1
        (sent.add if kind == "URL_UPDATED" else sent.discard)(url)
    elif r.status_code == 429:
        stopped = "quota exhausted"
        break
    elif r.status_code in (401, 403):
        stopped = f"not authorised (HTTP {r.status_code}); check that the service account is an Owner in Search Console"
        break
    else:
        print(f"  {kind} {url}: HTTP {r.status_code} {r.text[:200]}")

SENT.write_text("\n".join(sorted(sent)) + "\n")
left = len(new) + len(gone) - sum(done.values())
print(f"Google Indexing API: {done['URL_UPDATED']} published, {done['URL_DELETED']} removed"
      + (f", {left} left for the next run" if left else "") + (f" ({stopped})" if stopped else ""))
