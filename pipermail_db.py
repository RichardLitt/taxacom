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
