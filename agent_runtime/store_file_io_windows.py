"""The Windows half of :func:`agent_runtime.store_file_io.narrow_windows_acl`: the DACL, in-process.

A sibling module so the store helpers carry no Win32 binding on a platform with no
Windows: the bundled phone profile switches this module off, and ``store_file_io``
imports it only inside ``narrow_windows_acl``, whose production callers all sit behind
``os.name == "nt"``. The rules (the grant, never a raise) are ``store_file_io``'s.

The DACL is written through ``advapi32`` rather than an ``icacls`` spawn (q-boot,
2026-10-17): a secure write narrows up to three names, and three process spawns per
write was the whole of its cost. The result is the DACL ``icacls <path>
/inheritance:r /grant:r <user>:(R,W,D)`` produced on a fresh file — protected (no
inherited ACEs), one ACCESS_ALLOWED ACE for the process token's user, mask
:data:`WINDOWS_STORE_ACCESS_MASK` — except that any explicit ACE for another principal
is dropped too, where ``icacls /grant:r`` would have kept it.
"""

from __future__ import annotations

import ctypes
from pathlib import Path

try:  # a POSIX ctypes may refuse the Windows typedefs; the phone never imports this
    from ctypes import wintypes
except (ImportError, ValueError):  # pragma: no cover - not Windows
    wintypes = None  # type: ignore[assignment]

__layer__ = "stores"
__all__ = ["WINDOWS_STORE_ACCESS_MASK", "narrow_windows_acl"]

_FILE_GENERIC_READ = 0x00120089
_FILE_GENERIC_WRITE = 0x00120116
_DELETE = 0x00010000
# ``store_file_io.WINDOWS_STORE_GRANT`` ("(R,W,D)") as the mask icacls writes for it.
WINDOWS_STORE_ACCESS_MASK = _FILE_GENERIC_READ | _FILE_GENERIC_WRITE | _DELETE

_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1
_ACL_REVISION = 2
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_ACL_HEADER_BYTES = 8
_ACCESS_ALLOWED_ACE_BYTES_WITHOUT_SID = 8

_bound: tuple[ctypes.WinDLL, ctypes.WinDLL] | None = None


def _dlls() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """advapi32 and kernel32 with their signatures declared, bound once per process."""

    global _bound
    if _bound is not None:
        return _bound
    if wintypes is None:
        raise OSError("ctypes.wintypes is unavailable")
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    advapi32.AddAccessAllowedAce.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _bound = (advapi32, kernel32)
    return _bound


def _token_user(advapi32: ctypes.WinDLL, kernel32: ctypes.WinDLL) -> ctypes.Array | None:
    """The TOKEN_USER buffer for this process (its first field points at the SID)."""

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        return None
    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value or 1)
        if not advapi32.GetTokenInformation(
            token, _TOKEN_USER_CLASS, buffer, needed, ctypes.byref(needed)
        ):
            return None
        return buffer
    finally:
        kernel32.CloseHandle(token)


def narrow_windows_acl(path: Path) -> str:
    """A protected DACL with one grant to this process's user; the outcome, never a raise."""

    try:
        advapi32, kernel32 = _dlls()
    except (AttributeError, OSError):
        return "skipped:not_windows"
    try:
        token_user = _token_user(advapi32, kernel32)
        if token_user is None:
            return f"error:token{ctypes.get_last_error()}"
        sid = ctypes.c_void_p.from_buffer(token_user).value
        size = _ACL_HEADER_BYTES + _ACCESS_ALLOWED_ACE_BYTES_WITHOUT_SID
        size = (size + advapi32.GetLengthSid(sid) + 3) & ~3
        acl = ctypes.create_string_buffer(size)
        if not advapi32.InitializeAcl(acl, size, _ACL_REVISION):
            return f"error:acl{ctypes.get_last_error()}"
        if not advapi32.AddAccessAllowedAce(acl, _ACL_REVISION, WINDOWS_STORE_ACCESS_MASK, sid):
            return f"error:ace{ctypes.get_last_error()}"
        status = advapi32.SetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            acl,
            None,
        )
    except (OSError, ValueError, ctypes.ArgumentError) as exc:
        return f"error:{type(exc).__name__}"
    return "narrowed" if status == 0 else f"error:win{status}"
