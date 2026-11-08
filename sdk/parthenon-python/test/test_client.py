"""Tests for the Parthenon Python SDK client (no network)."""
import io
import json
import urllib.request

import pytest

from parthenon import Client, ParthenonError


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_client_requires_base_url_and_credential():
    with pytest.raises(ParthenonError):
        Client(base_url="", credential="x")
    with pytest.raises(ParthenonError):
        Client(base_url="http://x", credential="")


def test_submit_builds_request(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = req.data
        return _FakeResponse(json.dumps({"session_id": "abc", "status": "queued"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = Client(base_url="http://localhost:8002", credential="phn_cl_sk_x")
    out = c.submit({"email_body": "hi"})

    assert out["session_id"] == "abc"
    assert captured["url"].endswith("/integrate/submit")
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer phn_cl_sk_x"
    assert json.loads(captured["body"]) == {"input": {"email_body": "hi"}}


def test_config_uses_get(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        return _FakeResponse(json.dumps({"client_name": "Acme"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = Client(base_url="http://localhost:8002/", credential="phn_cl_pk_x")
    out = c.config()

    assert out["client_name"] == "Acme"
    assert captured["method"] == "GET"
    assert captured["url"] == "http://localhost:8002/integrate/config"
