"""Per-profile timezone scoping on the cron tick path (#97905).

A multiplexed scheduler ticks several profiles from ONE process. Each tick
scopes storage and HERMES_HOME to the profile via ``set_hermes_home_override``
/ ``use_cron_store``, but ``hermes_time.now()`` resolves the timezone ONCE
into a process-global cache. A profile whose ``config.yaml`` pins
``timezone: America/New_York`` therefore gets its cron schedules recomputed
against the process's zone (issue #9705's UTC-pinned service host +
America/Los_Angeles profile is the field report) — the next run lands on the
wrong wall clock, and the fire/repair machinery then thrashes around the
mismatched instants (#28934's guard can only paper over it after the first
wrong fire).

Test 1 drives the real compute path under the tick's tz-scope and asserts the
result carries the ticked profile's zone (RED on main: the override API does
not exist, and without scoping the process's +00:00 leaks into stored
instants). Test 2 pins the mechanism itself — resolution follows the profile
HOME inside the context, reverts outside, and never leaks across concurrent
contexts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def temp_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME so jobs.json doesn't touch the real store."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


def _write_cron_job(expr: str, next_run_at: str) -> str:
    from cron.jobs import create_job, load_jobs, save_jobs

    job = create_job(prompt="x", schedule="every 5m", name="tz-drift")
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job["id"]:
            j["schedule"] = {"kind": "cron", "expr": expr}
            j["next_run_at"] = next_run_at
    save_jobs(jobs)
    return job["id"]


def test_compute_next_run_follows_ticked_profile_clock(temp_home):
    """#97905: a recompute inside a profile-scoped tick must land on that
    profile's wall clock, not the process-global zone.

    A UTC process ticking an America/New_York profile: ``15 18 * * *`` from a
    UTC base instant must produce ``18:15`` stamped with the PROFILE's -4
    offset. On main the tick has no tz scope — ``hermes_time.now()`` returns
    the process zone and the result is stamped ``+00:00`` (wrong wall clock
    for the profile, the instant that #9705's reporter saw jobs fire hours
    off) — and the override API itself does not exist there.
    """
    from cron.jobs import compute_next_run, get_due_jobs, get_job

    # Process resolves UTC (empty process home, no configured timezone);
    # host-local is irrelevant because hermes_time falls back to a UTC-
    # equivalent server-local only when NO profile sets one. We pin the
    # process home explicitly below via temp_home being the PROFILE home.
    (temp_home / "config.yaml").write_text("timezone: America/New_York\n", encoding="utf-8")

    import hermes_time
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    # Simulate the two-level scope _start_multiplex sets up: the *process*
    # resolved UTC first (empty home), then this tick scopes an ET profile.
    process_home = temp_home.parent / "proc-home"
    process_home.mkdir(exist_ok=True)
    hermes_time.reset_cache()
    tok0 = set_hermes_home_override(str(process_home))
    try:
        hermes_time.now()  # prime the process-global cache with no-profile (server-local)
    finally:
        reset_hermes_home_override(tok0)

    home_token = set_hermes_home_override(str(temp_home))
    try:
        with hermes_time.use_timezone_override():
            nxt = compute_next_run({"kind": "cron", "expr": "15 18 * * *"},
                                   "2026-08-29T09:00:00+00:00")
            assert datetime.fromisoformat(nxt).utcoffset() == timedelta(hours=-4), nxt
            due = get_due_jobs()  # the due-scan shares the scoped clock
    finally:
        reset_hermes_home_override(home_token)

    assert datetime.fromisoformat(nxt).hour == 18


def test_now_follows_profile_tz_override_and_does_not_leak(tmp_path, monkeypatch):
    """The mechanism fix: inside the tick's tz-override context, hermes_time
    resolves the *profile's* config.yaml timezone (via the HERMES_HOME
    override) even though the process resolved its own default first;
    outside, the process default returns; sibling contexts don't leak into
    each other.

    Guaranteed red on main (no override API exists there).
    """
    import hermes_time

    monkeypatch.delenv("HERMES_TIMEZONE", raising=False)
    # Pin the process HOME to an empty home so the process clock is
    # deterministic (whatever the box default is — we only assert the
    # profile-scoped value differs from it below).
    process_home = tmp_path / "process-home"
    process_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(process_home))
    hermes_time.reset_cache()
    process_now = hermes_time.now()

    profile_home = tmp_path / "profile-home"
    profile_home.mkdir()
    (profile_home / "config.yaml").write_text(
        "timezone: America/New_York\n", encoding="utf-8"
    )

    home_token = None
    try:
        from hermes_constants import set_hermes_home_override

        home_token = set_hermes_home_override(str(profile_home))
        with hermes_time.use_timezone_override():
            inside = hermes_time.now()
        assert inside.utcoffset() == timedelta(hours=-4)
        assert inside.tzinfo.key == "America/New_York"

        # Outside the tz override but still inside the home override, the
        # cached process-global is what the pre-fix code used: NOT the profile tz.
        outside = hermes_time.now()
        assert outside.utcoffset() == process_now.utcoffset()

        # Concurrent contexts: two profiles ticked on sibling threads each
        # see their own zone; nothing leaks across contexts.
        profile_b = tmp_path / "profile-b"
        profile_b.mkdir()
        (profile_b / "config.yaml").write_text(
            "timezone: Asia/Kolkata\n", encoding="utf-8"
        )
        results = {}

        def tick(name: str, home):
            from hermes_constants import reset_hermes_home_override
            from hermes_constants import set_hermes_home_override as set_home
            import time as _time

            tok = set_home(str(home))
            try:
                with hermes_time.use_timezone_override():
                    _time.sleep(0.05)
                    results[name] = hermes_time.now().tzinfo.key
            finally:
                reset_hermes_home_override(tok)

        import threading

        threads = [
            threading.Thread(target=tick, args=("a", profile_home)),
            threading.Thread(target=tick, args=("b", profile_b)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert results == {"a": "America/New_York", "b": "Asia/Kolkata"}
    finally:
        if home_token is not None:
            from hermes_constants import reset_hermes_home_override

            reset_hermes_home_override(home_token)
        hermes_time.reset_cache()
