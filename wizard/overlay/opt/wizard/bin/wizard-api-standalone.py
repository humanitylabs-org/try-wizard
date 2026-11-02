#!/usr/bin/env python3
"""Dedicated Hermes API listener for the standalone Wizard app."""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter, _STATIC_FEATURE_FLAGS
from gateway.session_context import clear_session_vars, delegation_delivery_mode, set_session_vars
from tools.delegate_tool_dispatch import _resolve_async_wake_sid


def verify_wizard_join_contract() -> None:
    """Refuse to launch Wizard on a Hermes build that can strand delegated work."""
    capability = _STATIC_FEATURE_FLAGS.get("delegation_delivery")
    if not isinstance(capability, dict) or capability.get("supported") is not True:
        raise RuntimeError("Hermes does not advertise delegated-work ownership")
    if "join" not in capability.get("modes", []):
        raise RuntimeError("Hermes does not advertise delegation_delivery=join")
    tokens = set_session_vars(
        platform="api_server", chat_id="wizard-startup-canary", session_id="wizard-startup-canary",
        async_delivery=False, delegation_delivery="join")
    try:
        if delegation_delivery_mode() != "join":
            raise RuntimeError("Hermes did not bind delegation_delivery=join")
        if _resolve_async_wake_sid("wizard-startup-canary") is not None:
            raise RuntimeError("Hermes would detach joined Wizard work")
    finally:
        clear_session_vars(tokens)


async def main() -> int:
    verify_wizard_join_contract()
    if "--check" in sys.argv[1:]:
        print("wizard_join_contract=ok")
        return 0
    key = os.environ.get("WIZARD_HERMES_API_KEY") or os.environ.get("API_SERVER_KEY") or ""
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "host": os.environ.get("WIZARD_API_HOST", "127.0.0.1"),
        "port": int(os.environ.get("WIZARD_API_PORT", "8865")),
        "key": key,
        "model_name": os.environ.get("API_SERVER_MODEL_NAME", ""),
    }))
    if not await adapter.connect():
        return 1

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await adapter.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
