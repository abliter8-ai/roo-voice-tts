#!/usr/bin/env python3
"""
normalize.py -- structural text normalization front-end for the Roo NeuTTS pipeline.

Runs BEFORE espeak phonemization, on the raw user text.

THE GOVERNING PRINCIPLE — read this before adding a rule
--------------------------------------------------------
espeak-ng's en-GB front-end already reads numbers, decimals, ordinals,
percentages, clock times, currencies-as-digits and most symbols CORRECTLY.
Measured on the shipped path:

    "1234567890123"  -> "one trillion two hundred and thirty four billion ..."
    "27.4%"          -> "twenty seven point four percent"
    "09:45"          -> "nine forty five"
    "22nd"           -> "twenty second"
    "COVID-19"       -> "covid nineteen"
    "R&D", "A/B"     -> "R and D", "A slash B"

So this module performs **NO number-to-word conversion**. It rewrites only the
STRUCTURE that espeak demonstrably mangles, and leaves the digits in place for
espeak to read. Every rule below is backed by a measured espeak failure, listed
next to it. A rule that merely duplicates espeak is not neutral — it is a
regression risk with no upside, because it replaces a correct reading with our
own reimplementation of one.

Measured espeak failures this module repairs:

    "2024-03-14"        -> "two thousand and twenty four DASH zero three DASH ..."
    "2024-03-14T09:45Z" -> "... DASH ... TEE nine forty five zero zero ZED"
    "3-2", "50-50"      -> "three DASH two", "fifty DASH fifty"
    "555-1234"          -> "five hundred and fifty five DASH one thousand ..."
    "8837-XZ"           -> "eight thousand eight hundred and thirty seven EKSZED"
    "$1,200"            -> "DOLLAR one thousand two hundred"  (symbol first, singular)
    "Q3"                -> "cue three"
    "Prof./vs./Ms./Mt./approx./No./Inc./Jr./Sgt./Fig./Jan." -> spelled or clipped

Abbreviations espeak already reads correctly (Dr., Mr., Mrs., St., e.g., etc.)
are still expanded here, for a second reason: their trailing period is a
sentence terminator to `split_text`, and a chunk boundary landing on "Dr." would
hand the model a fragment — the out-of-distribution rambling failure v2.0.0 fixed.

Safety contract: `normalize()` NEVER raises and NEVER returns empty. It is a
cosmetic front-end; it must not be able to take generation down. On any internal
error it returns the input unchanged. Tests exercise `_normalize` directly so
real errors surface there rather than being masked.

Public API:  normalize(text) -> str
"""
import re

_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _ordinal_suffix(day: int) -> str:
    """Day-of-month suffix only (1..31). espeak reads '14th' -> 'fourteenth'
    correctly, so we emit the digits plus a suffix rather than words."""
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


# --------------------------------------------------------------- abbreviations
# Two classes, because the trailing period is ambiguous: it is both part of the
# abbreviation and a possible sentence terminator, and `split_text` treats it as
# a sentence end either way.
#
# PREFIX — grammatically cannot end a sentence ("Dr. Smith"). The period is
# always noise, so drop it. Dropping it also stops split_text cutting a chunk
# after "Dr." and handing the model a fragment.
_ABBR_PREFIX = [
    # espeak gets these WRONG (spells or clips them)
    (r"\bProf\.", "Professor"), (r"\bMs\.", "Miz"), (r"\bMt\.", "Mount"),
    (r"\bvs\.", "versus"), (r"\bapprox\.", "approximately"),
    (r"\bNo\.\s*(?=\d)", "number "), (r"\bSgt\.", "Sergeant"),
    (r"\bCapt\.", "Captain"), (r"\bRd\.", "Road"), (r"\bAve\.", "Avenue"),
    (r"\bBlvd\.", "Boulevard"), (r"\bFig\.", "Figure"),
    (r"\bJan\.", "January"), (r"\bFeb\.", "February"), (r"\bMar\.", "March"),
    (r"\bApr\.", "April"), (r"\bJun\.", "June"), (r"\bJul\.", "July"),
    (r"\bAug\.", "August"), (r"\bSept?\.", "September"), (r"\bOct\.", "October"),
    (r"\bNov\.", "November"), (r"\bDec\.", "December"),
    # espeak reads these correctly — expanded only to protect sentence splitting
    (r"\bDr\.", "Doctor"), (r"\bMr\.", "Mister"), (r"\bMrs\.", "Missus"),
    (r"\bSt\.", "Saint"),
    (r"\be\.g\.", "for example"), (r"\bi\.e\.", "that is"),
]

# SUFFIX — can legitimately end a sentence ("...of Acme Inc. Q3 rose..."). Keep
# the period when what follows looks like a new sentence (whitespace then a
# capital, or end of text), drop it otherwise. Getting this wrong runs two
# sentences together and loses the pause.
_ABBR_SUFFIX = [
    (r"\bInc\.", "Incorporated"), (r"\bLtd\.", "Limited"),
    (r"\bJr\.", "Junior"), (r"\bSr\.", "Senior"),
    (r"\betc\.", "et cetera"), (r"\bPh\.\s?D\.", "P H D"),
]
_SENTENCE_END_AHEAD = r"(?=\s+[\"'(‘“]?[A-Z]|\s*$)"

# ------------------------------------------------------------------- currency
# espeak emits the unit BEFORE the number and never pluralises ("$1,200" ->
# "dollar one thousand two hundred"). We reorder and pluralise; the digits stay
# digits so espeak still reads the number.
_CUR = {"$": ("dollar", "dollars"), "€": ("euro", "euros"),
        "£": ("pound", "pounds"), "¥": ("yen", "yen")}
_CURRENCY_RE = re.compile(
    r"([$€£¥])\s?(\d(?:[\d,]*\d)?(?:\.\d+)?)"      # must END on a digit, so a
    r"(\s+(?:thousand|million|billion|trillion))?",  # trailing comma stays put
    re.I)

# ISO forms. Validated in the handlers — an out-of-range month/day is left alone
# rather than rewritten or crashed on.
_ISO_TS_RE = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2})?\s*"
    r"(?:Z|[+-]\d{2}:?\d{2})?")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Hyphenated token that STARTS with a digit and contains a letter somewhere
# (8837-XZ). The digit-first requirement is deliberate: espeak reads the
# letter-first forms (COVID-19, GPT-4, RTX-5060) correctly, so they must not match.
_ID_CODE_RE = re.compile(r"\b\d[\dA-Za-z]*(?:-[\dA-Za-z]+)+\b")

# Hyphenated groups of pure digits: a range (3-2), a year range (2024-2025) or a
# phone/serial (555-1234). Disambiguated in the handler.
_DIGIT_GROUPS_RE = re.compile(r"\b\d+(?:-\d+)+\b")

_QUARTER_RE = re.compile(r"\bQ([1-4])\b")

# Clock times and any other digit:digit pair. This rule exists because of the
# LIBRARY phonemizer, not the espeak CLI — they disagree, and the library is what
# the engine actually runs. With preserve_punctuation=True (a training-time
# setting we cannot change), "09:45" phonemizes to `zˈiəɹəʊ nˈaɪn:fˈɔːti fˈaɪv`:
# the hour reads as "zero nine", and a bare ':' is glued between two phoneme
# tokens with no space — a form that appears nowhere in training, where colons
# are separated by spaces as normal prose punctuation. Splitting the pair fixes
# both: "9 45" reads "nine forty five" and leaves the phoneme stream clean.
_CLOCK_RE = re.compile(r"\b(\d{1,2}):([0-5]\d)(?::[0-5]\d)?\b")
_COLON_BETWEEN_DIGITS_RE = re.compile(r"(?<=\d):(?=\d)")


def _valid_date(y: int, mo: int, d: int) -> bool:
    return 1 <= mo <= 12 and 1 <= d <= 31 and 1000 <= y <= 2999


def _spoken_date(y: str, mo: str, d: str) -> str:
    day = int(d)
    return f"the {day}{_ordinal_suffix(day)} of {_MONTHS[int(mo)]} {y}"


def _iso_ts(m):
    y, mo, d, hh, mi = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    if not _valid_date(int(y), int(mo), int(d)):
        return m.group(0)
    out = _spoken_date(y, mo, d)
    if int(hh) <= 23 and int(mi) <= 59:
        out += f" at {hh}:{mi}"          # espeak reads "09:45" as "nine forty five"
    return out


def _iso_date(m):
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if not _valid_date(int(y), int(mo), int(d)):
        return m.group(0)
    return _spoken_date(y, mo, d)


def _spell_chars(token: str) -> str:
    """Digits and letters, one at a time, hyphens dropped: '8837-XZ' ->
    '8 8 3 7 X Z'. Digits stay as digits (espeak says 'eight eight three seven');
    letters are upper-cased so espeak spells rather than pronounces them."""
    return " ".join(c.upper() for c in token if c.isalnum())


def _id_code(m):
    tok = m.group(0)
    if not any(c.isalpha() for c in tok):
        return tok                       # pure digits -> _digit_groups handles it
    return _spell_chars(tok)


def _digit_groups(m):
    tok = m.group(0)
    groups = tok.split("-")
    digits = sum(len(g) for g in groups)
    both_years = (len(groups) == 2
                  and all(len(g) == 4 and 1000 <= int(g) <= 2999 for g in groups))
    if both_years:
        return " to ".join(groups)       # "2024-2025" -> "2024 to 2025"
    if len(groups) >= 3 or digits >= 7:
        return _spell_chars(tok)         # "555-1234" -> "5 5 5 1 2 3 4"
    return " to ".join(groups)           # "3-2" -> "3 to 2"


def _clock(m):
    h, mi = int(m.group(1)), m.group(2)
    if h > 23:
        return m.group(0).replace(":", " ")   # not a time; just unglue it
    if mi == "00":
        return f"{h} o'clock"
    return f"{h} {mi}"                        # seconds, if any, are dropped


def _currency(m):
    sym, num, scale = m.group(1), m.group(2), m.group(3) or ""
    unit = _CUR[sym][0] if num.rstrip("0").rstrip(".") == "1" else _CUR[sym][1]
    return f"{num}{scale} {unit}"


def _normalize(text: str) -> str:
    """The real implementation. Raises on programming errors so tests catch them;
    callers go through normalize(), which is fail-safe."""
    t = text
    for pat, rep in _ABBR_PREFIX:
        t = re.sub(pat, rep, t)
    for pat, rep in _ABBR_SUFFIX:
        t = re.sub(pat + _SENTENCE_END_AHEAD, rep + ".", t)   # keeps the full stop
        t = re.sub(pat, rep, t)                               # mid-sentence

    t = _ISO_TS_RE.sub(_iso_ts, t)       # before _ISO_DATE_RE and the hyphen rules
    t = _ISO_DATE_RE.sub(_iso_date, t)
    t = _ID_CODE_RE.sub(_id_code, t)     # digit-first mixed tokens only
    t = _DIGIT_GROUPS_RE.sub(_digit_groups, t)
    t = _CURRENCY_RE.sub(_currency, t)
    t = _QUARTER_RE.sub(lambda m: f"quarter {m.group(1)}", t)
    t = _CLOCK_RE.sub(_clock, t)                    # after _iso_ts, which emits HH:MM
    t = _COLON_BETWEEN_DIGITS_RE.sub(" ", t)        # ratios etc: "16:9" -> "16 9"

    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def normalize(text: str) -> str:
    """Fail-safe wrapper. A cosmetic front-end must never be able to break
    generation: on any internal error, or if a rule ate the whole string, the
    original text is returned and espeak reads it as it did before."""
    try:
        out = _normalize(text)
    except Exception:
        return text
    return out if out.strip() else text


if __name__ == "__main__":
    import sys
    src = " ".join(sys.argv[1:]) or sys.stdin.read()
    print(normalize(src))
