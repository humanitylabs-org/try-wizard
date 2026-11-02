#!/bin/bash
# QA driver for Wizard.app on Thales: post a QA command to the running app.
# usage: qa.sh "<command> [arg]"   e.g. qa.sh choose-this-mac | qa.sh snapshot /tmp/x.png | qa.sh state
cat > /tmp/wizard-mvp-qa-post.swift <<'EOF'
import Foundation
DistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.qa"),
    object: CommandLine.arguments[1], userInfo: nil, deliverImmediately: true)
RunLoop.main.run(until: Date().addingTimeInterval(0.3))
EOF
if [[ ! -x /tmp/wizard-mvp-qa-post || /tmp/wizard-mvp-qa-post.swift -nt /tmp/wizard-mvp-qa-post ]]; then
  xcrun swiftc -O /tmp/wizard-mvp-qa-post.swift -o /tmp/wizard-mvp-qa-post 2>/dev/null
fi
/tmp/wizard-mvp-qa-post "$1"
