"""Bookmarks (Bookmarks menu, Ctrl+B to add), as FileZilla's: a name, a local folder and/or a remote folder, and
whether opening it turns on synchronised browsing and directory comparison.

Global bookmarks are in bookmarks.json and always in the menu; a Site Manager site's own bookmarks are kept with
the site (its "bookmarks" list in sites.json) and listed only while connected to it. (No Qt here.)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from . import sites


@dataclass
class Bookmark:
    name: str
    local: str = ""
    remote: str = ""
    sync: bool = False
    compare: bool = False

    @staticmethod
    def from_dict(d: dict) -> "Bookmark":
        return Bookmark(str(d.get("name", "Bookmark")), str(d.get("local", "")), str(d.get("remote", "")),
                        bool(d.get("sync", False)), bool(d.get("compare", False)))


def _path() -> str:
    return os.path.join(sites.data_dir(), "bookmarks.json")


def load_global() -> list[Bookmark]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            return [Bookmark.from_dict(d) for d in json.load(fh) if isinstance(d, dict)]
    except (OSError, ValueError):
        return []


def save_global(items: list[Bookmark]) -> None:
    sites._save("bookmarks.json", [asdict(b) for b in items])


def load_site(site_id: str) -> list[Bookmark]:
    s = next((x for x in sites.load_sites() if x["id"] == site_id), None)
    return [Bookmark.from_dict(d) for d in (s or {}).get("bookmarks", []) if isinstance(d, dict)]


def save_site(site_id: str, items: list[Bookmark]) -> bool:
    all_sites = sites.load_sites()
    for s in all_sites:
        if s["id"] == site_id:
            s["bookmarks"] = [asdict(b) for b in items]
            sites.save_sites(all_sites)
            return True
    return False


def site_name(site_id: str) -> str:
    return next((s.get("name", "") for s in sites.load_sites() if s["id"] == site_id), "")


def unique(name: str, taken: list[Bookmark]) -> str:
    names = {b.name for b in taken}
    n, out = 2, name
    while out in names:
        out = f"{name} ({n})"
        n += 1
    return out
