"""Step 2 of specs/ask-a-question.md (section 6.2): exact values read from the question text by plain
code, never by the model - dates, "top N", countries, branches, regions, segments, products, IFRS 9
stages, metrics and "by <dimension>".

Matching works on a lower-cased copy of the question. Each match "uses up" its words, and the
extractors run most-specific first, so "car loans" is a product (not CAR), "Mount Lebanon" a region
(not the country), and "cost to income" one metric (not cost + income).
"""
import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional

from . import vocab

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTH_ABBR = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
MONTH_ABBR["sept"] = 9
_MONTH_RE = "|".join(sorted(list(MONTHS) + list(MONTH_ABBR), key=len, reverse=True))
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "twenty": 20}
SORT_WORDS = {  # word -> high | low | good | bad (section 6.4)
    "top": "high", "highest": "high", "largest": "high", "biggest": "high", "most": "high", "maximum": "high",
    "lowest": "low", "smallest": "low", "least": "low", "bottom": "low", "minimum": "low",
    "best": "good", "strongest": "good", "worst": "bad", "weakest": "bad", "poorest": "bad",
}
FUZZY = 0.85


@dataclass
class Period:
    date_from: date
    date_to: date
    label: str

    @property
    def is_range(self) -> bool:
        return self.date_from != self.date_to


@dataclass
class Extracted:
    period: Optional[Period] = None
    top_n: Optional[int] = None
    sort_word: Optional[str] = None           # high | low | good | bad
    countries: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    branches: list = field(default_factory=list)       # branch ids
    segments: list = field(default_factory=list)
    products: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    metrics: list = field(default_factory=list)        # metric keys, in the order they appear
    dimension: Optional[str] = None
    by_flag: bool = False
    status: Optional[str] = None               # open | closed | all (limit breaches)


class _Text:
    """The question, lower-cased, with a way to find a phrase as whole words and use it up."""

    def __init__(self, question: str):
        self.s = " " + re.sub(r"\s+", " ", re.sub(r"[^\w\s\-/.%]", " ", question.lower())) + " "

    def find(self, phrase: str) -> Optional[re.Match]:
        return re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", self.s)

    def take(self, phrase: str) -> bool:
        m = self.find(phrase)
        if m:
            self.use(m.start(), m.end())
        return bool(m)

    def use(self, start: int, end: int) -> None:
        self.s = self.s[:start] + " " * (end - start) + self.s[end:]

    def tokens(self) -> list:
        return [(m.group(), m.start(), m.end()) for m in re.finditer(r"[\w\-]+", self.s)]


def _fmt(d: date) -> str:
    return f"{d.day} {calendar.month_abbr[d.month]} {d.year}"


def _month(year: int, month: int) -> Period:
    return Period(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]),
                  f"{calendar.month_name[month]} {year}")


def _day(d: date) -> Period:
    return Period(d, d, _fmt(d))


def _range(start: date, end: date, label: str) -> Period:
    return Period(start, end, label)


def _month_num(word: str) -> Optional[int]:
    word = word.rstrip(".")
    return MONTHS.get(word) or MONTH_ABBR.get(word)


def _period(t: _Text, today: date) -> Optional[Period]:
    """First date phrase in the question. Unknown or impossible dates are ignored (never guessed)."""
    def at(pattern):
        return re.search(pattern, t.s)

    m = at(r"(?<!\w)(\d{4})-(\d{2})-(\d{2})(?!\w)")
    if m:
        try:
            p = _day(date(int(m[1]), int(m[2]), int(m[3])))
            t.use(m.start(), m.end())
            return p
        except ValueError:
            pass
    m = at(rf"(?<!\w)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?(?:\s+(\d{{4}}))?(?!\w)")
    if m:
        try:
            p = _day(date(int(m[3] or today.year), _month_num(m[2]), int(m[1])))
            t.use(m.start(), m.end())
            return p
        except ValueError:
            pass
    m = at(rf"(?<!\w)({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?!\w)")
    if m:
        try:
            p = _day(date(int(m[3] or today.year), _month_num(m[1]), int(m[2])))
            t.use(m.start(), m.end())
            return p
        except ValueError:
            pass
    m = at(rf"(?<!\w)({_MONTH_RE})\.?\s+(\d{{4}})(?!\w)")
    if m:
        t.use(m.start(), m.end())
        return _month(int(m[2]), _month_num(m[1]))
    m = at(r"(?<!\w)(last|past|previous)\s+(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")\s+(day|week|month)s?(?!\w)")
    if m:
        n = int(m[2]) if m[2].isdigit() else NUMBER_WORDS[m[2]]
        days = {"day": n, "week": 7 * n, "month": 30 * n}[m[3]]
        t.use(m.start(), m.end())
        return _range(today - timedelta(days=days - 1), today, f"Last {n} {m[3]}{'s' if n != 1 else ''}")
    for phrase, make in [
        ("today", lambda: _day(today)),
        ("yesterday", lambda: _day(today - timedelta(days=1))),
        ("this week", lambda: _range(today - timedelta(days=today.weekday()), today, "This week")),
        ("last week", lambda: _range(today - timedelta(days=today.weekday() + 7),
                                     today - timedelta(days=today.weekday() + 1), "Last week")),
        ("previous week", lambda: _range(today - timedelta(days=today.weekday() + 7),
                                         today - timedelta(days=today.weekday() + 1), "Last week")),
        ("this month", lambda: _month(today.year, today.month)),
        ("last month", lambda: _month(*((today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)))),
        ("previous month", lambda: _month(*((today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)))),
        ("year to date", lambda: _range(date(today.year, 1, 1), today, f"Year to date {today.year}")),
        ("ytd", lambda: _range(date(today.year, 1, 1), today, f"Year to date {today.year}")),
        ("this year", lambda: _range(date(today.year, 1, 1), today, f"Year to date {today.year}")),
        ("last year", lambda: _range(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1))),
    ]:
        if t.take(phrase):
            return make()
    m = at(r"(?<!\w)q([1-4])(?:\s+(\d{4}))?(?!\w)")
    if m:
        year, q = int(m[2] or today.year), int(m[1])
        t.use(m.start(), m.end())
        return _range(date(year, 3 * q - 2, 1), date(year, 3 * q, calendar.monthrange(year, 3 * q)[1]), f"Q{q} {year}")
    # A bare month name: full names only ("may" only after in/for/of/during - it's also a verb).
    m = at(r"(?<!\w)(?:(?:in|for|of|during)\s+)?(" + "|".join(n for n in MONTHS if n != "may") + r")(?!\w)") \
        or at(r"(?<!\w)(?:in|for|of|during)\s+(may)(?!\w)")
    if m:
        month = MONTHS[m[1]]
        year = today.year if month <= today.month else today.year - 1
        t.use(m.start(), m.end())
        return _month(year, month)
    m = at(r"(?<!\w)(20\d{2})(?!\w)")
    if m:
        year = int(m[1])
        t.use(m.start(), m.end())
        return _range(date(year, 1, 1), min(date(year, 12, 31), today), str(year))
    return None


def _top_n(t: _Text) -> tuple:
    """("top 5" -> 5, "high"). "last 7 days" was already used up by the date step."""
    words = "|".join(SORT_WORDS)
    nums = r"\d{1,3}|" + "|".join(NUMBER_WORDS)
    m = re.search(rf"(?<!\w)({words}|first)\s+({nums})(?!\w)", t.s) or re.search(rf"(?<!\w)({nums})\s+({words})(?!\w)", t.s)
    if not m:
        return None, None
    word, num = (m[1], m[2]) if not (m[1].isdigit() or m[1] in NUMBER_WORDS) else (m[2], m[1])
    t.use(m.start(), m.end())
    n = int(num) if num.isdigit() else NUMBER_WORDS[num]
    return (n if n > 0 else None), SORT_WORDS.get(word)


def _sort_word(t: _Text) -> Optional[str]:
    hits = [(t.find(w).start(), kind) for w, kind in SORT_WORDS.items() if t.find(w)]
    return min(hits)[1] if hits else None


def _similar(a: str, b: str) -> bool:
    return a == b or (len(b) >= 4 and SequenceMatcher(None, a, b).ratio() >= FUZZY)


def _fuzzy_take(t: _Text, name: str) -> bool:
    """Finds `name` (one or more words) allowing small typos ("Riyad Central"), and uses it up."""
    if t.take(name.lower()):
        return True
    want = name.lower().split()
    toks = t.tokens()
    for i in range(len(toks) - len(want) + 1):
        window = toks[i:i + len(want)]
        if all(_similar(tok[0], w) for tok, w in zip(window, want)):
            t.use(window[0][1], window[-1][2])
            return True
    return False


def _branches_and_regions(t: _Text, names: dict) -> tuple:
    branches, regions = [], []
    for b in sorted(names["branches"], key=lambda b: -len(b["name"])):
        if _fuzzy_take(t, b["name"]):
            branches.append(b["id"])
    country_words = {w for aliases in vocab.COUNTRIES.values() for w in aliases} | {c.lower() for c in vocab.COUNTRIES}
    for region in sorted(names["regions"], key=len, reverse=True):
        if region.lower() not in country_words and _fuzzy_take(t, region):
            regions.append(region)
    # A city on its own ("Riyadh branch"): the first word of exactly one branch's name.
    first_words = {}
    for b in names["branches"]:
        first_words.setdefault(b["name"].split()[0].lower(), []).append(b["id"])
    for word, ids in first_words.items():
        if len(ids) == 1 and len(word) >= 4 and ids[0] not in branches and word not in country_words and _fuzzy_take(t, word):
            branches.append(ids[0])
    return branches, regions


def _named_values(t: _Text, values: list, aliases: dict) -> list:
    """Segments / products: the name, its plural, the name without a trailing " loan", or an alias."""
    found = []
    for value in sorted(values, key=len, reverse=True):
        low = value.lower()
        base = re.sub(r"\s+loans?$", "", low)
        options = {low, base, f"{base}s", f"{base} loan", f"{base} loans", *aliases.get(base, [])}
        if any(t.find(o) for o in sorted(options, key=len, reverse=True)):
            found.append(value)
    return found


def _use_all(t: _Text, phrases) -> None:
    for p in sorted(phrases, key=len, reverse=True):
        while t.take(p):
            pass


def extract(question: str, today: date, names: dict) -> Extracted:
    t = _Text(question)
    out = Extracted()
    out.period = _period(t, today)
    out.top_n, top_word = _top_n(t)

    # Segments and products share words ("SME", "Corporate"): both read before either is used up.
    out.segments = _named_values(t, names["segments"], {})
    out.products = _named_values(t, names["products"], vocab.PRODUCT_ALIASES)
    for value in out.segments + out.products:
        base = re.sub(r"\s+loans?$", "", value.lower())
        _use_all(t, [value.lower(), f"{base} loans", f"{base} loan", f"{base}s", base, *vocab.PRODUCT_ALIASES.get(base, [])])

    out.branches, out.regions = _branches_and_regions(t, names)
    for country, aliases in vocab.COUNTRIES.items():
        if any(t.find(a) for a in aliases + [country.lower()]):
            out.countries.append(country)
            _use_all(t, aliases + [country.lower()])

    out.stages = sorted({int(n) for n in re.findall(r"(?<!\w)stage\s*([123])(?!\w)", t.s)})
    word_stage = {"one": 1, "two": 2, "three": 3}
    out.stages = sorted(set(out.stages) | {word_stage[w] for w in re.findall(r"(?<!\w)stage\s+(one|two|three)(?!\w)", t.s)})

    m = re.search(r"(?<!\w)(?:by|per|across|for each|each|split by|broken down by)\s+(product|segment|branch|currency)(?:e?s|ies)?(?!\w)", t.s)
    if m:
        out.dimension = m[1]
        t.use(m.start(), m.end())

    # Tables for the data-quality question are read before metrics use up words like "loans".
    out.tables = [table for table, words in vocab.SOURCE_TABLES.items() if any(t.find(w) for w in words)]

    phrases = sorted(((p, key) for key, ps in vocab.METRIC_SYNONYMS.items() for p in ps), key=lambda x: -len(x[0]))
    hits = []
    for phrase, key in phrases:
        m = t.find(phrase)
        while m:
            hits.append((m.start(), key))
            t.use(m.start(), m.end())
            m = t.find(phrase)
    for _, key in sorted(hits):
        if key not in out.metrics:
            out.metrics.append(key)

    out.by_flag = bool(re.search(r"(?<!\w)(flags?|by type|check)(?!\w)", t.s))
    if re.search(r"(?<!\w)(closed|resolved)(?!\w)", t.s):
        out.status = "closed"
    elif re.search(r"(?<!\w)(all|history|historic|past|ever)(?!\w)", t.s):
        out.status = "all"
    elif re.search(r"(?<!\w)(open|current|active|unresolved)(?!\w)", t.s):
        out.status = "open"

    out.sort_word = top_word or _sort_word(t)
    return out
