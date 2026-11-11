"""Regression: CH internal allowlist must include the conversation activity routes.

The persistent-agent-activity-state change added the `PUT`/`GET` activity
endpoints but did not register them in the Communication Hub internal allowlist,
so every CH activity upsert/hydrate was rejected with 403
`internal.allowlist.denied` / `endpoint_not_allowlisted` (log-proven: repeated
"Activity upsert failed ... returned 403" warnings in communication-hub.log).
"""
from app.api.deps import _CH_ALLOWLIST


def test_ch_allowlist_includes_activity_put():
    assert (
        "PUT",
        "/api/v1/internal/data/conversations/{conv_session_id}/activity",
    ) in _CH_ALLOWLIST


def test_ch_allowlist_includes_activity_get():
    assert (
        "GET",
        "/api/v1/internal/data/conversations/{conv_session_id}/activity",
    ) in _CH_ALLOWLIST
