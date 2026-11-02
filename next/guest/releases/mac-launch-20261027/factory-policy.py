#!/usr/bin/env python3
"""One factory selection policy; WAM still resolves and installs every app."""
import copy

# Files is a declared `uses` dependency of the pinned Agent Service (first chat).
# Do not silently discard it until that upstream dependency is made optional.
ONBOARDING = {'shell', 'agent-service', 'agent', 'ai-connection',
              'claude-subscription', 'transcription', 'files'}


def releases(full):
    """Keep the full immutable release for WAM; bootstrap only its onboarding closure."""
    onboarding = copy.deepcopy(full)
    onboarding['default_apps'] = {k: v for k, v in full['default_apps'].items() if k in ONBOARDING}
    assert ONBOARDING == set(onboarding['default_apps']), 'missing onboarding default'
    background = copy.deepcopy(full)
    # This is the default app set, not the recommendation prefetch catalogue.
    # WAM bootstrap handles dependency resolution, installed alternatives and retries.
    for row in background['default_apps'].values():
        if row:
            row['install'] = 'bootstrap'
    return onboarding, background
