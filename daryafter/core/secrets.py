"""Protect saved passwords. On Windows they are encrypted with DPAPI, which ties
them to the current Windows user; on other systems they are only obfuscated."""
from __future__ import annotations

import base64
import os

_DPAPI = "dpapi:"
_PLAIN = "plain:"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # CryptProtectData and CryptUnprotectData take the same seven parameters
    if not func(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> str:
    if not text:
        return ""
    raw = text.encode("utf-8")
    if os.name == "nt":
        try:
            return _DPAPI + base64.b64encode(_dpapi(raw, True)).decode("ascii")
        except Exception:
            pass
    return _PLAIN + base64.b64encode(raw).decode("ascii")


def unprotect(blob: str) -> str:
    """Returns "" if the value can't be decrypted (e.g. it belongs to another user)."""
    if not blob:
        return ""
    try:
        if blob.startswith(_DPAPI):
            return _dpapi(base64.b64decode(blob[len(_DPAPI):]), False).decode("utf-8")
        if blob.startswith(_PLAIN):
            return base64.b64decode(blob[len(_PLAIN):]).decode("utf-8")
    except Exception:
        return ""
    return ""
