"""Tests for per-session secret vault and redaction."""

from __future__ import annotations

import asyncio

from ansible_forge.safety.secret_vault import REDACTION_PLACEHOLDER, SecretVault, SessionVault


def test_store_and_retrieve() -> None:
    v = SessionVault("sess-a")
    v.store("db_pass", "longsecretvalue", "db")

    assert v.get("db_pass") == "longsecretvalue"


def test_get_missing_returns_none() -> None:
    v = SessionVault("sess-a")
    assert v.get("none") is None


def test_redact_replaces_known_secret() -> None:
    v = SessionVault("sess-a")
    secret = "abcdef"
    v.store("token", secret, "")
    text = f"run with {secret} here"

    out = v.redact(text)

    assert secret not in out
    assert REDACTION_PLACEHOLDER.format(name="token") in out


def test_redact_skips_short_values() -> None:
    v = SessionVault("sess-a")
    v.store("tiny", "abcde", "")  # len 5 < _SECRET_MIN_LENGTH
    assert v.redact("use abcde in cmd") == "use abcde in cmd"


def test_list_names() -> None:
    v = SessionVault("sess-a")
    v.store("a", "secretone1", "first")
    v.store("b", "secrettwo2", "second")

    names = v.list_names()
    by_name = {x["name"]: x["description"] for x in names}

    assert set(by_name) == {"a", "b"}
    assert by_name["a"] == "first"


def test_delete() -> None:
    v = SessionVault("sess-a")
    v.store("tmp", "deleteme1", "")
    assert v.delete("tmp") is True
    assert v.get("tmp") is None
    assert v.delete("tmp") is False


def test_session_isolation() -> None:
    global_vault = SecretVault()
    va = global_vault.for_session("s1")
    vb = global_vault.for_session("s2")

    va.store("k", "sharedname1", "")
    vb.store("other", "onlyinb2!", "")

    assert va.get("other") is None
    assert vb.get("k") is None


async def test_create_pending_then_store_unblocks() -> None:
    v = SessionVault("sess-p")

    evt = v.create_pending("api_key")

    async def delayed_store() -> None:
        await asyncio.sleep(0.01)
        v.store("api_key", "pendingval", "")

    t = asyncio.create_task(delayed_store())
    await asyncio.wait_for(evt.wait(), timeout=1.0)

    assert v.get("api_key") == "pendingval"
    await t


async def test_store_without_pending_sets_value() -> None:
    v = SessionVault("sess-p")
    v.store("plain", "plainsecret", "")
    assert v.get("plain") == "plainsecret"


def test_redact_dict_deep() -> None:
    v = SessionVault("sess-a")
    v.store("pwd", "deepsecret", "")
    data = {"x": {"y": "token deepsecret here"}, "ok": True}

    out = v.redact_dict(data)

    assert "deepsecret" not in str(out)
    assert REDACTION_PLACEHOLDER.format(name="pwd") in out["x"]["y"]
    assert out["ok"] is True


def test_destroy_session_via_secret_vault() -> None:
    sv = SecretVault()
    sess = sv.for_session("gone")
    sess.store("z", "zsecret!", "")
    sv.destroy_session("gone")

    sess2 = sv.for_session("gone")
    assert sess2.get("z") is None
