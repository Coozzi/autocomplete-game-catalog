#!/usr/bin/env python3
"""Build a deterministic add-only catalog release from Discord and reviewed manual data."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://discord.com/api/v9/applications/detectable"
MAX_BODY = 16 * 1024 * 1024
MAX_ENTRIES = 50_000
MAX_MANUAL = 5_000
MAX_PATTERNS = 16
MAX_TOTAL = 8 * 1024 * 1024
MAX_DELTA_BYTES = 512 * 1024
MAX_FIELD = 128
GENERIC = {"electron.exe", "chrome.exe", "msedge.exe", "discord.exe", "explorer.exe", "game.exe", "client.exe", "app.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "java.exe", "javaw.exe", "rundll32.exe", "launcher.exe", "bootstrapper.exe", "updater.exe", "update.exe", "installer.exe", "install.exe", "setup.exe", "service.exe", "crashhandler.exe", "crashhandler64.exe", "crashreporter.exe", "crashpad_handler.exe", "werfault.exe", "dllhost.exe", "svchost.exe"}
MANUAL_ID = re.compile(r"^manual:[a-z0-9]+(?:-[a-z0-9]+)*$")


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def normalize_pattern(raw):
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > MAX_FIELD or not raw.isascii():
        raise ValueError("invalid executable path")
    value = raw.replace("/", "\\").lower()
    parts = value.split("\\")
    if (value.startswith("\\") or len(parts) > 8 or any(not part or part in (".", "..") for part in parts)
            or not parts[-1].endswith(".exe") or parts[-1] in GENERIC
            or any((ord(c) < 32 or ord(c) == 127) or c in "*?:|" for c in value)):
        raise ValueError(f"unsafe or generic executable path: {raw}")
    return "\\".join(parts)


def normalize_entry(entry, manual=False):
    if not isinstance(entry, dict) or set(entry) != {"id", "name", "windows_executables"}:
        raise ValueError("entry must contain exactly id, name, windows_executables")
    ident, name, patterns = entry["id"], entry["name"], entry["windows_executables"]
    if manual:
        if not isinstance(ident, str) or len(ident) > 96 or not MANUAL_ID.fullmatch(ident):
            raise ValueError("manual ID must use manual:<stable_ascii_slug>")
    elif not ((isinstance(ident, str) and ident.isascii() and ident.isdecimal() and len(ident) <= 20)
              or (isinstance(ident, int) and not isinstance(ident, bool) and 0 <= ident <= 2**64 - 1)):
        raise ValueError("Discord ID must be an unsigned decimal integer")
    else:
        ident = str(ident)
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > MAX_FIELD or any(unicodedata.category(c) == "Cc" for c in name):
        raise ValueError("invalid display name")
    if not isinstance(patterns, list) or not 1 <= len(patterns) <= MAX_PATTERNS:
        raise ValueError("entry needs 1-16 executable paths")
    normalized = sorted(set(normalize_pattern(pattern) for pattern in patterns))
    return {"id": ident, "name": name, "windows_executables": normalized}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)


def load_manual(path):
    data = read_json(path)
    if not isinstance(data, dict) or set(data) != {"schema_version", "entries"} or data["schema_version"] != 1:
        raise ValueError("manual catalog must use schema_version 1 and entries only")
    entries = [normalize_entry(item, manual=True) for item in data["entries"]]
    if len(entries) > MAX_MANUAL or len({e["id"] for e in entries}) != len(entries):
        raise ValueError("manual catalog entry count exceeded or IDs duplicated")
    return entries


def fetch_discord():
    request = urllib.request.Request(URL, headers={"Accept": "application/json", "User-Agent": "AutoComplete-public-catalog/1"})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("Discord catalog endpoint redirected; refusing non-allowlisted destination")

    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError("Discord catalog returned a non-success status")
        chunks, size = [], 0
        while True:
            chunk = response.read(min(65536, MAX_BODY + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BODY:
                raise ValueError("Discord catalog exceeded 16 MiB")
    return json.loads(b"".join(chunks), object_pairs_hook=no_duplicate_keys)


def discord_entries(records):
    if not isinstance(records, list) or len(records) > MAX_ENTRIES:
        raise ValueError("Discord response must be an array of at most 50,000 entries")
    if not records:
        raise ValueError("Discord catalog returned an empty feed")
    result, ids = [], set()
    skipped = {}
    max_reason_count = MAX_ENTRIES * MAX_PATTERNS

    def count(reason):
        skipped[reason] = min(max_reason_count, skipped.get(reason, 0) + 1)

    for raw in records:
        if not isinstance(raw, dict):
            count("invalid_record_type")
            continue
        # Well-formed but unsupported records (no themes or usable Windows binary) are not catalog entries.
        ident = raw.get("id")
        if not ((isinstance(ident, str) and ident.isascii() and ident.isdecimal() and len(ident) <= 20)
                or (isinstance(ident, int) and not isinstance(ident, bool) and 0 <= ident <= 2**64 - 1)):
            count("invalid_id")
            continue
        ident = str(ident)
        name = raw.get("name")
        themes, executables = raw.get("themes"), raw.get("executables")
        if not isinstance(name, str):
            count("invalid_name_type")
            continue
        try:
            name_valid = bool(name) and len(name.encode("utf-8")) <= MAX_FIELD and not any(unicodedata.category(c) == "Cc" for c in name)
        except UnicodeEncodeError:
            name_valid = False
        if not name_valid:
            count("invalid_name_value")
            continue
        if themes is None:
            count("unsupported_themes")
            continue
        if not isinstance(themes, list) or not 1 <= len(themes) <= 32:
            count("invalid_themes")
            continue
        try:
            themes_valid = all(isinstance(t, str) and t and len(t.encode("utf-8")) <= MAX_FIELD
                               and not any(unicodedata.category(c) == "Cc" for c in t) for t in themes)
        except UnicodeEncodeError:
            themes_valid = False
        if not themes_valid:
            count("invalid_themes")
            continue
        if not isinstance(executables, list):
            count("invalid_executable_list")
            continue
        if len(executables) > MAX_PATTERNS:
            count("executable_limit")
            continue
        paths = []
        for exe in executables:
            if not isinstance(exe, dict):
                count("invalid_executable_record")
                continue
            is_launcher, os_name, executable_name = exe.get("is_launcher"), exe.get("os"), exe.get("name")
            if not isinstance(is_launcher, bool) or not isinstance(os_name, str):
                count("invalid_executable_fields")
                continue
            if is_launcher or os_name.lower() != "win32":
                continue
            if not isinstance(executable_name, str):
                count("invalid_executable_name_type")
                continue
            try:
                paths.append(normalize_pattern(executable_name))
            except (ValueError, UnicodeEncodeError):
                # Reject unsafe/generic names without exposing upstream text in logs.
                count("unsafe_executable_name")
        paths = sorted(set(paths))
        if not paths:
            count("no_safe_windows_executable")
            continue
        if ident in ids:
            raise ValueError("duplicate Discord application ID")
        ids.add(ident)
        result.append({"id": ident, "name": name, "windows_executables": paths})
    if not result:
        raise ValueError("Discord catalog contained no usable entries")
    return result, dict(sorted(skipped.items()))


def validate_previous(pointer_path):
    pointer_path = Path(pointer_path)
    pointer = read_json(pointer_path)
    expected = {"schema_version", "feed", "revision", "entry_count", "snapshot", "latest_delta"}
    if not isinstance(pointer, dict) or set(pointer) != expected:
        raise ValueError("previous manifest pointer fields invalid")
    if pointer["schema_version"] != 1 or pointer["feed"] != "autocomplete-public-catalog":
        raise ValueError("previous manifest pointer schema/feed unsupported")
    if not isinstance(pointer["revision"], int) or pointer["revision"] < 1:
        raise ValueError("previous revision invalid")

    def referenced_file(ref, allowed_prefix):
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValueError("manifest file reference fields invalid")
        rel = ref["path"]
        if (not isinstance(rel, str) or not rel.startswith(allowed_prefix) or ".." in Path(rel).parts
                or "\\" in rel or Path(rel).is_absolute()):
            raise ValueError("manifest file path is outside its immutable feed directory")
        file_path = pointer_path.parent / rel
        payload = file_path.read_bytes()
        if hashlib.sha256(payload.rstrip(b"\n")).hexdigest() != ref["sha256"]:
            raise ValueError("previous referenced file hash mismatch")
        return json.loads(payload, object_pairs_hook=no_duplicate_keys)

    snapshot = referenced_file(pointer["snapshot"], "snapshots/")
    if not isinstance(snapshot, dict) or set(snapshot) != {"schema_version", "feed", "revision", "entry_count", "entries", "sha256"}:
        raise ValueError("previous snapshot fields invalid")
    if (snapshot["schema_version"] != 1 or snapshot["feed"] != "autocomplete-public-catalog"
            or snapshot["revision"] != pointer["revision"]):
        raise ValueError("previous snapshot identity mismatch")
    if not isinstance(snapshot["entries"], list):
        raise ValueError("previous snapshot entries invalid")
    entries = [normalize_entry(item, manual=str(item.get("id", "")).startswith("manual:")) for item in snapshot["entries"]]
    if entries != sorted(entries, key=lambda e: e["id"]) or len({e["id"] for e in entries}) != len(entries):
        raise ValueError("previous snapshot entries are not uniquely sorted")
    digest = hashlib.sha256(canonical(entries)).hexdigest()
    if snapshot["entry_count"] != len(entries) or pointer["entry_count"] != len(entries) or snapshot["sha256"] != digest:
        raise ValueError("previous snapshot count/hash mismatch")
    # Ensure latest_delta is present, hash-checked, and actually advances the pointer revision.
    delta = referenced_file(pointer["latest_delta"], "deltas/")
    if (not isinstance(delta, dict) or delta.get("schema_version") != 1
            or delta.get("feed") != "autocomplete-public-catalog"
            or delta.get("to_revision") != pointer["revision"]
            or not isinstance(delta.get("operations"), list)):
        raise ValueError("previous latest delta identity invalid")
    delta_payload = dict(delta)
    delta_hash = delta_payload.pop("sha256", None)
    if set(delta) != {"schema_version", "feed", "from_revision", "to_revision", "operations", "sha256"} or delta_hash != hashlib.sha256(canonical(delta_payload)).hexdigest():
        raise ValueError("previous latest delta schema/hash mismatch")
    return pointer["revision"], {entry["id"]: entry for entry in entries}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", required=True)
    parser.add_argument("--previous", help="previous published manifest pointer JSON")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--validate-only", action="store_true", help="validate manual data without network")
    args = parser.parse_args()
    manual = load_manual(args.manual)
    if args.validate_only:
        return 0
    old_revision, previous = (0, {})
    if args.previous:
        old_revision, previous = validate_previous(args.previous)
    fetched, skipped = discord_entries(fetch_discord())
    if skipped:
        print(json.dumps({"discord_skipped_reason_counts": skipped}, sort_keys=True, separators=(",", ":")), file=sys.stderr)
    additions = {}
    for entry in fetched + manual:
        ident = entry["id"]
        if ident in previous:
            if previous[ident] != entry:
                raise ValueError(f"published ID is immutable and changed: {ident}")
            continue
        if ident in additions and additions[ident] != entry:
            raise ValueError(f"ID collision across sources: {ident}")
        additions[ident] = entry
    if not additions:
        print(json.dumps({"changed": False, "revision": old_revision}, separators=(",", ":")))
        return 0
    merged = dict(previous)
    merged.update(additions)
    entries = sorted(merged.values(), key=lambda entry: entry["id"])
    if len(entries) > MAX_ENTRIES or sum(len(canonical(entry)) for entry in entries) > MAX_TOTAL:
        raise ValueError("catalog exceeds entry or normalized byte limit")
    revision = old_revision + 1
    digest = hashlib.sha256(canonical(entries)).hexdigest()
    out = Path(args.out_dir)
    snapshot_path = f"snapshots/catalog-v{revision:08d}.json"
    delta_path = f"deltas/delta-{revision:08d}.json"
    snapshot = {"schema_version": 1, "feed": "autocomplete-public-catalog", "revision": revision,
                "entry_count": len(entries), "entries": entries, "sha256": digest}
    delta = {"schema_version": 1, "feed": "autocomplete-public-catalog", "from_revision": old_revision,
             "to_revision": revision, "operations": [{"op": "add", "entry": e} for e in sorted(additions.values(), key=lambda entry: entry["id"])]}
    delta["sha256"] = hashlib.sha256(canonical(delta)).hexdigest()
    snapshot_bytes, delta_bytes = canonical(snapshot) + b"\n", canonical(delta) + b"\n"
    if len(snapshot_bytes) > MAX_TOTAL:
        raise ValueError("serialized snapshot exceeds the 8 MiB client cache limit")
    if len(delta_bytes) > MAX_DELTA_BYTES:
        raise ValueError("serialized delta exceeds the 512 KiB client catch-up limit")
    pointer = {"schema_version": 1, "feed": "autocomplete-public-catalog", "revision": revision,
               "entry_count": len(entries),
               "snapshot": {"path": snapshot_path, "sha256": hashlib.sha256(snapshot_bytes.rstrip(b"\n")).hexdigest()},
               "latest_delta": {"path": delta_path, "sha256": hashlib.sha256(delta_bytes.rstrip(b"\n")).hexdigest()}}
    for relative, payload in ((snapshot_path, snapshot_bytes), (delta_path, delta_bytes)):
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(f"refusing to rewrite immutable published file: {relative}")
        else:
            path.write_bytes(payload)
    (out / "manifest.json").write_bytes(canonical(pointer) + b"\n")
    print(json.dumps({"changed": True, "revision": revision, "additions": len(additions)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"catalog publisher: {exc}", file=sys.stderr)
        raise SystemExit(1)
