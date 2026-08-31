#!/usr/bin/env python3
"""Detect office document formats from their content without executing them."""

from __future__ import annotations

import struct
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree


OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
PDF_MAGIC = b"%PDF-"
RTF_MAGIC = b"{\\rtf"
CFB_FREE_SECTOR = 0xFFFFFFFF
CFB_END_OF_CHAIN = 0xFFFFFFFE
CFB_MAX_REGULAR_SECTOR = 0xFFFFFFF9
MAX_CFB_FAT_SECTORS = 4_096
MAX_CFB_DIRECTORY_SECTORS = 16_384
MAX_ZIP_MEMBERS = 20_000
MAX_ZIP_SNIFF_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ZIP_SNIFF_COMPRESSION_RATIO = 2_000
PROPRIETARY_OFFICE_SUFFIXES = {".wps", ".et"}
KNOWN_DOCUMENT_SUFFIXES = {
    ".doc", ".docx", ".docm", ".dotx", ".dotm", ".wps", ".rtf",
    ".xls", ".xlsx", ".xlsm", ".xltx", ".xltm", ".ods", ".odt", ".csv",
    ".tsv", ".et", ".pdf", ".txt",
}
WORD_MAIN_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    "application/vnd.ms-word.document.macroEnabled.main+xml",
    "application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
}
EXCEL_MAIN_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    "application/vnd.ms-excel.template.macroEnabled.main+xml",
}


@dataclass(frozen=True)
class DocumentDetection:
    declared_suffix: str
    detected_kind: str
    contains_macros: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CompoundFileError(ValueError):
    """Raised when a file starts like CFB but its directory cannot be read safely."""


class ZipSafetyError(ValueError):
    """Raised before a sniffing read could expand untrusted archive data."""


def _read_small_zip_member(archive: zipfile.ZipFile, name: str, maximum: int) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError:
        raise
    if info.flag_bits & 0x1:
        raise ZipSafetyError(f"{name} 已加密")
    if info.file_size < 0 or info.file_size > min(maximum, MAX_ZIP_SNIFF_MEMBER_BYTES):
        raise ZipSafetyError(f"{name} 超出嗅探读取上限")
    if info.compress_size > 0 and info.file_size / info.compress_size > MAX_ZIP_SNIFF_COMPRESSION_RATIO:
        raise ZipSafetyError(f"{name} 压缩比例超出安全上限")
    with archive.open(info) as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ZipSafetyError(f"{name} 解压内容超出嗅探读取上限")
    return data


def _content_type_overrides(data: bytes) -> dict[str, str]:
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("OOXML 内容类型包含不允许的实体声明")
    root = ElementTree.fromstring(data)
    return {
        node.attrib.get("PartName", "").lstrip("/"): node.attrib.get("ContentType", "")
        for node in root
        if node.tag.rsplit("}", 1)[-1] == "Override"
    }


def _sector(data: bytes, sector_id: int, sector_size: int) -> bytes:
    if sector_id < 0 or sector_id > CFB_MAX_REGULAR_SECTOR:
        raise CompoundFileError("OLE 扇区编号无效")
    start = (sector_id + 1) * sector_size
    end = start + sector_size
    if end > len(data):
        raise CompoundFileError("OLE 扇区超出文件范围")
    return data[start:end]


def _u32_values(data: bytes) -> tuple[int, ...]:
    if len(data) % 4:
        raise CompoundFileError("OLE 扇区长度无效")
    return struct.unpack(f"<{len(data) // 4}I", data)


def compound_stream_names(path: Path) -> set[str]:
    """Read CFB directory names only; no stream payload or macro is executed."""

    data = path.read_bytes()
    if len(data) < 512 or not data.startswith(OLE_MAGIC):
        raise CompoundFileError("OLE 文件头不完整")
    if data[0x1C:0x1E] != b"\xfe\xff":
        raise CompoundFileError("OLE 字节序不受支持")
    sector_shift = struct.unpack_from("<H", data, 0x1E)[0]
    if sector_shift not in {9, 12}:
        raise CompoundFileError("OLE 扇区大小无效")
    sector_size = 1 << sector_shift
    if len(data) < sector_size:
        raise CompoundFileError("OLE 头部长度不足")

    fat_sector_count = struct.unpack_from("<I", data, 0x2C)[0]
    first_directory_sector = struct.unpack_from("<I", data, 0x30)[0]
    first_difat_sector = struct.unpack_from("<I", data, 0x44)[0]
    difat_sector_count = struct.unpack_from("<I", data, 0x48)[0]
    if fat_sector_count == 0 or fat_sector_count > MAX_CFB_FAT_SECTORS:
        raise CompoundFileError("OLE FAT 数量无效")
    if difat_sector_count > MAX_CFB_FAT_SECTORS:
        raise CompoundFileError("OLE DIFAT 数量超出安全上限")

    fat_sector_ids = [
        sector_id
        for sector_id in struct.unpack_from("<109I", data, 0x4C)
        if sector_id <= CFB_MAX_REGULAR_SECTOR
    ]
    next_difat = first_difat_sector
    seen_difat: set[int] = set()
    for _ in range(difat_sector_count):
        if next_difat in seen_difat:
            raise CompoundFileError("OLE DIFAT 出现循环")
        seen_difat.add(next_difat)
        values = _u32_values(_sector(data, next_difat, sector_size))
        fat_sector_ids.extend(value for value in values[:-1] if value <= CFB_MAX_REGULAR_SECTOR)
        next_difat = values[-1]
    if len(fat_sector_ids) < fat_sector_count:
        raise CompoundFileError("OLE FAT 目录不完整")
    fat_sector_ids = fat_sector_ids[:fat_sector_count]

    fat: list[int] = []
    for sector_id in fat_sector_ids:
        fat.extend(_u32_values(_sector(data, sector_id, sector_size)))

    directory_parts: list[bytes] = []
    current = first_directory_sector
    seen_directory: set[int] = set()
    while current != CFB_END_OF_CHAIN:
        if current in seen_directory:
            raise CompoundFileError("OLE 目录链出现循环")
        if len(seen_directory) >= MAX_CFB_DIRECTORY_SECTORS:
            raise CompoundFileError("OLE 目录链超出安全上限")
        if current > CFB_MAX_REGULAR_SECTOR or current >= len(fat):
            raise CompoundFileError("OLE 目录链索引无效")
        seen_directory.add(current)
        directory_parts.append(_sector(data, current, sector_size))
        current = fat[current]

    names: set[str] = set()
    directory = b"".join(directory_parts)
    for offset in range(0, len(directory), 128):
        entry = directory[offset : offset + 128]
        if len(entry) != 128:
            break
        name_length = struct.unpack_from("<H", entry, 64)[0]
        entry_type = entry[66]
        if entry_type == 0 or name_length < 2 or name_length > 64 or name_length % 2:
            continue
        try:
            name = entry[: name_length - 2].decode("utf-16le")
        except UnicodeDecodeError:
            continue
        if name:
            names.add(name)
    if not names:
        raise CompoundFileError("OLE 目录为空或损坏")
    return names


def _detect_zip(path: Path, declared_suffix: str) -> DocumentDetection:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                return DocumentDetection(declared_suffix, "unsafe-archive", detail="ZIP 成员数量超出安全上限")
            names = {info.filename.replace("\\", "/").lstrip("/") for info in infos}
            if any(info.flag_bits & 0x1 for info in infos):
                return DocumentDetection(declared_suffix, "encrypted-archive", detail="ZIP 成员已加密")
            if "[Content_Types].xml" in names:
                try:
                    overrides = _content_type_overrides(
                        _read_small_zip_member(archive, "[Content_Types].xml", 1_048_576)
                    )
                except ZipSafetyError as error:
                    return DocumentDetection(declared_suffix, "unsafe-archive", detail=str(error))
                except (KeyError, ValueError, ElementTree.ParseError, RuntimeError) as error:
                    return DocumentDetection(declared_suffix, "damaged-archive", detail=str(error))
            else:
                overrides = {}
            if (
                "word/document.xml" in names
                and overrides.get("word/document.xml") in WORD_MAIN_CONTENT_TYPES
            ):
                macros = "word/vbaProject.bin" in names
                return DocumentDetection(declared_suffix, "docx", macros)
            if (
                "xl/workbook.xml" in names
                and overrides.get("xl/workbook.xml") in EXCEL_MAIN_CONTENT_TYPES
            ):
                macros = "xl/vbaProject.bin" in names
                return DocumentDetection(declared_suffix, "xlsx", macros)
            if "content.xml" in names:
                try:
                    mimetype = _read_small_zip_member(archive, "mimetype", 512).decode("ascii", errors="replace").strip()
                except ZipSafetyError as error:
                    return DocumentDetection(declared_suffix, "unsafe-archive", detail=str(error))
                except KeyError:
                    mimetype = ""
                if mimetype == "application/vnd.oasis.opendocument.spreadsheet":
                    return DocumentDetection(declared_suffix, "ods")
                if mimetype == "application/vnd.oasis.opendocument.text":
                    return DocumentDetection(declared_suffix, "odt")
            return DocumentDetection(
                declared_suffix,
                "proprietary-office" if declared_suffix in PROPRIETARY_OFFICE_SUFFIXES else "unknown-archive",
                detail="压缩容器不含受支持的 Office 正文结构",
            )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError) as error:
        return DocumentDetection(declared_suffix, "damaged-archive", detail=str(error))


def _detect_ole(path: Path, declared_suffix: str) -> DocumentDetection:
    try:
        names = compound_stream_names(path)
    except (OSError, CompoundFileError) as error:
        return DocumentDetection(declared_suffix, "damaged-ole", detail=str(error))
    folded = {name.casefold() for name in names}
    if {"encryptedpackage", "encryptioninfo"}.issubset(folded):
        return DocumentDetection(declared_suffix, "encrypted-office", detail="Office 加密容器")
    if "workbook" in folded or "book" in folded:
        return DocumentDetection(declared_suffix, "xls")
    if "worddocument" in folded:
        return DocumentDetection(declared_suffix, "doc")
    return DocumentDetection(
        declared_suffix,
        "proprietary-office" if declared_suffix in PROPRIETARY_OFFICE_SUFFIXES else "unknown-ole",
        detail="OLE 容器不含 WordDocument、Workbook 或 Book 流",
    )


def _looks_like_text(prefix: bytes) -> bool:
    if not prefix:
        return True
    if b"\x00" in prefix:
        return False
    try:
        prefix.decode("utf-8-sig")
        return True
    except UnicodeDecodeError:
        try:
            prefix.decode("gb18030")
            return True
        except UnicodeDecodeError:
            return False


def detect_document(path: Path) -> DocumentDetection:
    declared_suffix = path.suffix.casefold()
    try:
        with path.open("rb") as handle:
            prefix = handle.read(8_192)
    except OSError as error:
        return DocumentDetection(declared_suffix, "unreadable", detail=str(error))
    if prefix.startswith(ZIP_MAGIC):
        return _detect_zip(path, declared_suffix)
    if prefix.startswith(OLE_MAGIC):
        return _detect_ole(path, declared_suffix)
    if declared_suffix == ".et":
        return DocumentDetection(
            declared_suffix,
            "proprietary-office",
            detail="ET 文件未识别为 XLS、XLSX 或 ODS 兼容容器",
        )
    if prefix.startswith(PDF_MAGIC):
        return DocumentDetection(declared_suffix, "pdf")
    if prefix.lstrip(b"\xef\xbb\xbf\x20\t\r\n").lower().startswith(RTF_MAGIC):
        return DocumentDetection(declared_suffix, "rtf")
    if declared_suffix == ".wps" and _looks_like_text(prefix):
        return DocumentDetection(
            declared_suffix,
            "proprietary-office",
            detail="WPS 文件未识别为兼容 Office、ODF 或 RTF 容器",
        )
    if declared_suffix in KNOWN_DOCUMENT_SUFFIXES and _looks_like_text(prefix):
        return DocumentDetection(declared_suffix, "text")
    return DocumentDetection(
        declared_suffix,
        "proprietary-office" if declared_suffix in PROPRIETARY_OFFICE_SUFFIXES else "unknown-binary",
        detail="未识别到受支持的文档容器或文本编码",
    )
