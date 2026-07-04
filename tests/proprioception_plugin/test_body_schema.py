"""Tests for the body-schema generator (C:\\tools\\body-schema-gen.py).

The generator maintains Hermes's stable self-model in SOUL.md. The two things
that MUST hold: (1) the fingerprint is over rendered bytes so a model swap or a
label tweak doesn't churn the cached prefix; (2) a partial dashboard read can
never amputate her anatomy and persist it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_GEN_PATH = Path(r"C:\tools\body-schema-gen.py")

pytestmark = pytest.mark.skipif(not _GEN_PATH.exists(), reason="generator not installed")


def _load():
    spec = importlib.util.spec_from_file_location("body_schema_gen", _GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["body_schema_gen"] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load()


def _systems(labels_by_cat):
    out = []
    for cat, labels in labels_by_cat.items():
        for i, lbl in enumerate(labels):
            out.append({"id": f"{cat[:3]}{i}", "cat": cat, "label": lbl,
                        "state": "ok", "detail": "answering on :9999 - 42 GiB free"})
    return out


# --- role normalization: the fingerprint-stability keystone ---

def test_strip_model_paren():
    assert gen._strip_model_paren("Main brain (Qwen3.6-27B NVFP4)") == "Main brain"
    assert gen._strip_model_paren("Document vision (reads scans/photos)") == "Document vision"
    assert gen._strip_model_paren("Disk space (C:)") == "Disk space"
    assert gen._strip_model_paren("Watchdog") == "Watchdog"


def test_fingerprint_stable_across_model_swap():
    """A model swap changes the label's parenthetical but not the roster shape.
    The rendered block — and thus the fingerprint — must be identical."""
    a = _systems({"AI models": ["Main brain (Qwen3.6-27B NVFP4)", "Document vision (8B)"]})
    b = _systems({"AI models": ["Main brain (Llama-70B FP8)", "Document vision (32B)"]})
    block_a = gen.render_block(a, None)
    block_b = gen.render_block(b, None)
    assert block_a == block_b, "model swap must not change the rendered self-model"


def test_block_excludes_live_state():
    systems = _systems({"AI models": ["Main brain (X)"]})
    block = gen.render_block(systems, None)
    # nouns only — no state, no detail, no numbers from the dashboard
    assert ":9999" not in block
    assert "42 GiB" not in block
    assert "answering" not in block
    assert "ok" not in block.split("state")[0].lower() or "state" not in block.lower()


def test_block_has_no_timestamp():
    import re
    block = gen.render_block(_systems({"AI models": ["Main brain (X)"]}), None)
    # a date/time inside the cached-prefix block is a cache bomb; there must be none
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", block)
    assert not re.search(r"\b\d\d:\d\d\b", block)


def test_block_uses_capability_not_possession_language():
    block = gen.render_block(_systems({"AI models": ["Main brain (X)"]}), None)
    low = block.lower()
    assert "it is mine" not in low
    assert "i have this sense" not in low
    assert "can read my host machine" in low  # capability framing
    assert "not moods" in low or "not feelings" in low  # honesty stamp present


def test_render_is_deterministic():
    systems = _systems({"AI models": ["B (x)", "A (y)"], "Self-healing": ["Watchdog", "Medic"]})
    assert gen.render_block(systems, None) == gen.render_block(list(reversed(systems)), None)


# --- splice: insert once, replace idempotently, never touch hand-written text ---

def test_splice_insert_then_replace_idempotent():
    soul = "# SOUL\n\nHand-written principle.\n"
    block1 = gen.render_block(_systems({"AI models": ["Main (x)"]}), None)
    once = gen.splice(soul, block1)
    assert once.count(gen.BEGIN) == 1
    assert "Hand-written principle." in once
    # re-splicing the same block replaces in place — no duplication
    twice = gen.splice(once, block1)
    assert twice.count(gen.BEGIN) == 1
    assert twice.count(gen.END) == 1
    assert "Hand-written principle." in twice


def test_splice_replaces_stale_block_preserving_surroundings():
    soul = "# SOUL\n\nAbove.\n"
    old = gen.render_block(_systems({"AI models": ["Old (x)"]}), None)
    spliced = gen.splice(soul, old)
    new = gen.render_block(_systems({"AI models": ["New (x)"], "Self-healing": ["Medic"]}), None)
    replaced = gen.splice(spliced, new)
    assert replaced.count(gen.BEGIN) == 1
    assert "New" in replaced and "Old" not in replaced
    assert "Above." in replaced


# --- the partial-read guard (the most dangerous failure the panel found) ---

def test_floor_guard_aborts_on_tiny_roster(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(gen, "SOUL_PATH", tmp_path / "SOUL.md")
    monkeypatch.setattr(gen, "fetch_home",
                        lambda *a, **k: {"systems": _systems({"AI models": ["A (x)"]})})  # 1 system
    monkeypatch.setattr(sys, "argv", ["gen"])
    rc = gen.main()
    assert rc == 0
    assert not (tmp_path / "SOUL.md").exists()  # never wrote an amputated portrait


def test_shrink_requires_confirmation(monkeypatch, tmp_path):
    import json
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"last_fp": "old", "last_count": 20}), encoding="utf-8")
    soul = tmp_path / "SOUL.md"
    soul.write_text("# SOUL\n", encoding="utf-8")
    monkeypatch.setattr(gen, "STATE_PATH", state)
    monkeypatch.setattr(gen, "SOUL_PATH", soul)
    monkeypatch.setattr(gen, "ABSOLUTE_FLOOR", 3)
    monkeypatch.setattr(gen, "time", type("T", (), {"sleep": staticmethod(lambda *_: None),
                                                     "strftime": staticmethod(lambda *_: "t")}))
    # dashboard reports a SHRUNK roster (12 systems), then a second read disagrees
    reads = [
        {"systems": _systems({"AI models": ["a (1)", "b (2)", "c (3)", "d (4)", "e (5)",
                                            "f (6)", "g (7)", "h (8)", "i (9)", "j (10)",
                                            "k (11)", "l (12)"]})},
        {"systems": _systems({"AI models": ["a (1)", "b (2)", "c (3)"]})},  # different count
    ]
    monkeypatch.setattr(gen, "fetch_home", lambda *a, **k: reads.pop(0))
    monkeypatch.setattr(sys, "argv", ["gen"])
    rc = gen.main()
    assert rc == 0
    # unconfirmed shrink → must NOT overwrite SOUL.md
    assert soul.read_text(encoding="utf-8") == "# SOUL\n"


def test_no_write_when_fingerprint_unchanged(monkeypatch, tmp_path):
    import json
    systems = _systems({"AI models": ["Main (x)"], "Self-healing": ["Medic", "Watchdog"],
                        "This computer": ["Disk", "GPU"], "Office & network": ["Leonard"],
                        "Memory & data": ["Honcho"], "Hermes for the office": ["Gateway"],
                        "extra1": ["a"], "extra2": ["b"], "extra3": ["c"], "extra4": ["d"]})
    # pin ontology to None so the test's fp matches what main() will render
    monkeypatch.setattr(gen, "_ontology_digest", lambda: None)
    block = gen.render_block(systems, None)
    import hashlib
    fp = hashlib.sha256(block.encode("utf-8")).hexdigest()[:12]
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"last_fp": fp, "last_count": len(systems)}), encoding="utf-8")
    soul = tmp_path / "SOUL.md"
    soul.write_text("# SOUL\n", encoding="utf-8")
    monkeypatch.setattr(gen, "STATE_PATH", state)
    monkeypatch.setattr(gen, "SOUL_PATH", soul)
    monkeypatch.setattr(gen, "fetch_home", lambda *a, **k: {"systems": systems})
    monkeypatch.setattr(sys, "argv", ["gen"])
    rc = gen.main()
    assert rc == 0
    assert soul.read_text(encoding="utf-8") == "# SOUL\n"  # byte-stable → untouched
