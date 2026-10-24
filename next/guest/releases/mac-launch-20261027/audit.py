#!/usr/bin/env python3
"""Fail-closed admission for the single Mac launch guest rebuild.

Default invocation is a read-only audit. --admit-and-build never constructs a
VM until every source/queue gate is resolved and its evidence is present.
No release publication, appcast mutation, signing or stable promotion occurs.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
HERE = Path(__file__).resolve().parent


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_preparation(manifest, queue):
    """Source mapping is not final acceptance; an intent-only RC cannot bootstrap."""
    errors = []
    loaded = {}
    for key, spec in [('mapping', manifest['queue'].get('mapping')), ('candidate', manifest.get('wizardOsCandidate'))]:
        path = (HERE / (spec or {}).get('path', '.missing')).resolve()
        if not spec or not path.is_relative_to(HERE.resolve()) or not path.is_file() or digest(path) != spec.get('sha256'):
            errors.append(key + ' missing or digest mismatch')
        else:
            loaded[key] = json.loads(path.read_text())
    mapping = loaded.get('mapping')
    if mapping:
        rows = mapping.get('entries', [])
        selection = hashlib.sha256(json.dumps(manifest['finalPins'], sort_keys=True).encode()).hexdigest()
        if mapping.get('sourceSelectionSha256') != selection:
            errors.append('queue mapping selects different final pins')
        if mapping.get('queueSha256') != queue['queueSha256'] or len(rows) != queue['entryCount']:
            errors.append('queue mapping snapshot mismatch')
        if [r.get('id') for r in rows] != list(range(1, queue['entryCount'] + 1)):
            errors.append('queue mapping IDs must be complete, ordered and unique')
        if [(r.get('queueLine'), r.get('entry')) for r in rows] != [(r['queueLine'], r['entry']) for r in queue['entries']]:
            errors.append('queue mapping altered original queue entries')
        for row in rows:
            for component in row.get('components', []):
                if component.get('pinnedCommit') != manifest['finalPins'].get(component.get('component')):
                    errors.append('queue mapping component pin mismatch: ' + str(row.get('id')))
        if any(r.get('status') == 'not-fully-carried' for r in rows):
            errors.append('queue has explicitly uncarried or unproven requirements; see queue-mapping.json')
    candidate = loaded.get('candidate')
    if candidate:
        base = candidate.get('baseRelease', {})
        path = (HERE / base.get('snapshot', '.missing')).resolve()
        if not path.is_relative_to(HERE.resolve()) or not path.is_file() or digest(path) != base.get('sha256'):
            errors.append('candidate base stable snapshot digest mismatch')
        for key, app in [('wam', 'wizard-app-manager'), ('service', 'wizard-agent-service'), ('ux', 'wizard-ux')]:
            if candidate.get('components', {}).get(app, {}).get('commit') != manifest['finalPins'][key]:
                errors.append('candidate component pin mismatch: ' + key)
        if candidate.get('default_apps', {}).get('recorder', {}).get('commit') != manifest['finalPins']['recorder']:
            errors.append('candidate Recorder pin mismatch')
        if candidate.get('status') != 'factory-bootstrap-ready':
            errors.append('Wizard OS source RC is not yet an executable factory bootstrap release')
    return errors


def inspect(manifest, root):
    errors = []
    stable_path = HERE / manifest["stable"]["manifest"]
    if digest(stable_path) != manifest["stable"]["sha256"]:
        errors.append("stable release snapshot digest mismatch")
    queue = json.loads((HERE / manifest["queue"]["manifest"]).read_text())
    errors.extend(inspect_preparation(manifest, queue))
    if len(queue["entries"]) != manifest["queue"]["entryCount"]:
        errors.append("queue coverage count mismatch")
    if queue["queueSha256"] != manifest["queue"]["sha256"]:
        errors.append("queue snapshot identity mismatch")
    for name, source in manifest["sourceInputs"].items():
        if not SHA.fullmatch(source.get("commit", "")):
            errors.append("invalid exact source pin: " + name)
    for name, pin in manifest["finalPins"].items():
        if not isinstance(pin, str) or not SHA.fullmatch(pin):
            errors.append("unresolved final pin: " + name)
    if manifest["factory"]["version"] is None:
        errors.append("factory manifest version/admission policy unresolved")
    if manifest["status"] != "admitted":
        errors.append("freeze is not admitted")
    for blocker in manifest["blockers"]:
        if blocker["status"] != "resolved":
            errors.append("open gate: " + blocker["id"])
    pending = [entry for entry in queue["entries"] if entry["status"] != "verified"]
    if pending:
        errors.append(f"queue entries without source/acceptance evidence: {len(pending)}")
    execution = manifest.get("execution") or {}
    if not execution.get("argv") or not execution.get("recipe") or not DIGEST.fullmatch(execution.get("sha256") or ""):
        errors.append("reviewed complete assembly recipe is not pinned")
    if root is not None:
        if execution.get("recipe"):
            recipe = (root / execution["recipe"]).resolve()
            if not recipe.is_relative_to(root.resolve()) or not recipe.is_file() or digest(recipe) != execution.get("sha256"):
                errors.append("assembly recipe missing or digest mismatch")
        # Admission receipts are local, credential-free evidence files whose
        # exact bytes are part of the staged inventory, not web links alone.
        for entry in manifest["blockers"] + queue["entries"]:
            evidence = entry.get("evidence", [])
            if not evidence:
                errors.append("missing staged gate evidence")
                continue
            for receipt in evidence:
                p = (root / receipt["path"]).resolve()
                if not p.is_relative_to(root.resolve()) or not p.is_file():
                    errors.append("missing or escaping evidence path")
                elif not DIGEST.fullmatch(receipt.get("sha256", "")) or digest(p) != receipt["sha256"]:
                    errors.append("evidence digest mismatch")
        if not (root / "staged-files.json").is_file():
            errors.append("staged file inventory missing")
        else:
            inventory = json.loads((root / "staged-files.json").read_text())
            for name, expected in inventory["files"].items():
                p = root / name
                if not p.is_file() or p.is_symlink() or digest(p) != expected:
                    errors.append("staged file mismatch: " + name)
            for name, target in inventory.get("symlinks", {}).items():
                p = root / name
                if not p.is_symlink() or os.readlink(p) != target:
                    errors.append("staged symlink mismatch: " + name)
        # final/ contains reviewed integrated sources, never an arbitrary
        # overwrite of the frozen source-input archives.
        for name, pin in manifest["finalPins"].items():
            stamp = root / "final" / name / ".wizard-source.json"
            if not stamp.is_file() or json.loads(stamp.read_text()).get("commit") != pin:
                errors.append("missing exact integrated source: " + name)
        native = root / "final/native"
        payload = native / "next/guest/build-runtime-payload.py"
        if payload.is_file():
            helper = native / "next/guest/release-pins.py"
            expected = {name: manifest["finalPins"][name] for name in ["ux", "service", "wam"]}
            try:
                # Execute only the exact staged and inventory-verified read-only pin validator.
                result = subprocess.run([sys.executable, str(helper), str(HERE / "pins.json")],
                                        capture_output=True, text=True, check=True, timeout=20)
                consumed = json.loads(result.stdout)["sources"]
                source = payload.read_text()
                if any(consumed.get(k) != v for k, v in expected.items()) or "_release_pins.load(a.pins)" not in source or "assert pins==expected" not in source:
                    errors.append("runtime payload consumer does not use final integrated pins")
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                errors.append("runtime pin validator failed or is missing")
        else:
            errors.append("integrated runtime payload recipe missing")
        provision = native / "next/guest/overlay/opt/wizard/bin/wizard-provision"
        if not provision.is_file() or "WIZARD_RELEASE" not in provision.read_text():
            errors.append("factory provisioner does not consume frozen Wizard OS release")
    return errors


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument("--admit-and-build", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((HERE / "pins.json").read_text())
    errors = inspect(manifest, args.stage_root)
    if args.admit_and_build:
        if sys.platform != "darwin":
            errors.append("heavy rebuild requires the Thales Mac worker")
        if args.stage_root is None or not args.stage_root.resolve().is_relative_to(Path("/Volumes/ThalesMedia")):
            errors.append("heavy source/work must be staged on ThalesMedia")
    print(json.dumps({"status": "blocked" if errors else "admitted", "blockers": errors,
                      "queueEntries": manifest["queue"]["entryCount"],
                      "publishing": False, "buildStarted": not errors and args.admit_and_build}, indent=2))
    if errors:
        return 2
    if not args.admit_and_build:
        return 0
    assert args.stage_root is not None
    root = args.stage_root.resolve()
    # A full reviewed assembly recipe is required, not bare build-image.sh all:
    # that command alone neither overlays the split-source runtime nor fixes
    # the mutable bootstrap. The receipt hashes the recipe before admission.
    execution = manifest["execution"]
    env = dict(os.environ)
    env["SIGN_IDENTITY"] = "-"
    return subprocess.run(execution["argv"], cwd=root, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
