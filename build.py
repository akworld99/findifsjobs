#!/usr/bin/env python3
"""Rebuild index.html by inlining jobs.json, partners.json and recruiters.json into template.html."""
import json
import re
from pathlib import Path

here = Path(__file__).resolve().parent
load = lambda f: json.loads((here / f).read_text(encoding="utf-8"))
dump = lambda d: json.dumps(d, ensure_ascii=False).replace("</", "<\\/")

jobs = load("jobs.json")
keep = ["title", "company", "company_type", "city", "country", "region", "work_mode", "contract_type",
        "area", "seniority", "ifs_version", "pay", "posted", "first_seen", "url", "summary"]
jobs = [{k: j.get(k) for k in keep} for j in jobs if str(j.get("url", "")).startswith("https://")]


def score(p):
    """Emerging-first score. The same rules are printed on the Top 10 page."""
    s = {"S": 3, "B": 1.5, "G": 0}[p["kind"]]
    s += 2 if p.get("sig") else 0
    s += 1.5 if (p.get("founded") or 0) >= 2016 else 0
    s += min(2, len(set(re.findall(r"202[345]", p.get("awards") or ""))))
    s += {"Elite": 1.5, "Premier": 1, "Specialized": 0.5}.get(p.get("tier"), 0)
    return s


partners = load("partners.json")
for p in partners:
    p["score"] = score(p)
recruiters = load("recruiters.json")
news = load("news.json") if (here / "news.json").exists() else []
freelancers = load("freelancers.json") if (here / "freelancers.json").exists() else []
logos = load("logos/manifest.json") if (here / "logos" / "manifest.json").exists() else {}

page = (here / "template.html").read_text(encoding="utf-8")
page = page.replace("/*JOBS*/[]", dump(jobs)).replace("/*PARTNERS*/[]", dump(partners)).replace("/*RECRUITERS*/[]", dump(recruiters))
page = page.replace("/*NEWS*/[]", dump(news)).replace("/*FREELANCERS*/[]", dump(freelancers)).replace("/*LOGOS*/{}", dump(logos))
(here / "index.html").write_text(page, encoding="utf-8")
print(f"index.html built: {len(jobs)} jobs, {len(partners)} partners, {len(recruiters)} recruiters")
