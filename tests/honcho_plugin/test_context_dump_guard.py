"""Guards against unfiltered / unbounded Honcho context injection.

Calling ``peer.context()`` WITHOUT a search_query returns the peer's FULL
observation dump (potentially hundreds of stale entries).  Before these
guards, that happened on every init prewarm and on any turn whose user
message carried no text (image-only messages), and with ``contextTokens``
unset the whole dump was injected into the prompt uncapped.

Two guards are pinned here:
1. ``_semantic_query()`` — every context fetch gets a non-empty search
   query: the current message, else the last non-trivial one, else a
   neutral profile query.
2. ``contextTokens`` defaults to a real budget instead of uncapped;
   explicit 0 (or negative) opts out.
"""

from plugins.memory.honcho import HonchoMemoryProvider
from plugins.memory.honcho.client import (
    HonchoClientConfig,
    _parse_context_tokens,
    _DEFAULT_CONTEXT_TOKENS,
)


def _bare_provider() -> HonchoMemoryProvider:
    provider = object.__new__(HonchoMemoryProvider)
    provider._last_semantic_query = ""
    return provider


class TestSemanticQueryFallback:
    def test_non_trivial_query_used_and_remembered(self):
        provider = _bare_provider()
        query = provider._semantic_query("How do I reconcile the general ledger?")
        assert query == "How do I reconcile the general ledger?"
        assert provider._last_semantic_query == query

    def test_empty_query_falls_back_to_last_semantic(self):
        provider = _bare_provider()
        provider._semantic_query("Summarize the trial balance discrepancies")
        assert provider._semantic_query("") == "Summarize the trial balance discrepancies"
        assert provider._semantic_query(None) == "Summarize the trial balance discrepancies"

    def test_trivial_query_does_not_overwrite_last(self):
        provider = _bare_provider()
        provider._semantic_query("Draft the dispute worksheet")
        provider._semantic_query("ok")
        assert provider._last_semantic_query == "Draft the dispute worksheet"

    def test_slash_command_falls_back(self):
        provider = _bare_provider()
        provider._semantic_query("what changed in the payroll run?")
        assert (
            provider._semantic_query("/goal keep going")
            == "what changed in the payroll run?"
        )

    def test_no_history_uses_profile_fallback(self):
        provider = _bare_provider()
        assert provider._semantic_query() == HonchoMemoryProvider._PROFILE_FALLBACK_QUERY

    def test_result_is_never_empty(self):
        provider = _bare_provider()
        for prompt in ("", None, "ok", "/status", "   "):
            assert provider._semantic_query(prompt)


class TestContextTokensDefault:
    def test_unset_defaults_to_budget(self):
        assert _parse_context_tokens(None, None) == _DEFAULT_CONTEXT_TOKENS

    def test_dataclass_default_matches(self):
        assert HonchoClientConfig().context_tokens == _DEFAULT_CONTEXT_TOKENS

    def test_explicit_value_wins(self):
        assert _parse_context_tokens(1500, None) == 1500
        assert _parse_context_tokens(None, 800) == 800
        assert _parse_context_tokens(1500, 800) == 1500

    def test_zero_or_negative_disables_cap(self):
        assert _parse_context_tokens(0, None) is None
        assert _parse_context_tokens(None, 0) is None
        assert _parse_context_tokens(-1, None) is None

    def test_invalid_value_falls_through(self):
        assert _parse_context_tokens("garbage", None) == _DEFAULT_CONTEXT_TOKENS
        assert _parse_context_tokens("garbage", 900) == 900
