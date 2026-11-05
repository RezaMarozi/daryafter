"""File categories used for sorting downloads into sub-folders."""
from __future__ import annotations

import os

CATEGORY_EXTENSIONS: dict[str, frozenset[str]] = {
    "Video": frozenset("mp4 mkv avi mov wmv flv webm m4v mpg mpeg 3gp ts".split()),
    "Music": frozenset("mp3 flac wav aac ogg m4a wma opus aiff".split()),
    "Compressed": frozenset("zip rar 7z tar gz bz2 xz zst tgz iso img cab".split()),
    "Documents": frozenset("pdf doc docx xls xlsx ppt pptx txt rtf odt ods epub mobi csv md".split()),
    "Programs": frozenset("exe msi msix appx apk bat cmd ps1 dmg pkg deb rpm jar".split()),
    "Images": frozenset("jpg jpeg png gif bmp webp svg tiff ico heic raw psd".split()),
}
CATEGORY_ORDER = ["Video", "Music", "Compressed", "Documents", "Programs", "Images", "Other"]
_BY_EXT = {ext: cat for cat, exts in CATEGORY_EXTENSIONS.items() for ext in exts}


def category_for(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    return _BY_EXT.get(ext, "Other")


def looks_downloadable(url: str) -> bool:
    """True if a URL path ends in an extension we know is a real file."""
    from urllib.parse import urlsplit

    ext = os.path.splitext(urlsplit(url).path)[1].lower().lstrip(".")
    return ext in _BY_EXT and ext not in ("txt", "md", "csv", "svg")
