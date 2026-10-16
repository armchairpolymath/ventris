"""Open and save plain .gcode, Bambu .gcode.3mf archives and Prusa .bgcode files."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import bgcode

_PLATE_GCODE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")


class FileFormatError(Exception):
    pass


@dataclass
class Document:
    path: Path
    text: str
    inner_name: str | None = None  # G-code entry inside a .3mf, if any
    binary: bool = False  # opened from Prusa binary G-code

    @property
    def is_3mf(self) -> bool:
        return self.inner_name is not None

    @property
    def is_bgcode(self) -> bool:
        return self.binary


def is_3mf(path: Path) -> bool:
    return path.name.lower().endswith(".3mf")


def load(path: Path) -> Document:
    path = Path(path)
    if not is_3mf(path):
        raw = path.read_bytes()
        if bgcode.is_bgcode(raw):
            try:
                return Document(path, bgcode.decode(raw).to_text(), binary=True)
            except bgcode.BgcodeError as exc:
                raise FileFormatError(str(exc)) from exc
        return Document(path, _decode(raw))
    try:
        with zipfile.ZipFile(path) as z:
            plates = sorted((int(m.group(1)), n) for n in z.namelist()
                            if (m := _PLATE_GCODE.match(n)))
            if not plates:
                raise FileFormatError(
                    "This .3mf has no sliced G-code inside. Slice it in Bambu Studio "
                    "and export with “Export plate sliced file”.")
            name = plates[0][1]
            return Document(path, _decode(z.read(name)), inner_name=name)
    except zipfile.BadZipFile as exc:
        raise FileFormatError(f"Not a valid .3mf archive: {exc}") from exc


def save(doc: Document, text: str, path: Path) -> None:
    """Save `text` to `path`. A .3mf target gets its plate G-code and md5 replaced."""
    path = Path(path)
    data = text.encode("utf-8")
    if doc.is_bgcode and (path.suffix.lower() == ".bgcode" or path == doc.path):
        raise FileFormatError(
            "Saving back to binary G-code (.bgcode) isn't supported. Save as a .gcode "
            "file instead — Prusa printers print plain .gcode files too.")
    if doc.is_3mf and is_3mf(path):
        _write_3mf(doc.path, doc.inner_name, data, path)
    elif is_3mf(path):
        raise FileFormatError("Plain G-code can only be saved as a .gcode file.")
    else:
        _atomic_write(path, data)


def _write_3mf(source: Path, inner: str, data: bytes, target: Path) -> None:
    md5_name = inner + ".md5"
    replaced = {inner: data, md5_name: hashlib.md5(data).hexdigest().upper().encode()}
    with zipfile.ZipFile(source) as src:
        if md5_name in src.namelist():
            # keep the casing style Bambu used for the hex digest
            original = src.read(md5_name).decode().strip()
            if original.islower():
                replaced[md5_name] = replaced[md5_name].lower()
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".3mf.tmp")
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
                for item in src.infolist():
                    if item.filename in replaced:
                        out.writestr(item, replaced.pop(item.filename),
                                     compress_type=zipfile.ZIP_DEFLATED)
                    else:
                        out.writestr(item, src.read(item.filename))
                for name, payload in replaced.items():
                    out.writestr(name, payload)
            os.replace(tmp, target)
        except BaseException:
            os.unlink(tmp)
            raise


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
