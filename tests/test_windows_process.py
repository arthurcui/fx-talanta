from types import SimpleNamespace

import pytest

from fx_talanta.acceptance import windows_process
from fx_talanta.observer.mt5 import ObservationFailure


def test_process_match_requires_full_executable_path(monkeypatch):
    binding = SimpleNamespace(terminal_path=r"C:\FOREX\terminal64.exe")
    seen = []

    def images(name):
        seen.append(name)
        return [
            (8, r"C:\CMC\terminal64.exe"),
            (6, r"c:\forex\terminal64.exe"),
            (2, r"C:\FOREX\terminal64.exe"),
        ]

    monkeypatch.setattr(windows_process, "_images", images)
    assert windows_process.matching_pids(binding) == [2, 6]
    assert seen == ["terminal64.exe"]


def test_unreadable_candidate_does_not_become_single_match(monkeypatch):
    def images(name):
        yield 2, r"C:\FOREX\terminal64.exe"
        raise ObservationFailure("PROCESS_INSPECTION_UNAVAILABLE")

    monkeypatch.setattr(windows_process, "_images", images)
    with pytest.raises(ObservationFailure):
        windows_process.matching_pids(SimpleNamespace(terminal_path=r"C:\FOREX\terminal64.exe"))


def test_no_matching_process_stays_empty(monkeypatch):
    monkeypatch.setattr(windows_process, "_images", lambda _: iter([]))
    assert (
        windows_process.matching_pids(SimpleNamespace(terminal_path=r"C:\FOREX\terminal64.exe"))
        == []
    )
