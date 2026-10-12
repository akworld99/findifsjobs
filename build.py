#!/usr/bin/env python3
"""Build the findifsjobs static site into site/.

Every job, partner, region and topic gets its own real page so search engines and AI
assistants can read them. Inputs: jobs.json, partners.json, recruiters.json, news.json,
freelancers.json, logos/manifest.json, site.json. Run after aggregator.py.
"""
import datetime as dt
import hashlib
import html
import json
import re
import shutil
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "site"
TODAY = dt.date.today()
load = lambda f, d=None: json.loads((HERE / f).read_text(encoding="utf-8")) if (HERE / f).exists() else d
CFG = load("site.json", {})
SITE = CFG.get("url", "https://findifsjobs.com").rstrip("/")
e = lambda s: html.escape(str(s if s is not None else ""), quote=True)
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
known = lambda v: v and v != "Not stated"
nice = lambda d: dt.date.fromisoformat(d[:10]).strftime("%-d %b %Y") if d else ""
plural = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")

jobs = [j for j in load("jobs.json", []) if str(j.get("url", "")).startswith("https://")]
partners, recruiters = load("partners.json", []), load("recruiters.json", [])
news = sorted(load("news.json", []), key=lambda n: n["date"], reverse=True)
freelancers, LOGOS = load("freelancers.json", []), load("logos/manifest.json", {})

REG = {"NA": ("USA & Canada", "the USA and Canada", "usa-canada"), "UK": ("UK & Ireland", "the UK and Ireland", "uk-ireland"),
       "NORD": ("Nordics", "the Nordics", "nordics"), "DACH": ("DACH", "Germany, Austria and Switzerland", "dach"),
       "EU": ("Rest of Europe", "Benelux, France and the rest of Europe", "europe"),
       "MEA": ("Middle East & Africa", "the Middle East and Africa", "middle-east-africa"),
       "SA": ("South Asia", "South Asia", "south-asia"), "APAC": ("Asia Pacific", "Asia Pacific", "asia-pacific")}
KIND = {"S": "IFS specialist", "B": "ERP boutique", "G": "Global firm"}

# ------------------------------------------------------------------ data prep
for j in jobs:
    j["when"] = j.get("posted") or j.get("first_seen") or TODAY.isoformat()
    j["loc"] = ", ".join(x for x in (j.get("city"), j.get("country")) if known(x))
    j["slug"] = slug(f"{j['title']} {j['company']}")[:70].strip("-") + "-" + hashlib.md5(j["url"].encode()).hexdigest()[:6]
    j["path"] = f"jobs/{j['slug']}/"
    j["remote"] = j.get("work_mode") in ("Remote", "Hybrid")
jobs.sort(key=lambda j: j["when"], reverse=True)


for n in news:
    n["path"] = f"news/{slug(n['title'])[:70].strip('-')}/"


def pscore(p):
    """Emerging-first score. The same rules are printed on the Top 10 pages."""
    s = {"S": 3, "B": 1.5, "G": 0}[p["kind"]]
    s += 2 if p.get("sig") else 0
    s += 1.5 if (p.get("founded") or 0) >= 2016 else 0
    s += min(2, len(set(re.findall(r"202[345]", p.get("awards") or ""))))
    s += {"Elite": 1.5, "Premier": 1, "Specialized": 0.5}.get(p.get("tier"), 0)
    return s


for p in partners:
    p["score"], p["path"] = pscore(p), f"partners/{slug(p['n'])}/"
    p["jobs"] = [j for j in jobs if j["company"].lower().startswith(p["n"].lower().split(" (")[0])]
PBY = {p["n"].lower(): p for p in partners}
top10 = {r: sorted((p for p in partners if r in p["r"]), key=lambda p: (-(p["score"] + 3 * (p.get("home") == r)), p["n"]))[:10] for r in REG}
# Editorial override: a named partner is placed first in a region, the rest keep their scored order.
PIN = {"SA": "Inivos"}
for _r, _n in PIN.items():
    _p = PBY[_n.lower()]
    top10[_r] = ([_p] + [x for x in top10[_r] if x is not _p])[:10]

countries = {c: n for c, n in Counter(j["country"] for j in jobs if known(j.get("country"))).items() if n >= 2}
areas = {a: n for a, n in Counter(j["area"] for j in jobs if known(j.get("area"))).items() if n >= 3}
cpath = lambda c: f"ifs-jobs/{slug(c)}/"
apath = lambda a: f"ifs-jobs/{slug(a)}-jobs/"
SPECIAL = {"remote": ("Remote and hybrid IFS jobs", lambda j: j["remote"], "ifs-jobs/remote/"),
           "contract": ("IFS contract jobs", lambda j: j.get("contract_type") == "Contract", "ifs-jobs/contract/"),
           "cloud": ("IFS Cloud jobs", lambda j: j.get("ifs_version") == "IFS Cloud", "ifs-jobs/ifs-cloud/")}
_T = r"technical|developer|development|integration|engineer|programmer"
_title = lambda rx: (lambda j: bool(re.search(rx, j["title"], re.I)))
ROLES = {"functional": ("IFS functional consultant jobs", lambda j: bool(re.search(r"consultant", j["title"], re.I)) and not re.search(_T + r"|architect", j["title"], re.I), "ifs-jobs/functional-consultant/"),
         "technical": ("IFS technical consultant and developer jobs", _title(_T), "ifs-jobs/technical-developer/"),
         "architect": ("IFS solution architect jobs", _title(r"architect"), "ifs-jobs/solution-architect/"),
         "pm": ("IFS project manager jobs", _title(r"project manager|program(me)? manager|delivery manager|project lead|project director"), "ifs-jobs/project-manager/"),
         "support": ("IFS support jobs", _title(r"support"), "ifs-jobs/support/")}
ROLE_N = {k: sum(1 for j in jobs if v[1](j)) for k, v in ROLES.items()}
# Technical, architect, PM and support already have a module page each, so only the functional page is new.
AREA_ROLE = {"technical": "Technical / Development", "architect": "Architecture", "pm": "Project Management", "support": "Support / Admin"}
ROLES = {k: (v[0], v[1], apath(AREA_ROLE[k]) if k in AREA_ROLE else v[2]) for k, v in ROLES.items() if ROLE_N[k] >= 3 and AREA_ROLE.get(k, 1) in (1, *areas)}
ROLE_N.update({k: areas[a] for k, a in AREA_ROLE.items() if a in areas})
AREA_H = {AREA_ROLE[k]: ROLES[k][0] for k in ROLES if k in AREA_ROLE}
SPECIAL["functional"] = ROLES["functional"]
ROLE_SHORT = {"functional": "Functional consultant", "technical": "Technical and developer", "architect": "Solution architect", "pm": "Project manager", "support": "Support"}

# ------------------------------------------------------------------ components
PAGES = []          # (path, lastmod, priority) for the sitemap


def logo(name, root, wide=False):
    key = re.sub(r"^ifs \(.*\)$", "ifs", name.lower())
    l = LOGOS.get(key, {})
    words = [w for w in re.split(r"[\s&-]+", re.sub(r"\(.*?\)", "", name).strip()) if w]
    ini = (words[0][0] + words[1][0] if len(words) > 1 else name[:2]).upper()
    src = (l.get("wide") or l.get("icon")) if wide else (l.get("icon") or l.get("wide"))
    cls = "logo wide" if wide and l.get("wide") else "logo"
    img = f'<img src="{root}{e(src)}" alt="" loading="lazy">' if src else ""
    return f'<span class="{cls}" aria-hidden="true">{e(ini)}{img}</span>'


def ext(url, text):
    return f'<a href="{e(url)}" target="_blank" rel="noopener nofollow">{text}</a>' if str(url or "").startswith("https://") else ""


def job_row(j, root):
    tags = [t for t in (j.get("area"), j.get("ifs_version"), j.get("work_mode"), j.get("contract_type")) if known(t)]
    text = " ".join(str(j.get(k) or "") for k in ("title", "company", "city", "country", "area", "ifs_version", "summary")).lower()
    date = ("Posted " if j.get("posted") else "Added ") + nice(j["when"])[:-5]
    return (f'<li class="row" data-region="{e(j.get("region"))}" data-country="{e(j.get("country"))}" data-area="{e(j.get("area"))}" '
            f'data-contract="{e(j.get("contract_type"))}" data-type="{e(j.get("company_type"))}" data-remote="{int(j["remote"])}" '
            f'data-cloud="{int(j.get("ifs_version") == "IFS Cloud")}" data-pay="{int(bool(j.get("pay")))}" data-text="{e(text)}">'
            f'{logo(j["company"], root)}<div class="body"><h3><a href="{root}{j["path"]}">{e(j["title"])}</a></h3>'
            f'<p class="meta"><b>{e(j["company"])}</b>{" · " + e(j["loc"]) if j["loc"] else ""} · {e(j.get("company_type"))}</p>'
            f'<div class="tags">{"".join(f"""<span class="tag{" v" if t == "IFS Cloud" else ""}">{e(t)}</span>""" for t in tags)}</div></div>'
            f'<div class="side">{f"""<span class="pay">{e(j["pay"])}</span>""" if j.get("pay") else ""}<span class="muted">{date}</span>'
            f'<a href="{root}{j["path"]}">View job &rarr;</a></div></li>')


def job_list(items, root, label=None):
    label = label or f"{plural(len(items), 'open IFS job')}"
    rows = "".join(job_row(j, root) for j in items)
    return (f'<div class="listhead"><h2 id="count" data-label="{e(label)}" style="font-size:1.15rem">{e(label)}</h2>'
            f'<span class="muted small">Newest first. Each listing links to the original posting.</span></div>'
            f'<ul class="rows" id="jobs">{rows}<li class="empty" id="jobs-empty" hidden>No jobs match those filters. Clear one and try again.</li></ul>')


def options(values):
    return "".join(f'<option value="{e(v)}">{e(v)}</option>' for v in values)


def filters(items, show=("region", "country", "area", "contract", "type")):
    u = lambda k: sorted({j.get(k) for j in items if known(j.get(k))})
    sel = {"region": ("Region", "f-region", "All regions", u("region")), "country": ("Country", "f-country", "All countries", u("country")),
           "area": ("Module / area", "f-area", "All areas", u("area")), "contract": ("Contract", "f-contract", "Any", u("contract_type")),
           "type": ("Employer type", "f-type", "Any", u("company_type"))}
    out = "".join(f'<label>{sel[k][0]}<select id="{sel[k][1]}"><option value="">{sel[k][2]}</option>{options(sel[k][3])}</select></label>' for k in show)
    return (f'<form class="rail" id="filters" onsubmit="return false">{out}'
            '<label class="check"><input type="checkbox" id="f-remote"> Remote or hybrid</label>'
            '<label class="check"><input type="checkbox" id="f-cloud"> Names IFS Cloud</label>'
            '<label class="check"><input type="checkbox" id="f-pay"> Pay stated</label>'
            '<button type="button" class="linkbtn" id="f-reset">Clear all filters</button></form>')


def extras(root):
    mini = "".join(f'<li><a href="{root}{n["path"]}">{e(n["title"])}</a><span>{nice(n["date"])} · {e(n["tag"])}</span></li>' for n in news[:3])
    return (f'<aside class="extras"><div class="note accent"><h3>IFS freelancer?</h3><p class="small">Get featured on this board so partners and customers can find you. It\'s free.</p>'
            f'<a class="small" href="{root}freelancers/">Get featured &rarr;</a></div>'
            f'<div class="note"><h3>What\'s new in IFS</h3><ul>{mini}</ul><a class="small" href="{root}news/">All updates &rarr;</a></div></aside>')


def tags_for(p):
    out = [f'<span class="tag v">{e(p["tier"])}</span>' if p.get("tier") else "", f'<span class="tag">{KIND[p["kind"]]}</span>',
           '<span class="tag v">Emerging</span>' if p["kind"] != "G" and p.get("sig") else "",
           f'<span class="tag">Founded {p["founded"]}</span>' if p.get("founded") else ""]
    return "".join(out)


def btns(p, root, profile=True):
    out = [f'<a class="pbtn primary" href="{root}{p["path"]}">View profile<span aria-hidden="true">&rarr;</span></a>'] if profile else []
    for url, label in ((p.get("web"), "Website"), (p.get("careers"), "Careers")):
        if str(url or "").startswith("https://"):
            out.append(f'<a class="pbtn" href="{e(url)}" target="_blank" rel="noopener nofollow">{label}<span aria-hidden="true">&nearr;</span></a>')
    return '<div class="btns">' + "".join(out) + "</div>"


def faq(items):
    body = "".join(f"<div><h3>{e(q)}</h3><p>{e(a)}</p></div>" for q, a in items)
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in items]}
    return f'<section class="stack"><h2>Questions people ask</h2><div class="faq">{body}</div></section>', ld


NAV = [("", "Jobs"), ("top-ifs-partners/", "Top 10"), ("partners/", "Partners"), ("ifs-recruiters/", "Recruiters"),
       ("freelancers/", "Freelancers"), ("news/", "What's new"), ("ifs-hiring-report/", "Hiring report"), ("marketing-for-ifs-partners/", "Marketing")]


def page(path, title, desc, body, active="", ld=(), crumbs=(), priority="0.6", lastmod=None, index=True):
    depth = len([s for s in path.split("/") if s]) if not path.endswith(".html") else 0
    root = "/" if path == "404.html" else "../" * depth
    url = f"{SITE}/{path}" if path != "404.html" else SITE + "/"
    nav = "".join(f'<a href="{root}{p or ("./" if not root else "")}"{" aria-current=\"page\"" if p == active else ""}>{t}</a>' for p, t in NAV)
    trail = [("Home", "")] + list(crumbs)
    bc = ""
    lds = list(ld)
    if crumbs:
        bc = '<nav class="crumbs" aria-label="Breadcrumb">' + " / ".join(
            f'<a href="{root}{p or ("./" if not root else "")}">{e(t)}</a>' if p is not None else f"<span>{e(t)}</span>" for t, p in trail) + "</nav>"
        lds.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": t, "item": f"{SITE}/{p}" if p is not None else url} for i, (t, p) in enumerate(trail)]})
    body = body.replace("<!--crumbs-->", bc)
    if index and path != "404.html":
        lds.append({"@context": "https://schema.org", "@type": "WebPage", "url": url, "name": title, "description": desc, "dateModified": lastmod or TODAY.isoformat(),
                    "isPartOf": {"@type": "WebSite", "name": "findifsjobs", "url": SITE + "/"}})
    ga = CFG.get("ga_id")
    ga_tag = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={e(ga)}"></script><script>window.dataLayer=window.dataLayer||[];'
              f'function gtag(){{dataLayer.push(arguments)}}gtag("js",new Date());gtag("config","{e(ga)}");</script>') if ga else ""
    sc = CFG.get("search_console_meta")
    head = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}">'
            f'{"" if index else "<meta name=\"robots\" content=\"noindex\">"}'
            f'{f"<meta name=\"google-site-verification\" content=\"{e(sc)}\">" if sc else ""}'
            f'{f"<meta name=\"msvalidate.01\" content=\"{e(CFG.get("bing_meta"))}\">" if CFG.get("bing_meta") else ""}'
            f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(url)}">'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="findifsjobs"><meta name="twitter:card" content="summary">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap">'
            f'<link rel="icon" href="{root}favicon.ico" sizes="48x48"><link rel="icon" href="{root}favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="{root}apple-touch-icon.png">'
            f'<link rel="stylesheet" href="{root}assets/site.css">'
            + "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in lds)
            + f'{ga_tag}</head><body data-form="{e(CFG.get("form_endpoint", ""))}">')
    header = (f'<header class="top"><div class="wrap"><a class="brand" href="{root or "./"}">find<i>ifs</i>jobs</a>'
              f'<nav class="tabs" aria-label="Sections">{nav}</nav><a class="btn" href="{root}hire/">Hire IFS talent</a></div></header>')
    footer = (f'<footer><div class="wrap"><div style="display:flex;flex-direction:column;gap:10px"><h2>New IFS jobs every Monday</h2>'
              f'<form class="news-form" data-kind="newsletter" data-done="Subscribed. The next issue arrives on Monday."><input type="email" name="email" placeholder="you@company.com" aria-label="Email address" required>'
              f'<button class="btn" type="submit">Subscribe</button></form><p class="msg" hidden style="max-width:480px"></p></div>'
              f'<ul class="linklist"><li><a href="{root}about/">About and method</a></li><li><a href="{root}guides/">IFS career guides</a></li><li><a href="{root}ifs-partners/">IFS partners by country</a></li><li><a href="{root}ifs-hiring-report/">IFS hiring report</a></li><li><a href="{root}ifs-hiring-index/">IFS Hiring Index</a></li>'
              f'<li><a href="{root}ifs-jobs/remote/">Remote IFS jobs</a></li><li><a href="{root}ifs-jobs/contract/">IFS contract jobs</a></li>'
              f'<li><a href="{root}ifs-jobs/ifs-cloud/">IFS Cloud jobs</a></li><li><a href="{root}hire/">Hire IFS talent</a></li><li><a href="{root}marketing-for-ifs-partners/">Marketing for IFS partners</a></li></ul>'
              f'<p><b style="color:var(--ink);font-weight:500">findifsjobs.com</b> is an independent job board. It is not affiliated with, endorsed by or sponsored by IFS. '
              f'IFS and IFS Cloud are trademarks of their owner. Company names and logos belong to their owners and are shown to identify them.</p>'
              f'<p>Jobs refresh daily from public careers pages. Last updated {TODAY.strftime("%-d %B %Y")}.</p></div></footer>')
    out = OUT / path / "index.html" if not path.endswith(".html") else OUT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f'{head}{header}<main>{body}</main>{footer}<script src="{root}assets/site.js" defer></script></body></html>', encoding="utf-8")
    if index and path != "404.html":
        PAGES.append((path, lastmod or TODAY.isoformat(), priority))


def hero(eyebrow, h, lede, sub=True, extra="", h1cls=""):
    tag = "h1"
    return (f'<div class="hero{" sub" if sub else ""}"><div class="wrap"><!--crumbs--><p class="eyebrow">{e(eyebrow)}</p>'
            f'<{tag}{f" class=\"{h1cls}\"" if h1cls else ""}>{h}</{tag}><p class="lede">{lede}</p>{extra}</div></div>')


def links(pairs, root):
    return '<ul class="linklist">' + "".join(f'<li><a href="{root}{p}">{e(t)}{f" <span>{n}</span>" if n is not None else ""}</a></li>' for t, p, n in pairs) + "</ul>"


# ------------------------------------------------------------------ stats used across pages
N = len(jobs)
cloud_n = sum(j.get("ifs_version") == "IFS Cloud" for j in jobs)
remote_n = sum(j["remote"] for j in jobs)
by_country = Counter(j["country"] for j in jobs if known(j.get("country"))).most_common()
by_area = Counter(j["area"] for j in jobs if known(j.get("area"))).most_common()
by_region = Counter(j["region"] for j in jobs if j.get("region") in ("EMEA", "Americas", "APAC")).most_common()
by_type = Counter(j["company_type"] for j in jobs).most_common()
by_employer = Counter(j["company"] for j in jobs).most_common(12)
employers_n = len({j["company"] for j in jobs})
MONTH = TODAY.strftime("%B %Y")
country_links = lambda root: links([(c, cpath(c), n) for c, n in sorted(countries.items(), key=lambda x: -x[1])], root)
area_links = lambda root: links([(a, apath(a), n) for a, n in sorted(areas.items(), key=lambda x: -x[1])], root)
role_links = lambda root: links([(ROLE_SHORT[k], v[2], ROLE_N[k]) for k, v in ROLES.items()], root)
mstrip = lambda root: (f'<a class="mstrip" href="{root}marketing-for-ifs-partners/"><span class="mk" aria-hidden="true">&nearr;</span>'
                       f'<span class="mt"><span class="tk">For IFS partners</span><strong>Win more IFS deals. <em>Hire faster.</em></strong>'
                       f'<span class="ms">Marketing built for IFS partners: leads by industry, LinkedIn, events and hiring.</span></span>'
                       f'<span class="go">See how it works <i aria-hidden="true">&rarr;</i></span></a>')

# ------------------------------------------------------------------ build
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "assets").mkdir(parents=True)
for f in ("site.css", "site.js"):
    shutil.copy(HERE / "assets" / f, OUT / "assets" / f)
for f in ("favicon.ico", "favicon.svg", "apple-touch-icon.png"):   # at the site root, where browsers and Google look first
    shutil.copy(HERE / "assets" / f, OUT / f)
if (HERE / "logos").exists():
    shutil.copytree(HERE / "logos", OUT / "logos", ignore=shutil.ignore_patterns("*.txt", "manifest.json"))

# ---- home
top3c = ", ".join(f"{c} ({n})" for c, n in by_country[:3])
top3a = ", ".join(f"{a} ({n})" for a, n in by_area[:3])
GUIDE_LINKS = [("guides/how-to-become-an-ifs-consultant/", "How to become an IFS consultant"), ("guides/ifs-certification/", "IFS certification explained"),
               ("guides/ifs-skills-in-demand/", "IFS skills in demand")]
home_faq, home_ld = faq([
    ("How many IFS jobs are open right now?", f"findifsjobs lists {N} open IFS jobs from {employers_n} employers as of {TODAY.strftime('%-d %B %Y')}. The list refreshes every day from public careers pages."),
    ("Which countries have the most IFS jobs?", f"The countries with the most open IFS roles are {top3c}."),
    ("Which IFS modules are most in demand?", f"The busiest areas are {top3a}."),
    ("Do employers ask for IFS Cloud experience?", f"{cloud_n} of {N} listings name IFS Cloud. Apps 9 and Apps 10 experience usually appears as an alternative, not the main requirement."),
    ("Who posts IFS jobs?", "Four kinds of employer: IFS itself, IFS implementation partners, companies that run IFS in-house, and specialist recruiters. You can filter the list by employer type."),
])
stats = (f'<div class="stats"><span><b>{N}</b> open roles</span><span><b>{len(by_country)}</b> countries</span>'
         f'<span><b>{employers_n}</b> employers</span><span><b>{cloud_n}</b> on IFS Cloud</span></div>')
search = '<div class="search"><input type="search" id="f-q" placeholder="Search by title, company, city or skill" aria-label="Search jobs"><button class="btn" type="button" id="f-go">Search</button></div>'
home = (hero("IFS consultant, developer and architect jobs", "Find your next <em>IFS</em> job.",
             "Every open IFS consultant job in one list: IFS Cloud, Apps 10, FSM and EAM roles from the vendor, partners, customers and recruiters.", sub=False, extra=search + stats)
        + f'<div class="wrap"><div class="board">{filters(jobs)}<div class="list">{job_list(jobs, "")}</div>{extras("")}</div>'
        + f'<section class="stack"><h2>IFS jobs by role</h2>{role_links("")}</section>'
        + f'<section class="stack"><h2>IFS jobs by country</h2>{country_links("")}</section>'
        + f'<section class="stack"><h2>IFS jobs by module</h2>{area_links("")}</section>'
        + f'<section class="stack"><h2>IFS career guides</h2>{links([(t, p, None) for p, t in GUIDE_LINKS], "")}</section>{mstrip("")}{home_faq}</div>')
page("", f"IFS Consultant Jobs: {N} open IFS Cloud, ERP, EAM and FSM jobs | findifsjobs",
     f"{N} open IFS jobs from {employers_n} employers in {len(by_country)} countries. IFS Cloud consultants, developers, architects and support roles, updated daily.",
     home, active="", priority="1.0",
     ld=[home_ld, {"@context": "https://schema.org", "@type": "WebSite", "name": "findifsjobs", "url": SITE + "/",
                   "potentialAction": {"@type": "SearchAction", "target": SITE + "/?q={search_term_string}", "query-input": "required name=search_term_string"}},
         {"@context": "https://schema.org", "@type": "Organization", "name": "findifsjobs", "url": SITE + "/",
          "description": "Independent job board and directory for the IFS ERP ecosystem."}])

# ---- job pages
EMP = {"Contract": "CONTRACTOR", "Permanent": "FULL_TIME", "Fixed term": "TEMPORARY"}
CUR_SYM = {"£": "GBP", "€": "EUR", "₹": "INR", "RM": "MYR"}
DOLLAR = {"Canada": "CAD", "Australia": "AUD", "Singapore": "SGD", "New Zealand": "NZD"}


def salary(pay, country):
    """Turn the pay line from the advert into schema.org baseSalary. Returns None when it can't be read safely."""
    if not pay:
        return None
    cur = next((c for s, c in CUR_SYM.items() if s in pay), None) or (DOLLAR.get(country, "USD") if "$" in pay else None)
    lakh = bool(re.search(r"\d\s*L\b", pay))
    nums = [float(n.replace(",", "")) * (100000 if lakh else 1) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", pay)]
    unit = next((u for w, u in (("hour", "HOUR"), ("day", "DAY"), ("week", "WEEK"), ("month", "MONTH"), ("year", "YEAR"), ("annum", "YEAR")) if w in pay.lower()), None)
    if not cur or not nums:
        return None
    if not unit:
        if min(nums) < 20000:   # too low to be sure it is annual; leave it out rather than guess
            return None
        unit = "YEAR"
    if re.search(r"up to", pay, re.I):
        val = {"maxValue": max(nums)}
    elif len(nums) >= 2:
        val = {"minValue": min(nums[:2]), "maxValue": max(nums[:2])}
    else:
        val = {"value": nums[0]}
    return {"@type": "MonetaryAmount", "currency": cur, "value": {"@type": "QuantitativeValue", **val, "unitText": unit}}
for j in jobs:
    root = "../../"
    facts = [("Employer", j["company"]), ("Employer type", j.get("company_type")), ("Location", j["loc"]),
             ("Module / area", j.get("area")), ("IFS version", j.get("ifs_version")), ("Work mode", j.get("work_mode")),
             ("Contract", j.get("contract_type")), ("Seniority", j.get("seniority")), ("Pay", j.get("pay")),
             ("Posted" if j.get("posted") else "Added to the board", nice(j["when"]))]
    table = '<table class="facts">' + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in facts if known(v)) + "</table>"
    generic = re.match(r"^(Senior |Junior |Lead )?[\w /&]+ role at ", j.get("summary") or "")
    desc = (f"{j['company']} is hiring {'an' if j['title'][:1].lower() in 'aeiou' else 'a'} {j['title']}" + (f" in {j['loc']}" if j["loc"] else "") + ". "
            + (f"The role sits in {j['area']}" if known(j.get("area")) else "This is an IFS role")
            + (", and the advert names IFS Cloud" if j.get("ifs_version") == "IFS Cloud" else "") + ". "
            + (f"It is {j['work_mode'].lower()}. " if known(j.get("work_mode")) else "")
            + (f"The engagement is {j['contract_type'].lower()}. " if known(j.get("contract_type")) else "")
            + (f"Stated pay: {j['pay']}. " if j.get("pay") else ""))
    about = desc if generic or not j.get("summary") else f"{j['summary']} {desc}"
    adv = (f'<h2>From the advert</h2><p>{e(j["excerpt"])}</p><p class="muted small">An extract from {e(j["company"])}\'s own posting. The full advert and the application form are on the original page.</p>') if j.get("excerpt") else ""
    partner = PBY.get(j["company"].lower())
    related = [x for x in jobs if x is not j and (x["company"] == j["company"] or x.get("area") == j.get("area"))][:5]
    side = (f'<div class="stack"><div class="note"><h3>About this listing</h3><p class="small">findifsjobs found this role on {e(j["company"])}\'s public careers page or advert. '
            f'Applications go to the original posting, not to us.</p></div>'
            + (f'<div class="note"><h3>About {e(partner["n"])}</h3><p class="small">{e(partner["blurb"])}</p><a class="small" href="{root}{partner["path"]}">Partner profile &rarr;</a></div>' if partner else "")
            + (f'<div class="note"><h3>More IFS jobs</h3>{links([(c, cpath(c), None) for c in [j.get("country")] if c in countries] + [(a, apath(a), None) for a in [j.get("area")] if a in areas] + [("All IFS jobs", "", None)], root)}</div>') + "</div>")
    body = (hero(j.get("company_type") or "IFS job", e(j["title"]), f'<b style="color:var(--ink);font-weight:500">{e(j["company"])}</b>{" · " + e(j["loc"]) if j["loc"] else ""}', h1cls="small",
                 extra=f'<a class="btn bigbtn" href="{e(j["url"])}" target="_blank" rel="noopener nofollow">Apply on the original posting &rarr;</a>')
            + f'<div class="wrap"><div class="article"><div class="stack"><div class="prose"><h2>About the role</h2><p>{e(about)}</p>{adv}</div>{table}'
            + (f'<section class="stack"><h2>Similar IFS jobs</h2><ul class="rows">{"".join(job_row(x, root) for x in related)}</ul></section>' if related else "")
            + f'</div>{side}</div></div>')
    ld = []
    if known(j.get("country")):
        valid = (dt.date.fromisoformat((j.get("last_seen") or TODAY.isoformat())[:10]) + dt.timedelta(days=30)).isoformat()
        jp = {"@context": "https://schema.org", "@type": "JobPosting", "title": j["title"], "description": f"<p>{e(about)}</p>" + (f"<p>{e(j['excerpt'])}</p>" if j.get("excerpt") else ""),
              "datePosted": j["when"][:10], "validThrough": valid, "directApply": False, "url": f"{SITE}/{j['path']}",
              "hiringOrganization": {"@type": "Organization", "name": j["company"], **({"sameAs": partner["web"]} if partner and partner.get("web") else {})},
              "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": j["country"],
                                                            **({"addressLocality": j["city"]} if known(j.get("city")) and j["city"] != "Remote" else {}),
                                                            **({"addressRegion": j["state"]} if j.get("state") else {}),
                                                            **({"postalCode": j["postal"]} if j.get("postal") else {}),
                                                            **({"streetAddress": j["street"]} if j.get("street") else {})}},
              "industry": "Enterprise software (IFS ERP)", "occupationalCategory": j.get("area") or "IFS"}
        if j.get("contract_type") in EMP:
            jp["employmentType"] = EMP[j["contract_type"]]
        sal = salary(j.get("pay"), j.get("country"))
        if sal:
            jp["baseSalary"] = sal
        if j.get("work_mode") == "Remote":
            jp["jobLocationType"] = "TELECOMMUTE"
            jp["applicantLocationRequirements"] = {"@type": "Country", "name": j["country"]}
        ld.append(jp)
    page(j["path"], f"{j['title']} at {j['company']}{', ' + j['loc'] if j['loc'] else ''} | findifsjobs",
         f"{j['title']} at {j['company']}{' in ' + j['loc'] if j['loc'] else ''}. {j.get('area') or 'IFS'} role. See the details and apply on the original posting.",
         body, ld=ld, crumbs=[("IFS jobs", ""), (j["title"], None)], priority="0.7", lastmod=j["when"][:10])


# ---- landing pages
def landing(path, h, lede, items, title, desc, qa, crumb):
    block, ld = faq(qa)
    body = (hero("IFS jobs", e(h), lede) + f'<div class="wrap"><div class="board">{filters(items, show=("area", "contract", "type") if "ifs-jobs/" in path and len({j.get("country") for j in items}) == 1 else ("country", "area", "contract", "type"))}'
            f'<div class="list">{job_list(items, "../../")}</div>{extras("../../")}</div>'
            f'<section class="stack"><h2>IFS jobs by role</h2>{role_links("../../")}</section>'
            f'<section class="stack"><h2>IFS jobs by country</h2>{country_links("../../")}</section>'
            f'<section class="stack"><h2>IFS jobs by module</h2>{area_links("../../")}</section>{block}</div>')
    page(path, title, desc, body, ld=[ld], crumbs=[("IFS jobs", ""), (crumb, None)], priority="0.8")


for c, n in countries.items():
    items = [j for j in jobs if j.get("country") == c]
    emps = Counter(j["company"] for j in items).most_common(3)
    ars = Counter(j["area"] for j in items if known(j.get("area"))).most_common(3)
    emp_txt, ar_txt = ", ".join(x for x, _ in emps), ", ".join(x for x, _ in ars)
    landing(cpath(c), f"IFS jobs in {c}", f"{plural(n, 'open IFS role')} in {e(c)} from {plural(len({j['company'] for j in items}), 'employer')}, updated daily.", items,
            f"IFS jobs in {c}: {plural(n, 'open role')} ({MONTH}) | findifsjobs",
            f"{plural(n, 'open IFS job')} in {c}. Employers include {emp_txt}. IFS Cloud consultant, developer, architect and support roles, refreshed daily.",
            [(f"How many IFS jobs are open in {c}?", f"{plural(n, 'IFS role')} in {c} as of {TODAY.strftime('%-d %B %Y')}."),
             (f"Who is hiring for IFS in {c}?", f"The employers with the most open IFS roles in {c} are {emp_txt}."),
             (f"Which IFS skills are wanted in {c}?", f"The most common areas are {ar_txt}." if ar_txt else "Roles span several IFS modules.")], c)
for a, n in areas.items():
    items = [j for j in jobs if j.get("area") == a]
    cs = ", ".join(x for x, _ in Counter(j["country"] for j in items if known(j.get("country"))).most_common(3))
    landing(apath(a), AREA_H.get(a, f"IFS {a} jobs"), f"{plural(n, 'open IFS role')} in {e(a)}, updated daily.", items,
            f"{AREA_H.get(a, f'IFS {a} jobs')}: {plural(n, 'open role')} ({MONTH}) | findifsjobs",
            f"{plural(n, 'open IFS job')} in {a}. Mostly in {cs}. Filter by country, contract type and employer.",
            [(f"How many IFS {a} jobs are open?", f"{plural(n, 'role')} as of {TODAY.strftime('%-d %B %Y')}."),
             (f"Where are IFS {a} jobs?", f"Most are in {cs}.")], f"{a} jobs")
for key, (h, test, path) in SPECIAL.items():
    items = [j for j in jobs if test(j)]
    if items:
        landing(path, h, f"{plural(len(items), 'open role')}, updated daily.", items, f"{h}: {plural(len(items), 'open role')} ({MONTH}) | findifsjobs",
                f"{plural(len(items), 'open role')} on findifsjobs. {h} from IFS partners, customers and recruiters, refreshed daily.",
                [(f"How many {h[0].lower() + h[1:] if not h.startswith('IFS') else h} are open?", f"{plural(len(items), 'role')} out of {N} IFS jobs listed, as of {TODAY.strftime('%-d %B %Y')}."),
                 ("Who is hiring?", "The employers with the most of these roles are " + ", ".join(x for x, _ in Counter(j["company"] for j in items).most_common(3)) + "."),
                 ("Where are these jobs?", "Mostly in " + (", ".join(x for x, _ in Counter(j["country"] for j in items if known(j.get("country"))).most_common(3)) or "several countries") + ".")], h)

# ---- partners: directory and profiles
PC_RX = {"UK": r"\bUK\b|United Kingdom|England|Scotland", "USA": r"\bUSA\b|United States|Boston", "Canada": r"Canada|Ottawa", "Germany": "Germany", "Austria": "Austria",
         "Sri Lanka": "Sri Lanka"}
for _c in ("France", "India", "Netherlands", "Poland", "Saudi Arabia", "Japan", "Sweden", "Norway", "South Africa", "Indonesia", "Denmark", "Belgium", "Italy", "Australia", "Thailand"):
    PC_RX[_c] = _c
THE = {"UK": "the UK", "USA": "the USA", "Netherlands": "the Netherlands"}
PCOUNTRY = {p["n"]: next((c for c, rx in PC_RX.items() if re.search(rx, p["hq"])), None) for p in partners}
_pins = {n for n in PIN.values()}
PC_PAGES = {}
for _c in PC_RX:
    _l = sorted((p for p in partners if re.search(PC_RX[_c], p["hq"])), key=lambda p: (p["n"] not in _pins, -p["score"], p["n"]))
    if len(_l) >= 2:
        PC_PAGES[_c] = _l
PC_PAGES = dict(sorted(PC_PAGES.items(), key=lambda x: -len(x[1])))
cells = ""
for p in sorted(partners, key=lambda p: (-p["score"], p["n"])):
    text = " ".join(str(p.get(k) or "") for k in ("n", "hq", "focus", "blurb", "tier")).lower()
    pl = "".join(x for x in (f'<a href="../{p["path"]}">Profile</a>', ext(p.get("web"), "Website"), ext(p.get("careers"), "Careers")) if x)
    cells += (f'<li class="cell" data-regions="{" ".join(p["r"])}" data-kind="{p["kind"]}" data-tier="{e(p.get("tier") or "")}" data-score="{p["score"]}" data-name="{e(p["n"])}" data-text="{e(text)}">'
              f'<div class="head">{logo(p["n"], "../", True)}<div class="body"><h3><a href="../{p["path"]}" style="color:var(--ink)">{e(p["n"])}</a></h3><p class="meta">{e(p["hq"])}</p></div></div>'
              f'<p class="sum">{e(p["blurb"])}</p><p class="kv"><b>Focus:</b> {e(p["focus"])}</p>'
              + (f'<p class="kv"><b>Size:</b> {e(p["size"])}</p>' if p.get("size") else "")
              + f'<p class="kv"><b>Active in:</b> {", ".join(REG[x][0] for x in p["r"])}</p><div class="tags">{tags_for(p)}</div>{btns(p, "../")}</li>')
toolbar = ('<div class="toolbar"><input type="search" class="plain" id="p-q" placeholder="Search partners, industries, cities" aria-label="Search partners">'
           f'<select id="p-region" aria-label="Region"><option value="">All regions</option>{"".join(f"""<option value="{k}">{v[0]}</option>""" for k, v in REG.items())}</select>'
           '<select id="p-kind" aria-label="Type"><option value="">All types</option><option value="S">IFS specialists</option><option value="B">ERP boutiques</option><option value="G">Global firms</option></select>'
           '<select id="p-sort" aria-label="Sort"><option value="score">Emerging first</option><option value="az">A to Z</option><option value="tier">Highest tier first</option></select></div>')
page("partners/", f"IFS partner directory: {len(partners)} implementation partners | findifsjobs",
     f"{len(partners)} verified IFS partners across eight regions, with tier, size, focus and careers links. Sorted to surface emerging IFS specialists first.",
     hero("Partner directory", f"{len(partners)} IFS partners, emerging firms first", "Every firm is confirmed as an IFS partner by the IFS directory, an IFS announcement or an IFS event listing.")
     + f'<div class="wrap">{toolbar}<p class="muted small" id="p-count">{len(partners)} of {len(partners)} partners</p><ul class="grid" id="p-list">{cells}</ul><section class="stack"><h2>IFS partners by country</h2>{links([(c, f"ifs-partners/{slug(c)}/", len(v)) for c, v in PC_PAGES.items()], "../")}</section>{mstrip("../")}</div>',
     active="partners/", crumbs=[("Partner directory", None)], priority="0.8")

for p in partners:
    root = "../../"
    ranks = [(r, top10[r].index(p) + 1) for r in p["r"] if p in top10[r]]
    facts = [("Headquarters", p["hq"]), ("IFS partner tier", p.get("tier")), ("Type", KIND[p["kind"]]), ("Size", p.get("size")), ("Founded", p.get("founded")),
             ("Focus", p["focus"]), ("IFS awards", p.get("awards")), ("Active in", ", ".join(REG[x][0] for x in p["r"]))]
    table = '<table class="facts">' + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in facts if v) + "</table>"
    pc = PCOUNTRY.get(p["n"])
    bd = ""
    if ranks:
        br = min(ranks, key=lambda x: (x[1], x[0] != p.get("home")))[0]   # best placing; home region wins a tie
        bcode = (f'<a href="{SITE}/top-ifs-partners/{REG[br][2]}/"><img src="{SITE}/badges/top-10-ifs-partner-{REG[br][2]}.svg" '
                 f'alt="Top 10 IFS Partner {TODAY.year}, {REG[br][0]} - findifsjobs" width="220" height="82"></a>')
        bd = (f'<div class="note"><h3>Show your ranking</h3><img class="badge" src="{root}badges/top-10-ifs-partner-{REG[br][2]}.svg" alt="Top 10 IFS Partner {TODAY.year}, {e(REG[br][0])}" width="220" height="82">'
              f'<p class="small">Work at {e(p["n"])}? Paste this on your website or careers page.</p><textarea class="code" readonly rows="7" aria-label="Badge embed code" onclick="this.select()">{e(bcode)}</textarea></div>')
    rank_html = ('<div class="note"><h3>Rankings</h3><ul>' + "".join(f'<li><a href="{root}top-ifs-partners/{REG[r][2]}/">#{n} in {e(REG[r][0])}</a></li>' for r, n in ranks) + "</ul></div>") if ranks else ""
    pl = "".join(x for x in (ext(p.get("web"), "Website"), ext(p.get("careers"), "Careers page"), ext(p.get("src"), "Source for partner status")) if x)
    jobs_html = (f'<section class="stack"><h2>Open IFS jobs at {e(p["n"])}</h2><ul class="rows">{"".join(job_row(j, root) for j in p["jobs"])}</ul></section>' if p["jobs"]
                 else f'<section class="stack"><h2>Open IFS jobs at {e(p["n"])}</h2><p class="muted">No open roles from {e(p["n"])} are on the board today. '
                      + (ext(p.get("careers"), "Check their careers page") or "Check their website") + ".</p></section>")
    body = (hero("IFS partner", f'<span class="pagelogo">{logo(p["n"], root, True)}<span>{e(p["n"])}</span></span>', e(p["blurb"]), h1cls="small")
            + f'<div class="wrap"><div class="article"><div class="stack">'
            + (f'<div class="prose"><h2>What stands out</h2><p>{e(p["sig"])}</p></div>' if p.get("sig") else "")
            + f'{table}<div class="tags">{tags_for(p)}</div>{jobs_html}</div><div class="stack">{rank_html}{bd}{f"""<div class="note"><h3>More partners</h3><a class="small" href="{root}ifs-partners/{slug(pc)}/">IFS partners in {e(THE.get(pc, pc))} &rarr;</a></div>""" if pc in PC_PAGES else ""}<div class="note"><h3>Links</h3><div class="cell" style="border:0;padding:0;background:none"><div class="foot" style="border:0;padding:0;flex-direction:column">{pl}</div></div></div></div></div>{mstrip(root)}</div>')
    page(p["path"], f"{p['n']}: IFS partner profile, jobs and facts | findifsjobs",
         f"{p['n']} is an IFS partner based in {p['hq']}. {p['blurb']} Tier, size, focus, awards and open IFS jobs.", body, active="partners/",
         ld=[{"@context": "https://schema.org", "@type": "Organization", "name": p["n"], **({"url": p["web"]} if p.get("web") else {}), "description": p["blurb"]}],
         crumbs=[("Partner directory", "partners/"), (p["n"], None)], priority="0.6")

# ---- top 10 by region
METHOD = ('<p class="method"><b>How the ranking works.</b> Scores guide the list and the final order is an editorial decision. Points for being IFS-only (3) or an ERP boutique (1.5), a recent growth signal such as a merger, new tier or new market (2), '
          'being founded since 2016 (1.5), IFS awards from 2023 to 2025 (1 each, up to 2), partner tier (Elite 1.5, Premier 1, Specialized 0.5) and a home base in the region (3). '
          'Facts come from the IFS partner directory, IFS press releases and each firm\'s own site. This is an editorial ranking by findifsjobs, not an IFS one.</p>')
pills = lambda cur, root: '<div class="pills">' + "".join(f'<a class="pill" href="{root}top-ifs-partners/{v[2]}/"{" aria-pressed=\"true\"" if k == cur else ""}>{v[0]}</a>' for k, v in REG.items()) + "</div>"


def pod(p, i, root):
    return (f'<li class="pod{" first" if i == 0 else ""}"><span class="rk" aria-hidden="true">{i + 1:02d}</span>{logo(p["n"], root, True)}'
            f'<h2><a href="{root}{p["path"]}">{e(p["n"])}</a></h2><p class="meta">{e(p["hq"])}{" · " + e(p["size"]) if p.get("size") else ""}</p>'
            f'<p class="sum">{e(p.get("sig") or p["blurb"])}</p><div class="tags">{tags_for(p)}</div>{btns(p, root)}</li>')


def rrow(p, i, root):
    return (f'<li class="rrow"><span class="rk" aria-hidden="true">{i + 1:02d}</span>{logo(p["n"], root, True)}<div class="body"><h3><a href="{root}{p["path"]}">{e(p["n"])}</a></h3>'
            f'<p class="meta">{e(p["hq"])}{" · " + e(p["size"]) if p.get("size") else ""}</p><p class="sum">{e(p.get("sig") or p["blurb"])}</p>'
            f'{f"""<p class="kv"><b>Awards:</b> {e(p["awards"])}</p>""" if p.get("awards") else ""}<div class="tags">{tags_for(p)}</div></div>{btns(p, root)}</li>')


for r, (short, long, rs) in REG.items():
    root = "../../"
    t = top10[r]
    names = ", ".join(p["n"] for p in t[:5])
    block, fl = faq([(f"Who are the top IFS partners in {long}?", f"By findifsjobs' emerging-first ranking, the top five are {names}."),
                     (f"How is the ranking decided?", "Partners score points for IFS-only focus, recent growth signals, founding since 2016, IFS awards from 2023 to 2025, partner tier and a home base in the region. Global firms are listed but not favoured. The scores guide the list and the final order is an editorial decision by findifsjobs."),
                     ("Is this an official IFS ranking?", "No. It is an independent editorial ranking by findifsjobs, built from public facts.")])
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"Top 10 IFS partners in {long}", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": p["n"], "url": f"{SITE}/{p['path']}"} for i, p in enumerate(t)]}
    page(f"top-ifs-partners/{rs}/", f"Top 10 IFS partners in {long} (2026) | findifsjobs",
         f"The top 10 IFS implementation partners in {long}: {names} and more. Ranked on focus, growth, awards and tier, with the method shown.",
         hero("The 2026 ranking", f'Top 10 <em>IFS partners</em> in {e(long)}', "Ranked for people choosing where to work or who to hire. Specialists and fast-growing firms come first.", h1cls="mega")
         + f'<div class="wrap">{pills(r, root)}<ol class="podium">{"".join(pod(p, i, root) for i, p in enumerate(t[:3]))}</ol>'
           f'<ol class="rrows" start="4">{"".join(rrow(p, i + 3, root) for i, p in enumerate(t[3:]))}</ol>{METHOD}{block}</div>',
         active="top-ifs-partners/", ld=[il, fl], crumbs=[("Top 10 partners", "top-ifs-partners/"), (short, None)], priority="0.9")
idx = "".join(
    f'<li><a class="tcard" href="{v[2]}/"><span class="ten" aria-hidden="true">10</span><span class="tk">Top 10 IFS partners</span><strong>{e(v[0])}</strong>'
    f'<span class="lead">No. 1: {e(top10[k][0]["n"])}</span><span class="stackl">{"".join(logo(p["n"], "../") for p in top10[k][:5])}</span>'
    f'<span class="go">See the ranking <i aria-hidden="true">&rarr;</i></span></a></li>' for k, v in REG.items())
page("top-ifs-partners/", "Top 10 IFS partners by region (2026) | findifsjobs",
     "Top 10 IFS implementation partners in eight regions: USA and Canada, UK and Ireland, Nordics, DACH, Europe, Middle East and Africa, South Asia and Asia Pacific.",
     hero("The 2026 ranking", "Top 10 <em>IFS partners</em>, region by region", "Eight rankings. Specialists and fast-growing firms come first, and the scoring is printed on every list.", h1cls="mega")
     + f'<div class="wrap"><ul class="tgrid">{idx}</ul>{METHOD}</div>', active="top-ifs-partners/", crumbs=[("Top 10 partners", None)], priority="0.9")

# ---- recruiters
def rcell(r):
    return (f'<li class="cell"><div class="head">{logo(r["n"], "../", True)}<div class="body"><h3>{e(r["n"])}</h3><p class="meta">{e(r["hq"])}</p></div></div>'
            f'<p class="sum">{e(r["blurb"])}</p><p class="kv"><b>Covers:</b> {e(r["cover"])}</p><p class="kv"><b>Evidence:</b> {e(r["ev"])}</p>'
            f'<div class="tags"><span class="tag{" v" if r["tier"] == 1 else ""}">{e(r["focus"])}</span>{f"""<span class="tag">{e(r["type"])}</span>""" if r.get("type") else ""}</div>'
            f'<div class="foot">{"".join(x for x in (ext(r.get("web"), "Website"), ext(r.get("jobs"), "IFS jobs"), ext(r.get("src"), "Source")) if x)}</div></li>')


spec = [r for r in recruiters if r["tier"] == 1]
block, fl = faq([("Which recruiters specialise in IFS?", f"{len(spec)} firms run an IFS-only business or a dedicated IFS desk: {', '.join(r['n'] for r in spec)}."),
                 ("Do IFS recruiters place contractors or permanent staff?", "Most specialists do both. Contract roles dominate in the UK; permanent roles are more common with partners and customers.")])
page("ifs-recruiters/", "IFS recruiters: specialist IFS recruitment agencies | findifsjobs",
     f"{len(spec)} recruitment firms that specialise in IFS, plus generalists that regularly carry IFS roles. Coverage, focus and evidence for each.",
     hero("IFS recruiters", "Who recruits for IFS", f"{len(spec)} firms run an IFS-only business or a dedicated IFS desk. The rest are generalists that regularly carry IFS roles.")
     + f'<div class="wrap"><h2 style="font-size:1.1rem">IFS specialists</h2><ul class="grid">{"".join(rcell(r) for r in spec)}</ul>'
     f'<h2 style="font-size:1.1rem">Also recruiting IFS roles</h2><ul class="grid">{"".join(rcell(r) for r in recruiters if r["tier"] == 2)}</ul>{block}</div>',
     active="ifs-recruiters/", ld=[fl], crumbs=[("Recruiters", None)], priority="0.8")

# ---- freelancers
fl_cells = "".join(
    f'<li class="cell"><div class="head">{logo(f["name"], "../")}<div class="body"><h3>{e(f["name"])}</h3><p class="meta">{e(f.get("location") or "")}</p></div></div>'
    f'<p class="sum">{e(f["headline"])}</p>{f"""<p class="kv"><b>Modules:</b> {e(f["modules"])}</p>""" if f.get("modules") else ""}'
    f'<div class="tags">{f"""<span class="tag v">{e(f["versions"])}</span>""" if f.get("versions") else ""}{f"""<span class="tag">{e(f["availability"])}</span>""" if f.get("availability") else ""}</div>'
    f'<div class="foot">{ext(f.get("linkedin"), "LinkedIn profile")}</div></li>' for f in freelancers) or \
    '<li class="empty" style="grid-column:1/-1;border:1px dashed var(--line);border-radius:var(--r)">No freelancers featured yet. Be the first.</li>'
fl_form = ('<form class="form" data-kind="freelancer profile" data-done="Profile received. We review each one before it goes live.">'
           '<label>Full name<input type="text" name="name" required></label><label>Email (not shown publicly)<input type="email" name="email" required></label>'
           '<label class="full">Headline<input type="text" name="headline" placeholder="e.g. IFS Finance Consultant, 8 years, Apps 10 and Cloud" required></label>'
           '<label>Modules<input type="text" name="modules" placeholder="Finance, Projects, EAM"></label>'
           '<label>IFS versions<select name="versions"><option>IFS Cloud</option><option>IFS Cloud and Apps 10</option><option>Apps 10</option><option>Apps 9 or earlier</option><option>FSM / PSO</option></select></label>'
           '<label>Based in<input type="text" name="location" placeholder="City, country"></label>'
           '<label>Availability<select name="availability"><option>Available now</option><option>Within 1 month</option><option>Within 3 months</option><option>Not available, open to offers</option></select></label>'
           '<label class="full">LinkedIn profile<input type="url" name="linkedin" placeholder="https://www.linkedin.com/in/..." required></label>'
           '<label class="check full"><input type="checkbox" name="consent" required> Show my profile publicly on findifsjobs</label>'
           '<div class="full"><button class="btn" type="submit">Get featured</button></div><p class="msg full" hidden></p></form>')
three = lambda items: '<div class="three">' + "".join(f'<div><h3>{e(a)}</h3><p class="muted small">{e(b)}</p></div>' for a, b in items) + "</div>"
page("freelancers/", "IFS freelancers: get featured free | findifsjobs",
     "IFS contractors and freelancers can add a free profile to findifsjobs so IFS partners and customers can find them. No fee, no commission.",
     hero("For IFS freelancers", "Get featured on findifsjobs, free", "If you contract in IFS, add your profile. Partners and IFS customers looking for project cover will see your modules, availability and how to reach you. No fee, no commission.")
     + f'<div class="wrap">{three([("A profile on the board", "Your headline, modules, IFS versions, location and availability."), ("Direct contact", "Companies reach you through your LinkedIn profile. We do not sit in the middle."), ("Free, and yours to remove", "Ask at any time and your profile comes down.")])}'
     f'{fl_form}<h2 style="font-size:1.1rem">Featured freelancers</h2><ul class="grid">{fl_cells}</ul></div>', active="freelancers/", crumbs=[("Freelancers", None)], priority="0.7")

# ---- news
def nart(n, big=False):
    d = dt.date.fromisoformat(n["date"][:10])
    return (f'<span class="nart t-{slug(n["tag"])}{" big" if big else ""}" aria-hidden="true"><b>{d.day}</b><i>{d.strftime("%b %Y")}</i><em>{e(n["tag"])}</em></span>')


def ncard(n, root, feat=False):
    return (f'<li class="ncard{" feat" if feat else ""}" data-tag="{e(n["tag"])}"><a href="{root}{n["path"]}">{nart(n)}<span class="nbody">'
            f'<span class="tags"><span class="tag v">{e(n["tag"])}</span><span class="tag">{e(n["source"])}</span></span><strong>{e(n["title"])}</strong>'
            f'<span class="sum">{e(n["summary"])}</span><span class="go">Read more <i aria-hidden="true">&rarr;</i></span></span></a></li>')


tags = list(dict.fromkeys(n["tag"] for n in news))
n_pills = '<div class="pills" id="n-pills" role="group" aria-label="Topic"><button type="button" class="pill" data-t="" aria-pressed="true">All</button>' + "".join(f'<button type="button" class="pill" data-t="{e(t)}">{e(t)}</button>' for t in tags) + "</div>"
page("news/", "What's new in the IFS space: releases, partners, customers | findifsjobs",
     "Recent IFS news in one place: IFS Cloud releases, partner mergers and new partnerships, customer wins, company results and events. Each item links to its source.",
     hero("What's new", "What's new in the <em>IFS space</em>", "Product releases, partner moves, customer wins and events. Each story links to its source.", h1cls="mega")
     + f'<div class="wrap">{n_pills}<ul class="ngrid" id="n-list">{"".join(ncard(n, "../", i == 0) for i, n in enumerate(news))}</ul></div>',
     active="news/", crumbs=[("What's new", None)], priority="0.7", lastmod=news[0]["date"] if news else None)
for n in news:
    more = [x for x in news if x is not n][:3]
    page(n["path"], f"{n['title']} | findifsjobs", n["summary"],
         hero(n["tag"], e(n["title"]), f'{nice(n["date"])} · Source: {e(n["source"])}', h1cls="small")
         + f'<div class="wrap"><div class="article"><div class="stack">{nart(n, True)}<div class="prose"><p style="font-size:1.1rem">{e(n["summary"])}</p></div>'
           f'<a class="btn bigbtn" href="{e(n["url"])}" target="_blank" rel="noopener nofollow">Read the full story at {e(n["source"])} &nearr;</a></div>'
           f'<div class="stack"><div class="note"><h3>About this update</h3><p class="small">A short summary by findifsjobs. The full story and all figures are at the source.</p></div></div></div>'
           f'<section class="stack"><h2>More updates</h2><ul class="ngrid">{"".join(ncard(x, "../../") for x in more)}</ul></section></div>',
         active="news/", crumbs=[("What's new", "news/"), (n["title"], None)], priority="0.5", lastmod=n["date"][:10],
         ld=[{"@context": "https://schema.org", "@type": "Article", "headline": n["title"], "datePublished": n["date"][:10], "description": n["summary"],
              "author": {"@type": "Organization", "name": "findifsjobs"}, "isBasedOn": n["url"]}])

# ---- hiring report
def tbl(title, pairs, total=N):
    rows = "".join(f'<tr><th>{e(k)}</th><td class="n">{v}</td><td class="n">{v * 100 // total}%</td></tr>' for k, v in pairs)
    return f'<section class="stack"><h2>{e(title)}</h2><div class="scroll"><table class="facts"><tr><th>&nbsp;</th><td><b>Open roles</b></td><td><b>Share</b></td></tr>{rows}</table></div></section>'


rep_summary = (f"{N} open IFS roles from {employers_n} employers in {len(by_country)} countries. {cloud_n} ({cloud_n * 100 // N}%) name IFS Cloud and {remote_n} ({remote_n * 100 // N}%) are remote or hybrid. "
               f"The busiest country is {by_country[0][0]} with {by_country[0][1]} roles, and the busiest area is {by_area[0][0]} with {by_area[0][1]}.")
block, fl = faq([("How many IFS jobs are open worldwide?", f"{N} on findifsjobs as of {TODAY.strftime('%-d %B %Y')}, from {employers_n} employers."),
                 ("What share of IFS jobs ask for IFS Cloud?", f"{cloud_n * 100 // N}% of listings name IFS Cloud ({cloud_n} of {N})."),
                 ("What share of IFS jobs are remote or hybrid?", f"{remote_n * 100 // N}% ({remote_n} of {N}).")])


def ring(pct):
    c = 2 * 3.14159 * 26
    return (f'<svg class="ring" viewBox="0 0 64 64" width="64" height="64" aria-hidden="true"><circle cx="32" cy="32" r="26" fill="none" stroke="var(--line)" stroke-width="6"/>'
            f'<circle cx="32" cy="32" r="26" fill="none" stroke="var(--brand)" stroke-width="6" stroke-linecap="round" stroke-dasharray="{c * pct / 100:.1f} {c:.1f}" transform="rotate(-90 32 32)"/></svg>')


def bars(key, title, pairs, first=False):
    mx = max(v for _, v in pairs)
    rows = "".join(
        f'<li class="bar" tabindex="0" data-tip="{e(k)}: {plural(v, "open role")}, {v * 100 // N}% of all listings"><span class="bl">{e(k)}</span>'
        f'<span class="bt"><i style="--w:{v * 100 / mx:.1f}%"></i></span><span class="bv">{v}</span><span class="bp">{v * 100 // N}%</span></li>' for k, v in pairs)
    return f'<div class="chart{" in" if first else ""}" id="c-{key}"{"" if first else " hidden"}><ol class="barlist" aria-label="{e(title)}">{rows}</ol></div>'


CHARTS = [("country", "By country", "Open IFS roles by country", by_country[:12]), ("area", "By module", "Open IFS roles by module", by_area),
          ("region", "By region", "Open IFS roles by region", by_region), ("type", "By employer type", "Open IFS roles by employer type", by_type),
          ("employer", "Top employers", "Employers with the most open IFS roles", by_employer)]
cloud_pct, remote_pct = cloud_n * 100 // N, remote_n * 100 // N
tiles = (f'<ul class="tiles"><li><b>{N}</b><span>open IFS roles</span></li><li><b>{employers_n}</b><span>employers hiring</span></li><li><b>{len(by_country)}</b><span>countries</span></li>'
         f'<li class="withring">{ring(cloud_pct)}<div><b>{cloud_pct}%</b><span>name IFS Cloud</span></div></li><li class="withring">{ring(remote_pct)}<div><b>{remote_pct}%</b><span>remote or hybrid</span></div></li></ul>')
takeaways = (f'<ul class="takes"><li><span>Busiest country</span><strong>{e(by_country[0][0])}</strong><em>{by_country[0][1]} open roles</em></li>'
             f'<li><span>Busiest module</span><strong>{e(by_area[0][0])}</strong><em>{by_area[0][1]} open roles</em></li>'
             f'<li><span>Biggest hirer</span><strong>{e(by_employer[0][0])}</strong><em>{by_employer[0][1]} open roles</em></li></ul>')
chart_tabs = '<div class="pills" id="c-tabs" role="group" aria-label="Break the roles down by">' + "".join(
    f'<button type="button" class="pill" data-c="{k}" data-title="{e(t)}" aria-pressed="{"true" if i == 0 else "false"}">{e(lbl)}</button>' for i, (k, lbl, t, _) in enumerate(CHARTS)) + "</div>"
chart_box = (f'<section class="chartbox"><div class="chead"><h2 id="c-title">{e(CHARTS[0][2])}</h2>{chart_tabs}</div>'
             + "".join(bars(k, t, pairs, i == 0) for i, (k, _, t, pairs) in enumerate(CHARTS))
             + '<p class="muted small">Bars show open roles. The percentage is the share of all listings on the board. Hover or tap a bar for detail.</p></section>')
page("ifs-hiring-report/", f"IFS hiring report, {MONTH}: {N} open roles by country and module | findifsjobs",
     f"IFS job market snapshot for {MONTH}: {rep_summary}",
     hero("Hiring report", f"IFS hiring report, <em>{MONTH}</em>", e(rep_summary), h1cls="mega")
     + f'<div class="wrap">{tiles}{takeaways}{chart_box}'
     + f'<details class="tview"><summary>View the data as tables</summary><div class="stack" style="margin-top:18px">'
     + tbl("By region", by_region) + tbl("By country", by_country[:12]) + tbl("By module / area", by_area) + tbl("By employer type", by_type) + tbl("Employers with the most open roles", by_employer)
     + f'</div></details><p class="muted small">Based on every listing on findifsjobs on {TODAY.strftime("%-d %B %Y")}. The board covers public careers pages of IFS, partners, customers and recruiters, so it is a sample of the market, not a census. Free to quote with a link to this page.</p>'
     + f'{block}</div>', active="ifs-hiring-report/", ld=[fl], crumbs=[("Hiring report", None)], priority="0.9")

# ---- hire, about, 404
hire_form = ('<form class="form" data-kind="employer request" data-done="Request received. We will reply by email.">'
             '<label>Company<input type="text" name="company" required></label><label>Work email<input type="email" name="email" required></label>'
             '<label>Role<input type="text" name="role" placeholder="e.g. IFS Cloud Finance Consultant"></label>'
             f'<label>Module / area<select name="area">{options(a for a, _ in by_area)}</select></label>'
             '<label>What you need<select name="need"><option>Contract consultant</option><option>Permanent hire</option><option>Featured listing</option><option>Claim a partner or recruiter profile</option></select></label>'
             '<label>Region<select name="region"><option>EMEA</option><option>Americas</option><option>APAC</option><option>Remote / any</option></select></label>'
             '<div class="full"><button class="btn" type="submit">Send request</button></div><p class="msg full" hidden></p></form>')
page("hire/", "Hire IFS consultants and developers | findifsjobs",
     "Find IFS talent for your project: request a shortlist, feature a role or claim your partner profile on the job board built for the IFS ecosystem.",
     hero("For partners and IFS customers", "Find the right IFS talent for your project", "Tell us the module, the version and the start date. The board reaches people who already work in IFS.")
     + f'<div class="wrap">{three([("Request a shortlist", "Contract or permanent. You describe the role and we match on module, version and region."), ("Feature a role", "Pin your listing to the top of its module and region and include it in the weekly email."), ("List your firm", "Partners and recruiters can claim their profile, add a logo and link their open roles.")])}{hire_form}{mstrip("../")}</div>',
     crumbs=[("Hire IFS talent", None)], priority="0.7")
mk_form = ('<form class="form" data-kind="marketing enquiry" data-done="Got it. We will reply by email within two working days.">'
           '<label>Your name<input type="text" name="name" required></label><label>Work email<input type="email" name="email" required></label>'
           '<label>Company<input type="text" name="company" required></label>'
           '<label>What you need most<select name="need"><option>More qualified leads</option><option>LinkedIn and content</option><option>Event marketing</option><option>Hiring and employer brand</option><option>Not sure yet</option></select></label>'
           '<label class="full">Anything we should know<input type="text" name="notes" placeholder="Markets, industries, timing"></label>'
           '<div class="full"><button class="btn" type="submit">Ask for a plan</button></div><p class="msg full" hidden></p></form>')
mk_faq, mk_ld = faq([("Who is this for?", "IFS implementation, services and technology partners, and firms that sell to IFS customers. Small and mid-sized partners get the most from it."),
                     ("What do you do first?", "A short call, then a written plan: who to target, what to say, which channels, and what it should cost per qualified lead."),
                     ("Does working with you affect the partner rankings?", "No. The Top 10 lists and the directory are editorial and separate from any paid work.")])
page("marketing-for-ifs-partners/", "IFS partner marketing: leads, LinkedIn, events and hiring | findifsjobs",
     "Marketing services built for IFS partners: lead generation by IFS industry, LinkedIn and content, event marketing and employer brand, from the team behind findifsjobs.",
     hero("For IFS partners", "Marketing built for <em>IFS partners</em>", "Most agencies have to learn what IFS Cloud, FSM and EAM are before they can sell them. We already work in this ecosystem every day.")
     + f'<div class="wrap">{three([("Leads by IFS industry", "Campaigns aimed at the buyers IFS partners sell to: manufacturing, energy, aerospace, service and asset-heavy firms. Paid, outbound and landing pages, measured on qualified meetings."), ("LinkedIn and content", "A company page and consultant profiles that IFS buyers notice. Case studies, module explainers and upgrade content that rank in search and in AI answers."), ("Events and hiring", "Before, during and after IFS Connect and industry shows. Plus employer brand and featured roles on this board when you need consultants fast.")])}'
       f'<div class="prose"><h2>How it works</h2><p>You tell us the markets and the IFS industries you want to grow in. We come back with a plan and a fixed monthly scope. No long lock-in.</p></div>{mk_form}{mk_faq}</div>',
     active="marketing-for-ifs-partners/", ld=[mk_ld], crumbs=[("Marketing for IFS partners", None)], priority="0.7")
page("about/", "About findifsjobs and how the data is collected",
     "findifsjobs is an independent job board and directory for the IFS ERP ecosystem. How jobs are collected, how partners are verified and how rankings work.",
     hero("About", "About findifsjobs", "An independent job board and directory for people who work with IFS Cloud, IFS Applications, FSM and EAM.")
     + f'<div class="wrap"><div class="prose"><h2>Where the jobs come from</h2><p>Every day the site reads the public careers pages and job feeds of IFS, IFS partners, companies that run IFS and specialist recruiters. '
     f'It keeps roles that are about IFS and drops the rest. Each listing links to the original posting, where you apply. Listings are removed 30 days after they were last seen.</p>'
     f'<h2>How partners are verified</h2><p>A firm appears in the partner directory only if the IFS partner directory, an IFS announcement or an IFS event listing confirms it. Each profile links to that source.</p>'
     f'<h2>How the rankings work</h2></div>{METHOD}<div class="prose"><h2>Independence</h2><p>findifsjobs is not affiliated with, endorsed by or sponsored by IFS. Rankings are editorial and cannot be bought.</p>'
     f'<h2>Corrections and removals</h2><p>If a listing or profile is yours and you want it changed or removed, use the <a href="../hire/">contact form</a> and say which page.</p></div></div>',
     crumbs=[("About", None)], priority="0.5")
page("404.html", "Page not found | findifsjobs", "That page is not here.",
     hero("404", "That page isn't here", 'The job may have closed. <a href="/">See all open IFS jobs</a>.'), index=False)

IND = {"manufacturing": ("manufacturing", r"manufactur|high-tech|chemicals|food"), "energy-utilities": ("energy and utilities", r"energy|utilit|\boil\b|\bgas\b|mining"),
       "aerospace-defence": ("aerospace and defence", r"a&d|aerospace|defen[cs]e|\bmro\b|maintenix"), "construction-engineering": ("construction and engineering", r"construction|engineering|project-based"),
       "field-service": ("field service", r"\bfsm\b|field service|scheduling optim"), "asset-management": ("asset management (EAM)", r"\beam\b|maintenance|asset|ultimo"),
       "telecom": ("telecom", r"telecom")}
IND_PAGES = {}
for k, (label, rx) in IND.items():
    lst = sorted((p for p in partners if re.search(rx, p["focus"], re.I)), key=lambda p: (-p["score"], p["n"]))
    if len(lst) >= 3:
        IND_PAGES[k] = (label, lst)
ind_links = lambda root: links([(f"IFS partners for {v[0]}", f"ifs-partners/for-{k}/", len(v[1])) for k, v in IND_PAGES.items()], root)
# ---- IFS partners by country
def pcell(p, root):
    return (f'<li class="cell"><div class="head">{logo(p["n"], root, True)}<div class="body"><h3><a href="{root}{p["path"]}" style="color:var(--ink)">{e(p["n"])}</a></h3><p class="meta">{e(p["hq"])}</p></div></div>'
            f'<p class="sum">{e(p["blurb"])}</p><p class="kv"><b>Focus:</b> {e(p["focus"])}</p>'
            + (f'<p class="kv"><b>Size:</b> {e(p["size"])}</p>' if p.get("size") else "")
            + (f'<p class="kv"><b>Open IFS jobs:</b> {len(p["jobs"])}</p>' if p["jobs"] else "")
            + f'<div class="tags">{tags_for(p)}</div>{btns(p, root)}</li>')


for c, lst in PC_PAGES.items():
    the = THE.get(c, c)
    names = ", ".join(p["n"] for p in lst[:5])
    spec = [p["n"] for p in lst if p["kind"] == "S"]
    hiring = [p["n"] for p in lst if p["jobs"]]
    block, fl = faq([(f"Who are the IFS partners in {the}?", f"findifsjobs lists {len(lst)} IFS partners headquartered in {the}: {', '.join(p['n'] for p in lst)}."),
                     (f"Which IFS partners in {the} work only on IFS?", (", ".join(spec) + " focus only on IFS.") if spec else f"The partners listed in {the} work on IFS alongside other software."),
                     (f"Which IFS partners in {the} are hiring?", (", ".join(hiring) + " have open IFS roles on the board today.") if hiring else "None of them has an open IFS role on the board today. Check each firm's careers page."),
                     ("How do you know these firms are IFS partners?", "Each one is confirmed by the IFS partner directory, an IFS announcement or an IFS event listing. The source is linked on every profile.")])
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"IFS partners in {the}", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": p["n"], "url": f"{SITE}/{p['path']}"} for i, p in enumerate(lst)]}
    others = links([(k, f"ifs-partners/{slug(k)}/", len(v)) for k, v in PC_PAGES.items() if k != c], "../../")
    page(f"ifs-partners/{slug(c)}/", f"IFS partners in {the}: {len(lst)} IFS implementation partners ({TODAY.year}) | findifsjobs",
         f"{len(lst)} IFS implementation partners headquartered in {the}: {names}{' and more' if len(lst) > 5 else ''}. Focus, size, tier and open IFS jobs for each.",
         hero("IFS implementation partners", f'IFS partners in <em>{e(the)}</em>', f"{len(lst)} verified IFS partners with their headquarters in {e(the)}. Firms based elsewhere that also deliver here are in the regional Top 10.")
         + f'<div class="wrap"><ul class="grid">{"".join(pcell(p, "../../") for p in lst)}</ul>'
           f'<section class="stack"><h2>IFS partners in other countries</h2>{others}</section>{mstrip("../../")}{block}</div>',
         active="partners/", ld=[il, fl], crumbs=[("Partner directory", "partners/"), (f"IFS partners in {the}", None)], priority="0.8")
page("ifs-partners/", f"IFS partners by country ({TODAY.year}) | findifsjobs",
     f"IFS implementation partners by country: {', '.join(list(PC_PAGES)[:8])} and more. {len(partners)} verified partners in total.",
     hero("IFS implementation partners", "IFS partners <em>by country</em>", f"{len(partners)} verified IFS partners, grouped by where they are headquartered.")
     + f'<div class="wrap">{links([(f"IFS partners in {THE.get(c, c)}", f"ifs-partners/{slug(c)}/", len(v)) for c, v in PC_PAGES.items()], "../")}'
       f'<section class="stack"><h2>By industry</h2>{ind_links("../")}</section><section class="stack"><h2>Regional rankings</h2>{links([(f"Top 10 in {v[0]}", f"top-ifs-partners/{v[2]}/", None) for v in REG.values()], "../")}</section>{mstrip("../")}</div>',
     active="partners/", crumbs=[("Partner directory", "partners/"), ("By country", None)], priority="0.7")

# ---- badges for ranked partners
(OUT / "badges").mkdir(exist_ok=True)
for r, (short, long, rs) in REG.items():
    (OUT / "badges" / f"top-10-ifs-partner-{rs}.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="440" height="164" viewBox="0 0 440 164" role="img" aria-label="Top 10 IFS Partner {TODAY.year}, {e(short)}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#23114F"/><stop offset="1" stop-color="#5B2BBF"/></linearGradient></defs>'
        f'<rect width="440" height="164" rx="22" fill="url(#g)"/><text x="30" y="118" font-family="Arial,Helvetica,sans-serif" font-weight="900" font-size="104" fill="#fff" fill-opacity=".16">10</text>'
        f'<g font-family="Arial,Helvetica,sans-serif" fill="#fff"><text x="170" y="52" font-size="15" font-weight="700" letter-spacing="2.5" fill="#CDB9F7">TOP 10 IFS PARTNER</text>'
        f'<text x="170" y="92" font-size="{30 if len(short) < 15 else 23}" font-weight="800">{e(short)}</text>'
        f'<text x="170" y="124" font-size="15" fill="#CDB9F7">{TODAY.year} ranking · findifsjobs.com</text></g></svg>', encoding="utf-8")

# ---- guides
role_mix = [(ROLE_SHORT[k], ROLE_N[k]) for k in ROLES]
pct = lambda n: f"{round(100 * n / N)}%" if N else "0%"
srcs = lambda items: '<h2>Sources</h2><ul>' + "".join(f'<li>{ext(u, e(t))}</li>' for t, u in items) + "</ul>"
top_areas = ", ".join(f"{a} ({n})" for a, n in by_area[:5])
G1_FAQ = [("Do I need to code to be an IFS consultant?", "No for functional roles, which are about business processes and configuration. Yes for technical roles, where PL/SQL and integration skills are the core of the job."),
          ("Is IFS Cloud experience required?", f"{cloud_n} of the {N} open IFS jobs on findifsjobs name IFS Cloud. Experience on Apps 9 or Apps 10 still counts, especially for upgrade projects."),
          ("Which IFS module should I learn first?", f"Start with the one closest to your background. By open roles today, the busiest areas are {top3a}."),
          ("Can IFS consultants work remotely?", f"Often. {remote_n} of {N} open roles are remote or hybrid.")]
g1_faq, g1_ld = faq(G1_FAQ)
G1 = (f'<div class="prose"><p class="answer"><b>Short answer.</b> Pick a track (functional or technical), build on a business area you already know, get hands-on with IFS Cloud through an employer that runs or implements it, '
      f'then prove it with an IFS Certified Practitioner exam. Most people get in through an IFS partner, the internal team of a company that runs IFS, or IFS itself.</p>'
      f'<h2>1. Choose a track</h2><p><b>Functional consultants</b> map how a business works onto IFS: they run workshops, configure the system, test and train users. They specialise by area, such as finance, supply chain, manufacturing, maintenance, projects, HCM or field service.</p>'
      f'<p><b>Technical consultants and developers</b> build what configuration cannot: customisations, integrations, data migration and reports. The usual toolkit is PL/SQL on Oracle, IFS Developer Studio, projections and client files, REST and OData APIs, IFS Connect, lobbies and workflows.</p>'
      f'<p>Later paths include solution architect and project manager. On the board today: {", ".join(f"{n} {t.lower()} roles" for t, n in role_mix)}.</p>'
      f'<h2>2. Start from what you know</h2><p>IFS employers hire for domain knowledge first. An accountant becomes a finance consultant faster than a generalist does. A maintenance planner already speaks the language of IFS EAM. Use your current field as the entry point and add the system on top.</p>'
      f'<h2>3. Get access to the system</h2><p>You cannot learn IFS well without an environment, and that almost always comes from an employer. Three routes work:</p>'
      f'<ul><li><b>Join an IFS partner</b> in a junior, graduate or support role. Partners train people because they need certified consultants. See the <a href="../../partners/">partner directory</a>.</li>'
      f'<li><b>Become the key user</b> where your company runs IFS. Many consultants started as the super user on their own employer\'s project.</li>'
      f'<li><b>Start in support.</b> Application support exposes you to every module and to real problems. See <a href="../../{ROLES["support"][2] if "support" in ROLES else ""}">IFS support jobs</a>.</li></ul>'
      f'<h2>4. Get certified</h2><p>IFS Academy runs the IFS Certified Practitioner exams, one per product area. It is the clearest signal for someone early in their IFS career. Details are in the <a href="../ifs-certification/">IFS certification guide</a>.</p>'
      f'<h2>5. Apply where the demand is</h2><p>As of {TODAY.strftime("%-d %B %Y")} the board lists {N} open IFS jobs from {employers_n} employers. The countries with the most roles are {top3c}. '
      f'Browse <a href="../../ifs-jobs/functional-consultant/">functional</a> or <a href="../../{ROLES["technical"][2] if "technical" in ROLES else ""}">technical</a> roles, or see <a href="../ifs-skills-in-demand/">which skills are in demand</a>.</p></div>')
G2_FAQ = [("What is IFS certification?", "A credential from IFS Academy that shows you know a product area of IFS Cloud. The main one is IFS Certified Practitioner, issued per area such as Finance, Supply Chain, Manufacturing, Projects, Maintenance or HCM."),
          ("How do you get IFS certified?", "You pass an exam for your product area. The Finance Consultant exam, for example, has 60 questions and a 70% pass mark according to its Credly badge page. Certification is then kept current through annual recertification."),
          ("Who can take IFS Academy training?", "IFS publishes its Academy programme for partners, with registration through the partner learning portal. If you work for an IFS customer or independently, ask IFS Academy what is open to you."),
          ("Is this the same as IFS food safety certification?", "No. IFS Food and other International Featured Standards audits are a separate organisation and have nothing to do with IFS the software company.")]
g2_faq, g2_ld = faq(G2_FAQ)
G2 = (f'<div class="prose"><p class="answer"><b>Short answer.</b> IFS certification is run by IFS Academy. The main credential is <b>IFS Certified Practitioner</b>, awarded per product area of IFS Cloud. You earn it by passing an exam and keep it through annual recertification. Badges are issued through Credly.</p>'
      f'<h2>The certifications</h2><p>Practitioner certifications exist for consultants in Finance, Supply Chain, Manufacturing, Projects, Maintenance and Human Capital Management, plus a Presales Consultant track. Each one attests to an in-depth understanding of that part of IFS Cloud and a good understanding of the overall solution.</p>'
      f'<p>IFS describes its product-based pathway as moving from Practitioner to Expert, supported by digital learning paths, specialist workshops and classroom training for functional and technical roles.</p>'
      f'<h2>The exam</h2><p>Using Finance Consultant (IFS Cloud) as the example: 60 questions, 70% to pass. It covers General Ledger, Accounts Receivable and Accounts Payable. Holders recertify each year as new IFS Cloud releases change the product.</p>'
      f'<h2>How to get access</h2><p>IFS Academy for Partners is aimed at IFS partner staff, who register through the partner learning portal. That is one reason joining a partner is the common way in. If you work at an IFS customer or as a freelancer, contact IFS Academy and ask which courses and exams are open to you.</p>'
      f'<h2>Is it worth it?</h2><p>It helps most early on, when you have little project history to point to, and when moving from Apps 9 or 10 to IFS Cloud. For senior roles, employers weigh completed implementations more heavily than badges. {cloud_n} of the {N} roles on the board today name IFS Cloud, so Cloud-specific proof is useful either way.</p>'
      f'<h2>Not the food standard</h2><p>Searches for "IFS certification" also return IFS Food and other International Featured Standards audits. Those are unrelated to IFS, the enterprise software company.</p>'
      + srcs([("IFS Academy for Partners (ifs.com)", "https://www.ifs.com/en/partners/academy"),
              ("IFS Certified Practitioner, Finance Consultant (Credly)", "https://www.credly.com/org/ifs/badge/ifs-certified-practitioner-financials-consultant-ifs-cloud"),
              ("IFS badges on Credly", "https://www.credly.com/org/ifs")]) + "</div>")
G3_FAQ = [("Which IFS skills are most in demand?", f"By open roles on findifsjobs in {MONTH}, the busiest areas are {top_areas}."),
          ("How many IFS jobs ask for IFS Cloud?", f"{cloud_n} of {N} ({pct(cloud_n)}) name IFS Cloud."),
          ("Are functional or technical IFS skills wanted more?", "By job title: " + ", ".join(f"{t.lower()} {n}" for t, n in role_mix) + "."),
          ("Where is demand for IFS skills highest?", f"The countries with the most open roles are {top3c}.")]
g3_faq, g3_ld = faq(G3_FAQ)
G3 = (f'<div class="prose"><p class="answer"><b>Short answer.</b> In {MONTH}, the IFS skills employers ask for most are {top_areas}. {cloud_n} of {N} open roles ({pct(cloud_n)}) name IFS Cloud. The figures come from the {N} live jobs on this board and update daily.</p>'
      f'<h2>Demand by module</h2></div>{tbl("Open roles by module or area", by_area)}<div class="prose"><h2>Demand by role</h2><p>Counted from job titles. A role can fall into more than one group, and some fall into none.</p></div>'
      f'{tbl("Open roles by type", role_mix)}<div class="prose"><h2>Where the demand is</h2></div>{tbl("Open roles by country", by_country[:10])}'
      f'<div class="prose"><h2>What this means for you</h2><ul><li><b>IFS Cloud is the baseline.</b> If your experience is on Apps 9 or 10, get on an upgrade project or take a Cloud certification.</li>'
      f'<li><b>Depth in one module beats a little of everything.</b> Adverts are written by module.</li>'
      f'<li><b>Remote is normal.</b> {remote_n} of {N} roles ({pct(remote_n)}) are remote or hybrid.</li></ul>'
      f'<p>The full breakdown, with charts, is in the <a href="../../ifs-hiring-report/">IFS hiring report</a>.</p></div>')
GUIDES = [("how-to-become-an-ifs-consultant", "How to become an IFS consultant", "The routes into IFS consulting: functional and technical tracks, how to get system access, certification and where the jobs are.", G1, g1_faq, g1_ld),
          ("ifs-certification", "IFS certification explained", "What IFS Certified Practitioner is, the tracks, the exam, who can access IFS Academy and whether it is worth it.", G2, g2_faq, g2_ld),
          ("ifs-skills-in-demand", f"IFS skills in demand ({MONTH})", f"Which IFS modules, roles and countries have the most open jobs in {MONTH}, from {N} live listings.", G3, g3_faq, g3_ld)]
# ---- question pages (answer first, detail after)
def qa(gs, gt, gd, answer, body, faqs, sources=None):
    f, l = faq(faqs)
    return (gs, gt, gd, f'<div class="prose"><p class="answer"><b>Short answer.</b> {answer}</p>{body}{srcs(sources) if sources else ""}</div>', f, l)


jl = lambda k, t: f'<a href="../../{ROLES[k][2]}">{t}</a>' if k in ROLES else t
hiring_partners = sorted((p for p in partners if p["jobs"]), key=lambda p: -len(p["jobs"]))
hp_txt = ", ".join(f"{p['n']} ({len(p['jobs'])})" for p in hiring_partners[:6]) or "none today"
junior = [j for j in jobs if j.get("seniority") == "Junior" or re.search(r"junior|graduate|trainee|intern\b|entry", j["title"], re.I)]
contract_n = sum(j.get("contract_type") == "Contract" for j in jobs)
perm_n = sum(j.get("contract_type") == "Permanent" for j in jobs)
tiers = Counter(p.get("tier") for p in partners if p.get("tier"))
IFS_IND = "aerospace and defence, energy, utilities and resources, construction and engineering, manufacturing, service industries and telecommunications"
GUIDES += [
    qa("what-does-an-ifs-functional-consultant-do", "What does an IFS functional consultant do?", "The day-to-day work of an IFS functional consultant, the skills needed and how many roles are open.",
       f"An IFS functional consultant turns how a business works into a configured IFS system. They run process workshops, set up the modules, test with users, train them and support go-live. They specialise by area, such as finance, supply chain, manufacturing, maintenance or projects, and they do not usually write code.",
       f'<h2>What the work looks like</h2><ul><li><b>Discover.</b> Workshops to map current processes and agree how they will run in IFS.</li><li><b>Configure.</b> Set up basic data, company structures, flows and permissions in the module.</li>'
       f'<li><b>Test and migrate.</b> Write test scripts, support user acceptance testing and check migrated data.</li><li><b>Train and go live.</b> Train key users, then stay close through cutover and the first weeks of live running.</li></ul>'
       f'<h2>Skills employers ask for</h2><p>Depth in one business area matters most. After that: experience of at least one full implementation, IFS Cloud knowledge, and the ability to run a workshop with senior people. Technical consultants handle code and integrations, so functional consultants need to brief them well, not replace them.</p>'
       f'<h2>Demand right now</h2><p>The board lists {ROLE_N.get("functional", 0)} {jl("functional", "IFS functional consultant jobs")} out of {N} open roles. The busiest areas are {top3a}.</p>',
       [("Is an IFS functional consultant a technical role?", "No. It is a business-process and configuration role. Coding, integrations and data migration tooling sit with technical consultants."),
        ("What background do IFS functional consultants have?", "Most come from the business area they now consult in: accountants into finance, planners into supply chain or manufacturing, maintenance engineers into EAM.")]),
    qa("what-does-an-ifs-technical-consultant-do", "What does an IFS technical consultant do?", "What IFS technical consultants and developers build, the tools they use and current demand.",
       "An IFS technical consultant builds what configuration alone cannot: customisations, integrations with other systems, data migration, reports and workflows. The core skills are PL/SQL on Oracle, the IFS development tooling and API-based integration.",
       f'<h2>What they build</h2><ul><li><b>Customisations and extensions</b> to the standard application.</li><li><b>Integrations</b> with other systems through REST and OData APIs and IFS Connect.</li>'
       f'<li><b>Data migration</b> from legacy systems, including cleansing and load tooling.</li><li><b>Reports, lobbies and workflows</b> that users work with every day.</li></ul>'
       f'<h2>What changed with IFS Cloud</h2><p>IFS Cloud is updated on a regular release cycle, so heavy modification of core code has become a liability. Technical work has moved toward configuration, extensions and API integrations that survive updates.</p>'
       f'<h2>Demand right now</h2><p>There are {ROLE_N.get("technical", 0)} {jl("technical", "IFS technical consultant and developer jobs")} on the board, out of {N} open roles.</p>',
       [("Which programming language do IFS developers use?", "PL/SQL is the core language, on an Oracle database. Integration and front-end work add API and web skills."),
        ("Can a technical consultant move into solution architecture?", f"Yes, it is a common path. There are {ROLE_N.get('architect', 0)} IFS solution architect roles open on the board today.")]),
    qa("ifs-cloud-vs-ifs-applications-10", "IFS Cloud vs IFS Applications 10: what changes for consultants", "How IFS Cloud differs from Apps 10 for people who implement and support it, and what to learn.",
       "IFS Cloud replaced IFS Applications 10 as the current product. For consultants the big changes are a single browser-based user experience, two feature releases a year (named like 25R1 and 25R2) with service updates in between, and a strong push away from core modifications toward configuration and API-based extensions.",
       f'<h2>What is different</h2><ul><li><b>One web client.</b> The older IFS Enterprise Explorer desktop client is gone. Everything runs in the browser.</li>'
       f'<li><b>Release cadence.</b> Two releases a year plus regular service updates, so customers stay current continuously instead of doing a big upgrade every few years.</li>'
       f'<li><b>Fewer modifications.</b> Staying on the update path means keeping the core clean and using configuration, extensions and APIs.</li>'
       f'<li><b>Broader scope.</b> ERP, EAM and service management sit on one platform, with AI features added release by release.</li></ul>'
       f'<h2>What it means for your career</h2><p>{cloud_n} of {N} open roles on this board ({pct(cloud_n)}) name IFS Cloud. Apps 9 and 10 experience is still valuable, because many customers are mid-upgrade and need people who know both sides. The quickest way to stay marketable is to get onto an upgrade project.</p>',
       [("Is IFS Applications 10 experience still useful?", "Yes. Upgrade projects need people who understand the old system and the new one. Pair it with IFS Cloud exposure as soon as you can."),
        ("How often is IFS Cloud released?", "Twice a year, with releases named by year and half, such as 25R1 and 25R2, plus service updates between them.")],
       [("What's new in IFS Cloud 25R2 (ifs.com)", "https://www.ifs.com/en/assets/cloud/what-new-in-ifs-cloud-25r2"), ("Table of IFS Cloud releases (IFS Community)", "https://community.ifs.com/upgrades-updates-81/table-of-ifs-cloud-releases-by-month-64959")]),
    qa("what-is-ifs-cloud", "What is IFS Cloud?", "A plain explanation of IFS Cloud: what it covers, who uses it and what it means for jobs.",
       f"IFS Cloud is the current enterprise software platform from IFS. It combines ERP, enterprise asset management (EAM) and service management in one product, for companies in {IFS_IND}. Despite the name, it can run in IFS's cloud or in a customer's own environment.",
       f'<h2>What it covers</h2><ul><li><b>ERP:</b> finance, supply chain, manufacturing, projects and HCM.</li><li><b>EAM:</b> maintaining plants, fleets, networks and other physical assets.</li>'
       f'<li><b>Service management:</b> field service, contracts and scheduling.</li></ul>'
       f'<h2>Who works with it</h2><p>IFS itself, its implementation partners, the customers who run it and specialist recruiters. This board lists {N} open roles from {employers_n} employers across those four groups.</p>'
       f'<h2>Where to go next</h2><p>See the <a href="../ifs-cloud-vs-ifs-applications-10/">differences from Apps 10</a>, or browse <a href="../../ifs-jobs/ifs-cloud/">IFS Cloud jobs</a>.</p>',
       [("Is IFS Cloud only available in the cloud?", "No. It can be hosted by IFS or deployed in the customer's own environment."),
        ("Which industries use IFS Cloud?", f"IFS focuses on {IFS_IND}.")]),
    qa("what-is-ifs-eam", "What is IFS EAM?", "What IFS enterprise asset management does, who uses it and the jobs it creates.",
       "IFS EAM is the enterprise asset management part of IFS Cloud. Companies use it to plan and carry out maintenance on physical assets such as plants, fleets, power networks and aircraft, and to manage spare parts, work orders and asset history.",
       f'<h2>What it does</h2><ul><li>Preventive and corrective maintenance planning</li><li>Work orders and mobile work execution</li><li>Spare parts and inventory for maintenance</li><li>Asset structures, history and performance</li></ul>'
       f'<h2>Who uses it</h2><p>Asset-heavy organisations: energy and utilities, manufacturing, mining, transport and defence. Aviation maintenance has its own IFS products alongside it.</p>'
       f'<h2>Jobs</h2><p>EAM consultants usually come from maintenance or reliability engineering. ' + (f'There are {areas["EAM / Maintenance"]} <a href="../../{apath("EAM / Maintenance")}">IFS EAM and maintenance jobs</a> on the board today.' if "EAM / Maintenance" in areas else "EAM roles appear regularly on the board.") + "</p>",
       [("Is IFS EAM a separate product from IFS Cloud?", "It is a capability within IFS Cloud. Customers can run EAM alone or together with ERP and service management."),
        ("What background suits an IFS EAM consultant?", "Maintenance planning, reliability engineering or asset management, plus experience of a maintenance system.")]),
    qa("what-is-ifs-fsm", "What is IFS FSM?", "What IFS Field Service Management is, how it relates to IFS Cloud and PSO, and the jobs around it.",
       "IFS FSM stands for IFS Field Service Management. It manages the work of field technicians: service requests, contracts and warranties, parts, mobile work execution and scheduling. IFS built its field service business on the 2012 acquisition of Metrix, and service management is now also part of IFS Cloud.",
       f'<h2>What it does</h2><ul><li>Service requests, contracts, warranties and SLAs</li><li>Mobile app for technicians, including offline work</li><li>Parts, returns and repair</li><li>Scheduling and dispatch, often with <a href="../what-is-ifs-pso/">IFS PSO</a></li></ul>'
       f'<h2>FSM and IFS Cloud</h2><p>FSM exists as a product in its own right and many customers still run it. New service management projects are increasingly delivered on IFS Cloud. Consultants with FSM experience are wanted for both.</p>'
       f'<h2>Jobs</h2><p>' + (f'There are {areas["Field Service"]} <a href="../../{apath("Field Service")}">IFS field service jobs</a> on the board today.' if "Field Service" in areas else "Field service roles appear regularly on the board.") + "</p>",
       [("Is IFS FSM the same as IFS Cloud?", "No. FSM is a standalone field service product. IFS Cloud includes its own service management capability, and new projects increasingly use that."),
        ("What is the difference between FSM and PSO?", "FSM manages service work end to end. PSO is the optimisation engine that decides which technician does which job and when.")],
       [("IFS acquires Metrix (Constellation Research)", "https://www.constellationr.com/research/blog/news-analysis-ifs-acquires-metrix-boost-mobility-and-service-management")]),
    qa("what-is-ifs-pso", "What is IFS PSO?", "What IFS Planning and Scheduling Optimization does and where PSO skills are used.",
       "IFS PSO stands for Planning and Scheduling Optimization. It is the engine that automatically assigns jobs to field technicians and resources, re-planning in real time as jobs overrun, traffic changes or urgent work arrives. It works with IFS FSM and IFS Cloud and can also schedule for other systems.",
       f'<h2>What it does</h2><ul><li>Builds and continuously re-optimises the schedule against travel, skills, parts and SLAs</li><li>Longer-range capacity and shift planning</li><li>What-if modelling of demand and workforce changes</li></ul>'
       f'<h2>Why it is a specialism</h2><p>Tuning PSO is closer to operations research than to ERP configuration. Good PSO consultants understand the business rules behind a schedule and can prove the gain in travel time and jobs per day. They are scarce, which keeps demand steady.</p>'
       f'<p>Related: <a href="../what-is-ifs-fsm/">What is IFS FSM?</a></p>',
       [("Can PSO be used without IFS FSM?", "Yes. It is used with IFS Cloud and FSM, and it can also be integrated with other service systems."),
        ("What skills does an IFS PSO consultant need?", "Field service process knowledge, comfort with data and optimisation rules, and integration awareness.")]),
    qa("ifs-vs-sap-consultant-career", "IFS vs SAP: which is the better consultant career?", "A fair comparison of building a consulting career in IFS versus SAP: market size, competition and where each fits.",
       "SAP is the far larger market, with more jobs and more consultants competing for them. IFS is a smaller, focused ecosystem where specialists are scarcer and easier to stand out among. Neither is better in general. SAP suits people who want the widest choice of employers. IFS suits people who want depth in asset-heavy and service-heavy industries.",
       f'<h2>How they differ</h2><ul><li><b>Market size.</b> SAP has many times more customers, partners and roles worldwide.</li><li><b>Competition.</b> The SAP talent pool is also much larger. In IFS, a consultant with two or three implementations is already well known to recruiters.</li>'
       f'<li><b>Industries.</b> IFS concentrates on {IFS_IND}. SAP spans almost every sector.</li><li><b>Community.</b> The IFS world is small. Reputation travels fast, in both directions.</li></ul>'
       f'<h2>How to choose</h2><p>Start from your industry background and the employers near you. If you already work in maintenance, field service, project-based manufacturing or defence, IFS experience compounds quickly. If you want maximum optionality across sectors, SAP offers more doors.</p>'
       f'<p>For a sense of IFS demand: {N} open roles from {employers_n} employers on this board today, in {len(by_country)} countries.</p>',
       [("Is it easy to move from SAP to IFS?", "Process knowledge transfers well, especially in finance, supply chain and maintenance. You still need hands-on IFS project time before employers treat you as an IFS consultant."),
        ("Is IFS a niche skill?", "It is narrower than SAP or Oracle, and that is the appeal: fewer specialists, and customers concentrated in industries with long-running programmes.")]),
    qa("which-ifs-partners-are-hiring", f"Which IFS partners are hiring? ({MONTH})", f"The IFS partners with open IFS roles right now, counted from live listings in {MONTH}.",
       f"As of {TODAY.strftime('%-d %B %Y')}, {len(hiring_partners)} IFS partners have open IFS roles on findifsjobs. The ones with the most are {hp_txt}.",
       '<h2>Partners with open roles</h2><ul>' + "".join(f'<li><a href="../../{p["path"]}">{e(p["n"])}</a>: {plural(len(p["jobs"]), "open role")} · {e(p["hq"])}</li>' for p in hiring_partners) + "</ul>"
       f'<p>The list updates daily. It covers partners whose careers pages the board can read; others are linked from the <a href="../../partners/">partner directory</a>.</p>',
       [("How often is this list updated?", "Every day, from the partners' own careers pages and job feeds."),
        ("Do all IFS partners appear here?", f"No. The directory lists {len(partners)} verified partners, and {len(hiring_partners)} of them have roles the board can currently read.")]),
    qa("entry-level-ifs-jobs", "Entry-level IFS jobs: how to get a first role", "Where junior and graduate IFS roles come from, how many are open and how to land one.",
       f"Entry-level IFS jobs are rare in adverts: {len(junior)} of {N} open roles on this board are junior, graduate or trainee positions. Most people get their first IFS role through an IFS partner's graduate intake, a support desk, or by becoming the key user on their own employer's IFS project.",
       ('<h2>Open junior roles today</h2><ul>' + "".join(f'<li><a href="../../{j["path"]}">{e(j["title"])}</a> at {e(j["company"])}</li>' for j in junior[:10]) + "</ul>" if junior else "")
       + f'<h2>Three ways in</h2><ul><li><b>Partner graduate and junior programmes.</b> Check the careers pages in the <a href="../../partners/">partner directory</a>, including firms with no advert up today.</li>'
       f'<li><b>Support roles.</b> Application support is the most common first job. See {jl("support", "IFS support jobs")}.</li><li><b>Key user at an IFS customer.</b> Volunteer for the project team where you work.</li></ul>'
       f'<p>The full route is in <a href="../how-to-become-an-ifs-consultant/">How to become an IFS consultant</a>.</p>',
       [("Can I get an IFS job with no experience?", "Yes, but usually not through an advert that says IFS consultant. Look at partner junior intakes, support roles and internal project roles at companies that run IFS."),
        ("Which IFS partners hire juniors?", "It changes month to month. Check the careers page on each partner profile, especially IFS-only specialists that are growing.")]),
    qa("ifs-contract-vs-permanent", "IFS contract vs permanent jobs: how the market splits", "How many IFS roles are contract versus permanent, and how to decide between them.",
       f"Of the {N} open IFS roles on this board, {perm_n} are permanent and {contract_n} are contract, with the rest not stating a type. Contract work is concentrated at recruiters and on upgrade and go-live phases. Permanent roles dominate at partners and at IFS itself.",
       f'<h2>Where each comes from</h2><ul><li><b>Permanent:</b> IFS, partners building long-term teams, and customers staffing an internal competence centre.</li>'
       f'<li><b>Contract:</b> specialist recruiters filling project peaks, such as migration, testing, cutover and hypercare.</li></ul>'
       f'<h2>How to choose</h2><p>Go permanent to build depth, get certified and work across several implementations. Go contract once you have a module people ask for by name and enough of a network to fill gaps between projects.</p>'
       f'<p>Browse <a href="../../ifs-jobs/contract/">IFS contract jobs</a>, the <a href="../../ifs-recruiters/">IFS recruiters</a> list, or get <a href="../../freelancers/">featured as a freelancer</a>.</p>',
       [("When should an IFS consultant go freelance?", "Usually after several full implementations in one area, when partners and recruiters already contact you directly."),
        ("Who posts IFS contract roles?", "Mostly specialist recruiters, plus partners that need extra capacity for a project phase.")]),
    qa("what-industries-use-ifs", "What industries use IFS?", "The industries IFS focuses on and what that means for consultants and partners.",
       f"IFS focuses on six industry groups: {IFS_IND}. What they share is complex physical assets, projects or field service, which is where IFS is strongest.",
       f'<h2>Why these industries</h2><p>IFS combines ERP with asset management and service management. That fits companies that build, maintain or service complex things: aircraft, power networks, factories, infrastructure and equipment in the field.</p>'
       f'<h2>What it means for careers</h2><p>Industry knowledge is a real asset in IFS. A consultant who understands defence maintenance or utility field work is harder to replace than a generalist. Partners specialise the same way; see <a href="../../ifs-partners/">IFS partners by industry and country</a>.</p>',
       [("Is IFS used in retail or banking?", "Rarely. IFS concentrates on asset-heavy, project-based and service-heavy industries."),
        ("Which IFS industry has the most partners?", "By the focus areas listed in the findifsjobs directory, energy, construction and manufacturing have the most partners.")]),
    qa("what-is-an-ifs-partner", "What is an IFS partner?", "What IFS partners do, the tiers you will see and how to choose one to work for or hire.",
       f"An IFS partner is an independent company authorised by IFS to sell, implement, extend or support IFS software. findifsjobs lists {len(partners)} verified partners, from IFS-only specialists to global consulting firms.",
       f'<h2>Types of partner</h2><ul><li><b>IFS specialists</b> that work only on IFS ({sum(p["kind"] == "S" for p in partners)} in the directory).</li><li><b>ERP boutiques</b> that cover IFS alongside other systems ({sum(p["kind"] == "B" for p in partners)}).</li>'
       f'<li><b>Global firms</b> with an IFS practice ({sum(p["kind"] == "G" for p in partners)}).</li></ul>'
       f'<h2>Tiers</h2><p>IFS groups partners into tiers. In the directory, {", ".join(f"{n} are {t}" for t, n in tiers.most_common())}; the rest have no tier published.</p>'
       f'<h2>Choosing one</h2><p>To work for: look at how many live projects they run in your module and whether they train and certify people. To hire: ask for references in your industry and on your IFS version. Start with the <a href="../../top-ifs-partners/">regional Top 10</a> or the <a href="../../partners/">full directory</a>.</p>',
       [("How do I check a company is really an IFS partner?", "Look for it in the IFS partner directory or an IFS announcement. Every profile on findifsjobs links to that source."),
        ("Are bigger IFS partners better?", "Not necessarily. Specialists often have deeper IFS teams in a given module or industry than a global firm's local practice.")]),
    qa("how-to-hire-an-ifs-consultant", "How to hire an IFS consultant", "A practical guide for companies hiring IFS consultants: where to find them, what to specify and how to assess them.",
       "Specify the module, the IFS version and the project phase before you search. Then use three channels at once: an IFS partner for a team, a specialist IFS recruiter for individual contractors or permanent hires, and direct reach to freelancers. Generic job boards rarely reach IFS people.",
       f'<h2>1. Write the brief</h2><ul><li>Module and industry (for example, IFS Cloud Finance in a project-based manufacturer)</li><li>Version: IFS Cloud, Apps 10 or earlier</li><li>Phase: design, build, migration, testing, cutover or support</li><li>Contract or permanent, location and start date</li></ul>'
       f'<h2>2. Pick the channel</h2><ul><li><b>Partners</b> for whole workstreams: <a href="../../partners/">partner directory</a>.</li><li><b>Recruiters</b> for named individuals: <a href="../../ifs-recruiters/">IFS recruiters</a>.</li>'
       f'<li><b>Direct:</b> <a href="../../hire/">post or request a shortlist</a> on this board.</li></ul>'
       f'<h2>3. Assess</h2><p>Ask for the last two implementations, their exact role and the go-live outcome. Have your own lead walk through one real scenario from your business. References from the customer side tell you more than certificates.</p>',
       [("How long does it take to hire an IFS consultant?", "It depends on the module and how scarce it is. Scarce specialisms such as scheduling optimisation or aviation maintenance take longer than finance or supply chain."),
        ("Should I hire a contractor or use a partner?", "Use a partner when you need a team and accountability for an outcome. Use contractors to fill specific gaps in a team you are managing yourself.")]),
]

for gs, gt, gd, gb, gf, gl in GUIDES:
    more = links([(t, f"guides/{x}/", None) for x, t, *_ in GUIDES if x != gs] + [("All open IFS jobs", "", None)], "../../")
    page(f"guides/{gs}/", f"{gt} | findifsjobs", gd,
         hero("IFS career guide", e(gt), f'{e(gd)} Updated {TODAY.strftime("%-d %B %Y")}.', h1cls="small")
         + f'<div class="wrap"><div class="stack">{gb}{gf}<section class="stack"><h2>Keep reading</h2>{more}</section></div></div>',
         ld=[gl, {"@context": "https://schema.org", "@type": "Article", "headline": gt, "description": gd, "dateModified": TODAY.isoformat(), "datePublished": "2026-10-10",
                  "author": {"@type": "Organization", "name": "findifsjobs"}, "publisher": {"@type": "Organization", "name": "findifsjobs"}}],
         active="-", crumbs=[("Guides", "guides/"), (gt, None)], priority="0.8")
page("guides/", "IFS career guides: getting in, certification and skills | findifsjobs",
     "Plain guides for people building a career in IFS: how to become an IFS consultant, how IFS certification works and which IFS skills are in demand.",
     hero("Guides", "IFS career <em>guides</em>", "Short, practical answers for people working in or moving into IFS.")
     + '<div class="wrap"><ul class="grid">' + "".join(f'<li class="cell"><h3><a href="{gs}/" style="color:var(--ink)">{e(gt)}</a></h3><p class="sum">{e(gd)}</p><div class="btns"><a class="pbtn primary" href="{gs}/">Read the guide<span aria-hidden="true">&rarr;</span></a></div></li>' for gs, gt, gd, *_ in GUIDES) + "</ul></div>",
     active="-", crumbs=[("Guides", None)], priority="0.7")

# ---- IFS partners by industry
for k, (label, lst) in IND_PAGES.items():
    names = ", ".join(p["n"] for p in lst[:5])
    block, fl = faq([(f"Which IFS partners specialise in {label}?", f"findifsjobs lists {len(lst)} IFS partners with a stated focus on {label}: {', '.join(p['n'] for p in lst)}."),
                     ("How is this list ordered?", "By the findifsjobs emerging-first score, which favours IFS specialists, recent growth, awards and tier. It is an editorial order, not an IFS one."),
                     ("How do you know their focus?", "From the IFS partner directory, IFS announcements and each firm's own site. The source is linked on every profile.")])
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"IFS partners for {label}", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": p["n"], "url": f"{SITE}/{p['path']}"} for i, p in enumerate(lst)]}
    page(f"ifs-partners/for-{k}/", f"Top IFS partners for {label} ({TODAY.year}): {len(lst)} firms | findifsjobs",
         f"{len(lst)} IFS implementation partners with a focus on {label}: {names}{' and more' if len(lst) > 5 else ''}. Size, tier, focus and open jobs for each.",
         hero("IFS partners by industry", f'IFS partners for <em>{e(label)}</em>', f"{len(lst)} verified IFS partners that name {e(label)} as a focus, emerging firms first.")
         + f'<div class="wrap"><ul class="grid">{"".join(pcell(p, "../../") for p in lst)}</ul>'
           f'<section class="stack"><h2>Other industries</h2>{links([(f"IFS partners for {v[0]}", f"ifs-partners/for-{x}/", len(v[1])) for x, v in IND_PAGES.items() if x != k], "../../")}</section>'
           f'{mstrip("../../")}{block}</div>',
         active="partners/", ld=[il, fl], crumbs=[("Partner directory", "partners/"), (f"For {label}", None)], priority="0.8")

# ---- monthly hiring index (a frozen snapshot per month, so the numbers can be cited)
HI = HERE / "hiring_index"
HI.mkdir(exist_ok=True)
snap = {"month": TODAY.strftime("%Y-%m"), "as_of": TODAY.isoformat(), "roles": N, "employers": employers_n, "countries": len(by_country), "cloud": cloud_n, "remote": remote_n,
        "by_area": by_area[:10], "by_country": by_country[:10], "by_employer": by_employer[:10], "by_type": by_type, "role_mix": role_mix}
(HI / f"{snap['month']}.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
snaps = sorted((json.loads(f.read_text()) for f in HI.glob("*.json")), key=lambda s: s["month"], reverse=True)
mname = lambda m: dt.date(int(m[:4]), int(m[5:7]), 1).strftime("%B %Y")
for i, s in enumerate(snaps):
    prev = snaps[i + 1] if i + 1 < len(snaps) else None
    sp = lambda n: f"{round(100 * n / s['roles'])}%"
    delta = (f" That is {'up' if s['roles'] >= prev['roles'] else 'down'} from {prev['roles']} in {mname(prev['month'])}." if prev else "")
    find = [f"{s['roles']} open IFS roles from {s['employers']} employers in {s['countries']} countries.{delta}",
            f"{s['cloud']} roles ({sp(s['cloud'])}) name IFS Cloud.", f"{s['remote']} roles ({sp(s['remote'])}) are remote or hybrid.",
            f"The busiest country is {s['by_country'][0][0]} with {s['by_country'][0][1]} roles, followed by {s['by_country'][1][0]} ({s['by_country'][1][1]}).",
            f"The most requested area is {s['by_area'][0][0]} ({s['by_area'][0][1]}), then {s['by_area'][1][0]} ({s['by_area'][1][1]}).",
            f"The employer with the most open roles is {s['by_employer'][0][0]} ({s['by_employer'][0][1]})."]
    mn = mname(s["month"])
    if i == 0:
        find0 = find[0]
    live = s["month"] == snap["month"]
    block, fl = faq([(f"How many IFS jobs were open in {mn}?", find[0]), (f"Which IFS skills were most in demand in {mn}?", find[4]), (f"Which country had the most IFS jobs in {mn}?", find[3]),
                     ("Where do the numbers come from?", "From the live listings on findifsjobs, which are read daily from the public careers pages of IFS, IFS partners, IFS customers and specialist recruiters.")])
    t = lambda title, pairs: tbl(title, [tuple(x) for x in pairs], s["roles"])
    page(f"ifs-hiring-index/{s['month']}/", f"IFS Hiring Index, {mn}: {s['roles']} open IFS jobs | findifsjobs",
         f"IFS Hiring Index for {mn}: {find[0]} {find[1]} {find[4]}",
         hero("IFS Hiring Index", f'IFS Hiring Index: <em>{mn}</em>', f'{"Live figures, updated daily until the month closes" if live else "Final figures for the month"}. Data as of {nice(s["as_of"])}.', h1cls="mega")
         + f'<div class="wrap"><div class="prose"><p class="answer"><b>Key findings.</b> {" ".join(find)}</p><p class="muted small">Free to quote with a link to this page. Source: findifsjobs IFS Hiring Index, {mn}.</p></div>'
           f'{t("Open roles by module or area", s["by_area"])}{t("Open roles by country", s["by_country"])}{t("Employers with the most open roles", s["by_employer"])}{t("Open roles by employer type", s["by_type"])}'
           f'<section class="stack"><h2>Other months</h2>{links([(mname(x["month"]), f"ifs-hiring-index/{x["month"]}/", x["roles"]) for x in snaps if x is not s] + [("Interactive hiring report", "ifs-hiring-report/", None)], "../../")}</section>{block}</div>',
         active="ifs-hiring-report/", crumbs=[("Hiring Index", "ifs-hiring-index/"), (mn, None)], priority="0.8", lastmod=s["as_of"],
         ld=[fl, {"@context": "https://schema.org", "@type": "Dataset", "name": f"IFS Hiring Index, {mn}", "description": " ".join(find[:3]), "url": f"{SITE}/ifs-hiring-index/{s['month']}/",
                  "dateModified": s["as_of"], "creator": {"@type": "Organization", "name": "findifsjobs", "url": SITE + "/"}, "license": "https://creativecommons.org/licenses/by/4.0/"}])
page("ifs-hiring-index/", "IFS Hiring Index: monthly IFS job market figures | findifsjobs",
     "A monthly count of the IFS job market: open roles, IFS Cloud share, top modules, countries and employers. Free to quote with a link.",
     hero("IFS Hiring Index", "The IFS <em>Hiring Index</em>", "One page of figures per month on who is hiring for IFS, where and for what. Free to quote with a link.", h1cls="mega")
     + '<div class="wrap"><ul class="grid">' + "".join(f'<li class="cell"><h3><a href="{s["month"]}/" style="color:var(--ink)">{mname(s["month"])}</a></h3><p class="sum">{s["roles"]} open roles · {s["employers"]} employers · {round(100 * s["cloud"] / s["roles"])}% name IFS Cloud</p>'
                                                         f'<div class="btns"><a class="pbtn primary" href="{s["month"]}/">See the figures<span aria-hidden="true">&rarr;</span></a></div></li>' for s in snaps) + "</ul></div>",
     active="ifs-hiring-report/", crumbs=[("Hiring Index", None)], priority="0.8")

# ---- sitemap, robots, llms.txt
(OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
    f"<url><loc>{SITE}/{p}</loc><lastmod>{m}</lastmod><priority>{pr}</priority></url>\n" for p, m, pr in PAGES) + "</urlset>\n", encoding="utf-8")
BOTS = ["Googlebot", "Bingbot", "GPTBot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "ClaudeBot", "Claude-SearchBot", "Google-Extended", "Applebot-Extended", "CCBot"]
(OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n\n" + "".join(f"User-agent: {b}\nAllow: /\n\n" for b in BOTS) + f"Sitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
if CFG.get("indexnow_key"):
    (OUT / f"{CFG['indexnow_key']}.txt").write_text(CFG["indexnow_key"], encoding="utf-8")
(HERE / "urls.txt").write_text("\n".join(f"{SITE}/{p}" for p, _, _ in PAGES) + "\n", encoding="utf-8")
llms = [f"# findifsjobs", "", f"> Independent job board and directory for the IFS ERP ecosystem (IFS Cloud, IFS Applications, FSM, EAM). Not affiliated with IFS. Updated daily; last update {TODAY.isoformat()}.", "",
        "## Key facts", f"- {rep_summary}", f"- {len(partners)} verified IFS partners and {len(recruiters)} recruiters are listed.", "",
        "## Main pages", f"- [All open IFS jobs]({SITE}/): {N} roles, filterable by country, module, contract and employer type",
        f"- [IFS hiring report]({SITE}/ifs-hiring-report/): open roles by region, country, module and employer",
        f"- [Top 10 IFS partners by region]({SITE}/top-ifs-partners/): eight regional rankings with the scoring method",
        f"- [IFS partner directory]({SITE}/partners/): tier, size, focus and careers links for each partner",
        f"- [IFS recruiters]({SITE}/ifs-recruiters/): specialist IFS recruitment firms",
        f"- [IFS partners by country]({SITE}/ifs-partners/): " + ", ".join(f"{c} ({len(v)})" for c, v in PC_PAGES.items()),
        f"- [IFS Hiring Index]({SITE}/ifs-hiring-index/): monthly figures, free to quote with a link. Latest: " + find0,
        *[f"- [{gt}]({SITE}/guides/{gs}/): {gd}" for gs, gt, gd, *_ in GUIDES],
        *[f"- [IFS partners for {v[0]}]({SITE}/ifs-partners/for-{k}/): " + ", ".join(p["n"] for p in v[1][:8]) for k, v in IND_PAGES.items()],
        f"- [Marketing for IFS partners]({SITE}/marketing-for-ifs-partners/): lead generation, LinkedIn, events and hiring marketing for IFS partner firms",
        f"- [What's new in IFS]({SITE}/news/): sourced news on releases, partners and customers",
        f"- [About and method]({SITE}/about/): how jobs are collected and partners verified", "", "## Top 10 IFS partners by region"]
llms += [f"- [{v[1][0].upper() + v[1][1:]}]({SITE}/top-ifs-partners/{v[2]}/): " + ", ".join(p["n"] for p in top10[k]) for k, v in REG.items()]
llms += ["", "## IFS jobs by country"] + [f"- [IFS jobs in {c}]({SITE}/{cpath(c)}): {n} open roles" for c, n in sorted(countries.items(), key=lambda x: -x[1])]
llms += ["", "## IFS jobs by module"] + [f"- [IFS {a} jobs]({SITE}/{apath(a)}): {n} open roles" for a, n in sorted(areas.items(), key=lambda x: -x[1])]
(OUT / "llms.txt").write_text("\n".join(llms) + "\n", encoding="utf-8")
if "github.io" not in SITE:
    (OUT / "CNAME").write_text(SITE.split("//")[1] + "\n", encoding="utf-8")
print(f"site built: {len(PAGES)} pages ({N} jobs, {len(partners)} partners, {len(countries)} country and {len(areas)} module pages)")
