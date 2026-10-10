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

countries = {c: n for c, n in Counter(j["country"] for j in jobs if known(j.get("country"))).items() if n >= 2}
areas = {a: n for a, n in Counter(j["area"] for j in jobs if known(j.get("area"))).items() if n >= 3}
cpath = lambda c: f"ifs-jobs/{slug(c)}/"
apath = lambda a: f"ifs-jobs/{slug(a)}-jobs/"
SPECIAL = {"remote": ("Remote and hybrid IFS jobs", lambda j: j["remote"], "ifs-jobs/remote/"),
           "contract": ("IFS contract jobs", lambda j: j.get("contract_type") == "Contract", "ifs-jobs/contract/"),
           "cloud": ("IFS Cloud jobs", lambda j: j.get("ifs_version") == "IFS Cloud", "ifs-jobs/ifs-cloud/")}

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
    mini = "".join(f'<li><a href="{e(n["url"])}" target="_blank" rel="noopener nofollow">{e(n["title"])}</a><span>{nice(n["date"])} · {e(n["tag"])}</span></li>' for n in news[:3])
    return (f'<aside class="extras"><div class="note accent"><h3>IFS freelancer?</h3><p class="small">Get featured on this board so partners and customers can find you. It\'s free.</p>'
            f'<a class="small" href="{root}freelancers/">Get featured &rarr;</a></div>'
            f'<div class="note"><h3>What\'s new in IFS</h3><ul>{mini}</ul><a class="small" href="{root}news/">All updates &rarr;</a></div></aside>')


def tags_for(p):
    out = [f'<span class="tag v">{e(p["tier"])}</span>' if p.get("tier") else "", f'<span class="tag">{KIND[p["kind"]]}</span>',
           '<span class="tag v">Emerging</span>' if p["kind"] != "G" and p.get("sig") else "",
           f'<span class="tag">Founded {p["founded"]}</span>' if p.get("founded") else ""]
    return "".join(out)


def faq(items):
    body = "".join(f"<div><h3>{e(q)}</h3><p>{e(a)}</p></div>" for q, a in items)
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in items]}
    return f'<section class="stack"><h2>Questions people ask</h2><div class="faq">{body}</div></section>', ld


NAV = [("", "Jobs"), ("top-ifs-partners/", "Top 10 partners"), ("partners/", "Partner directory"), ("ifs-recruiters/", "Recruiters"),
       ("freelancers/", "Freelancers"), ("news/", "What's new"), ("ifs-hiring-report/", "Hiring report")]


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
    ga = CFG.get("ga_id")
    ga_tag = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={e(ga)}"></script><script>window.dataLayer=window.dataLayer||[];'
              f'function gtag(){{dataLayer.push(arguments)}}gtag("js",new Date());gtag("config","{e(ga)}");</script>') if ga else ""
    sc = CFG.get("search_console_meta")
    head = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}">'
            f'{"" if index else "<meta name=\"robots\" content=\"noindex\">"}'
            f'{f"<meta name=\"google-site-verification\" content=\"{e(sc)}\">" if sc else ""}'
            f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(url)}">'
            f'<meta property="og:type" content="website"><meta property="og:site_name" content="findifsjobs"><meta name="twitter:card" content="summary">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;800&display=swap">'
            f'<link rel="stylesheet" href="{root}assets/site.css">'
            + "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False).replace("</", "<\\/")}</script>' for x in lds)
            + f'{ga_tag}</head><body data-form="{e(CFG.get("form_endpoint", ""))}">')
    header = (f'<header class="top"><div class="wrap"><a class="brand" href="{root or "./"}">find<i>ifs</i>jobs</a>'
              f'<nav class="tabs" aria-label="Sections">{nav}</nav><a class="btn" href="{root}hire/">Hire IFS talent</a></div></header>')
    footer = (f'<footer><div class="wrap"><div style="display:flex;flex-direction:column;gap:10px"><h2>New IFS jobs every Monday</h2>'
              f'<form class="news-form" data-kind="newsletter" data-done="Subscribed. The next issue arrives on Monday."><input type="email" name="email" placeholder="you@company.com" aria-label="Email address" required>'
              f'<button class="btn" type="submit">Subscribe</button></form><p class="msg" hidden style="max-width:480px"></p></div>'
              f'<ul class="linklist"><li><a href="{root}about/">About and method</a></li><li><a href="{root}ifs-hiring-report/">IFS hiring report</a></li>'
              f'<li><a href="{root}ifs-jobs/remote/">Remote IFS jobs</a></li><li><a href="{root}ifs-jobs/contract/">IFS contract jobs</a></li>'
              f'<li><a href="{root}ifs-jobs/ifs-cloud/">IFS Cloud jobs</a></li><li><a href="{root}hire/">Hire IFS talent</a></li></ul>'
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

# ------------------------------------------------------------------ build
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "assets").mkdir(parents=True)
for f in ("site.css", "site.js"):
    shutil.copy(HERE / "assets" / f, OUT / "assets" / f)
if (HERE / "logos").exists():
    shutil.copytree(HERE / "logos", OUT / "logos", ignore=shutil.ignore_patterns("*.txt", "manifest.json"))

# ---- home
top3c = ", ".join(f"{c} ({n})" for c, n in by_country[:3])
top3a = ", ".join(f"{a} ({n})" for a, n in by_area[:3])
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
home = (hero("The job board for the IFS ecosystem", "Find your next <em>IFS</em> job.",
             "IFS Cloud, Apps 10, FSM and EAM roles from the vendor, partners, customers and recruiters. One list, every region.", sub=False, extra=search + stats)
        + f'<div class="wrap"><div class="board">{filters(jobs)}<div class="list">{job_list(jobs, "")}</div>{extras("")}</div>'
        + f'<section class="stack"><h2>IFS jobs by country</h2>{country_links("")}</section>'
        + f'<section class="stack"><h2>IFS jobs by module</h2>{area_links("")}</section>{home_faq}</div>')
page("", f"IFS Jobs: {N} open IFS Cloud, ERP, EAM and FSM roles | findifsjobs",
     f"{N} open IFS jobs from {employers_n} employers in {len(by_country)} countries. IFS Cloud consultants, developers, architects and support roles, updated daily.",
     home, active="", priority="1.0",
     ld=[home_ld, {"@context": "https://schema.org", "@type": "WebSite", "name": "findifsjobs", "url": SITE + "/",
                   "potentialAction": {"@type": "SearchAction", "target": SITE + "/?q={search_term_string}", "query-input": "required name=search_term_string"}},
         {"@context": "https://schema.org", "@type": "Organization", "name": "findifsjobs", "url": SITE + "/",
          "description": "Independent job board and directory for the IFS ERP ecosystem."}])

# ---- job pages
EMP = {"Contract": "CONTRACTOR", "Permanent": "FULL_TIME", "Fixed term": "TEMPORARY"}
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
    partner = PBY.get(j["company"].lower())
    related = [x for x in jobs if x is not j and (x["company"] == j["company"] or x.get("area") == j.get("area"))][:5]
    side = (f'<div class="stack"><div class="note"><h3>About this listing</h3><p class="small">findifsjobs found this role on {e(j["company"])}\'s public careers page or advert. '
            f'Applications go to the original posting, not to us.</p></div>'
            + (f'<div class="note"><h3>About {e(partner["n"])}</h3><p class="small">{e(partner["blurb"])}</p><a class="small" href="{root}{partner["path"]}">Partner profile &rarr;</a></div>' if partner else "")
            + (f'<div class="note"><h3>More IFS jobs</h3>{links([(c, cpath(c), None) for c in [j.get("country")] if c in countries] + [(a, apath(a), None) for a in [j.get("area")] if a in areas] + [("All IFS jobs", "", None)], root)}</div>') + "</div>")
    body = (hero(j.get("company_type") or "IFS job", e(j["title"]), f'<b style="color:var(--ink);font-weight:500">{e(j["company"])}</b>{" · " + e(j["loc"]) if j["loc"] else ""}', h1cls="small",
                 extra=f'<a class="btn bigbtn" href="{e(j["url"])}" target="_blank" rel="noopener nofollow">Apply on the original posting &rarr;</a>')
            + f'<div class="wrap"><div class="article"><div class="stack"><div class="prose"><h2>About the role</h2><p>{e(about)}</p></div>{table}'
            + (f'<section class="stack"><h2>Similar IFS jobs</h2><ul class="rows">{"".join(job_row(x, root) for x in related)}</ul></section>' if related else "")
            + f'</div>{side}</div></div>')
    ld = []
    if known(j.get("country")):
        valid = (dt.date.fromisoformat((j.get("last_seen") or TODAY.isoformat())[:10]) + dt.timedelta(days=30)).isoformat()
        jp = {"@context": "https://schema.org", "@type": "JobPosting", "title": j["title"], "description": f"<p>{e(about)}</p>",
              "datePosted": j["when"][:10], "validThrough": valid, "directApply": False, "url": f"{SITE}/{j['path']}",
              "hiringOrganization": {"@type": "Organization", "name": j["company"], **({"sameAs": partner["web"]} if partner and partner.get("web") else {})},
              "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressCountry": j["country"],
                                                            **({"addressLocality": j["city"]} if known(j.get("city")) and j["city"] != "Remote" else {})}},
              "industry": "Enterprise software (IFS ERP)", "occupationalCategory": j.get("area") or "IFS"}
        if j.get("contract_type") in EMP:
            jp["employmentType"] = EMP[j["contract_type"]]
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
    landing(apath(a), f"IFS {a} jobs", f"{plural(n, 'open IFS role')} in {e(a)}, updated daily.", items,
            f"IFS {a} jobs: {plural(n, 'open role')} ({MONTH}) | findifsjobs",
            f"{plural(n, 'open IFS job')} in {a}. Mostly in {cs}. Filter by country, contract type and employer.",
            [(f"How many IFS {a} jobs are open?", f"{plural(n, 'role')} as of {TODAY.strftime('%-d %B %Y')}."),
             (f"Where are IFS {a} jobs?", f"Most are in {cs}.")], f"{a} jobs")
for key, (h, test, path) in SPECIAL.items():
    items = [j for j in jobs if test(j)]
    if items:
        landing(path, h, f"{plural(len(items), 'open role')}, updated daily.", items, f"{h}: {plural(len(items), 'open role')} ({MONTH}) | findifsjobs",
                f"{plural(len(items), 'open role')} on findifsjobs. {h} from IFS partners, customers and recruiters, refreshed daily.",
                [(f"How many {h.lower()} are open?", f"{plural(len(items), 'role')} out of {N} IFS jobs listed, as of {TODAY.strftime('%-d %B %Y')}.")], h)

# ---- partners: directory and profiles
cells = ""
for p in sorted(partners, key=lambda p: (-p["score"], p["n"])):
    text = " ".join(str(p.get(k) or "") for k in ("n", "hq", "focus", "blurb", "tier")).lower()
    pl = "".join(x for x in (f'<a href="../{p["path"]}">Profile</a>', ext(p.get("web"), "Website"), ext(p.get("careers"), "Careers")) if x)
    cells += (f'<li class="cell" data-regions="{" ".join(p["r"])}" data-kind="{p["kind"]}" data-tier="{e(p.get("tier") or "")}" data-score="{p["score"]}" data-name="{e(p["n"])}" data-text="{e(text)}">'
              f'<div class="head">{logo(p["n"], "../", True)}<div class="body"><h3><a href="../{p["path"]}" style="color:var(--ink)">{e(p["n"])}</a></h3><p class="meta">{e(p["hq"])}</p></div></div>'
              f'<p class="sum">{e(p["blurb"])}</p><p class="kv"><b>Focus:</b> {e(p["focus"])}</p>'
              + (f'<p class="kv"><b>Size:</b> {e(p["size"])}</p>' if p.get("size") else "")
              + f'<p class="kv"><b>Active in:</b> {", ".join(REG[x][0] for x in p["r"])}</p><div class="tags">{tags_for(p)}</div><div class="foot">{pl}</div></li>')
toolbar = ('<div class="toolbar"><input type="search" class="plain" id="p-q" placeholder="Search partners, industries, cities" aria-label="Search partners">'
           f'<select id="p-region" aria-label="Region"><option value="">All regions</option>{"".join(f"""<option value="{k}">{v[0]}</option>""" for k, v in REG.items())}</select>'
           '<select id="p-kind" aria-label="Type"><option value="">All types</option><option value="S">IFS specialists</option><option value="B">ERP boutiques</option><option value="G">Global firms</option></select>'
           '<select id="p-sort" aria-label="Sort"><option value="score">Emerging first</option><option value="az">A to Z</option><option value="tier">Highest tier first</option></select></div>')
page("partners/", f"IFS partner directory: {len(partners)} implementation partners | findifsjobs",
     f"{len(partners)} verified IFS partners across eight regions, with tier, size, focus and careers links. Sorted to surface emerging IFS specialists first.",
     hero("Partner directory", f"{len(partners)} IFS partners, emerging firms first", "Every firm is confirmed as an IFS partner by the IFS directory, an IFS announcement or an IFS event listing.")
     + f'<div class="wrap">{toolbar}<p class="muted small" id="p-count">{len(partners)} of {len(partners)} partners</p><ul class="grid" id="p-list">{cells}</ul></div>',
     active="partners/", crumbs=[("Partner directory", None)], priority="0.8")

for p in partners:
    root = "../../"
    ranks = [(r, top10[r].index(p) + 1) for r in p["r"] if p in top10[r]]
    facts = [("Headquarters", p["hq"]), ("IFS partner tier", p.get("tier")), ("Type", KIND[p["kind"]]), ("Size", p.get("size")), ("Founded", p.get("founded")),
             ("Focus", p["focus"]), ("IFS awards", p.get("awards")), ("Active in", ", ".join(REG[x][0] for x in p["r"]))]
    table = '<table class="facts">' + "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in facts if v) + "</table>"
    rank_html = ('<div class="note"><h3>Rankings</h3><ul>' + "".join(f'<li><a href="{root}top-ifs-partners/{REG[r][2]}/">#{n} in {e(REG[r][0])}</a></li>' for r, n in ranks) + "</ul></div>") if ranks else ""
    pl = "".join(x for x in (ext(p.get("web"), "Website"), ext(p.get("careers"), "Careers page"), ext(p.get("src"), "Source for partner status")) if x)
    jobs_html = (f'<section class="stack"><h2>Open IFS jobs at {e(p["n"])}</h2><ul class="rows">{"".join(job_row(j, root) for j in p["jobs"])}</ul></section>' if p["jobs"]
                 else f'<section class="stack"><h2>Open IFS jobs at {e(p["n"])}</h2><p class="muted">No open roles from {e(p["n"])} are on the board today. '
                      + (ext(p.get("careers"), "Check their careers page") or "Check their website") + ".</p></section>")
    body = (hero("IFS partner", f'<span class="pagelogo">{logo(p["n"], root, True)}<span>{e(p["n"])}</span></span>', e(p["blurb"]), h1cls="small")
            + f'<div class="wrap"><div class="article"><div class="stack">'
            + (f'<div class="prose"><h2>What stands out</h2><p>{e(p["sig"])}</p></div>' if p.get("sig") else "")
            + f'{table}<div class="tags">{tags_for(p)}</div>{jobs_html}</div><div class="stack">{rank_html}<div class="note"><h3>Links</h3><div class="cell" style="border:0;padding:0;background:none"><div class="foot" style="border:0;padding:0;flex-direction:column">{pl}</div></div></div></div></div></div>')
    page(p["path"], f"{p['n']}: IFS partner profile, jobs and facts | findifsjobs",
         f"{p['n']} is an IFS partner based in {p['hq']}. {p['blurb']} Tier, size, focus, awards and open IFS jobs.", body, active="partners/",
         ld=[{"@context": "https://schema.org", "@type": "Organization", "name": p["n"], **({"url": p["web"]} if p.get("web") else {}), "description": p["blurb"]}],
         crumbs=[("Partner directory", "partners/"), (p["n"], None)], priority="0.6")

# ---- top 10 by region
METHOD = ('<p class="method"><b>How the ranking works.</b> Points for being IFS-only (3) or an ERP boutique (1.5), a recent growth signal such as a merger, new tier or new market (2), '
          'being founded since 2016 (1.5), IFS awards from 2023 to 2025 (1 each, up to 2), partner tier (Elite 1.5, Premier 1, Specialized 0.5) and a home base in the region (3). '
          'Facts come from the IFS partner directory, IFS press releases and each firm\'s own site. This is an editorial ranking by findifsjobs, not an IFS one.</p>')
pills = lambda cur, root: '<div class="pills">' + "".join(f'<a class="pill" href="{root}top-ifs-partners/{v[2]}/"{" aria-pressed=\"true\"" if k == cur else ""}>{v[0]}</a>' for k, v in REG.items()) + "</div>"
for r, (short, long, rs) in REG.items():
    root = "../../"
    rows = "".join(
        f'<li class="row">{logo(p["n"], root)}<div class="body"><h3><a href="{root}{p["path"]}">{e(p["n"])}</a></h3><p class="meta">{e(p["hq"])}{" · " + e(p["size"]) if p.get("size") else ""}</p>'
        f'<p class="sum">{e(p.get("sig") or p["blurb"])}</p>{f"""<p class="kv"><b>Awards:</b> {e(p["awards"])}</p>""" if p.get("awards") else ""}<div class="tags">{tags_for(p)}</div></div>'
        f'<div class="side"><div class="links"><a href="{root}{p["path"]}">Profile</a>{ext(p.get("web"), "Website")}{ext(p.get("careers"), "Careers")}</div></div></li>' for p in top10[r])
    names = ", ".join(p["n"] for p in top10[r][:5])
    block, fl = faq([(f"Who are the top IFS partners in {long}?", f"By findifsjobs' emerging-first ranking, the top five are {names}."),
                     (f"How is the ranking decided?", "Partners score points for IFS-only focus, recent growth signals, founding since 2016, IFS awards from 2023 to 2025, partner tier and a home base in the region. Global firms are listed but not favoured."),
                     ("Is this an official IFS ranking?", "No. It is an independent editorial ranking by findifsjobs, built from public facts.")])
    il = {"@context": "https://schema.org", "@type": "ItemList", "name": f"Top 10 IFS partners in {long}", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": p["n"], "url": f"{SITE}/{p['path']}"} for i, p in enumerate(top10[r])]}
    page(f"top-ifs-partners/{rs}/", f"Top 10 IFS partners in {long} (2026) | findifsjobs",
         f"The top 10 IFS implementation partners in {long}: {names} and more. Ranked on focus, growth, awards and tier, with the method shown.",
         hero("Top 10 partners", f"Top 10 IFS partners in {e(long)}", "Ranked for people choosing where to work or who to hire. Specialists and fast-growing firms come first.")
         + f'<div class="wrap">{pills(r, root)}<ol class="rows rank">{rows}</ol>{METHOD}{block}</div>',
         active="top-ifs-partners/", ld=[il, fl], crumbs=[("Top 10 partners", "top-ifs-partners/"), (short, None)], priority="0.9")
idx = "".join(f'<li class="cell"><h3><a href="{v[2]}/" style="color:var(--ink)">Top 10 IFS partners in {e(v[1])}</a></h3><p class="sum">{e(", ".join(p["n"] for p in top10[k][:4]))} and more.</p><div class="foot"><a href="{v[2]}/">See the list &rarr;</a></div></li>' for k, v in REG.items())
page("top-ifs-partners/", "Top 10 IFS partners by region (2026) | findifsjobs",
     "Top 10 IFS implementation partners in eight regions: USA and Canada, UK and Ireland, Nordics, DACH, Europe, Middle East and Africa, South Asia and Asia Pacific.",
     hero("Top 10 partners", "Top 10 IFS partners by region", "Eight regional rankings. Specialists and fast-growing firms come first; the method is printed on every list.")
     + f'<div class="wrap"><ul class="grid">{idx}</ul>{METHOD}</div>', active="top-ifs-partners/", crumbs=[("Top 10 partners", None)], priority="0.9")

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
tags = list(dict.fromkeys(n["tag"] for n in news))
n_rows = "".join(
    f'<li class="row" data-tag="{e(n["tag"])}" style="grid-template-columns:minmax(0,1fr) auto"><div class="body"><h3><a href="{e(n["url"])}" target="_blank" rel="noopener nofollow">{e(n["title"])}</a></h3>'
    f'<p class="sum">{e(n["summary"])}</p><div class="tags"><span class="tag v">{e(n["tag"])}</span><span class="tag">{e(n["source"])}</span></div></div>'
    f'<div class="side" style="grid-column:auto"><span class="newsdate">{nice(n["date"])}</span></div></li>' for n in news)
n_pills = '<div class="pills" id="n-pills" role="group" aria-label="Topic"><button type="button" class="pill" data-t="" aria-pressed="true">All</button>' + "".join(f'<button type="button" class="pill" data-t="{e(t)}">{e(t)}</button>' for t in tags) + "</div>"
page("news/", "What's new in the IFS space: releases, partners, customers | findifsjobs",
     "Recent IFS news in one list: IFS Cloud releases, partner mergers and new partnerships, customer wins, company results and events. Each item links to its source.",
     hero("What's new", "What's new in the IFS space", "Product releases, partner moves, customer wins and events. Each item links to its source.")
     + f'<div class="wrap">{n_pills}<ul class="rows" id="n-list">{n_rows}</ul></div>', active="news/", crumbs=[("What's new", None)], priority="0.7",
     lastmod=news[0]["date"] if news else None)

# ---- hiring report
def tbl(title, pairs, total=N):
    rows = "".join(f'<tr><th>{e(k)}</th><td class="n">{v}</td><td class="n">{v * 100 // total}%</td></tr>' for k, v in pairs)
    return f'<section class="stack"><h2>{e(title)}</h2><div class="scroll"><table class="facts"><tr><th>&nbsp;</th><td><b>Open roles</b></td><td><b>Share</b></td></tr>{rows}</table></div></section>'


rep_summary = (f"{N} open IFS roles from {employers_n} employers in {len(by_country)} countries. {cloud_n} ({cloud_n * 100 // N}%) name IFS Cloud and {remote_n} ({remote_n * 100 // N}%) are remote or hybrid. "
               f"The busiest country is {by_country[0][0]} with {by_country[0][1]} roles, and the busiest area is {by_area[0][0]} with {by_area[0][1]}.")
block, fl = faq([("How many IFS jobs are open worldwide?", f"{N} on findifsjobs as of {TODAY.strftime('%-d %B %Y')}, from {employers_n} employers."),
                 ("What share of IFS jobs ask for IFS Cloud?", f"{cloud_n * 100 // N}% of listings name IFS Cloud ({cloud_n} of {N})."),
                 ("What share of IFS jobs are remote or hybrid?", f"{remote_n * 100 // N}% ({remote_n} of {N}).")])
page("ifs-hiring-report/", f"IFS hiring report, {MONTH}: {N} open roles by country and module | findifsjobs",
     f"IFS job market snapshot for {MONTH}: {rep_summary}",
     hero("Hiring report", f"IFS hiring report, {MONTH}", e(rep_summary))
     + f'<div class="wrap"><p class="muted small">Based on every listing on findifsjobs on {TODAY.strftime("%-d %B %Y")}. The board covers public careers pages of IFS, partners, customers and recruiters, so it is a sample of the market, not a census. Free to quote with a link to this page.</p>'
     + tbl("By region", by_region) + tbl("By country", by_country[:12]) + tbl("By module / area", by_area) + tbl("By employer type", by_type) + tbl("Employers with the most open roles", by_employer)
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
     + f'<div class="wrap">{three([("Request a shortlist", "Contract or permanent. You describe the role and we match on module, version and region."), ("Feature a role", "Pin your listing to the top of its module and region and include it in the weekly email."), ("List your firm", "Partners and recruiters can claim their profile, add a logo and link their open roles.")])}{hire_form}</div>',
     crumbs=[("Hire IFS talent", None)], priority="0.7")
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

# ---- sitemap, robots, llms.txt
(OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
    f"<url><loc>{SITE}/{p}</loc><lastmod>{m}</lastmod><priority>{pr}</priority></url>\n" for p, m, pr in PAGES) + "</urlset>\n", encoding="utf-8")
(OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
llms = [f"# findifsjobs", "", f"> Independent job board and directory for the IFS ERP ecosystem (IFS Cloud, IFS Applications, FSM, EAM). Not affiliated with IFS. Updated daily; last update {TODAY.isoformat()}.", "",
        "## Key facts", f"- {rep_summary}", f"- {len(partners)} verified IFS partners and {len(recruiters)} recruiters are listed.", "",
        "## Main pages", f"- [All open IFS jobs]({SITE}/): {N} roles, filterable by country, module, contract and employer type",
        f"- [IFS hiring report]({SITE}/ifs-hiring-report/): open roles by region, country, module and employer",
        f"- [Top 10 IFS partners by region]({SITE}/top-ifs-partners/): eight regional rankings with the scoring method",
        f"- [IFS partner directory]({SITE}/partners/): tier, size, focus and careers links for each partner",
        f"- [IFS recruiters]({SITE}/ifs-recruiters/): specialist IFS recruitment firms",
        f"- [What's new in IFS]({SITE}/news/): sourced news on releases, partners and customers",
        f"- [About and method]({SITE}/about/): how jobs are collected and partners verified", "", "## Top 10 IFS partners by region"]
llms += [f"- [{v[1][0].upper() + v[1][1:]}]({SITE}/top-ifs-partners/{v[2]}/): " + ", ".join(p["n"] for p in top10[k]) for k, v in REG.items()]
llms += ["", "## IFS jobs by country"] + [f"- [IFS jobs in {c}]({SITE}/{cpath(c)}): {n} open roles" for c, n in sorted(countries.items(), key=lambda x: -x[1])]
llms += ["", "## IFS jobs by module"] + [f"- [IFS {a} jobs]({SITE}/{apath(a)}): {n} open roles" for a, n in sorted(areas.items(), key=lambda x: -x[1])]
(OUT / "llms.txt").write_text("\n".join(llms) + "\n", encoding="utf-8")
if "github.io" not in SITE:
    (OUT / "CNAME").write_text(SITE.split("//")[1] + "\n", encoding="utf-8")
print(f"site built: {len(PAGES)} pages ({N} jobs, {len(partners)} partners, {len(countries)} country and {len(areas)} module pages)")
