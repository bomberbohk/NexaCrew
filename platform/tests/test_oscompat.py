"""OS-compatibility simulator tests.

Proves — via the NEXACREW_SIMULATE_OS simulator — that:
  * macOS High Sierra is detected as the `legacy_copilot` tier and prompts
    are relayed to GitHub Copilot in VS Code (end-to-end, with a simulated
    Copilot answering the relay file),
  * macOS Mountain Lion and Windows 7 land in `legacy_api`,
  * OSes below the minimum are refused.
"""

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import oscompat  # noqa: E402


def _detect(sim):
    os.environ["NEXACREW_SIMULATE_OS"] = sim
    try:
        return oscompat.detect()
    finally:
        os.environ.pop("NEXACREW_SIMULATE_OS", None)


def test_high_sierra_uses_copilot_relay():
    info = _detect("high_sierra")
    assert info["tier"] == "legacy_copilot"
    assert info["ai_strategy"] == "copilot_relay"
    assert info["supported"] is True
    assert "1.85" in (info["tools"]["vscode"] or "")


def test_mountain_lion_and_win7_use_api_mode():
    for sim in ("mountain_lion", "win7", "win8"):
        info = _detect(sim)
        assert info["tier"] == "legacy_api", sim
        assert info["ai_strategy"] == "api", sim
        assert info["supported"] is True, sim
    # sanity: modern OSes stay full
    for sim in ("win10", "catalina", "linux"):
        assert _detect(sim)["tier"] == "full", sim


def test_below_minimum_is_refused():
    os.environ["NEXACREW_SIMULATE_OS"] = "mountain_lion"
    try:
        info = oscompat.detect()
        assert info["supported"]
    finally:
        os.environ.pop("NEXACREW_SIMULATE_OS", None)
    # simulate macOS 10.7 (below Mountain Lion) directly
    oscompat._SIM_PROFILES["lion"] = ("Darwin", "10.7.5")
    info = _detect("lion")
    assert info["tier"] == "unsupported"
    assert not info["supported"]
    msg = oscompat.refuse_message(info)
    assert "BELOW the minimum" in msg and "Mountain Lion" in msg


def test_copilot_relay_end_to_end_simulated():
    """Full High-Sierra pipeline: the relay writes a prompt file; a simulated
    Copilot (thread) answers it; the provider returns the response."""
    os.environ["NEXACREW_SIMULATE_OS"] = "high_sierra"
    try:
        from app.providers import CopilotRelayProvider
        relay = CopilotRelayProvider()
        relay._vscode = None  # don't actually launch an editor in CI

        def fake_copilot():
            # wait for the prompt file to appear, then write the response —
            # exactly what Copilot in VS Code does on a real High Sierra Mac
            deadline = time.time() + 20
            while time.time() < deadline:
                prompts = list(CopilotRelayProvider.RELAY_DIR.glob("*_prompt.md"))
                if prompts:
                    p = prompts[0]
                    body = p.read_text(encoding="utf-8")
                    assert "HS TEST PROMPT" in body
                    rid = p.name.split("_")[0]
                    (CopilotRelayProvider.RELAY_DIR / f"{rid}_response.md").write_text(
                        "SIMULATED COPILOT ANSWER: 42", encoding="utf-8")
                    return
                time.sleep(0.2)

        t = threading.Thread(target=fake_copilot, daemon=True)
        t.start()
        out = relay.run("HS TEST PROMPT — what is the answer?")
        assert "SIMULATED COPILOT ANSWER: 42" in out
        # relay cleans up after itself
        assert not list(CopilotRelayProvider.RELAY_DIR.glob("*_prompt.md"))
    finally:
        os.environ.pop("NEXACREW_SIMULATE_OS", None)
