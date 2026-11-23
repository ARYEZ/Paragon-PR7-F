"""Directory listing filters (View > Directory listing filters, Ctrl+I) and the conditions remote search uses,
as FileZilla's. (No Qt here.)

A filter hides the entries it matches. It has conditions ("Filename" "ends with" ".tmp", "Filesize" "greater than"
"1000000" ...), a rule for combining them (all / any / none of them must match), what it applies to (files, folders)
and whether text is case-sensitive. Each filter is switched on separately for the local and the remote side; filters
are kept in filters.json in PR7-F's data folder.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field

FIELDS = {"name": "Filename", "size": "Filesize", "date": "Date", "path": "Path", "perms": "Permissions"}
TEXT_OPS = {"contains": "contains", "is": "is equal to", "begins": "begins with", "ends": "ends with",
            "regex": "matches regex", "not_contains": "does not contain"}
SIZE_OPS = {"greater": "greater than", "equals": "equals", "not_equals": "does not equal", "less": "less than"}
DATE_OPS = {"before": "before", "equals": "equals", "after": "after"}
MATCH = {"all": "Filter out items matching all of the following", "any": "Filter out items matching any of the "
         "following", "none": "Filter out items matching none of the following"}


def ops_for(field_name: str) -> dict:
    return SIZE_OPS if field_name == "size" else DATE_OPS if field_name == "date" else TEXT_OPS


@dataclass
class Condition:
    field: str = "name"
    op: str = "contains"
    value: str = ""


@dataclass
class Filter:
    name: str
    conditions: list[Condition] = field(default_factory=list)
    match: str = "all"
    files: bool = True
    dirs: bool = True
    case: bool = False

    @staticmethod
    def from_dict(d: dict) -> "Filter":
        conds = [Condition(**c) for c in d.get("conditions", []) if isinstance(c, dict)]
        return Filter(d.get("name", "Filter"), conds, d.get("match", "all"), bool(d.get("files", True)),
                      bool(d.get("dirs", True)), bool(d.get("case", False)))


# FileZilla's own starting set.
DEFAULTS = [
    Filter("Temporary and backup files", [Condition("name", "ends", "~"), Condition("name", "ends", ".bak"),
                                          Condition("name", "ends", ".tmp"), Condition("name", "begins", "~$")],
           "any", True, False),
    Filter("Thumbs.db and desktop.ini", [Condition("name", "is", "thumbs.db"), Condition("name", "is", "desktop.ini")],
           "any", True, False),
    Filter("CVS and SVN directories", [Condition("name", "is", "CVS"), Condition("name", "is", ".svn")], "any",
           False, True, True),
    Filter("Git directories", [Condition("name", "is", ".git")], "any", False, True, True),
    Filter("Hidden files (starting with a dot)", [Condition("name", "begins", ".")], "any", True, True, True),
    Filter("Configuration files", [Condition("name", "ends", ".ini"), Condition("name", "ends", ".cfg"),
                                   Condition("name", "ends", ".conf")], "any", True, False),
]


def _parse_date(text: str) -> float | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(text.strip(), fmt))
        except ValueError:
            continue
    return None


def _size(text: str) -> int | None:
    """'1000000', '1.5 MB', '200k' -> bytes."""
    m = re.fullmatch(r"\s*([\d.,]+)\s*([kmgt]?)i?b?\s*", text.lower())
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n * 1024 ** "_kmgt".index(m.group(2) or "_")) if m.group(2) else int(n)


def condition_matches(c: Condition, name: str, size: int, mtime: float, is_dir: bool, path: str, perms: str,
                      case: bool) -> bool:
    if c.field == "size":
        want = _size(c.value)
        if want is None or is_dir:
            return False
        return {"greater": size > want, "equals": size == want, "not_equals": size != want,
                "less": size < want}.get(c.op, False)
    if c.field == "date":
        want = _parse_date(c.value)
        if want is None or not mtime:
            return False
        day = time.strftime("%Y-%m-%d", time.localtime(mtime))
        if c.op == "equals":
            return day == c.value.strip()[:10]
        return mtime < want if c.op == "before" else mtime > want
    text = {"name": name, "path": path, "perms": perms}.get(c.field, "")
    value = c.value
    if c.op == "regex":
        try:
            return re.search(value, text, 0 if case else re.I) is not None
        except re.error:
            return False
    if not case:
        text, value = text.lower(), value.lower()
    return {"contains": value in text, "not_contains": value not in text, "is": text == value,
            "begins": text.startswith(value), "ends": text.endswith(value)}.get(c.op, False)


def filter_matches(f: Filter, name: str, size: int = 0, mtime: float = 0.0, is_dir: bool = False, path: str = "",
                   perms: str = "") -> bool:
    """Does the filter hide this entry?"""
    if (is_dir and not f.dirs) or (not is_dir and not f.files) or not f.conditions:
        return False
    hits = [condition_matches(c, name, size, mtime, is_dir, path, perms, f.case) for c in f.conditions]
    return {"all": all(hits), "any": any(hits), "none": not any(hits)}.get(f.match, False)


# ------------------------------------------------------------------------------------------ storage
def _path() -> str:
    from .sites import data_dir
    return os.path.join(data_dir(), "filters.json")


@dataclass
class FilterSet:
    filters: list[Filter]
    local: set[str] = field(default_factory=set)     # names of the filters on for the local side
    remote: set[str] = field(default_factory=set)

    def active(self, side: str) -> list[Filter]:
        on = self.local if side == "local" else self.remote
        return [f for f in self.filters if f.name in on]

    def hides(self, side: str, name: str, size=0, mtime=0.0, is_dir=False, path="", perms="") -> bool:
        return any(filter_matches(f, name, size, mtime, is_dir, path, perms) for f in self.active(side))


def load() -> FilterSet:
    try:
        with open(_path(), encoding="utf-8") as fh:
            d = json.load(fh)
        return FilterSet([Filter.from_dict(x) for x in d.get("filters", [])], set(d.get("local", [])),
                         set(d.get("remote", [])))
    except (OSError, ValueError, TypeError):
        return FilterSet([Filter.from_dict(asdict(f)) for f in DEFAULTS])


def save(fs: FilterSet) -> None:
    from .sites import _save
    _save("filters.json", {"filters": [asdict(f) for f in fs.filters], "local": sorted(fs.local),
                           "remote": sorted(fs.remote)})
