#!/usr/bin/env python3
"""Check a built mirror against the original Pipermail backup.

Usage: python3 test_site.py <archive-dir> <built-site-dir>
   e.g. python3 test_site.py ../archives/private/taxacom public

Needs only the Python standard library. Prints PASS/FAIL per check and
exits non-zero if any check fails. Checks are written against the raw
backup (mbox text, Pipermail databases, original HTML) rather than reusing
the renderer, so a rendering bug shows up as a failure.
"""
import copy
import email
import gzip
import html
import re
import sys
from difflib import SequenceMatcher
from email.header import decode_header, make_header
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).parent))
from build import decode  # noqa: E402
from pipermail_db import load_articles, read_mbox  # noqa: E402

SRC, SITE = Path(sys.argv[1]), Path(sys.argv[2])
ARCH = SITE / "pipermail" / "taxacom"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
failures = []


def check(name, problems):
    problems = list(problems)
    print(f"{'PASS' if not problems else 'FAIL'}  {name}")
    for p in problems[:10]:
        print(f"        {p}")
    if len(problems) > 10:
        print(f"        ... and {len(problems) - 10} more")
    if problems:
        failures.append(name)


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:  # keep \r exactly as written
        return fh.read()


def article(h):
    return h[h.find("<!--beginarticle-->"):h.find("<!--endarticle-->")]


def plain(h):
    """Visible text of an HTML fragment, whitespace-normalised."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", h)).split())


all_months = sorted(p.stem for p in SRC.glob("*.txt"))
html_months = {m for m in all_months if (SRC / m).is_dir()}
gen_months = [m for m in all_months if m not in html_months]

src_pages = {p.relative_to(SRC).as_posix() for p in SRC.glob("[0-9]*-*/*.html")} | {"index.html"}
out_pages = {p.relative_to(ARCH).as_posix() for p in ARCH.glob("**/*.html")}
out_html = {p: read(ARCH / p) for p in out_pages}
is_msg = re.compile(r"/\d+\.html$").search
src_messages = sorted(p for p in src_pages if is_msg(p))
out_messages = sorted(p for p in out_pages if is_msg(p))
STUB_RE = re.compile(r'^<!doctype html><html lang="en">.*http-equiv="refresh" content="0; url=/pipermail/taxacom/([^"]+)"', re.S)
stubs = {p: m.group(1) for p in out_messages if (m := STUB_RE.match(out_html[p]))}
full = [p for p in out_messages if p not in stubs]
resolve = lambda p: stubs.get(p, p)
print(f"{len(all_months)} months ({len(gen_months)} regenerated), {len(out_messages)} message URLs: "
      f"{len(full)} messages, {len(stubs)} duplicate-copy redirects\n")


def similarity(a, b):
    """Text similarity ignoring URLs (each import scrubbed attachments to different links)."""
    a, b = (" ".join(re.sub(r"\S*https?://\S+", " ", x).split()) for x in (a, b))
    if a == b:
        return 1.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    return sm.quick_ratio() and sm.ratio()

# --- Privacy ---------------------------------------------------------------
allowed = re.compile(r"^(index\.html|CNAME|\.nojekyll|robots\.txt|sitemap(-\d+)?\.xml|pagefind/.*|pipermail/taxacom/"
                     r"(index\.html|\d{4}-[A-Z][a-z]+\.txt\.gz|\d{4}-[A-Z][a-z]+/[a-z0-9]+\.html))$")
check("only expected files are published (no .pck, database/, lists/, raw .txt)",
      (p for p in (f.relative_to(SITE).as_posix() for f in SITE.rglob("*") if f.is_file())
       if not allowed.match(p) and not p.startswith(".git/")))  # .git: the gh-pages checkout itself

added = []
for p in out_messages:
    after = set(EMAIL_RE.findall(out_html[p]))
    before = set(EMAIL_RE.findall(decode((SRC / p).read_bytes()))) if p in src_pages else set()
    added += [f"{p}: {e}" for e in after - before]
check("no unobscured email addresses beyond those in the original public HTML", added)

# --- URLs ------------------------------------------------------------------
check("every original HTML page has the same path in the mirror", sorted(src_pages - out_pages))
check("every month has date/thread/subject/author pages",
      (f"{m}/{k}.html" for m in all_months for k in ("date", "thread", "subject", "author")
       if f"{m}/{k}.html" not in out_pages))

# Every message in every month's mbox has a page at its database filename.
complete, numbering = [], []
for m in all_months:
    db = load_articles(SRC / "database" / f"{m}-article")
    for msg in read_mbox(SRC / f"{m}.txt"):
        mid = (msg.get("Message-ID") or "").strip().strip("<>")
        if mid in db:
            if f"{m}/{db[mid]['filename']}" not in out_pages:
                complete.append(f"{m}: {mid} -> {db[mid]['filename']} missing")
        elif not any(p.startswith(f"{m}/9") for p in out_pages):
            complete.append(f"{m}: {mid} not in database and no fallback page")
check("every message in every month's .txt has a page at its original number", complete)
check("regenerated pages never reuse a number already used by an original page",
      (p for p in out_messages if p.split("/")[0] in gen_months and int(p[-11:-5]) < 900000
       and any(f"{x}/{p.split('/')[1]}" in src_pages for x in html_months)))

# --- Content ---------------------------------------------------------------
check("all .txt.gz downloads copied unchanged",
      (g.name for g in sorted(SRC.glob("*.txt.gz"))
       if not (ARCH / g.name).exists() or (ARCH / g.name).read_bytes() != g.read_bytes()))
check("all .txt.gz downloads are valid gzip",
      (g.name for g in sorted(ARCH.glob("*.txt.gz")) if not gzip.open(g).read(1)))

check("every page declares charset=utf-8",
      (p for p, h in out_html.items()
       if not re.search(r'charset="?utf-8', h[:max(h.lower().find("</head>"), 400)], re.I)))

# Kept pages are byte-identical to the backup; a redirected copy's text must
# closely match the page it redirects to (differences are Mailman-inserted links etc).
text_problems, merge_problems = [], []
for p in src_messages:
    if p in stubs:
        a = plain(article(decode((SRC / p).read_bytes())))
        b = plain(article(out_html[stubs[p]]))
        if (r := similarity(a, b)) < 0.85:
            merge_problems.append(f"{p} -> {stubs[p]}: {r:.2f} similar")
        continue
    want = article(decode((SRC / p).read_bytes()))
    got = re.sub(r'<span data-pagefind-filter="year" hidden>\d{4}</span>', "", article(out_html[p]))
    if want != got:
        text_problems.append(p)
check("original message bodies are unchanged", text_problems)
check("redirected original copies closely match the message they redirect to", merge_problems)


def mbox_body(msg):
    parts = [p for p in msg.walk() if not p.is_multipart()]
    out = []
    for p in parts:
        if p.get_content_maintype() == "text":
            raw = p.get_payload(decode=True) or b""
            for enc in ("utf-8", p.get_content_charset() or "cp1252", "cp1252"):
                try:
                    out.append(raw.decode(enc))
                    break
                except (LookupError, UnicodeDecodeError):
                    continue
    return "\n".join(out)


# The mbox can repeat a message under one filename, so a page passes if any copy matches.
# The database's encoding label is not trusted: a body counts as correct if it
# matches the raw mbox text either as stored or decoded per the label.
def ascii_share(t):
    return sum(32 <= ord(c) < 127 or c in "\r\n\t" for c in t) / max(len(t), 1)


matches, checked, garbled = {}, 0, []
for m in all_months:
    db = load_articles(SRC / "database" / f"{m}-article")
    for msg in read_mbox(SRC / f"{m}.txt"):
        mid = (msg.get("Message-ID") or "").strip().strip("<>")
        if mid not in db or f"{m}/{db[mid]['filename']}" in src_pages:
            continue
        p = f"{m}/{db[mid]['filename']}"
        page = out_html.get(resolve(p), "")
        raw = msg.get_payload() if not msg.is_multipart() else ""
        if db[mid].get("ctype") and "Content-Type" not in msg:
            msg["Content-Type"] = db[mid]["ctype"]
        candidates = [mbox_body(msg)]
        if db[mid].get("cenc") and "Content-Transfer-Encoding" not in msg:
            labelled = copy.deepcopy(msg)
            labelled["Content-Transfer-Encoding"] = db[mid]["cenc"]
            candidates.append(mbox_body(labelled))
        text = plain(article(page))
        if raw.strip() and ascii_share(raw) > 0.98 and ascii_share(text) < 0.9:
            garbled.append(f"{p}: mbox body is plain ASCII but page is {ascii_share(text):.0%} ASCII")
        bodies = [" ".join(EMAIL_RE.sub(lambda e: e.group().replace("@", " at "), b).split()) for b in candidates]
        subj = " ".join(EMAIL_RE.sub(lambda e: e.group().replace("@", " at "), db[mid]["subject"]).split())[:40]
        if p in stubs:  # a duplicate copy: the kept page must hold (nearly) the same text
            ok = any(b in text or similarity(b, text) >= 0.85 for b in bodies)
        else:
            ok = any(b in text for b in bodies) and subj in plain(page.split("</H1>")[0])
        matches[p] = matches.get(p, False) or ok
        checked += 1
check(f"regenerated pages ({checked} mbox messages) contain their mbox body and subject",
      sorted(p for p, ok in matches.items() if not ok))
check("regenerated pages are readable where the mbox text is plain ASCII (no mis-decoding)", sorted(set(garbled)))

# --- Duplicates and search ---------------------------------------------------
own = '<link rel="canonical" href="https://taxacom.org/pipermail/taxacom/{}">'
check(f"{len(full)} kept messages are searchable and canonical to themselves",
      (p for p in full if "data-pagefind-body" not in out_html[p] or own.format(p) not in out_html[p]))
check("every redirect points to a kept, searchable message",
      (f"{p} -> {t}" for p, t in stubs.items()
       if t in stubs or t not in out_html or "data-pagefind-body" not in out_html[t]))
check("redirects carry rel=canonical and are not searchable",
      (p for p, t in stubs.items() if own.format(t) not in out_html[p] or "data-pagefind-body" in out_html[p]))

seen, dupes = {}, []
for p in full:
    h = out_html[p]
    key = tuple(" ".join(re.search(rx, h, re.S).group(1).split()) for rx in
                (r'<I data-pagefind-meta="date">(.*?)</I>', r'<B data-pagefind-meta="author">(.*?)</B>',
                 r"<H1[^>]*>(.*?)</H1>")) + (plain(article(h)),)
    if key in seen:
        dupes.append(f"{p} duplicates {seen[key]}")
    seen.setdefault(key, p)
check("no two kept messages have the same date, author, subject and text", dupes)

check("month indexes never list a redirected copy",
      (f"{p} lists {f}" for p in out_pages if re.search(r"/(date|thread|subject|author)\.html$", p)
       for f in re.findall(r'<LI><A HREF="(\d+\.html)">', out_html[p]) if f"{p.split('/')[0]}/{f}" in stubs))
check("index/sort pages are not searchable",
      (p for p in out_pages if not is_msg(p) and "data-pagefind-body" in out_html[p]))

# --- Links -----------------------------------------------------------------
def broken_links(pages, root):
    out = set()
    for p, h in pages:
        hrefs = re.findall(r'(?:href|HREF)="([^"#:]+)(?:#[^"]*)?"', h)
        hrefs += re.findall(r'http-equiv="refresh" content="0; url=([^"]+)"', h)
        for href in hrefs:
            f = root / urljoin("/pipermail/taxacom/" + p, href).lstrip("/").removeprefix("pipermail/taxacom/")
            if f.is_dir():
                f = f / "index.html"
            if not f.exists():
                out.add(f"{p} -> {href}")
    return out


src_broken = broken_links(((p, (SRC / p).read_bytes().decode("latin1")) for p in src_pages), SRC)
out_broken = broken_links(out_html.items(), ARCH)
check(f"no new broken internal links ({len(src_broken)} were already broken in the backup, "
      f"{len(src_broken - out_broken)} of those now fixed)", sorted(out_broken - src_broken))

def outside_article(h):
    a, b = h.find("<!--beginarticle-->"), h.find("<!--endarticle-->")
    return h[:a] + h[b:] if a >= 0 and b >= 0 else h


dead = re.compile(r'(?:href|HREF)="(mailto:[^"]*|https?://(?:lists|mailman\.nhm)\.ku\.edu/[^"]*listinfo[^"]*)"')
check("no mailto: or old listinfo links outside message text",
      (f"{p}: {m.group(1)[:60]}" for p, h in out_html.items() for m in [dead.search(outside_article(h))] if m))
check("home page has the 'list today' section the listinfo links point to",
      [] if 'id="the-list-today"' in (SITE / "index.html").read_text() else ["missing #the-list-today"])

# --- Encoding --------------------------------------------------------------
spots = {
    "2024-November/137849.html": "Pére Cardon",
    "2009-September/031036.html": "POLIBOTÁNICA",
}
check("non-ASCII spot checks", (f"{p}: {s!r} not found" for p, s in spots.items()
                                if s not in html.unescape(out_html.get(resolve(p), ""))))
check("no U+FFFD replacement characters introduced in original pages",
      (p for p in src_messages if p not in stubs and out_html[p].count("�") > decode((SRC / p).read_bytes()).count("�")))

# --- Deployment ------------------------------------------------------------
check("CNAME is taxacom.org", [] if (SITE / "CNAME").read_text().strip() == "taxacom.org" else ["wrong CNAME"])
check("landing page loads the Pagefind UI",
      [] if "pagefind-ui.js" in (SITE / "index.html").read_text() else ["no search UI"])
check("Pagefind index exists (run pagefind first if this fails)",
      [] if (SITE / "pagefind" / "pagefind-entry.json").exists() else ["missing pagefind/pagefind-entry.json"])

# --- Crawling --------------------------------------------------------------
robots = (SITE / "robots.txt").read_text() if (SITE / "robots.txt").exists() else ""
check("robots.txt allows crawling and points to the sitemap",
      [] if "Sitemap: https://taxacom.org/sitemap.xml" in robots and "Disallow: /" not in robots
      else ["robots.txt missing, blocking, or without a Sitemap line"])
index_xml = (SITE / "sitemap.xml").read_text() if (SITE / "sitemap.xml").exists() else ""
map_files = re.findall(r"<loc>https://taxacom\.org/(sitemap-\d+\.xml)</loc>", index_xml)
check("sitemap index lists only sitemap files that exist",
      [f for f in map_files if not (SITE / f).exists()] or ([] if map_files else ["no sitemaps listed"]))
listed, too_big = [], []
for f in map_files:
    locs = re.findall(r"<loc>https://taxacom\.org(/[^<]*)</loc>", (SITE / f).read_text())
    listed += locs
    if len(locs) > 50000 or (SITE / f).stat().st_size > 50 * 1024 * 1024:
        too_big.append(f"{f}: {len(locs)} URLs")
check("each sitemap is within the 50,000-URL / 50 MB limits", too_big)
want = {"/", "/pipermail/taxacom/"} | {f"/pipermail/taxacom/{p}" for p in full}
got = set(listed)
check(f"sitemaps list exactly the home page, month list and {len(full)} kept messages, once each",
      [f"missing {u}" for u in sorted(want - got)] + [f"unexpected {u}" for u in sorted(got - want)]
      + ([f"{len(listed) - len(got)} duplicate entries"] if len(listed) != len(got) else []))

print(f"\n{len(failures)} check(s) failed" if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
