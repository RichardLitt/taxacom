"""Regenerate Pipermail HTML for months whose HTML was not in the backup.

Bodies come from <month>.txt (the mbox Pipermail kept); page numbers,
threading and author/subject come from database/<month>-article, so each
page lands at the URL it had on lists.ku.edu. Output mimics Pipermail's
own markup so build.py treats it like any other month.
"""
import html
import re
from datetime import datetime
from email.header import decode_header, make_header
from zoneinfo import ZoneInfo

from pipermail_db import load_articles, read_mbox, restore_headers

TZ = ZoneInfo("America/Chicago")  # lists.ku.edu server time, as in the original pages
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
URL_RE = re.compile(r"(https?://[^\s<>\"]+|ftp://[^\s<>\"]+)")
LISTINFO = "https://lists.ku.edu/listinfo/taxacom"


def obscure(s):
    return EMAIL_RE.sub(r"\1 at \2", s)


def header(msg, name):
    v = msg.get(name)
    if v is None:
        return ""
    try:
        return str(make_header(decode_header(v))).strip()
    except Exception:
        return str(v).strip()


def body_text(msg):
    parts = [p for p in msg.walk() if not p.is_multipart()] if msg.is_multipart() else [msg]
    out = []
    for p in parts:
        if p.get_content_maintype() != "text":
            continue
        raw = p.get_payload(decode=True) or b""
        cs = p.get_content_charset() or "utf-8"
        for enc in ("utf-8", cs, "cp1252"):  # labels are often wrong; valid UTF-8 is UTF-8
            try:
                out.append(raw.decode(enc))
                break
            except (LookupError, UnicodeDecodeError):
                continue
        else:
            out.append(raw.decode("cp1252", errors="replace"))
    return "\n".join(out)


def body_html(text):
    # Escape, then linkify URLs, as Pipermail does; addresses stay obscured.
    pieces = []
    for i, chunk in enumerate(URL_RE.split(obscure(text))):
        if i % 2:
            u = html.escape(chunk)
            pieces.append(f'<A HREF="{u}">{u}</A>')
        else:
            pieces.append(html.escape(chunk, quote=False).replace('"', "&quot;"))
    return "".join(pieces)


def show_date(epoch):
    return datetime.fromtimestamp(epoch, TZ).strftime("%a %b %e %H:%M:%S %Z %Y")


def esc(s):
    return html.escape(s or "", quote=False)


def sort_links(seq):
    return "\n".join(f'              <a href="{k}.html#{seq}">[ {k} ]</a>' for k in ("date", "thread", "subject", "author"))


def nav(prev, nxt):
    lines = []
    if prev:
        lines.append(f'        <LI>Previous message: <A HREF="{prev["filename"]}">{esc(prev["subject"])}\n</A></li>')
    if nxt:
        lines.append(f'        <LI>Next message: <A HREF="{nxt["filename"]}">{esc(nxt["subject"])}\n</A></li>')
    return "\n".join(lines)


def message_html(a, prev, nxt):
    seq = a["filename"][:-5]
    links = nav(prev, nxt)
    return f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<HTML>
 <HEAD>
   <TITLE> {esc(a["subject"])}
   </TITLE>
   <LINK REL="Index" HREF="index.html" >
   <META NAME="robots" CONTENT="index,nofollow">
   <style type="text/css">
       pre {{
           white-space: pre-wrap;
           }}
   </style>
   <META http-equiv="Content-Type" content="text/html; charset=utf-8">
 </HEAD>
 <BODY BGCOLOR="#ffffff">
   <H1>{esc(a["subject"])}</H1>
    <B>{esc(a["author"])}</B>
    {esc(a["email"])}<BR>
    <I>{show_date(a["epoch"])}</I>
    <P><UL>
{links}
         <LI> <B>Messages sorted by:</B>
{sort_links(seq)}
         </LI>
       </UL>
    <HR>
<!--beginarticle-->
<PRE>{body_html(a["body"])}
</PRE>
<!--endarticle-->
    <HR>
    <P><UL>
        <!--threads-->
{links}
         <LI> <B>Messages sorted by:</B>
{sort_links(seq)}
         </LI>
       </UL>

<hr>
<a href="{LISTINFO}">More information about the Taxacom
mailing list</a><br>
</body></html>
"""


def index_html(month_label, kind, arts, ordered):
    title = f"The Taxacom {month_label} Archive by {kind}"
    items = []
    for a in ordered:
        seq = a["filename"][:-5]
        indent = "<UL>" * a.get("depth", 0)
        outdent = "</UL>" * a.get("depth", 0)
        items.append(f'{indent}<LI><A HREF="{a["filename"]}">{esc(a["subject"])}\n</A><A NAME="{seq}">&nbsp;</A>\n'
                     f'<I>{esc(a["author"])}\n</I>{outdent}')
    first = min(arts, key=lambda a: a["epoch"])
    last = max(arts, key=lambda a: a["epoch"])
    sorts = " ".join(f'<a href="{k}.html">[ {k} ]</a>' for k in ("thread", "subject", "author", "date") if k != kind)
    return f"""<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<HTML>
  <HEAD>
     <title>{title}</title>
     <META NAME="robots" CONTENT="noindex,follow">
     <META http-equiv="Content-Type" content="text/html; charset=utf-8">
  </HEAD>
  <BODY BGCOLOR="#ffffff">
      <a name="start"></A>
      <h1>{month_label} Archives by {kind}</h1>
      <ul>
         <li> <b>Messages sorted by:</b>
	        {sorts}
	     <li><b><a href="{LISTINFO}">More info on this list...
                    </a></b></li>
      </ul>
      <p><b>Starting:</b> <i>{show_date(first["epoch"])}</i><br>
         <b>Ending:</b> <i>{show_date(last["epoch"])}</i><br>
         <b>Messages:</b> {len(arts)}<p>
     <ul>
{chr(10).join(items)}
    </ul>
    <p>
      <a name="end"><b>Last message date:</b></a>
       <i>{show_date(last["epoch"])}</i><br>
    <b>Archived on:</b> <i>{show_date(last["epoch"])}</i>
    <p>
   <ul>
         <li> <b>Messages sorted by:</b>
	        {sorts}
	     <li><b><a href="{LISTINFO}">More info on this list...
                    </a></b></li>
     </ul>
     <p>
     <hr>
     <i>This archive was generated by Pipermail 0.09 (Mailman edition).</i>
  </BODY>
</HTML>
"""


def strip_subject(s):
    return re.sub(r"^((re|fw|fwd|aw)\s*:\s*|\[taxacom\]\s*|taxacom:\s*)+", "", s, flags=re.I).lower()


def articles_for_month(txt_path, db_path, next_free):
    """Return (articles, next_free). Each article dict has filename, subject,
    author, email, epoch, body, threadKey. Messages missing from the database
    get fresh numbers starting at next_free (they never had a public URL)."""
    db = load_articles(db_path)
    arts = {}
    for msg in read_mbox(txt_path):
        mid = header(msg, "Message-ID").strip("<>")
        if mid in arts:
            continue  # the mbox repeats some messages; one page each
        d = db.get(mid)
        if d:
            restore_headers(msg, d)
            a = {"filename": d["filename"], "subject": obscure(d["subject"]), "author": obscure(d["author"]),
                 "email": obscure(d["email"]), "epoch": int(d["date"]), "threadKey": d["threadKey"]}
        else:
            try:
                epoch = int(datetime.strptime(header(msg, "Date")[:31].strip(), "%a, %d %b %Y %H:%M:%S %z").timestamp())
            except ValueError:
                epoch = 0
            a = {"filename": f"{next_free:06d}.html", "subject": obscure(header(msg, "Subject")),
                 "author": obscure(re.sub(r"^.*\((.*)\)$", r"\1", header(msg, "From"))),
                 "email": obscure(header(msg, "From").split(" (")[0]), "epoch": epoch,
                 "threadKey": f"{epoch:011d}.{next_free:06d}-"}
            next_free += 1
        a["body"] = body_text(msg)
        arts[mid] = a
    # Messages sharing a filename (repeat imports under new ids) collapse to one page.
    by_file = {}
    for a in arts.values():
        by_file.setdefault(a["filename"], a)
    return list(by_file.values()), next_free


def render_month(month, arts):
    """Return {filename: html} for one month's message and index pages."""
    y, mname = month.split("-")
    label = f"{mname} {y}"
    by_date = sorted(arts, key=lambda a: (a["epoch"], a["filename"]))
    pages = {}
    for i, a in enumerate(by_date):
        prev = by_date[i - 1] if i else None
        nxt = by_date[i + 1] if i + 1 < len(by_date) else None
        pages[a["filename"]] = message_html(a, prev, nxt)
    thread = sorted(arts, key=lambda a: a["threadKey"])
    for a in thread:
        a["depth"] = min(a["threadKey"].count("-") - 1, 10)
    pages["date.html"] = index_html(label, "date", arts, by_date)
    pages["thread.html"] = index_html(label, "thread", arts, thread)
    for a in arts:
        a["depth"] = 0
    pages["subject.html"] = index_html(label, "subject", arts,
                                       sorted(arts, key=lambda a: (strip_subject(a["subject"]), a["epoch"])))
    pages["author.html"] = index_html(label, "author", arts,
                                      sorted(arts, key=lambda a: (a["author"].lower(), a["epoch"])))
    pages["index.html"] = '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=thread.html"><a href="thread.html">thread.html</a>'
    return pages
