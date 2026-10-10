#!/usr/bin/env python3
"""Download partner, recruiter and employer logos into logos/ so the site serves its own copies.

logos/wide/<slug>.<ext>   the company's own logo (from the address stored in partners.json / recruiters.json)
logos/icon/<slug>.png     a small square icon for the company's website domain
logos/manifest.json       {"company name (lower case)": {"wide": "...", "icon": "..."}}

Files already downloaded are kept, so the daily run only fetches what is new.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDE, ICON = HERE / "logos" / "wide", HERE / "logos" / "icon"
UA = "Mozilla/5.0 (compatible; findifsjobs/0.1; +https://findifsjobs.com)"
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp", "image/avif": "avif",
       "image/gif": "gif", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico"}
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def grab(url, min_bytes=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        data = r.read(3_000_000)
    if ctype not in EXT and b"<svg" in data[:600]:
        ctype = "image/svg+xml"
    if ctype not in EXT or len(data) < min_bytes:
        raise ValueError(f"not a usable image ({ctype or 'no type'}, {len(data)} bytes)")
    return data, EXT[ctype]


def trim(path):
    """Crop the empty margin around a raster logo so it fills its box. Needs Pillow; skipped without it."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return
    try:
        im = Image.open(path).convert("RGBA")
        flat = Image.new("RGBA", im.size, (255, 255, 255, 255))
        flat.alpha_composite(im)
        diff = ImageChops.difference(flat.convert("RGB"), Image.new("RGB", im.size, (255, 255, 255)))
        box = diff.point(lambda v: 255 if v > 18 else 0).getbbox()
        if not box:
            return                                   # all white (a white-on-clear logo): leave it alone
        w, h = box[2] - box[0], box[3] - box[1]
        if w * h > 0.8 * im.size[0] * im.size[1] and max(im.size) <= 600:
            return                                   # already tight and small
        pad = max(2, int(0.04 * max(w, h)))
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.size[0], box[2] + pad), min(im.size[1], box[3] + pad))
        im = im.crop(box)
        im.thumbnail((480, 240))
        out = path.with_suffix(".png")
        im.save(out, optimize=True)
        if out != path:
            path.unlink()
    except Exception:
        pass


def existing(folder, s):
    return next((p for p in folder.glob(s + ".*")), None)


def main():
    WIDE.mkdir(parents=True, exist_ok=True)
    ICON.mkdir(parents=True, exist_ok=True)
    firms = {}                                   # name -> (logo url, website domain)
    for f in ("partners.json", "recruiters.json"):
        for p in json.loads((HERE / f).read_text(encoding="utf-8")):
            firms[p["n"]] = (p.get("logo"), urllib.parse.urlparse(p.get("web") or "").netloc.removeprefix("www."))
    extra = HERE / "employers.json"              # employers that only appear in job listings: name -> domain
    if extra.exists():
        for name, dom in json.loads(extra.read_text(encoding="utf-8")).items():
            firms.setdefault(name, (None, dom))
    manifest, log = {}, []
    for name, (logo_url, dom) in sorted(firms.items()):
        s, entry = slug(name), {}
        w = existing(WIDE, s)
        if not w and logo_url:
            try:
                data, ext = grab(logo_url)
                w = WIDE / f"{s}.{ext}"
                w.write_bytes(data)
                trim(w)
                w = existing(WIDE, s)
            except Exception as e:
                log.append(f"wide  {name}: {str(e)[:80]}")
        if w:
            entry["wide"] = f"logos/wide/{w.name}"
        i = existing(ICON, s)
        if not i and dom:
            for src in (f"https://www.google.com/s2/favicons?domain={dom}&sz=128", f"https://icons.duckduckgo.com/ip3/{dom}.ico"):
                try:
                    data, ext = grab(src, min_bytes=700)   # tiny files are the "unknown site" placeholder
                    i = ICON / f"{s}.{ext}"
                    i.write_bytes(data)
                    break
                except Exception as e:
                    err = str(e)[:80]
            else:
                log.append(f"icon  {name}: {err}")
        if i:
            entry["icon"] = f"logos/icon/{i.name}"
        if entry:
            manifest[name.lower()] = entry
    (HERE / "logos" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "logos" / "last_run.txt").write_text(f"{len(manifest)} of {len(firms)} firms have a logo or icon\n" + "\n".join(log) + "\n", encoding="utf-8")
    print(f"{len(manifest)} of {len(firms)} firms have a logo or icon; {len(log)} misses")


if __name__ == "__main__":
    main()
