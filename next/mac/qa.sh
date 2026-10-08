#!/bin/bash
# QA driver for Wizard.app on Thales: post a QA command to the running app.
# usage: qa.sh "<command> [arg]"   e.g. qa.sh choose-this-mac | qa.sh snapshot /tmp/x.png | qa.sh state
cat > /tmp/wizard-qa-post.swift <<'EOF'
import Foundation
DistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.qa"),
    object: CommandLine.arguments[1], userInfo: nil, deliverImmediately: true)
RunLoop.main.run(until: Date().addingTimeInterval(0.3))
EOF
if [[ ! -x /tmp/wizard-qa-post || /tmp/wizard-qa-post.swift -nt /tmp/wizard-qa-post ]]; then
  xcrun swiftc -O /tmp/wizard-qa-post.swift -o /tmp/wizard-qa-post 2>/dev/null
fi
/tmp/wizard-qa-post "$1"
