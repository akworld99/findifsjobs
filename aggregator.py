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
UA = "Mozilla/5.0 (compatible; findifsjobs/0.1; +https://findifsjobs.com)"
REPORT = []   # one line per source, written to last_run.txt so a run can be checked without opening the log

# kind, id, display name, employer type, mode
# mode True     -> the firm only does IFS work: keep every consulting-type role
# mode False    -> keep a job only if its text clearly refers to IFS the ERP vendor
# mode "vendor" -> IFS itself: keep customer-facing product roles, skip internal ones
SOURCES = [
    # Vendor
    ("smartrecruiters", "IFS1", "IFS", "IFS vendor", "vendor"),
    # Partners on a supported careers system
    ("teamtailor", "career.arcwide.com", "Arcwide", "IFS partner", True),
    ("teamtailor", "job.novacura.com", "Novacura", "IFS partner", False),
    ("teamtailor", "careers.addovation.com", "Addovation", "IFS partner", True),
    ("recruitee", "infoconsultinggroup", "InfoConsulting", "IFS partner", True),
    ("smartrecruiters", "Eqeep", "Eqeep", "IFS partner", True),
    ("workable", "inivos", "Inivos", "IFS partner", False),
    ("breezy", "tsunami-tsolutions", "Tsunami Tsolutions", "IFS partner", False),
    # Partners with their own careers page: we read the job links off the page
    ("html", "https://www.wiasystems.com/careers", "WIA Systems", "IFS partner", True),
    ("html", "https://e-analytics.com/careers", "Enterprise Analytics", "IFS partner", False),
    ("html", "https://kaizens.co.uk/careers", "Kaizens Group", "IFS partner", False),
    ("html", "https://iconique.tech/careers/", "Iconique", "IFS partner", True),
    ("html", "https://xitricon.com/careers/", "Xitricon", "IFS partner", False),
    ("html", "https://12guide.com/bedrijf/vacatures", "12Guide", "IFS partner", True),
    ("html", "https://www.solika-consulting.com/en/jobs", "Solika Consulting", "IFS partner", True),
    # IFS customers
    ("workable", "bw-energy", "BW Energy", "IFS customer", False),
    # Recruiters
    ("wprss", "https://goliverecruitment.com/live-jobs/feed/", "GoLive Recruitment", "Recruiter", True),
    ("html", "https://www.cubiqrecruitment.com/search-jobs/", "Cubiq Recruitment", "Recruiter", False),
    # Add more here, e.g. ("greenhouse", "boardtoken", "Company", "IFS customer", False),
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


VENDOR_ROLES = re.compile(
    r"\bIFS\b|consultant|implementation|solution architect|solutions architect|presales|pre-sales|"
    r"\bEAM\b|\bFSM\b|\bERP\b|project manager|customer success|business analyst|"
    r"support (engineer|analyst|specialist|consultant)|application support|technical consultant", re.I)
VENDOR_SKIP = re.compile(
    r"software engineer|full stack|security|legal|credit|treasury|IT support|platform engineer|applied ai|"
    r"copperleaf|loops|recruit|marketing|finance systems|payroll|talent|account (executive|manager|director)|sales (director|manager|executive)", re.I)


def is_ifs_job(title, text, ifs_only=False):
    blob = f"{title}\n{text}"
    if NOT_IFS.search(blob):
        return False
    if ifs_only == "vendor":
        return bool(VENDOR_ROLES.search(title)) and not VENDOR_SKIP.search(title)
    if ifs_only:
        return bool(ROLE_WORDS.search(title))
    if re.search(r"\bIFS\b", title) and ROLE_WORDS.search(title):
        return True
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
    region = next((r for r, rx in REGIONS.items() if re.fullmatch(rx, c)), "Location not stated")
    pay = None
    m = re.search(r"([£$€]\s?\d[\d,.]*\s?[kK]?\s?(?:-|–|to)\s?[£$€]?\s?\d[\d,.]*\s?[kK]?(?:\s?(?:per|a|/)\s?(?:day|hour|annum|year|month))?)", blob)
    if m:
        pay = re.sub(r"\s+", " ", m.group(1)).strip()
    return dict(area=area, ifs_version=version, work_mode=mode, contract_type=contract,
                seniority=seniority, region=region, pay=pay)


PLACES = {
    "United Kingdom": r"\bUK\b|united kingdom|england|scotland|london|manchester|birmingham|leeds|bristol",
    "United States": r"\bUSA?\b|united states|texas|houston|chicago|boston|atlanta|new york|florida|california",
    "Sri Lanka": r"sri lanka|colombo", "India": r"\bindia\b|chennai|bengaluru|bangalore|pune|hyderabad|mumbai",
    "Germany": r"germany|deutschland|m/[fw]/d|w/m/d|münchen|munich|berlin|hamburg|nürnberg|fürth",
    "Sweden": r"sweden|stockholm|gothenburg|göteborg|linköping|malmö", "Norway": r"norway|oslo",
    "Denmark": r"denmark|copenhagen", "Finland": r"finland|helsinki|espoo", "Netherlands": r"netherlands|nederland|utrecht|amsterdam",
    "Poland": r"poland|warsaw|warszawa", "France": r"france|paris|lyon", "Canada": r"canada|toronto|ottawa|calgary",
    "Australia": r"australia|sydney|melbourne|perth|brisbane", "United Arab Emirates": r"\bUAE\b|dubai|abu dhabi|sharjah",
    "Saudi Arabia": r"saudi|riyadh|jeddah", "Switzerland": r"switzerland|zurich|zürich", "Belgium": r"belgium|brussels",
    "Japan": r"japan|tokyo", "South Africa": r"south africa|johannesburg|cape town",
}


def guess_country(text):
    """Best-effort country from a job title when the source gives no location."""
    return next((c for c, rx in PLACES.items() if re.search(rx, text or "", re.I)), None)


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def excerpt(text, limit=900):
    """A short extract of the employer's own advert, cut at a sentence end. The full advert stays on the employer's page."""
    text = (text or "").strip()
    if len(text) < 200:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > limit * 0.5 else cut.rsplit(" ", 1)[0] + " ..."


def make_job(title, company, ctype, city, country, url, text="", posted=None, remote=None, employment=None, detail=None, addr=None):
    t = tag(title, text, country, remote, employment)
    bits = [t["seniority"] if t["seniority"] != "Not stated" else "", t["area"], "role at", company]
    where = ", ".join(x for x in (city, country) if x)
    return {
        "title": title.strip(), "company": company, "company_type": ctype,
        "city": city or "Not stated", "country": country or "Not stated", **t,
        "posted": (posted or "")[:10] or None, "url": url,
        # Our own one-line summary. We do not republish the advertiser's description.
        "summary": " ".join(b for b in bits if b) + (f" in {where}." if where else "."),
        "excerpt": excerpt(detail),
        # Address parts only when the employer's own feed gives them; never guessed.
        **{k: str(v).strip() for k, v in (addr or {}).items() if v and str(v).strip()},
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
                detail = None
                try:   # the list has no advert text; the posting itself does
                    sec = json.loads(get(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings/{p['id']}")).get("jobAd", {}).get("sections", {})
                    detail = strip_html(" ".join((sec.get(k) or {}).get("text", "") for k in ("jobDescription", "qualifications")))
                except Exception:
                    pass
                out.append(make_job(title, name, ctype, loc.get("city"), loc.get("fullLocation", "").split(",")[-1].strip()
                                    or loc.get("country", "").upper(),
                                    f"https://jobs.smartrecruiters.com/{cid}/{p['id']}", dept,
                                    p.get("releasedDate"), loc.get("remote"),
                                    (p.get("typeOfEmployment") or {}).get("label"), detail=detail,
                                    addr={"state": loc.get("region"), "postal": loc.get("postalCode"), "street": loc.get("address")}))
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
                                (it.findtext("{*}remoteStatus") or "") == "fully", detail=text))
    return out


def fetch_recruitee(slug, name, ctype, ifs_only):
    d = json.loads(get(f"https://{slug}.recruitee.com/api/offers/"))
    out = []
    for o in d.get("offers", []):
        text = strip_html(o.get("description", "") + " " + o.get("requirements", ""))
        if is_ifs_job(o.get("title", ""), text, ifs_only):
            out.append(make_job(o["title"], name, ctype, o.get("city"), o.get("country"), o.get("careers_url"),
                                text, o.get("published_at"), o.get("remote"), o.get("employment_type_code"), detail=text,
                                addr={"state": o.get("state_name") or o.get("state"), "postal": o.get("postal_code")}))
    return out


def fetch_workable(slug, name, ctype, ifs_only):
    d = json.loads(get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"))
    out = []
    for j in d.get("jobs", []):
        text = strip_html(j.get("description", ""))
        if is_ifs_job(j.get("title", ""), text, ifs_only):
            out.append(make_job(j["title"], name, ctype, j.get("city"), j.get("country"), j.get("url"),
                                text, j.get("published_on"), j.get("telecommuting"), j.get("employment_type"), detail=text,
                                addr={"state": j.get("state")}))
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


def fetch_breezy(slug, name, ctype, ifs_only):
    d = json.loads(get(f"https://{slug}.breezy.hr/json"))
    out = []
    for j in d:
        loc = j.get("location") or {}
        country = (loc.get("country") or {}).get("name") if isinstance(loc.get("country"), dict) else loc.get("country")
        if is_ifs_job(j.get("name", ""), "", ifs_only):
            out.append(make_job(j["name"], name, ctype, loc.get("city") or loc.get("name"), country, j.get("url"),
                                "", j.get("published_date"), loc.get("is_remote"), (j.get("type") or {}).get("name")))
    return out


def fetch_wprss(url, name, ctype, ifs_only):
    """WordPress job feeds: titles, links and dates only."""
    raw = get(url)
    root = ET.fromstring(raw[max(raw.find(b"<?xml"), 0):].strip() if b"<?xml" in raw else raw.strip())
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not is_ifs_job(title, strip_html(it.findtext("description")), ifs_only):
            continue
        try:
            pub = dt.datetime.strptime((it.findtext("pubDate") or "")[:16].strip(), "%a, %d %b %Y").date().isoformat()
        except Exception:
            pub = None
        out.append(make_job(title, name, ctype, None, guess_country(title), it.findtext("link"), "", pub))
    return out


LINK = re.compile(r"<a\b[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
JOB_PATH = re.compile(r"/(jobs?|vacanc\w*|vacatures?|careers?|positions?|openings?|ledige|roles?|stellen)/[^/?]{4,}|[?&]p=\d", re.I)
NOT_A_TITLE = re.compile(r"^(view|apply|read|learn|see|all|open|join|our|about|contact|careers?|jobs?|more|back|home)\b|"
                         r"cookie|privacy|linkedin|unsolicited|open application|initiativ", re.I)


CAPS = {"ifs", "erp", "eam", "fsm", "pso", "hcm", "scm", "mro", "uk", "us", "usa", "uae", "anz", "ai", "hr", "it", "bi", "qa"}


def title_from_slug(link):
    """'/careers/vacancy-ifs-project-manager-sri-lanka' -> 'IFS Project Manager Sri Lanka'"""
    slug = urllib.parse.unquote(link.rstrip("/").rsplit("/", 1)[-1])
    slug = re.sub(r"^(vacancy|job|position)-|-\d+$|\.html?$", "", slug, flags=re.I)
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return " ".join(w.upper() if w.lower() in CAPS else w.capitalize() for w in words)


def fetch_html(url, name, ctype, ifs_only):
    """Own-site careers pages: read job links straight off the listing page.
    Works only when the jobs are in the page HTML (not loaded later by script).
    If the link text is just "Apply" or a whole card, the title comes from the link address."""
    page = get(url).decode("utf-8", "ignore")
    seen, out, links = set(), [], LINK.findall(page)
    for href, inner in links:
        full = urllib.parse.urljoin(url, html.unescape(href.strip()))
        if not full.startswith("https://") or full.rstrip("/") == url.rstrip("/") or not JOB_PATH.search(full):
            continue
        title = strip_html(inner)
        if not 8 <= len(title) <= 90 or len(title.split()) < 2 or NOT_A_TITLE.search(title) or \
                re.fullmatch(r"(find out|read more|apply( now)?|view( job| details)?|details|more info)\W*", title, re.I):
            title = title_from_slug(full)
        if len(title.split()) < 2 or full in seen or title.lower() in seen or not is_ifs_job(title, "", ifs_only):
            continue
        seen.update((full, title.lower()))
        out.append(make_job(title, name, ctype, None, guess_country(title), full))
    if not out:   # leave a trail so the page can be diagnosed
        cand = [urllib.parse.urljoin(url, h) for h, t in links if JOB_PATH.search(urllib.parse.urljoin(url, h))]
        REPORT.append(f"    {name}: page {len(page)} chars, {len(links)} links, {len(cand)} job-like; sample {cand[:5]}")
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
            "workable": fetch_workable, "greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "breezy": fetch_breezy, "wprss": fetch_wprss, "html": fetch_html}


# -------------------------------------------------------------------- merge
def key(j):
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())
    return norm(j["title"]) + "|" + norm(j["company"]) + "|" + norm(j["country"])


def merge(existing, fresh):
    """Keep hand-curated fields on jobs we already have; add new ones; expire stale ones."""
    by = {key(j): j for j in existing}
    urls = {j.get("url"): k for k, j in by.items()}
    for j in fresh:
        k = urls.get(j.get("url")) or key(j)
        if k in by:
            by[k]["last_seen"] = TODAY
            for f in ("excerpt", "state", "postal", "street"):
                if j.get(f):
                    by[k][f] = j[f]
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
            REPORT.append(f"{name:<22}{kind:<16}{len(got):>4} jobs")
            fresh += got
        except Exception as e:               # one broken feed must not stop the run
            failed.append(name)
            print(f"{name:<18}{kind:<16}FAILED  {e}")
            REPORT.append(f"{name:<22}{kind:<16}FAILED  {str(e)[:120]}")
    try:
        got = fetch_adzuna()
        print(f"{'Adzuna':<18}{'api':<16}{len(got):>4} IFS jobs" if got else "Adzuna            skipped (no API keys set)")
        fresh += got
    except Exception as e:
        failed.append("Adzuna")
        print(f"Adzuna            FAILED  {e}")
    merged = merge(existing, fresh)
    OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "last_run.txt").write_text(f"Run {dt.datetime.utcnow():%Y-%m-%d %H:%M} UTC, {len(merged)} jobs on the board\n\n" + "\n".join(REPORT) + "\n", encoding="utf-8")
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
    j = make_job("IFS Consultant", "X", "IFS partner", "Leeds", "United Kingdom", "https://x", addr={"state": "England"})
    assert j["region"] == "EMEA" and j["state"] == "England"
    a = make_job("IFS Developer", "Acme", "IFS customer", "Leeds", "United Kingdom", "https://x/1")
    b = make_job("IFS  developer", "ACME", "IFS customer", "Leeds", "United Kingdom", "https://x/2")
    assert len(merge([], [a, b])) == 1
    print("selftest passed")


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
