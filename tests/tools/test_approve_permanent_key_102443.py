"""Regression tests for #102443.

Choosing 'always' on an approval prompt persists the detector's pattern key
(a description string such as 'script execution via heredoc', or the
synthetic 'execute_code' key) into ``command_allowlist``. The command-text
matcher (``_command_matches_permanent_allowlist``) compared allowlist
entries against command text via exact/fnmatch — a pattern key can never
equal command text, so before the fix:

  - the persisted entry presented as coverage while silently never matching
    at the command level, and
  - ``execute_code`` persisted as an allowlist entry short-circuited the
    gate for the LITERAL command text ``execute_code`` (false positive).

The fix excludes detector pattern keys from the command-text matcher. They
remain enforced through ``is_approved()`` / ``_approval_key_aliases``,
where pattern-key approvals have always actually been checked — so the
'always' choice keeps working for its real purpose, the command matcher
only ever sees command patterns, and the config no longer misrepresents
itself as command rules.
"""

import os

import pytest

import tools.approval as A


@pytest.fixture(autouse=True)
def _clean_state():
    A._session_approved.clear()
    A._pending.clear()
    A._permanent_approved.clear()
    saved = {}
    for k in ("HERMES_INTERACTIVE", "HERMES_GATEWAY_SESSION",
              "HERMES_EXEC_ASK", "HERMES_YOLO_MODE"):
        if k in os.environ:
            saved[k] = os.environ.pop(k)
    yield
    A._session_approved.clear()
    A._pending.clear()
    A._permanent_approved.clear()
    os.environ.update(saved)


class TestPatternKeysExcludedFromCommandMatcher:
    def test_detector_description_is_recognized_as_pattern_key(self):
        assert A._is_detector_pattern_key("script execution via heredoc")
        assert A._is_detector_pattern_key("execute_code")
        assert A._is_detector_pattern_key("tirith:homograph_url")
        assert A._is_detector_pattern_key("plugin_rule:example")

    def test_command_patterns_are_not_pattern_keys(self):
        assert not A._is_detector_pattern_key("podman *")
        assert not A._is_detector_pattern_key("git status")

    def test_persisted_description_never_matches_command_text(self, monkeypatch):
        """The #102443 shape: 'always' saved a description string.

        The matcher must skip the pattern keys (they are not command text)
        without breaking a legitimate manual glob rule sitting beside them.
        """
        monkeypatch.setattr(A, "_permanent_approved", {
            "script execution via heredoc",
            "execute_code",
            "cargo *",
        })
        # Manual glob still works alongside pattern-key entries.
        assert A._command_matches_permanent_allowlist("cargo build")
        # The false positive is gone: the literal command text
        # 'execute_code' no longer short-circuits via the pattern key.
        assert not A._command_matches_permanent_allowlist("execute_code")

    def test_legacy_regex_keys_also_excluded(self, monkeypatch):
        monkeypatch.setattr(A, "_permanent_approved", {
            "(python[23]?|perl|ruby|node)\\s+<<",
        })
        assert not A._command_matches_permanent_allowlist("python3 <<'EOF'")

    def test_pattern_key_still_enforced_via_is_approved(self):
        """Excluding pattern keys from the command matcher must not break
        the real 'always' path: is_approved() resolves pattern keys."""
        A.approve_permanent("script execution via heredoc")
        assert A.is_approved("some-session", "script execution via heredoc")
        # Aliases still resolve the removed regex key to the description.
        assert A.is_approved(
            "some-session", "(python[23]?|perl|ruby|node)\\s+<<")


class TestAlwaysEndToEndPersistAndSkip:
    """End-to-end: 'always' on a heredoc prompt must silence the SAME
    detector class on the next call (the reporter's exact scenario)."""

    @pytest.fixture(autouse=True)
    def _manual_mode(self, monkeypatch):
        monkeypatch.setattr(A, "_get_approval_mode", lambda: "manual")

    def test_always_on_heredoc_silences_next_heredoc(self):
        os.environ["HERMES_INTERACTIVE"] = "1"
        calls = []

        def cb(*args, **kwargs):
            calls.append(kwargs)
            return "always"

        first = A.check_dangerous_command(
            "python3 - <<'EOF'\nprint(1)\nEOF", "local", approval_callback=cb)
        assert first["approved"] is True
        assert len(calls) == 1
        assert "script execution via heredoc" in A._permanent_approved

        # Second identical-class command: no second prompt (#102443:
        # pre-fix this re-prompted forever).
        second = A.check_dangerous_command(
            "python3 - <<'EOF'\nprint(2)\nEOF", "local", approval_callback=cb)
        assert second["approved"] is True
        assert len(calls) == 1
