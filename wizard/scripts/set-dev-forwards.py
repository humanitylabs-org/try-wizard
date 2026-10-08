#!/usr/bin/env python3
"""Set Wizard.app dev port forwards (QA only): ssh + onboarding + UX + Hermes (via dev relay)."""
import json
import subprocess

BID = "com.aiwizards.desktop"
mappings = [
    {"hostPort": 2222, "guestPort": 22, "protocol": "tcp"},
    {"hostPort": 18930, "guestPort": 8930, "protocol": "tcp"},
    {"hostPort": 18923, "guestPort": 18923, "protocol": "tcp"},
    {"hostPort": 18865, "guestPort": 18865, "protocol": "tcp"},
]
payload = json.dumps({"schemaVersion": 1, "mappings": mappings}, separators=(",", ":")).encode()
subprocess.run(["defaults", "write", BID, "portForwardingPreferences", "-data", payload.hex()], check=True)
print("dev forwards set")
