#!/usr/bin/env python3
"""Source contract for the WizardOS-update review fixes in Host/OSUpdates.swift (wizard-app-manager#696, review 4).

CI never compiles next/mac/Host, so these pin the shape of each fix:
  a. the low-disk skip tells every device (finish), so no device keeps sends paused;
  b. an Update now request the Host couldn't act on expires (15 min, never a when_idle one) and is dropped;
  c. the Host waits for update-request-clear to succeed before it stops the VM for the disk copy;
  d. a release newer than the target (cut during the stop/copy/boot) is a good update, not a restore.
"""
import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "Host" / "OSUpdates.swift").read_text()


def body(name: str) -> str:
    """The text of `func <name>(` up to the next func at the same indentation."""
    m = re.search(r"\n    (?:private |static )*func " + re.escape(name) + r"\(", SRC)
    assert m, name
    nxt = re.search(r"\n    (?:private |static |@\w+ )*(?:func|var|let) ", SRC[m.end():])
    return SRC[m.start(): m.end() + (nxt.start() if nxt else len(SRC))]


class LowDisk(unittest.TestCase):
    def test_low_disk_skip_finishes(self):
        run = body("run")
        branch = run[run.index("freeNeeded"): run.index("busy = true; begin()")]
        self.assertIn('finish(result: "skipped", reason: reason)', branch)
        self.assertNotIn('"phase": "done"', branch)   # finish() writes the end, and tells the guest
        self.assertLess(branch.index('"target": target'), branch.index("finish("))  # tellGuest needs id + target


class ExpiredRequest(unittest.TestCase):
    def test_expired_request_is_dropped_before_acting(self):
        tick = body("tick")
        self.assertIn("Self.expired(req)", tick)
        self.assertLess(tick.index("Self.expired(req)"), tick.index('let target = req["target"]'))
        drop = tick[tick.index("Self.expired(req)"): tick.index('let target = req["target"]')]
        self.assertIn('"update-request-clear"', drop)
        self.assertNotIn("self.run(", drop)

    def test_ttl_and_when_idle(self):
        self.assertRegex(SRC, r"static let requestTTL: TimeInterval = 15 \* 60")
        exp = body("expired")
        self.assertIn('req["when_idle"] as? Bool != true', exp)
        self.assertIn('req["requested_at"]', exp)
        self.assertIn("ISO8601DateFormatter()", exp)


class ClearBeforeStop(unittest.TestCase):
    def test_stop_waits_for_the_clear(self):
        run = body("run")
        self.assertNotIn("vm.stop(", run)                                  # the copy (and any stop) is in backUp
        self.assertNotIn("liveBackup(", run)
        clear = run.index('self.vm.control("update-request-clear") { [weak self] data in')
        self.assertIn("self.backUp(kind: kind, st)", run[clear:])
        self.assertIn('Self.object(data), o["error"] == nil', run[clear:])
        self.assertNotIn('vm.control("update-request-clear") { _ in }', run[run.index("busy = true; begin()"):])
        self.assertIn("liveBackup(kind: kind)", body("backUp"))
        self.assertIn("vm.stop(", body("stopAndCopy"))


class LiveBackup(unittest.TestCase):
    """The copy without a shutdown: freeze -> pause -> flush + clone -> resume -> thaw; anything else falls back."""
    def test_order(self):
        b = body("liveBackup")
        order = ['vm.control("freeze', "self.vm.pause", "F_FULLFSYNC", "clonefile(", "let thawAndGo", "self.vm.resume"]
        at = [b.index(x) for x in order]
        self.assertEqual(at, sorted(at), order)
        go = b[b.index("let thawAndGo"): b.index("guard paused else")]
        self.assertIn('vm.control("thaw"', go)
        self.assertIn("self.install(kind: kind)", go)               # the install starts only after the thaw
        self.assertIn("if ok { thawAndGo(); return }", b[b.index("self.vm.resume"):])   # thaw after resume

    def test_not_frozen_thaws_then_falls_back(self):
        b = body("liveBackup")
        branch = b[b.index('["frozen"] as? Bool == true else {'): b.index("let frozenAt")]
        self.assertIn('vm.control("thaw"', branch)
        self.assertIn("fallBack(", branch)
        self.assertIn("stopAndCopy(kind: kind)", b)                    # the fallback is the stop-based copy

    def test_no_resume_restarts_on_the_unchanged_disk(self):
        b = body("liveBackup")
        branch = b[b.index("if ok { thawAndGo(); return }"):]
        self.assertLess(branch.index("removeItem(at: Self.copyURL)"), branch.index("vm.stop(forceOnTimeout: true"))
        self.assertIn('finish(result: "failed"', branch)

    def test_guest_freeze_arms_its_watchdog_first(self):
        ctl = (Path(__file__).resolve().parents[2] / "guest" / "overlay" / "opt" / "wizard" / "bin" / "wizard-ctl").read_text()
        freeze = ctl[ctl.index("\n  freeze)"): ctl.index("\n  thaw)")]
        self.assertLess(freeze.index("systemd-run"), freeze.index("fsfreeze -f /"))
        self.assertIn('"$arg1" -le 120', freeze)
        thaw = ctl[ctl.index("\n  thaw)"):]
        self.assertIn("fsfreeze -u /", thaw)
        self.assertIn("systemctl stop wizard-thaw-watchdog.timer", thaw)
        marker = (Path(__file__).resolve().parents[2] / "guest" / "overlay" / "etc" / "wizard" / "updates-by-host").read_text()
        self.assertIn("\nlive-backup", marker)   # wam/updates.py host_backup_stops_box


class NewerIsSuccess(unittest.TestCase):
    def test_verify_accepts_newer(self):
        v = body("verify")
        self.assertIn('Self.newer(installed ?? "", than: target ?? "")', v)
        self.assertIn("!landed", v)
        self.assertNotIn("installed != target {", v.replace("if landed && installed != target {", ""))

    def test_newer_compares_numbers(self):
        n = body("newer")
        self.assertIn('split(separator: "-", maxSplits: 1)', n)   # 0.3.241-mac.1 is 0.3.241
        self.assertIn("n.count == 3", n)
        self.assertIn("return x[i] > y[i]", n)


if __name__ == "__main__":
    unittest.main(verbosity=2)
