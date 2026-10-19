#!/usr/bin/env python3
"""Build a static, searchable mirror of the Taxacom Pipermail archive.

Copies the public archive (HTML + gzipped monthly text) into public/,
keeping the original /pipermail/taxacom/... paths so old lists.ku.edu
links map 1:1. Transcodes every page to UTF-8 and marks message pages
for Pagefind. Never touches lists/ (subscriber data) or database/.

The archive holds up to three copies of some messages under different
numbers (old imports). One copy is kept (see dedupe.py); the others become
small redirect stubs so their URLs still work, and are dropped from the
month indexes.

Months whose HTML is missing from the backup (232 of 398) are rebuilt
from <month>.txt plus database/<month>-article; see pipermail_render.py.

Usage: python3 build.py <archive-dir> <out-dir>
Then:  npx -y pagefind@1.5.2 --site <out-dir>
"""
import re
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from dedupe import drop_index_entries, find_canonical
from pipermail_render import articles_for_month, render_month

STATIC = Path(__file__).parent / "static"
DOMAIN = "taxacom.org"

CHARSET_RE = re.compile(rb'charset=(?:3d)?"?([A-Za-z0-9_-]*)', re.I)
MONTH_DIR_RE = re.compile(r"^\d{4}-[A-Z][a-z]+$")

BANNER = (
    '<div data-pagefind-ignore="all" style="font:14px sans-serif;background:#f3f1ea;'
    'border-bottom:1px solid #ccc;padding:6px 10px;margin:-8px -8px 12px">'
    '<a href="/">Search the Taxacom archive</a> &middot; <a href="/pipermail/taxacom/">Browse by month</a> &middot; '
    'Mirror of the former lists.ku.edu archive (1992&ndash;2025)</div>'
)


def decode(raw: bytes) -> str:
    m = CHARSET_RE.search(raw[:2000])
    cs = (m.group(1).decode() if m else "") or "utf-8"
    if cs.lower() == "us-ascii":
        cs = "utf-8"  # Pipermail often mislabels 8-bit content as ascii
    for enc in (cs, "utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("cp1252", errors="replace")


def fix_charset(html: str) -> str:
    return re.sub(r'charset=(?:3d)?"?[A-Za-z0-9_-]*', "charset=utf-8", html, count=1, flags=re.I)


def set_lang(html: str) -> str:
    return re.sub(r"<HTML>", '<HTML lang="en">', html, count=1, flags=re.I)


LISTINFO_RE = re.compile(r'https?://(?:lists\.ku\.edu|mailman\.nhm\.ku\.edu)/(?:cgi-bin/)?(?:mailman/)?listinfo/taxacom/?')
MAILTO_RE = re.compile(r'<A\s+HREF="mailto:[^"]*"[^>]*>(.*?)</A>', re.S | re.I)
MADE_RE = re.compile(r'\s*<LINK REL="made" HREF="mailto:[^"]*"\s*>', re.I)


def retarget_links(html: str) -> str:
    """Outside the message text: point the dead listinfo links at the home
    page, and unlink mailto: reply links to the defunct list address."""
    a, b = html.find("<!--beginarticle-->"), html.find("<!--endarticle-->")
    if a < 0 or b < 0:
        a = b = len(html)
    def fix(part):
        part = LISTINFO_RE.sub("/#the-list-today", part)
        part = MADE_RE.sub("", part)
        return MAILTO_RE.sub(r"\1", part)
    return fix(html[:a]) + html[a:b] + fix(html[b:])


def message_page(html: str, year: str, canonical: str, searchable: bool) -> str:
    html = retarget_links(set_lang(fix_charset(html)))
    html = re.sub(r"</HEAD>", f'<link rel="canonical" href="https://{DOMAIN}{canonical}">\n</HEAD>',
                  html, count=1, flags=re.I)
    # Only canonical message pages carry data-pagefind-body, so index pages
    # and duplicate copies are left out of search.
    attr = " data-pagefind-body" if searchable else ""
    html = re.sub(r"<BODY([^>]*)>", lambda m: f"<BODY{m.group(1)}{attr}>" + BANNER,
                  html, count=1, flags=re.I)
    html = re.sub(r"<H1>", '<H1 data-pagefind-meta="title">', html, count=1, flags=re.I)
    html = re.sub(r"<B>", '<B data-pagefind-meta="author">', html, count=1)
    html = re.sub(r"<I>", '<I data-pagefind-meta="date">', html, count=1)
    # Hide prev/next/sort nav lists and footers from the index.
    html = re.sub(r"<(P><)?UL>", lambda m: f"<{m.group(1) or ''}UL data-pagefind-ignore>", html, flags=re.I)
    html = html.replace("<!--beginarticle-->",
                        f'<span data-pagefind-filter="year" hidden>{year}</span><!--beginarticle-->', 1)
    return html


def stub_page(title: str, canonical: str) -> str:
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>'
            f'<link rel="canonical" href="https://{DOMAIN}{canonical}">'
            f'<meta http-equiv="refresh" content="0; url={canonical}">'
            f'<p>This is a duplicate copy. The message is at <a href="{canonical}">{canonical}</a>.</p>')


def index_page(html: str) -> str:
    html = retarget_links(set_lang(fix_charset(html)))
    return re.sub(r"<BODY([^>]*)>", lambda m: f"<BODY{m.group(1)}>" + BANNER, html, count=1, flags=re.I)


SITEMAP_MAX = 50000  # URLs per sitemap file, the protocol's limit


def write_sitemaps(out: Path, message_urls) -> int:
    """Write robots.txt, sitemap.xml (an index) and sitemap-N.xml files.

    The month and sort pages are noindex, so without a sitemap crawlers can
    reach messages only through pages they are told not to keep. The
    sitemaps list the home page, the month list and every kept message;
    redirect stubs are left out because they are canonical to another URL.
    Returns the number of sitemap files written."""
    urls = ["/", "/pipermail/taxacom/"] + sorted(message_urls)
    chunks = [urls[i:i + SITEMAP_MAX] for i in range(0, len(urls), SITEMAP_MAX)]
    for old in out.glob("sitemap*.xml"):
        old.unlink()
    for i, chunk in enumerate(chunks, 1):
        body = "".join(f"<url><loc>https://{DOMAIN}{escape(u)}</loc></url>\n" for u in chunk)
        (out / f"sitemap-{i}.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}</urlset>\n", encoding="utf-8")
    index = "".join(f"<sitemap><loc>https://{DOMAIN}/sitemap-{i}.xml</loc></sitemap>\n"
                    for i in range(1, len(chunks) + 1))
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{index}</sitemapindex>\n", encoding="utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: https://{DOMAIN}/sitemap.xml\n", encoding="utf-8")
    return len(chunks)


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    dest = out / "pipermail" / "taxacom"
    # Empty the output, keeping .git: out/ may be a checkout of the gh-pages branch.
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    dest.mkdir(parents=True)

    # month -> {filename: html}, from the backup's HTML or regenerated from mbox + database.
    months = {}
    preferred = set()  # message urls listed in Pipermail's database
    next_free = 900000  # numbers for messages that never had a page; far above the real 1-138xxx range
    for txt in sorted(src.glob("*.txt"), key=lambda p: p.stem):
        m, d = txt.stem, src / txt.stem
        if d.is_dir():
            pages = {}
            for f in d.glob("*.html"):
                raw = f.read_bytes()
                if f.name == "index.html" and len(raw) < 100:
                    # Pipermail's index.html was a symlink, saved as its target's name.
                    target = raw.decode().strip()
                    pages[f.name] = (f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={target}">'
                                     f'<a href="{target}">{target}</a>')
                else:
                    pages[f.name] = decode(raw)
            # Some months lost pages (e.g. 2006-June): rebuild any message the
            # mbox has but the HTML lacks, and if so regenerate the indexes so
            # they list it.
            arts, next_free = articles_for_month(txt, src / "database" / f"{m}-article", next_free)
            lost = [a for a in arts if a["filename"] not in pages]
            missing_idx = {"date.html", "thread.html", "subject.html", "author.html"} - pages.keys()
            if lost or missing_idx:
                listed = [a for a in arts if a["filename"] in pages or a in lost]
                regen = render_month(m, listed)
                for a in lost:
                    pages[a["filename"]] = regen[a["filename"]]
                for name in ({"date.html", "thread.html", "subject.html", "author.html"} if lost else missing_idx):
                    pages[name] = regen[name]
        else:
            arts, next_free = articles_for_month(txt, src / "database" / f"{m}-article", next_free)
            pages = render_month(m, arts)
        preferred.update(f"/pipermail/taxacom/{m}/{a['filename']}" for a in arts)
        months[m] = pages

    messages = {f"/pipermail/taxacom/{m}/{name}": html
                for m, pages in months.items() for name, html in pages.items() if name[:-5].isdigit()}
    canonical = find_canonical(messages, preferred)
    removed = {u for u, c in canonical.items() if u != c}

    n = 0
    for m, pages in months.items():
        (dest / m).mkdir()
        gone = {u.rsplit("/", 1)[1] for u in removed if u.startswith(f"/pipermail/taxacom/{m}/")}
        for name, html in pages.items():
            url = f"/pipermail/taxacom/{m}/{name}"
            if url in removed:
                title = re.search(r"<TITLE>(.*?)</TITLE>", html, re.S | re.I)
                page = stub_page(" ".join(title.group(1).split()) if title else "Taxacom", canonical[url])
            elif url in messages:
                page = message_page(html, m[:4], url, True)
            elif "http-equiv=\"refresh\"" in html[:100]:
                page = html
            else:
                page = index_page(drop_index_entries(html, gone))
            (dest / m / name).write_text(page, encoding="utf-8")
            n += 1
    for gz in src.glob("*.txt.gz"):
        shutil.copy2(gz, dest / gz.name)
    (dest / "index.html").write_text(index_page(decode((src / "index.html").read_bytes())), encoding="utf-8")
    shutil.copytree(STATIC, out, dirs_exist_ok=True)
    maps = write_sitemaps(out, (u for u in messages if u not in removed))
    print(f"wrote {n} pages across {len(months)} months: {len(messages) - len(removed)} messages, "
          f"{len(removed)} duplicate copies as redirects, to {dest}; {maps} sitemap file(s)")


if __name__ == "__main__":
    main()
