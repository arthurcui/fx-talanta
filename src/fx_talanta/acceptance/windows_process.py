"""Read-only Windows process identity checks without launching a shell.

Toolhelp snapshots and PROCESS_QUERY_LIMITED_INFORMATION identify the full image
path. This still has the existing PID-reuse/lifecycle race; it is not a process
lock. An unreadable terminal candidate fails closed instead of being omitted.
"""

import ctypes as c
import os
from pathlib import PureWindowsPath

from fx_talanta.observer.contracts import windows_path
from fx_talanta.observer.mt5 import ObservationFailure


def _images(executable):
    if os.name != "nt":
        raise ObservationFailure("WINDOWS_PROCESS_QUERY_REQUIRED")

    class Entry(c.Structure):
        _fields_ = [
            ("size", c.c_uint32),
            ("usage", c.c_uint32),
            ("pid", c.c_uint32),
            ("heap", c.c_size_t),
            ("module", c.c_uint32),
            ("threads", c.c_uint32),
            ("parent", c.c_uint32),
            ("priority", c.c_int32),
            ("flags", c.c_uint32),
            ("name", c.c_wchar * 260),
        ]

    api = c.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateToolhelp32Snapshot": ([c.c_uint32, c.c_uint32], c.c_void_p),
        "Process32FirstW": ([c.c_void_p, c.POINTER(Entry)], c.c_int),
        "Process32NextW": ([c.c_void_p, c.POINTER(Entry)], c.c_int),
        "OpenProcess": ([c.c_uint32, c.c_int, c.c_uint32], c.c_void_p),
        "QueryFullProcessImageNameW": (
            [c.c_void_p, c.c_uint32, c.c_wchar_p, c.POINTER(c.c_uint32)],
            c.c_int,
        ),
        "CloseHandle": ([c.c_void_p], c.c_int),
    }
    for name, (args, result) in signatures.items():
        getattr(api, name).argtypes, getattr(api, name).restype = args, result
    snapshot = api.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == c.c_void_p(-1).value or snapshot is None:
        raise ObservationFailure("PROCESS_INSPECTION_UNAVAILABLE")
    try:
        row = Entry()
        row.size = c.sizeof(row)
        present = api.Process32FirstW(snapshot, c.byref(row))
        while present:
            if row.name.casefold() == executable.casefold():
                handle = api.OpenProcess(0x1000, False, row.pid)
                if not handle:
                    # A process may exit between snapshot and inspection.
                    if c.get_last_error() != 87:  # ERROR_INVALID_PARAMETER
                        raise ObservationFailure("PROCESS_INSPECTION_UNAVAILABLE")
                else:
                    try:
                        size = c.c_uint32(32768)
                        path = c.create_unicode_buffer(size.value)
                        if not api.QueryFullProcessImageNameW(handle, 0, path, c.byref(size)):
                            raise ObservationFailure("PROCESS_INSPECTION_UNAVAILABLE")
                        yield row.pid, path.value
                    finally:
                        api.CloseHandle(handle)
            present = api.Process32NextW(snapshot, c.byref(row))
        if c.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ObservationFailure("PROCESS_INSPECTION_UNAVAILABLE")
    finally:
        api.CloseHandle(snapshot)


def matching_pids(binding):
    expected = windows_path(binding.terminal_path)
    return sorted(
        pid
        for pid, path in _images(PureWindowsPath(binding.terminal_path).name)
        if windows_path(path) == expected
    )
