"""Saved sites (Site Manager), recent quick connections, trusted host keys and certificates. (No Qt here.)

Where: %APPDATA%\\Paragon\\PR7-F (PR7F_DATA points elsewhere; the tests do). Site settings are JSON; passwords
are never in it: they go to Windows Credential Manager through `keyring` (service "Paragon PR7-F"). If no
credential store works, a password isn't kept and PR7-F asks for it when connecting (FileZilla's "Ask for password").
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, fields

from .remote import Site

SERVICE = "Paragon PR7-F"
_memory: dict[str, str] = {}  # instead of keyring when PR7F_MEMORY_KEYRING is set (tests)


def data_dir() -> str:
    d = os.environ.get("PR7F_DATA") or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"),
                                                   "Paragon", "PR7-F")
    os.makedirs(d, exist_ok=True)
    return d


def known_hosts_path() -> str:
    return os.path.join(data_dir(), "known_hosts")


def _path(name: str) -> str:
    return os.path.join(data_dir(), name)


def _load(name: str, default):
    try:
        with open(_path(name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(name: str, data) -> None:
    tmp = _path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, _path(name))  # never a half-written file


# ------------------------------------------------------------------------------------------ passwords
def _memory_only() -> bool:
    return bool(os.environ.get("PR7F_MEMORY_KEYRING"))  # the tests: never the real Credential Manager


def _keyring():
    if _memory_only():
        return None
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:  # noqa: BLE001 - no credential store: passwords aren't kept
        return None


def can_store_passwords() -> bool:
    return _memory_only() or _keyring() is not None


def set_password(key: str, password: str) -> bool:
    if _memory_only():
        _memory[key] = password
        return True
    kr = _keyring()
    if kr is None:
        return False
    try:
        if password:
            kr.set_password(SERVICE, key, password)
        else:
            delete_password(key)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_password(key: str) -> str:
    if _memory_only():
        return _memory.get(key, "")
    kr = _keyring()
    if kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, key) or ""
    except Exception:  # noqa: BLE001
        return ""


def delete_password(key: str) -> None:
    _memory.pop(key, None)
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, key)
        except Exception:  # noqa: BLE001 - nothing stored
            pass


# ------------------------------------------------------------------------------------------ sites
SITE_KEYS = [f.name for f in fields(Site) if f.name not in ("password", "timeout")]


def load_sites() -> list[dict]:
    """[{"id", "folder", **Site fields without the password}], in the Site Manager's order."""
    return [s for s in _load("sites.json", []) if isinstance(s, dict) and s.get("id")]


def save_sites(sites: list[dict]) -> None:
    _save("sites.json", [{k: v for k, v in s.items() if k != "password"} for s in sites])


def new_site(name: str = "New site") -> dict:
    s = {k: v for k, v in asdict(Site("")).items() if k in SITE_KEYS}
    s.update(id=uuid.uuid4().hex, name=name, folder="")
    return s


def to_site(d: dict) -> Site:
    s = Site(**{k: d[k] for k in SITE_KEYS if k in d})
    s.password = get_password(d["id"]) if s.logon in ("normal", "key") else ""
    return s


def remove_site(sites: list[dict], site_id: str) -> list[dict]:
    delete_password(site_id)
    return [s for s in sites if s["id"] != site_id]


# ------------------------------------------------------------------------------------------ recent servers
def recent() -> list[dict]:
    return [r for r in _load("recent.json", []) if isinstance(r, dict) and r.get("host")][:10]


def add_recent(site: Site) -> None:
    """The quick-connect bar's history (no passwords: those are asked again, or come from the Site Manager)."""
    entry = {"host": site.host, "user": site.user, "port": site.port, "protocol": site.protocol,
             "encryption": site.encryption}
    items = [entry] + [r for r in recent() if (r.get("host"), r.get("user"), r.get("port"), r.get("protocol")) !=
                       (site.host, site.user, site.port, site.protocol)]
    _save("recent.json", items[:10])


# ------------------------------------------------------------------------------------------ certificates
def trusted_cert(host: str, sha256: str) -> bool:
    return sha256 in _load("trusted_certs.json", {}).get(host, [])


def trust_cert(host: str, sha256: str) -> None:
    d = _load("trusted_certs.json", {})
    d.setdefault(host, [])
    if sha256 not in d[host]:
        d[host].append(sha256)
    _save("trusted_certs.json", d)
