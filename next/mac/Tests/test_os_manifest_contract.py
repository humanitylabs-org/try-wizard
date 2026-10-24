#!/usr/bin/env python3
"""Compile the actual production manifest validator in a bounded Mac fixture."""
import argparse,pathlib,subprocess
import unittest
if __name__ != '__main__':
 raise unittest.SkipTest('Mac Swift fixture: invoke directly with a work directory on Thales')
p=argparse.ArgumentParser();p.add_argument('work',type=pathlib.Path);p.add_argument('--emit-only',action='store_true');p.add_argument('--source',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[1]/'App/main.swift');a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True)
source=a.source.read_text()
def function(signature):
 start=source.index(signature);left=source.index('{',start);depth=1;i=left+1
 while depth:
  depth+=(source[i]=='{')-(source[i]=='}');i+=1
 return source[start:i]
contract=(a.source.parent.parent/'Shared/UpdateContract.swift').read_text()
source_saved=source; source=contract
abi=function('enum WizardGuestABI')
source=source_saved
feed_types='\n'.join(function(s) for s in ('struct Part:', 'struct Background:', 'struct Feed:', 'struct ImageIndex:'))
selector=function('static func selectImage(')
code='import Foundation\nimport CoreFoundation\nimport CryptoKit\n'+abi+'\nenum OSInstaller {\nstatic func error(_ s:String)->NSError { NSError(domain:"test",code:1,userInfo:[NSLocalizedDescriptionKey:s]) }\n'+function('static func sha256(of')+'\n'+function('static func verifyManifest(in')+'\n'+feed_types+'\n'+selector+'\n}\n'+r'''
let root=URL(fileURLWithPath:CommandLine.arguments[1])
try FileManager.default.createDirectory(at:root.appendingPathComponent("boot"),withIntermediateDirectories:true)
var hashes:[String:String]=[:]
for name in ["disk.img","boot/vmlinux","boot/initrd"] {
 let file=root.appendingPathComponent(name)
 try Data(("QA only "+name).utf8).write(to:file)
 hashes[name]=try OSInstaller.sha256(of:file)
}
func manifest(_ version:String,_ files:[String:String]) throws {
 try JSONSerialization.data(withJSONObject:["version":version,"files":files]).write(to:root.appendingPathComponent("manifest.json"))
}
for version in ["0.3.0","0.4.0","0.4.1"] {
 try manifest(version,hashes);try OSInstaller.verifyManifest(in:root)
 print("MANIFEST_"+version+"_PASS")
}
try manifest("0.4.9",hashes)
do { try OSInstaller.verifyManifest(in:root);fatalError("unknown future version accepted") } catch {}
for abi in [0,1] {
 try JSONSerialization.data(withJSONObject:["version":"future-display-only","guestABI":abi,"files":hashes]).write(to:root.appendingPathComponent("manifest.json"))
 try OSInstaller.verifyManifest(in:root)
}
for abi in [2,999,-1] {
 try JSONSerialization.data(withJSONObject:["version":"0.4.1","guestABI":abi,"files":hashes]).write(to:root.appendingPathComponent("manifest.json"))
 do { try OSInstaller.verifyManifest(in:root);fatalError("unknown ABI accepted") } catch {}
}
for raw in [true as Any, "1" as Any, 1.5 as Any] {
 try JSONSerialization.data(withJSONObject:["version":"0.4.1","guestABI":raw,"files":hashes]).write(to:root.appendingPathComponent("manifest.json"))
 do { try OSInstaller.verifyManifest(in:root);fatalError("malformed ABI accepted") } catch {}
}
func indexImage(_ build: String, _ abi: Int) -> [String:Any] {
 ["version":"display-only","imageBuild":build,"guestABI":abi,"bytes":10,"installBytes":100,
  "sha256":String(repeating:"a",count:64),"parts":[["url":"https://downloads.aiwizards.com/os/"+build+"/image.part00","bytes":10,"sha256":String(repeating:"b",count:64)]]]
}
let indexData=try JSONSerialization.data(withJSONObject:["images":[indexImage("0.4.9",1),indexImage("0.4.10",1),indexImage("99",2)]])
let index=try JSONDecoder().decode(OSInstaller.ImageIndex.self,from:indexData)
let selected=try OSInstaller.selectImage(index)
precondition(selected.imageBuild == "0.4.10")
let rejected=try JSONDecoder().decode(OSInstaller.ImageIndex.self,from:JSONSerialization.data(withJSONObject:["images":[indexImage("99",2)]]))
do { _ = try OSInstaller.selectImage(rejected);fatalError("unsupported index ABI accepted") } catch {}
precondition(!WizardGuestABI.requiresFreshApply(baked:"same",bundled:"same"))
precondition(WizardGuestABI.requiresFreshApply(baked:nil,bundled:nil))
precondition(WizardGuestABI.requiresFreshApply(baked:"old",bundled:"new"))
do { try WizardGuestABI.requireSystemOwner(["systemOwner":"guest-feed"],diskIdentity:"fixture",incomingBuild:"309");fatalError("foreign owner accepted") } catch {}
var bad=hashes;bad["disk.img"]=String(repeating:"0",count:64)
try manifest("0.4.0",bad)
do { try OSInstaller.verifyManifest(in:root);fatalError("bad digest accepted") } catch {}
print("UNKNOWN_VERSION_AND_CORRUPTION_REJECTED")
'''
shared=(a.source.parent.parent/'Shared/Shared.swift').read_text()
source,installer=shared,code
legacy=function('static var legacyBootstrapNeeded: Bool')
code=installer+r'''
enum WizardUpdate {
 static func error(_ text:String)->NSError { NSError(domain:"test",code:1,userInfo:[NSLocalizedDescriptionKey:text]) }
 static var dir:URL { root }; static var journal:URL { root.appendingPathComponent("journal.json") }
 static func json(_ url:URL)->[String:Any] {
  guard let data=try? Data(contentsOf:url),let obj=try? JSONSerialization.jsonObject(with:data) as? [String:Any] else { return [:] };return obj
 }
}
enum WizardDiskIdentity {
 static func completed(_ receipt:[String:Any],modern:[String:Any],journal:[String:Any],disk:URL,home:URL)->Bool { false }
}
enum WizardShared {
 static var osInstalled:Bool { true };static var osDir:URL { root };static var supportDir:URL { root }
'''+legacy+'\n}\n'+r'''
for version in ["0.4.0","0.4.1"] {
 try manifest(version,hashes)
 precondition(!WizardShared.legacyBootstrapNeeded,"precomposed factory misclassified as legacy")
 print("NONLEGACY_"+version+"_PASS")
}
try manifest("0.4.9",hashes)
precondition(WizardShared.legacyBootstrapNeeded,"unknown version bypassed legacy admission")
print("UNKNOWN_VERSION_NOT_PRECOMPOSED_PASS")
'''
swift=a.work/'main.swift';swift.write_text(code)
if a.emit_only: raise SystemExit(0)
subprocess.run(['xcrun','swiftc','-O',str(swift),'-o',str(a.work/'test')],check=True)
subprocess.run([str(a.work/'test'),str(a.work/'fixture')],check=True)
