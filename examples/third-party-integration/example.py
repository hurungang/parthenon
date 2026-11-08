"""Runnable example: invoke a Parthenon agent type through a client credential.

Run against a local Parthenon instance:

    export PARTHENON_BASE_URL=http://localhost:8002
    export PARTHENON_CLIENT_KEY=phn_cl_sk_...
    python example.py
"""
from __future__ import annotations

import os
import sys

# Allow running directly from the repo without installing the SDK.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "parthenon-python"))

from parthenon import Client, ParthenonError  # noqa: E402


def main() -> int:
    base_url = os.environ.get("PARTHENON_BASE_URL", "http://localhost:8002")
    credential = os.environ.get("PARTHENON_CLIENT_KEY")
    if not credential:
        print("Set PARTHENON_CLIENT_KEY to a phn_cl_sk_… or phn_cl_pk_… credential.")
        return 1

    client = Client(base_url=base_url, credential=credential)
    try:
        cfg = client.config()
        print("Client config:", cfg)

        result = client.submit(
            {"email_body": "I'd like a refund for my order #1234 — it arrived damaged."}
        )
        print("Submit result:", result)
        print("Session id:", result.get("session_id"))
        return 0
    except ParthenonError as exc:
        print("Parthenon call failed:", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
