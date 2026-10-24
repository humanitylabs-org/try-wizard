import Foundation
let args = Array(CommandLine.arguments.dropFirst())
let host = args.first == "--host"
DistributedNotificationCenter.default().postNotificationName(Notification.Name(host ? "org.humanitylabs.wizard.mvp.host.command" : "org.humanitylabs.wizard.mvp.qa"), object: (host ? Array(args.dropFirst()) : args).joined(separator: " "), userInfo: nil, deliverImmediately: true)
RunLoop.current.run(until: Date().addingTimeInterval(0.15))
