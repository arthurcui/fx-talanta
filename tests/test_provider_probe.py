import importlib.util
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "probe_public_feeds", Path(__file__).resolve().parents[1] / "scripts/probe_public_feeds.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_feed_metadata_without_retaining_article_text():
    body = b"""<rss><channel><item><guid>id</guid><title>private content</title>
    <pubDate>Mon, 02 Nov 2026 14:00:00 +0900</pubDate></item></channel></rss>"""
    result = probe.summarize_xml(body)
    assert result["items"] == result["items_with_ids"] == 1
    assert result["latest_publication"] == "2026-11-02T05:00:00+00:00"
    assert "private content" not in str(result) and "title" not in result


def test_missing_timezone_duplicates_and_future_dates_are_reported():
    body = b"""<rss><channel><item><guid>x</guid><pubDate>bad</pubDate></item>
    <item><guid>x</guid><date>2099-01-01T00:00:00Z</date></item>
    <item><date>2026-11-02T00:00:00</date></item></channel></rss>"""
    result = probe.summarize_xml(body)
    assert result["duplicate_ids"] == 1
    assert result["timestamp_missing_or_invalid"] == 2
    assert result["future_timestamp_count"] == 1


@pytest.mark.parametrize(
    "body",
    [b"<!DOCTYPE rss><rss/>", b"<html>blocked</html>", "<!DOCTYPE rss><rss/>".encode("utf-16")],
)
def test_non_feed_and_entity_documents_rejected(body):
    with pytest.raises(ValueError):
        probe.summarize_xml(body)


@pytest.mark.parametrize(
    "code,state", [(304, "NOT_MODIFIED"), (403, "HTTP_ERROR"), (429, "HTTP_ERROR")]
)
def test_http_outcomes_never_qualify_coverage(monkeypatch, code, state):
    class Opener:
        def open(self, request, timeout):
            assert timeout == 15
            assert request.get_header("If-modified-since") == "fixture-date"
            raise urllib.error.HTTPError(request.full_url, code, "private diagnostic", {}, None)

    monkeypatch.setattr(probe.urllib.request, "build_opener", lambda *a: Opener())
    result = probe.probe("fed", "fixture-date")
    assert result["probe_state"] == state
    assert not result["qualified_for_trading"]
    assert "private diagnostic" not in str(result)


def test_default_tls_requires_certificate_and_hostname_checks():
    import ssl

    ctx = probe.tls_context("default")
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_native_backend_missing_dependency_does_not_fall_back(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "truststore", None)
    with pytest.raises(RuntimeError, match="requires"):
        probe.tls_context("native")


def test_insecure_context_rejected_before_network(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(probe, "tls_context", lambda _: SimpleNamespace(check_hostname=False))
    with pytest.raises(RuntimeError, match="verified TLS"):
        probe.probe("ecb")
