"""Open and save plain .gcode, Bambu .gcode.3mf and Prusa .bgcode files; read Ruida .rd jobs."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import bgcode, ruida

_PLATE_GCODE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")


class FileFormatError(Exception):
    pass


@dataclass
class Document:
    path: Path
    text: str
    inner_name: str | None = None  # G-code entry inside a .3mf, if any
    binary: bool = False  # opened from Prusa binary G-code
    newline: str = "\n"  # line ending the file used; restored on save
    read_only: bool = False  # decoded views (Ruida .rd) can't be saved

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
        if path.suffix.lower() == ".rd":
            try:
                return Document(path, ruida.decode(raw).to_text(), read_only=True)
            except ruida.RuidaError as exc:
                raise FileFormatError(str(exc)) from exc
        if bgcode.is_bgcode(raw):
            try:
                return Document(path, bgcode.decode(raw).to_text(), binary=True)
            except bgcode.BgcodeError as exc:
                raise FileFormatError(str(exc)) from exc
        return _text_document(path, _decode(raw))
    try:
        with zipfile.ZipFile(path) as z:
            plates = sorted((int(m.group(1)), n) for n in z.namelist()
                            if (m := _PLATE_GCODE.match(n)))
            if not plates:
                raise FileFormatError(
                    "This .3mf has no sliced G-code inside. Slice it in Bambu Studio "
                    "and export with “Export plate sliced file”.")
            name = plates[0][1]
            return _text_document(path, _decode(z.read(name)), inner_name=name)
    except zipfile.BadZipFile as exc:
        raise FileFormatError(f"Not a valid .3mf archive: {exc}") from exc


def save(doc: Document, text: str, path: Path) -> None:
    """Save `text` to `path`. A .3mf target gets its plate G-code and md5 replaced."""
    path = Path(path)
    if doc.read_only:
        raise FileFormatError("This is a decoded view of a laser job (.rd) and can't be "
                              "saved. Ventris opens .rd files read-only.")
    if doc.newline != "\n":
        text = text.replace("\n", doc.newline)
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
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".3mf.tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(source) as src, \
                zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            if md5_name in src.namelist():
                # keep the casing style Bambu used for the hex digest
                if src.read(md5_name).decode().strip().islower():
                    replaced[md5_name] = replaced[md5_name].lower()
            for item in src.infolist():
                if item.filename in replaced:
                    out.writestr(item, replaced.pop(item.filename),
                                 compress_type=zipfile.ZIP_DEFLATED)
                else:
                    out.writestr(item, src.read(item.filename))
            for name, payload in replaced.items():
                out.writestr(name, payload)
        # Both archives are closed now; Windows can't replace a file that is still open.
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
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


def _text_document(path: Path, text: str, inner_name: str | None = None) -> Document:
    """Normalize line endings to \\n for editing, remembering the original style."""
    newline = "\r\n" if "\r\n" in text else "\n"
    if newline != "\n":
        text = text.replace("\r\n", "\n")
    return Document(path, text, inner_name=inner_name, newline=newline)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")
