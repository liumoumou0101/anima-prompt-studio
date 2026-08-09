from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore:
    """Store SSH passwords in Windows Credential Manager, never in SQLite."""

    TARGET_PREFIX = "AnimaPromptStudio/SSH/"

    def __init__(self, backend=None) -> None:
        self.backend = backend if backend is not None else (
            WindowsCredentialBackend() if sys.platform == "win32" else None
        )

    @property
    def available(self) -> bool:
        return self.backend is not None

    def read_password(self, profile_id: str) -> str:
        if not self.backend or not profile_id:
            return ""
        return self.backend.read(self.TARGET_PREFIX + profile_id)

    def save_password(self, profile_id: str, username: str, password: str) -> None:
        if not self.backend:
            raise CredentialStoreError("当前系统不支持安全保存密码。")
        if not profile_id or not password:
            return
        self.backend.write(self.TARGET_PREFIX + profile_id, username, password)

    def delete_password(self, profile_id: str) -> None:
        if self.backend and profile_id:
            self.backend.delete(self.TARGET_PREFIX + profile_id)


class MemoryCredentialBackend:
    """Non-persistent backend used by automated tests."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, str]] = {}

    def write(self, target: str, username: str, password: str) -> None:
        self.values[target] = (username, password)

    def read(self, target: str) -> str:
        return self.values.get(target, ("", ""))[1]

    def delete(self, target: str) -> None:
        self.values.pop(target, None)


class WindowsCredentialBackend:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def __init__(self) -> None:
        self.advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.advapi32.CredWriteW.argtypes = [ctypes.POINTER(self.CREDENTIALW), wintypes.DWORD]
        self.advapi32.CredWriteW.restype = wintypes.BOOL
        self.advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self.CREDENTIALW)),
        ]
        self.advapi32.CredReadW.restype = wintypes.BOOL
        self.advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.advapi32.CredDeleteW.restype = wintypes.BOOL
        self.advapi32.CredFree.argtypes = [ctypes.c_void_p]

    def write(self, target: str, username: str, password: str) -> None:
        raw = password.encode("utf-16-le")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = self.CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = username
        if not self.advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialStoreError(f"Windows 凭据保存失败：{ctypes.get_last_error()}")

    def read(self, target: str) -> str:
        pointer = ctypes.POINTER(self.CREDENTIALW)()
        if not self.advapi32.CredReadW(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self.ERROR_NOT_FOUND:
                return ""
            raise CredentialStoreError(f"Windows 凭据读取失败：{error}")
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(pointer)

    def delete(self, target: str) -> None:
        if not self.advapi32.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != self.ERROR_NOT_FOUND:
                raise CredentialStoreError(f"Windows 凭据删除失败：{error}")
