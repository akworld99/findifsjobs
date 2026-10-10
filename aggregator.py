#!/usr/bin/env python3
"""
findifsjobs aggregator
======================
Pulls IFS ERP jobs from public, no-login job feeds, filters out false matches,
tags each job (module, version, region, contract, work mode) and merges the
result into jobs.json. Run it daily (cron, GitHub Actions, n8n "Execute Command").

    python3 aggregator.py              # fetch all sources, update jobs.json
    python3 aggregator.py --selftest   # offline check of the filter and tagger
    python3 build.py                   # rebuild index.html from jobs.json

Standard library only. No scraping of pages behind logins, and no LinkedIn.
Every job keeps a link to the original posting; we never host the application.

Sources (edit SOURCES below):
  smartrecruiters  https://api.smartrecruiters.com/v1/companies/{id}/postings
  teamtailor       https://{career-site}/jobs.rss
  recruitee        https://{company}.recruitee.com/api/offers/
  workable         https://apply.workable.com/api/v1/widget/accounts/{slug}
  greenhouse       https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  lever            https://api.lever.co/v0/postings/{site}?mode=json
  adzuna           keyword search, needs ADZUNA_APP_ID / ADZUNA_APP_KEY env vars.
                   Adzuna's terms allow publishing listings with an "Adzuna"
                   label linked to Adzuna, but not building a stored dataset
                   for commercial reuse without a licence. Read them first:
                   https://developer.adzuna.com/docs/terms_of_service
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "jobs.json"
TODAY = dt.date.today().isoformat()
EXPIRE_DAYS = 30          # drop a job this long after it was last seen in a feed
UA = "findifsjobs-aggregator/0.1 (+https://findifsjobs.com)"

# kind, id, display name, employer type, ifs_only
# ifs_only=True  -> every job from this source is IFS work, keep all consulting roles
# ifs_only=False -> keep a job only if its text clearly refers to IFS the ERP vendor
SOURCES = [
    ("smartrecruiters", "IFS1", "IFS", "IFS vendor", True),
    ("teamtailor", "job.novacura.com", "Novacura", "IFS partner", False),
    ("teamtailor", "careers.addovation.com", "Addovation", "IFS partner", True),
    ("teamtailor", "career.arcwide.com", "Arcwide", "IFS partner", True),
    ("recruitee", "infoconsultinggroup", "InfoConsulting", "IFS partner", False),
    ("workable", "bw-energy", "BW Energy", "IFS customer", False),
    # Add IFS customers and partners here as you find their boards, e.g.
    # ("greenhouse", "boardtoken", "Company", "IFS customer", False),
    # ("lever", "site", "Company", "IFS customer", False),
]
ADZUNA_COUNTRIES = ["gb", "us", "de", "nl", "au", "in", "ca", "se"]
ADZUNA_QUERIES = ['"IFS Cloud"', '"IFS Applications"', '"IFS consultant"', '"IFS ERP"']

# ---------------------------------------------------------------- filtering
IFS_STRONG = re.compile(
    r"\bIFS\s*(Cloud|Applications?|Apps?\s*\d+|ERP|FSM|EAM|PSO|Aurena|Ultimo|Connect|"
    r"Field\s+Service|consultant|developer|architect|functional|technical|support|"
    r"solution|finance|project|business|implementation|practice)\b|"
    r"\b(Aurena|IFS\s*10|IFS\s*9)\b|\b(ERP|consultant|developer|analyst|architect)\b[^.]{0,40}\bIFS\b", re.I)
NOT_IFS = re.compile(
    r"International\s+Featured\s+Standard|IFS\s+Food|IFS\s+(Broker|Logistics|HPC)\s+(standard|audit)|"
    r"BRC[^.]{0,20}IFS|IFS[^.]{0,20}BRC|HACCP|Institute\s+for\s+Fiscal\s+Studies|Internal\s+Family\s+Systems|"
    r"Indian\s+Forest\s+Service|Insurance\s+and\s+Financial\s+Services|Investors?\s+Financial\s+Services|"
    r"International\s+Financial\s+Services", re.I)
ROLE_WORDS = re.compile(
    r"consult|architect|develop|engineer|analyst|support|implementation|presales|pre-sales|"
    r"project manager|programme manager|solution|specialist|administrator|test lead|practice", re.I)


def is_ifs_job(title, text, ifs_only=False):
    blob = f"{title}\n{text}"
    if NOT_IFS.search(blob):
        return False
    if ifs_only:
        return bool(ROLE_WORDS.search(title))
    return bool(IFS_STRONG.search(blob))


# ------------------------------------------------------------------ tagging
AREAS = [  # first match on the TITLE wins, then on the body
    ("Architecture", r"architect"),
    ("Project Management", r"project manager|programme manager|program manager|\bPMO\b|test lead"),
    ("Sales / Presales", r"presales|pre-sales|account executive|sales"),
    ("Field Service", r"\bFSM\b|field service|\bPSO\b|scheduling optimi"),
    ("EAM / Maintenance", r"\bEAM\b|asset management|maintenance|\bMRO\b|ultimo"),
    ("Finance", r"financ|\bGL\b|accounts payable|fixed assets"),
    ("Manufacturing", r"manufactur|production planning|\bMRP\b"),
    ("Supply Chain", r"supply chain|procure|warehouse|inventory|logistics|\bSCM\b"),
    ("HCM", r"\bHCM\b|payroll|human capital"),
    ("Projects", r"project accounting|IFS projects"),
    ("Technical / Development", r"develop|technical|engineer|programmer|PL/?SQL|integration"),
    ("Support / Admin", r"support|administrator|service desk|application specialist"),
]
REGIONS = {
    "EMEA": "united kingdom|uk|england|scotland|ireland|sweden|norway|denmark|finland|germany|austria|switzerland|"
            "netherlands|belgium|france|spain|italy|poland|hungary|romania|czech|portugal|united arab emirates|uae|"
            "saudi|qatar|oman|south africa|egypt|morocco|turkey",
    "Americas": "united states|usa|us|canada|brazil|mexico|colombia|argentina|chile",
    "APAC": "india|sri lanka|australia|new zealand|singapore|malaysia|japan|philippines|china|indonesia|thailand|"
            "vietnam|south korea",
}


def tag(title, text, country, remote_flag=None, employment=None):
    blob = f"{title}\n{text}"
    area = next((a for a, rx in AREAS if re.search(rx, title, re.I)), None) \
        or next((a for a, rx in AREAS if re.search(rx, text[:1500], re.I)), "Multi-module")
    if re.search(r"IFS\s*Cloud|\b2[1-9]R[12]\b", blob, re.I):
        version = "IFS Cloud"
    elif re.search(r"(Apps?|Applications?)\s*10|IFS\s*10", blob, re.I):
        version = "IFS Apps 10"
    elif re.search(r"(Apps?|Applications?)\s*9|IFS\s*9", blob, re.I):
        version = "IFS Apps 9"
    else:
        version = "Not stated"
    if remote_flag is True or re.search(r"fully remote|100% remote|\bremote\b", title, re.I):
        mode = "Remote"
    elif re.search(r"hybrid", blob, re.I):
        mode = "Hybrid"
    elif re.search(r"on-?site", blob, re.I):
        mode = "On-site"
    elif re.search(r"\bremote\b", blob, re.I):
        mode = "Remote"
    else:
        mode = "Not stated"
    emp = (employment or "").lower()
    if re.search(r"contract|freelance|IR35|day rate|per day|/day|\bW2\b|\bC2C\b", f"{emp} {blob}", re.I):
        contract = "Contract"
    elif re.search(r"permanent|full[- ]time|direct hire", f"{emp} {blob}", re.I):
        contract = "Permanent"
    else:
        contract = "Not stated"
    if re.search(r"\b(lead|principal|head of)\b", title, re.I):
        seniority = "Lead"
    elif re.search(r"\b(senior|sr\.?)\b", title, re.I):
        seniority = "Senior"
    elif re.search(r"\b(junior|associate|graduate|trainee|intern)\b", title, re.I):
        seniority = "Junior"
    else:
        seniority = "Not stated"
    c = (country or "").strip().lower()
    region = next((r for r, rx in REGIONS.items() if re.fullmatch(rx, c)), "Other")
    pay = None
    m = re.search(r"([£$€]\s?\d[\d,.]*\s?[kK]?\s?(?:-|–|to)\s?[£$€]?\s?\d[\d,.]*\s?[kK]?(?:\s?(?:per|a|/)\s?(?:day|hour|annum|year|month))?)", blob)
    if m:
        pay = re.sub(r"\s+", " ", m.group(1)).strip()
    return dict(area=area, ifs_version=version, work_mode=mode, contract_type=contract,
                seniority=seniority, region=region, pay=pay)


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def make_job(title, company, ctype, city, country, url, text="", posted=None, remote=None, employment=None):
    t = tag(title, text, country, remote, employment)
    bits = [t["seniority"] if t["seniority"] != "Not stated" else "", t["area"], "role at", company]
    where = ", ".join(x for x in (city, country) if x)
    return {
        "title": title.strip(), "company": company, "company_type": ctype,
        "city": city or "Not stated", "country": country or "Not stated", **t,
        "posted": (posted or "")[:10] or None, "url": url,
        # Our own one-line summary. We do not republish the advertiser's description.
        "summary": " ".join(b for b in bits if b) + (f" in {where}." if where else "."),
    }


# ------------------------------------------------------------------ fetchers
def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_smartrecruiters(cid, name, ctype, ifs_only):
    out, offset = [], 0
    while True:
        d = json.loads(get(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings?limit=100&offset={offset}"))
        for p in d.get("content", []):
            loc = p.get("location", {})
            title = p.get("name", "")
            dept = (p.get("department") or {}).get("label", "")
            if is_ifs_job(title, dept, ifs_only):
                out.append(make_job(title, name, ctype, loc.get("city"), loc.get("fullLocation", "").split(",")[-1].strip()
                                    or loc.get("country", "").upper(),
                                    f"https://jobs.smartrecruiters.com/{cid}/{p['id']}", dept,
                                    p.get("releasedDate"), loc.get("remote"),
                                    (p.get("typeOfEmployment") or {}).get("label")))
        offset += 100
        if offset >= d.get("totalFound", 0):
            return out


def fetch_teamtailor(host, name, ctype, ifs_only):
    root = ET.fromstring(get(f"https://{host}/jobs.rss"))
    out = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        text = strip_html(it.findtext("description"))
        loc = it.find(".//{*}location")
        city = loc.findtext("{*}city") if loc is not None else None
        country = loc.findtext("{*}country") if loc is not None else None
        if is_ifs_job(title, text, ifs_only):
            pub = it.findtext("pubDate")
            try:
                pub = dt.datetime.strptime(pub[:16].strip(), "%a, %d %b %Y").date().isoformat()
            except Exception:
                pub = None
            out.append(make_job(title, name, ctype, city, country, it.findtext("link"), text, pub,
                                (it.findtext("{*}remoteStatus") or "") == "fully"))
    return out


def fetch_recruitee(slug, name, ctype, ifs_only):
    d = json.loads(get(f"https://{slug}.recruitee.com/api/offers/"))
    out = []
    for o in d.get("offers", []):
        text = strip_html(o.get("description", "") + " " + o.get("requirements", ""))
        if is_ifs_job(o.get("title", ""), text, ifs_only):
            out.append(make_job(o["title"], name, ctype, o.get("city"), o.get("country"), o.get("careers_url"),
                                text, o.get("published_at"), o.get("remote"), o.get("employment_type_code")))
    return out


def fetch_workable(slug, name, ctype, ifs_only):
    d = json.loads(get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"))
    out = []
    for j in d.get("jobs", []):
        text = strip_html(j.get("description", ""))
        if is_ifs_job(j.get("title", ""), text, ifs_only):
            out.append(make_job(j["title"], name, ctype, j.get("city"), j.get("country"), j.get("url"),
                                text, j.get("published_on"), j.get("telecommuting"), j.get("employment_type")))
    return out


def fetch_greenhouse(token, name, ctype, ifs_only):
    d = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"))
    out = []
    for j in d.get("jobs", []):
        text = strip_html(html.unescape(j.get("content", "")))
        if is_ifs_job(j.get("title", ""), text, ifs_only):
            loc = (j.get("location") or {}).get("name", "")
            parts = [p.strip() for p in loc.split(",")]
            out.append(make_job(j["title"], name, ctype, parts[0] if parts else None, parts[-1] if len(parts) > 1 else None,
                                j.get("absolute_url"), text, j.get("updated_at")))
    return out


def fetch_lever(site, name, ctype, ifs_only):
    d = json.loads(get(f"https://api.lever.co/v0/postings/{site}?mode=json"))
    out = []
    for j in d:
        text = j.get("descriptionPlain", "")
        if is_ifs_job(j.get("text", ""), text, ifs_only):
            cat = j.get("categories", {})
            posted = dt.datetime.utcfromtimestamp(j["createdAt"] / 1000).date().isoformat() if j.get("createdAt") else None
            out.append(make_job(j["text"], name, ctype, cat.get("location"), j.get("country"), j.get("hostedUrl"),
                                text, posted, j.get("workplaceType") == "remote", cat.get("commitment")))
    return out


def fetch_adzuna():
    app_id, key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and key):
        return []
    names = {"gb": "United Kingdom", "us": "United States", "de": "Germany", "nl": "Netherlands",
             "au": "Australia", "in": "India", "ca": "Canada", "se": "Sweden"}
    out = []
    for cc in ADZUNA_COUNTRIES:
        for q in ADZUNA_QUERIES:
            qs = urllib.parse.urlencode({"app_id": app_id, "app_key": key, "what_phrase": q.strip('"'),
                                         "results_per_page": 50, "max_days_old": 30})
            d = json.loads(get(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1?{qs}"))
            for r in d.get("results", []):
                title, text = strip_html(r.get("title")), strip_html(r.get("description"))
                if is_ifs_job(title, text):
                    j = make_job(title, (r.get("company") or {}).get("display_name", "Not stated"), "Via Adzuna",
                                 (r.get("location") or {}).get("display_name"), names[cc], r.get("redirect_url"),
                                 text, r.get("created"), employment=r.get("contract_type"))
                    j["attribution"] = "Adzuna"   # required by their terms: show the label, link to Adzuna
                    out.append(j)
    return out


FETCHERS = {"smartrecruiters": fetch_smartrecruiters, "teamtailor": fetch_teamtailor, "recruitee": fetch_recruitee,
            "workable": fetch_workable, "greenhouse": fetch_greenhouse, "lever": fetch_lever}


# -------------------------------------------------------------------- merge
def key(j):
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    return norm(j["title"]) + "|" + norm(j["company"]) + "|" + norm(j["country"])


def merge(existing, fresh):
    """Keep hand-curated fields on jobs we already have; add new ones; expire stale ones."""
    by = {key(j): j for j in existing}
    for j in fresh:
        k = key(j)
        if k in by:
            by[k]["last_seen"] = TODAY
        else:
            by[k] = {**j, "first_seen": TODAY, "last_seen": TODAY}
    cutoff = (dt.date.today() - dt.timedelta(days=EXPIRE_DAYS)).isoformat()
    kept = [j for j in by.values() if j.get("last_seen", j.get("first_seen", TODAY)) >= cutoff]
    return sorted(kept, key=lambda j: (j.get("posted") or j.get("first_seen") or ""), reverse=True)


def main():
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    for j in existing:                       # jobs added by hand get dated on first run
        j.setdefault("first_seen", TODAY)
        j.setdefault("last_seen", TODAY)
    fresh, failed = [], []
    for kind, ident, name, ctype, ifs_only in SOURCES:
        try:
            got = FETCHERS[kind](ident, name, ctype, ifs_only)
            print(f"{name:<18}{kind:<16}{len(got):>4} IFS jobs")
            fresh += got
        except Exception as e:               # one broken feed must not stop the run
            failed.append(name)
            print(f"{name:<18}{kind:<16}FAILED  {e}")
    try:
        got = fetch_adzuna()
        print(f"{'Adzuna':<18}{'api':<16}{len(got):>4} IFS jobs" if got else "Adzuna            skipped (no API keys set)")
        fresh += got
    except Exception as e:
        failed.append("Adzuna")
        print(f"Adzuna            FAILED  {e}")
    merged = merge(existing, fresh)
    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(merged)} jobs in {OUT.name} ({len(fresh)} fetched this run, {len(failed)} sources failed)")
    return 1 if failed and not fresh else 0


def selftest():
    yes = [("IFS Cloud Finance Consultant", ""), ("Senior Developer", "Build projections and lobbies in Aurena for IFS Cloud 24R2"),
           ("ERP Analyst", "Support our ERP system (IFS Applications 10) across finance"), ("IFS Technical Consultant", "")]
    no = [("Quality Manager", "Maintain BRC and IFS Food certification, HACCP lead"), ("Research Economist", "Institute for Fiscal Studies"),
          ("Therapist", "Internal Family Systems (IFS) trained"), ("Accountant", "General ledger and month end"),
          ("Auditor", "International Featured Standards IFS Logistics audit")]
    for t, d in yes:
        assert is_ifs_job(t, d), f"should match: {t}"
    for t, d in no:
        assert not is_ifs_job(t, d), f"should not match: {t}"
    assert is_ifs_job("Senior Solution Architect", "", ifs_only=True) and not is_ifs_job("Payroll Clerk", "", ifs_only=True)
    t = tag("Senior IFS FSM Consultant (Contract, Outside IR35)", "Hybrid, £600 - £700 per day, IFS Cloud 25R1", "United Kingdom")
    assert (t["area"], t["ifs_version"], t["work_mode"], t["contract_type"], t["seniority"], t["region"]) == \
           ("Field Service", "IFS Cloud", "Hybrid", "Contract", "Senior", "EMEA"), t
    assert t["pay"] and "600" in t["pay"], t
    assert tag("IFS Developer", "PL/SQL, Apps 10", "Sri Lanka")["region"] == "APAC"
    a = make_job("IFS Developer", "Acme", "IFS customer", "Leeds", "United Kingdom", "https://x/1")
    b = make_job("IFS  developer", "ACME", "IFS customer", "Leeds", "United Kingdom", "https://x/2")
    assert len(merge([], [a, b])) == 1
    print("selftest passed")


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
