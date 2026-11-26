#!/usr/bin/env python3
"""Which Mac tester build the release train makes public now (wizard-os#720, run by .github/workflows/promote.yml).

The same rule as WizardOS For everyone (wizard-os tools/release_train.py promote-soaked) and the phone train
(wizard-ux tools/phone_release.py promote): the newest tester build (a GitHub prerelease "WizardOS <version> for Mac
(build <build>)") published SOAK_HOURS or more ago whose build is above the live public appcast's. Younger tester
builds wait their turn; older ones are skipped. No person approves it (Miguel, 21 Nov 2026); an open issue labelled
release-blocker in the org holds it (the workflow checks that).

    release-train-pick.py <releases.json> <live build>    # prints "version build" or nothing, and why on stderr
"""
import json
import re
import sys
from datetime import datetime, timezone

SOAK_HOURS = 72
TITLE = re.compile(r'WizardOS (\d+\.\d+\.\d+) for Mac \(build ([1-9]\d*)\)')


def hours(item, now):
    when = item.get('published_at')
    if not when:
        return None
    return (now - datetime.fromisoformat(when.replace('Z', '+00:00'))).total_seconds() / 3600


def pick(releases, live, now, need=SOAK_HOURS):
    """((version, build) or None, a one-line reason)."""
    tester = []
    for r in releases:
        m = TITLE.fullmatch(r.get('name') or '')
        if not (m and r.get('prerelease') and not r.get('draft') and r.get('tag_name') == 'v' + m.group(1)):
            continue
        build = int(m.group(2))
        if build > live:
            tester.append((build, m.group(1), r))
    if not tester:
        return None, f'nothing to promote: no tester build above public build {live}'
    tester.sort(reverse=True)
    due = [t for t in tester if (hours(t[2], now) or 0) >= need]
    if not due:
        build, version, r = tester[-1]
        return None, f'WAITING: build {build} ({version}) is {hours(r, now) or 0:.1f}h old; tester builds are promoted at {need}h'
    build, version, r = due[0]
    return (version, build), f'build {build} ({version}) soaked {hours(r, now):.1f}h (>= {need}h)'


def main(argv):
    pages = json.loads(open(argv[1]).read())
    releases = [r for page in pages for r in page] if pages and isinstance(pages[0], list) else pages
    found, why = pick(releases, int(argv[2]), datetime.now(timezone.utc))
    print(why, file=sys.stderr)
    if found:
        print(*found)


if __name__ == '__main__':
    main(sys.argv)
