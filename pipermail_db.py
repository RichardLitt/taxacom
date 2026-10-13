"""Read Mailman 2 Pipermail archive databases (database/<month>-article).

Each file is a marshal'd dict of message-id -> pickled HyperArch.Article.
Article bodies are emptied once Pipermail writes HTML, but the metadata
(filename, sequence, threadKey, author, date, subject) survives. Classes
are stubbed, so unpickling runs no archive code.
"""
import io
import marshal
import pickle


class _Article:
    def __setstate__(self, state):
        self.__dict__.update(state)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        return _Article


def _text(v):
    return v.decode("latin1") if isinstance(v, bytes) else v


def load_articles(path):
    """Return {message-id: dict of article fields} for one month."""
    with open(path, "rb") as fh:
        raw = marshal.load(fh)
    out = {}
    for key, blob in raw.items():
        a = _Unpickler(io.BytesIO(blob), encoding="latin1").load().__dict__
        out[_text(key)] = {k: _text(v) for k, v in a.items()}
    return out


import base64
import email
import re

# Pipermail separator: "From user at host  Wed Dec 10 05:08:09 2025"
_FROM_RE = re.compile(rb"^From \S.*\s\w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d \d{4}\r?$", re.M)


def read_mbox(path):
    """Yield email.message.Message objects from a Pipermail <month>.txt file."""
    data = open(path, "rb").read()
    starts = [m.start() for m in _FROM_RE.finditer(data)]
    for a, b in zip(starts, starts[1:] + [len(data)]):
        chunk = data[a:b]
        yield email.message_from_bytes(chunk[chunk.index(b"\n") + 1:])


_BASE64_LINE_RE = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


def _looks_base64(body):
    lines = [l.strip() for l in body.strip().splitlines()]
    joined = "".join(lines)
    if not joined or len(joined) % 4 or not all(_BASE64_LINE_RE.match(l) for l in lines):
        return False
    try:
        data = base64.b64decode(joined, validate=True)
    except ValueError:
        return False
    # Real encoded mail decodes to text; plain words like "test" decode to noise.
    text = data.decode("utf-8", errors="replace")
    return sum((c.isprintable() and c != "\ufffd") or c in "\r\n\t" for c in text) >= 0.95 * max(len(text), 1)

_QP_RE = re.compile(r"=[0-9A-Fa-f]{2}|=\r?\n")


def restore_headers(msg, article):
    """Put back the Content-Type / Content-Transfer-Encoding the .txt dropped.

    The database records how a message arrived, but the .txt sometimes
    stored the body already decoded (e.g. 3,000 messages labelled base64
    are plain text). Only restore the encoding if the body still looks
    encoded, or plain text gets decoded into junk.
    """
    if article.get("ctype") and "Content-Type" not in msg:
        msg["Content-Type"] = article["ctype"]
    cenc = (article.get("cenc") or "").lower()
    if cenc and "Content-Transfer-Encoding" not in msg and not msg.is_multipart():
        body = msg.get_payload()
        if (cenc == "base64" and _looks_base64(body)) or (cenc == "quoted-printable" and _QP_RE.search(body)):
            msg["Content-Transfer-Encoding"] = cenc
