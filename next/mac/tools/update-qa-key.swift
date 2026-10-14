import Foundation
import CryptoKit
let path = CommandLine.arguments[1]
if !FileManager.default.fileExists(atPath: path) {
    let key = Curve25519.Signing.PrivateKey()
    FileManager.default.createFile(atPath: path, contents: key.rawRepresentation.base64EncodedData(), attributes: [.posixPermissions: 0o600])
}
let key = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(base64Encoded: Data(contentsOf: URL(fileURLWithPath: path)))!)
print(key.publicKey.rawRepresentation.base64EncodedString())
