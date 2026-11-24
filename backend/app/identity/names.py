"""Indian-name-aware normalisation, phonetic keys and similarity.

Problems this handles (all common in Indian admission data):
  * initials:            "R. Karthik"  vs  "Karthik Ramasamy"
  * token order:         "Kumar Ramesh" vs "Ramesh Kumar"
  * transliteration:     "Lakshmi" / "Laxmi", "Sreeram" / "Shriram", "Vasanth" / "Wasant"
  * honorifics/noise:    "Mr. Arun Kumar", "Kum. Priya"
"""
from __future__ import annotations

import re
import unicodedata

import jellyfish
from rapidfuzz.distance import JaroWinkler

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "shri", "sri", "smt", "kum", "kumari", "selvi",
               "thiru", "tmt", "master", "late"}

# Order matters: longer patterns first.
_FOLDS = [
    ("ksh", "x"), ("ks", "x"), ("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"),
    ("ou", "u"), ("sh", "s"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"), ("gh", "g"),
    ("ph", "f"), ("ch", "c"), ("jh", "j"), ("w", "v"), ("z", "j"), ("q", "k"), ("y", "i"),
]


def normalize(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z\s.]", " ", s).replace(".", " ")
    toks = [t for t in s.split() if t and t not in _HONORIFICS]
    return " ".join(toks)


def fold(token: str) -> str:
    t = token
    for a, b in _FOLDS:
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)       # collapse doubled letters
    return t


def tokens(name: str) -> list[str]:
    return [fold(t) for t in normalize(name).split()]


def phonetic_key(name: str | None) -> str:
    """Order-independent phonetic key over full tokens (initials ignored). Used for blocking."""
    toks = [t for t in tokens(name or "") if len(t) > 1]
    keys = sorted(jellyfish.metaphone(t) for t in toks)
    return " ".join(k for k in keys if k)


def _tok_sim(a: str, b: str) -> float:
    if len(a) == 1 or len(b) == 1:                 # initial vs full token
        return 0.9 if a[0] == b[0] else 0.0
    return JaroWinkler.similarity(a, b)


def name_similarity(a: str | None, b: str | None) -> float:
    """0..1, order-independent, initials-aware.

    Greedy token alignment: every token of the shorter name must find a partner in the longer
    one. A full given name that matches nothing caps the score at 0.7, so a shared surname
    ("Rohit Agarwal" vs "Saurabh Agarwal") cannot carry two different people over the
    threshold. Whole-string comparison is only used when the token counts differ
    ("Lakshmipriya" vs "Lakshmi Priya").
    """
    ta, tb = tokens(a or ""), tokens(b or "")
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    remaining = list(long_)
    scores, weak_full_token = [], False
    for t in sorted(short, key=len, reverse=True):     # match full tokens before initials
        best_i, best = -1, 0.0
        for i, u in enumerate(remaining):
            s_ = _tok_sim(t, u)
            if s_ > best:
                best_i, best = i, s_
        scores.append(best)
        if len(t) > 1 and best < 0.75:
            weak_full_token = True
        if best_i >= 0:
            remaining.pop(best_i)
    align = sum(scores) / len(scores)
    if len(short) == 1 and len(long_) > 1:
        align *= 0.9                                   # one-word name vs a full name: less certain
    if weak_full_token:
        align = min(align, 0.7)
    if len(ta) != len(tb):
        whole = JaroWinkler.similarity("".join(ta), "".join(tb))
        align = max(align, whole if whole >= 0.93 else 0.0)
    return round(align, 4)
