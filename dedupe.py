"""Find duplicate copies of messages left by repeat imports of the archive.

Two message pages are the same message if they have the same date line and
either
  * an identical body, or
  * the same author and subject, and bodies that are at least 90% similar
    once tags, whitespace and Mailman-inserted URLs (listinfo links wrapped
    around addresses, scrubbed-attachment links) are ignored.
The copy kept is the one in Pipermail's database (the one the original
month indexes link to); failing that, the lowest-numbered copy.
"""
import html as htmllib
import re
from difflib import SequenceMatcher

SIMILARITY = 0.9
MAILMAN_URL_RE = re.compile(r"https?://\S*(?:mailman|/attachments/)\S*")


def field(h, pattern):
    m = re.search(pattern, h, re.S | re.I)
    return " ".join(m.group(1).split()) if m else ""


def article(h):
    return h[h.find("<!--beginarticle-->"):h.find("<!--endarticle-->")]


def normalised_body(h):
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", article(h)))
    return " ".join(MAILMAN_URL_RE.sub(" ", text).split())


def similar(a, b):
    if a == b:
        return True
    sm = SequenceMatcher(None, a, b, autojunk=False)
    return sm.real_quick_ratio() >= SIMILARITY and sm.quick_ratio() >= SIMILARITY and sm.ratio() >= SIMILARITY


def find_canonical(pages, preferred=frozenset()):
    """pages: {url: Pipermail message html}; preferred: urls to keep when they
    have copies. Returns {url: canonical url}; a kept copy maps to itself."""
    parent = {}
    rank = lambda u: (u not in preferred, u)

    def root(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(a, b):
        ra, rb = root(a), root(b)
        if ra != rb:
            keep, drop = sorted((ra, rb), key=rank)
            parent[drop] = keep

    exact, loose = {}, {}
    norm = {}
    for url in sorted(pages):
        h = pages[url]
        parent[url] = url
        date = field(h, r"<I>(.*?)</I>")
        e = (date, article(h))
        if e in exact:
            union(exact[e], url)
            continue
        exact[e] = url
        norm[url] = normalised_body(h)
        key = (date, field(h, r"<B>(.*?)</B>").lower(), field(h, r"<H1>(.*?)</H1>").lower())
        for other in loose.setdefault(key, []):
            if similar(norm[other], norm[url]):
                union(other, url)
                break
        else:
            loose[key].append(url)
    return {u: root(u) for u in pages}


def drop_index_entries(index_html, removed):
    """Remove <LI> entries for removed filenames from a Pipermail index page."""
    def keep(m):
        return "" if m.group(1) in removed else m.group(0)
    return re.sub(r'<LI><A HREF="(\d+\.html)">.*?</I>\n?', keep, index_html, flags=re.S)
