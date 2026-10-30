"""Safely inventory and extract only Gerber/Excellon files from source ZIPs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = (
    ROOT / "gerbers" / "Gerber_PCB_Valentine_Feb_New.zip",
    ROOT / "gerbers" / "Gerber_Prickly-Laser-Module-2.5.zip",
)
OUT = Path(__file__).resolve().parent / "fixtures" / "extracted"
MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_RATIO = 250


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member_name(name: str) -> PurePosixPath:
    if "\\" in name or name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"Unsafe ZIP path: {name!r}")
    return path


def classify_member(name: str, data: bytes) -> str | None:
    """Identify a manufacturing file by content, using suffix only as a hint."""
    text = data[:200_000].decode("ascii", errors="ignore")
    upper = text.upper()
    suffix = Path(name).suffix.lower()
    has_xy = bool(re.search(r"(?im)^\s*X[+-]?[\d.]+|\bX[+-]?[\d.]+Y[+-]?[\d.]+", text))
    has_tools = bool(re.search(r"(?im)^\s*T\d+\s*C[+-]?[\d.]+", text))
    if suffix in {".drl", ".xln", ".exc"} and (has_xy or has_tools) and ("M48" in upper or "METRIC" in upper or "INCH" in upper):
        return "excellon"
    if "%FS" in upper and ("%MO" in upper or "%ADD" in upper or "D01*" in upper):
        return "gerber"
    if suffix in {".gbr", ".ger", ".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs", ".gtp", ".gbp", ".gko", ".gm1", ".gml", ".gdd", ".gdl"}:
        if any(token in upper for token in ("%MOMM", "%MOIN", "%ADD", "D01*")):
            return "gerber"
    if ("M48" in upper or (suffix in {".drl", ".xln", ".exc", ".txt"} and has_xy)) and has_xy:
        return "excellon"
    return None


def inspect_archive(archive: Path, out_root: Path = OUT) -> dict:
    if not archive.is_file():
        raise FileNotFoundError(archive)
    board_id = re.sub(r"[^a-z0-9]+", "-", archive.stem.lower()).strip("-")
    target_root = out_root / board_id
    target_root.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    total_size = 0
    extracted = []
    archive_entries = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                safe_member_name(info.filename.rstrip("/"))
                continue
            rel = safe_member_name(info.filename)
            key = rel.as_posix().casefold()
            if key in seen:
                raise ValueError(f"Duplicate/case-colliding ZIP path: {info.filename!r}")
            seen.add(key)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symbolic link is not allowed in ZIP: {info.filename!r}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"ZIP member exceeds size limit: {info.filename!r}")
            total_size += info.file_size
            if total_size > MAX_TOTAL_BYTES:
                raise ValueError("ZIP exceeds total uncompressed size limit")
            if info.file_size and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise ValueError(f"ZIP member exceeds compression-ratio limit: {info.filename!r}")

            archive_entries.append({"name": rel.as_posix(), "size": info.file_size})
            data = bundle.read(info)
            kind = classify_member(info.filename, data)
            if kind is None:
                continue
            destination = target_root.joinpath(*rel.parts)
            resolved = destination.resolve()
            if os.path.commonpath((str(target_root.resolve()), str(resolved))) != str(target_root.resolve()):
                raise ValueError(f"ZIP path escapes extraction root: {info.filename!r}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if sha256(destination) != hashlib.sha256(data).hexdigest():
                    raise FileExistsError(f"Existing extracted file differs from archive member: {destination}")
            else:
                destination.write_bytes(data)
            extracted.append({
                "path": destination.relative_to(out_root).as_posix(),
                "archiveMember": rel.as_posix(),
                "kind": kind,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })

    return {
        "archive": archive.name,
        "archivePath": archive.relative_to(ROOT).as_posix(),
        "archiveSize": archive.stat().st_size,
        "archiveSha256": sha256(archive),
        "boardId": board_id,
        "entryCount": len(archive_entries),
        "entries": archive_entries,
        "extractedManufacturingFiles": extracted,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"extractionPolicy": "content-sniffed Gerber/Excellon only; path/size/ratio guarded", "boards": [inspect_archive(p) for p in ARCHIVES]}
    dest = Path(__file__).resolve().parent / "fixture_inventory.json"
    dest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(dest)
    print(f"Extracted {sum(len(b['extractedManufacturingFiles']) for b in result['boards'])} manufacturing files")


if __name__ == "__main__":
    main()
