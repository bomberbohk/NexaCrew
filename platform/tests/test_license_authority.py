# SPDX-License-Identifier: MIT
"""Tests for the mapstudiousa.com license-authority client.

Covers the contract with backend/nexacrew-license-api.php: activation,
re-validation, definitive rejection (revoked), offline grace behaviour and
the unconfigured (evaluation) mode. The HTTP layer is mocked — no network.
"""
import json
import time

import pytest

from app import license_authority as la


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh state + isolated grant cache for every test."""
    monkeypatch.setattr(la, "_CACHE_FILE", tmp_path / "authority_grant.json")
    with la._STATE_LOCK:
        la._state.update({"configured": False, "licensed": False,
                          "status": "unconfigured", "company": "", "plan": "",
                          "seats": 0, "expires_at": None, "last_check_at": None,
                          "last_ok_at": None, "detail": ""})
    yield


CFG = {"authority_license_key": "AAAAA-BBBBB-CCCCC-DDDDD",
       "authority_url": "https://mapstudiousa.com/backend/nexacrew-license-api.php",
       "authority_check_hours": 12}


def test_unconfigured_is_evaluation_mode():
    st = la.check_once({"authority_license_key": "", "authority_url": ""})
    assert st["status"] == "unconfigured"
    assert st["licensed"] is True          # evaluation mode never blocks ops


def test_activation_success(monkeypatch):
    seen = {}

    def fake_post(url, payload):
        seen.update(payload)
        return 200, {"ok": True, "status": "active", "company": "ACME Corp",
                     "plan": "business", "seats": 25,
                     "expires_at": "2027-08-15 00:00:00", "grant": "x.y"}

    monkeypatch.setattr(la, "_post", fake_post)
    st = la.check_once(CFG)
    assert st["licensed"] is True and st["status"] == "active"
    assert st["company"] == "ACME Corp" and st["seats"] == 25
    assert seen["action"] == "activate"          # first contact activates
    assert seen["key"] == CFG["authority_license_key"]
    assert len(seen["fingerprint"]) == 64        # sha256 hex
    assert seen["hostname"] and seen["mac"]      # hardware identity sent


def test_second_check_validates_not_activates(monkeypatch):
    monkeypatch.setattr(la, "_post", lambda u, p: (200, {"ok": True, "company": "A",
                                                         "plan": "starter", "seats": 5}))
    la.check_once(CFG)
    actions = []
    monkeypatch.setattr(la, "_post",
                        lambda u, p: (actions.append(p["action"]),
                                      (200, {"ok": True}))[1])
    la.check_once(CFG)
    assert actions == ["validate"]


def test_revoked_is_definitive(monkeypatch):
    monkeypatch.setattr(la, "_post", lambda u, p: (403, {"ok": False,
                                                         "status": "revoked",
                                                         "error": "license revoked"}))
    st = la.check_once(CFG)
    assert st["licensed"] is False and st["status"] == "revoked"


def test_offline_grace_honours_cached_grant(monkeypatch):
    monkeypatch.setattr(la, "_post", lambda u, p: (200, {"ok": True, "company": "A",
                                                         "plan": "starter", "seats": 5}))
    la.check_once(CFG)                             # activate + cache grant

    def unreachable(u, p):
        raise ConnectionError("authority unreachable after 3 attempts: timeout")

    monkeypatch.setattr(la, "_post", unreachable)
    st = la.check_once(CFG)
    assert st["status"] == "grace" and st["licensed"] is True


def test_grace_expires_after_window(monkeypatch):
    la._save_cache({"activated": True, "ok_at": time.time() - la.GRACE_S - 60,
                    "grant": "x.y"})

    def unreachable(u, p):
        raise ConnectionError("down")

    monkeypatch.setattr(la, "_post", unreachable)
    st = la.check_once(CFG)
    assert st["status"] == "error" and st["licensed"] is False


def test_cache_write_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(la, "_CACHE_FILE", tmp_path / "g.json")
    la._save_cache({"activated": True, "ok_at": 1.0})
    assert json.loads((tmp_path / "g.json").read_text())["activated"] is True
    assert not (tmp_path / "g.tmp").exists()       # temp file cleaned up
