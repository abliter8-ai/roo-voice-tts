#!/usr/bin/env python3
"""
normalize.py -- text normalization front-end for the Roo NeuTTS pipeline.

Runs BEFORE espeak phonemization. Raw espeak reads digits, dates, times, ISO
timestamps and symbols literally and often wrong for this voice: it says "dash"
for '-', spells "2024" oddly, reads "Q3" as letters, says "tee" etc. That is
failure mode #1 behind the elevated user-issue rate. This module expands the
common machine-y tokens into plain spoken English so espeak gets clean words.

Design goals:
  * self-contained (no num2words/inflect) so it drops into Dave's engine as-is
  * conservative: only rewrite tokens we are confident about; never mangle prose
  * British reading ("one hundred and twenty", "the fourteenth of March")

Public API:  normalize(text) -> str
"""
import re

# ---------------------------------------------------------------- numbers -----
_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]
_ORD_IRR = {"one": "first", "two": "second", "three": "third", "five": "fifth",
            "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_MONTH_RE = "|".join(_MONTHS[1:])


def _under_1000(n):
    w = []
    if n >= 100:
        w += [_ONES[n // 100], "hundred"]
        n %= 100
        if n:
            w.append("and")
    if n >= 20:
        w.append(_TENS[n // 10])
        if n % 10:
            w.append(_ONES[n % 10])
    elif n > 0:
        w.append(_ONES[n])
    return w


def int_to_words(n):
    n = int(n)
    if n == 0:
        return "zero"
    neg = n < 0
    n = abs(n)
    parts = []
    for val, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= val:
            parts += _under_1000(n // val) + [name]
            n %= val
    if n:
        parts += _under_1000(n)
    s = " ".join(parts)
    return ("minus " + s) if neg else s


def ordinal_words(n):
    w = int_to_words(n)
    head = w.split()
    last = head[-1]
    if last in _ORD_IRR:
        head[-1] = _ORD_IRR[last]
    elif last.endswith("y"):
        head[-1] = last[:-1] + "ieth"
    else:
        head[-1] = last + "th"
    return " ".join(head)


def year_words(y):
    y = int(y)
    if 2000 <= y <= 2009:
        return "two thousand" if y == 2000 else "two thousand and " + int_to_words(y - 2000)
    if 1100 <= y < 2000 or 2010 <= y < 2100:
        hi, lo = divmod(y, 100)
        if lo == 0:
            return int_to_words(hi) + " hundred"
        lo_w = int_to_words(lo) if lo >= 10 else "oh " + int_to_words(lo)
        return int_to_words(hi) + " " + lo_w
    return int_to_words(y)


def _decimal_words(intp, frac):
    left = int_to_words(int(intp)) if intp not in ("", None) else "zero"
    digits = " ".join(_ONES[int(d)] for d in frac)
    return f"{left} point {digits}"


def _time_words(h, m):
    h, m = int(h), int(m)
    if h > 12:          # 24-hour clock -> 12-hour spoken form
        h -= 12
    elif h == 0:
        h = 12
    hw = int_to_words(h)
    if m == 0:
        return f"{hw} o'clock"
    if m < 10:
        return f"{hw} oh {int_to_words(m)}"
    return f"{hw} {int_to_words(m)}"


# ---------------------------------------------------------------- patterns ----
# Abbreviations first: also removes periods that would break sentence splitting.
_ABBR = [
    (r"\bDr\.", "Doctor"), (r"\bMr\.", "Mister"), (r"\bMrs\.", "Missus"),
    (r"\bMs\.", "Miz"), (r"\bProf\.", "Professor"), (r"\bSt\.", "Saint"),
    (r"\bMt\.", "Mount"), (r"\bvs\.", "versus"), (r"\be\.g\.", "for example"),
    (r"\bi\.e\.", "that is"), (r"\betc\.", "et cetera"), (r"\bapprox\.", "approximately"),
    (r"\bNo\.\s*(?=\d)", "number "),
]

_SYMBOL = [
    (r"\s*&\s*", " and "), (r"(?<=\d)\s*%", " percent"),
    (r"\s*\+\s*", " plus "), (r"\s*=\s*", " equals "),
    (r"(?<=\w)\s*/\s*(?=\w)", " slash "),
    (r"(?<=\d)\s*-\s*(?=\d)", " to "),   # numeric range 3-4 -> "3 to 4"
    (r"(?<=\s)@(?=\s)", " at "), (r"(?<=\s)#(?=\d)", "number "),
]

_CUR = {"$": "dollars", "€": "euros", "£": "pounds"}


def _iso_ts(m):
    y, mo, d, h, mi = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    date = f"the {ordinal_words(int(d))} of {_MONTHS[int(mo)]} {year_words(y)}"
    return f"{date} at {_time_words(h, mi)}"


def _iso_date(m):
    y, mo, d = m.group(1), m.group(2), m.group(3)
    return f"the {ordinal_words(int(d))} of {_MONTHS[int(mo)]} {year_words(y)}"


def _spell_code(m):
    # hyphenated alphanumeric ID (8837-XZ) -> digits as words, letters spelled
    parts = []
    for ch in m.group(0):
        if ch.isdigit():
            parts.append(_ONES[int(ch)])
        elif ch == "-":
            continue
        else:
            parts.append(ch.upper())
    return " ".join(parts)


def _cur(m):
    sym, num, scale = m.group(1), m.group(2), m.group(3) or ""
    num = num.replace(",", "")
    if "." in num:
        i, f = num.split(".")
        val = _decimal_words(i, f)
    else:
        val = int_to_words(num)
    scale = (" " + scale) if scale else ""
    return f"{val}{scale} {_CUR[sym]}"


def normalize(text):
    t = text
    for pat, rep in _ABBR:
        t = re.sub(pat, rep, t)

    # ISO timestamp  2024-03-14T09:45:00Z  (seconds + Z optional)
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2})?Z?\b", _iso_ts, t)
    # ISO date       2024-03-14
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _iso_date, t)

    # hyphenated alphanumeric IDs (8837-XZ) -> spelled out, before number rules
    t = re.sub(r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b",
               _spell_code, t)

    # currency  $1,200 / €1.2 million / £5
    t = re.sub(r"([$€£])\s?([\d,]+(?:\.\d+)?)(?:\s+(million|billion|thousand))?",
               _cur, t, flags=re.I)

    # "14 March 2024"  and  "March 14, 2024"
    t = re.sub(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b",
               lambda m: f"the {ordinal_words(int(m.group(1)))} of {m.group(2)} {year_words(m.group(3))}",
               t)
    t = re.sub(rf"\b({_MONTH_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
               lambda m: f"the {ordinal_words(int(m.group(2)))} of {m.group(1)} {year_words(m.group(3))}",
               t)

    # standalone clock time  09:45(:00)
    t = re.sub(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\b",
               lambda m: _time_words(m.group(1), m.group(2)), t)

    # quarters  Q3 -> "quarter three"
    t = re.sub(r"\bQ([1-4])\b", lambda m: f"quarter {int_to_words(m.group(1))}", t)

    # percent / symbols
    for pat, rep in _SYMBOL:
        t = re.sub(pat, rep, t)

    # ordinals  3rd -> third
    t = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b",
               lambda m: ordinal_words(int(m.group(1))), t)

    # decimals  1.2 -> "one point two"
    t = re.sub(r"\b(\d+)\.(\d+)\b",
               lambda m: _decimal_words(m.group(1), m.group(2)), t)

    # bare integers (with optional thousands commas)
    t = re.sub(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b",
               lambda m: int_to_words(m.group(0).replace(",", "")), t)

    # tidy whitespace
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


if __name__ == "__main__":
    import sys
    src = " ".join(sys.argv[1:]) or sys.stdin.read()
    print(normalize(src))
