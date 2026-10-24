#!/usr/bin/env python3
"""Stage, do not publish. Sparkle 2.10 signs BOTH archive and complete feed.
Private signing key is an external path on Thales, never a CLI value or payload.
"""
import argparse, hashlib, json, pathlib, plistlib, subprocess, xml.etree.ElementTree as X
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
p=argparse.ArgumentParser(); p.add_argument('bundle',type=pathlib.Path); p.add_argument('output',type=pathlib.Path); p.add_argument('--base-url',required=True); p.add_argument('--sign-tool',required=True); p.add_argument('--key-file',required=True); a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
d=plistlib.loads((a.bundle/'Contents/Info.plist').read_bytes()); manifest=json.loads((a.bundle/'Contents/Resources/wizard-release.json').read_text())
assert manifest['build']==d['CFBundleVersion'] and manifest['arch']=='arm64' and manifest['hostProtocol']==1
name=f"Wizard-{d['CFBundleVersion']}.zip"; archive=a.output/name
subprocess.run(['/usr/bin/ditto','-c','-k','--sequesterRsrc','--keepParent',str(a.bundle),str(archive)],check=True)
sign=[a.sign_tool,'--ed-key-file',a.key_file]
sig=subprocess.check_output([*sign,'-p',str(archive)],text=True).strip()
ns='http://www.andymatuschak.org/xml-namespaces/sparkle'; wn='https://humanitylabs.co/wizard-updates/v1'
X.register_namespace('sparkle',ns); X.register_namespace('wizard',wn)
rss=X.Element('rss',version='2.0'); channel=X.SubElement(rss,'channel'); X.SubElement(channel,'title').text='Wizard MVP staged updates'
item=X.SubElement(channel,'item'); X.SubElement(item,'title').text='Wizard '+d['CFBundleShortVersionString']
for k,v in [('version',d['CFBundleVersion']),('shortVersionString',d['CFBundleShortVersionString']),('minimumSystemVersion','14.0.0'),('hardwareRequirements','arm64')]: X.SubElement(item,'{'+ns+'}'+k).text=v
X.SubElement(item,'{'+wn+'}contract').text=json.dumps(manifest,sort_keys=True,separators=(',',':'))
X.SubElement(item,'{'+wn+'}sha256').text=digest(archive)
X.SubElement(item,'enclosure',{'url':a.base_url.rstrip('/')+'/'+name,'type':'application/octet-stream','length':str(archive.stat().st_size),'{'+ns+'}edSignature':sig})
feed=a.output/'appcast.xml'; X.ElementTree(rss).write(feed,encoding='utf-8',xml_declaration=True)
subprocess.run([*sign,str(feed)],check=True); subprocess.run([*sign,'--verify',str(feed)],check=True); subprocess.run([*sign,'--verify',str(archive),sig],check=True)
receipt={'build':manifest['build'],'releaseID':manifest['releaseID'],'archive':name,'archiveSHA256':subprocess.check_output(['/usr/bin/shasum','-a','256',str(archive)],text=True).split()[0],'feedSHA256':hashlib.sha256(feed.read_bytes()).hexdigest(),'archiveBytes':archive.stat().st_size,'signaturesVerified':True,'appleSigning':'not asserted by this tool','publication':'staged only'}
(a.output/f"receipt-{manifest['build']}.json").write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt))
