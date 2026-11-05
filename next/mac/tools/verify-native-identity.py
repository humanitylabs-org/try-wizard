#!/usr/bin/env python3
"""Inspect real built/mounted app identity and every ICNS PNG; no app launch.

Only stdlib is needed on the Mac build host. Source/fixture checks do not prove
native execution, signing, updater rename installation, or Finder's icon cache.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import zlib

MAC = Path(__file__).resolve().parents[1]
ASSETS = MAC/'assets/brand'
DARK = ASSETS/'dark'
SOURCE_SHA256 = '228489a32e0c6e0d7e668e7cbe752fbfd6bfc9c8de23b45552325ab23bc91481'
SOURCE_RGBA_SHA256 = '1951b6b320126cd7294f32c36e8099a9d0a107d0eb478088ed503832b9e10a44'
APP_ID = 'org.humanitylabs.wizard.mvp'
HOST_ID = APP_ID+'.host'
HOST = Path('Contents/Library/LoginItems/Wizard Host.app')
spec = importlib.util.spec_from_file_location('native_icon', MAC/'assets/build-icon.py')
assert spec and spec.loader
icon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icon)
sha = lambda b: hashlib.sha256(b).hexdigest()


def png_rgba(data):
    """Decode the noninterlaced 8-bit RGBA PNGs used by this exact asset set."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    w,h,depth,color,compression,filtering,interlace = struct.unpack('>IIBBBBB',data[16:29])
    assert depth == 8 and color == 6 and compression == filtering == interlace == 0
    at=8; compressed=[]
    while at<len(data):
        n=struct.unpack('>I',data[at:at+4])[0]; kind=data[at+4:at+8]; chunk=data[at+8:at+8+n]
        assert zlib.crc32(kind+chunk)&0xffffffff == struct.unpack('>I',data[at+8+n:at+12+n])[0]
        if kind==b'IDAT': compressed.append(chunk)
        at+=12+n
    raw=zlib.decompress(b''.join(compressed)); stride=w*4
    assert len(raw)==h*(stride+1)
    pixels=bytearray(); previous=bytearray(stride)
    for y in range(h):
        start=y*(stride+1); method=raw[start]; row=bytearray(raw[start+1:start+1+stride])
        assert method in range(5)
        for x in range(stride):
            a=row[x-4] if x>=4 else 0; b=previous[x]; c=previous[x-4] if x>=4 else 0
            p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
            predictor=a if pa<=pb and pa<=pc else b if pb<=pc else c
            row[x]=(row[x]+(0,a,b,(a+b)//2,predictor)[method])&255
        pixels.extend(row); previous=row
    return (w,h),bytes(pixels)


def verify_sources():
    p=json.loads((DARK/'provenance.json').read_text())
    assert p['source_sha256']['wizard-ux-icon-512.png']==SOURCE_SHA256
    for name,expected in p['source_sha256'].items(): assert sha((DARK/'originals'/name).read_bytes())==expected,name
    original=(DARK/'originals/wizard-ux-icon-512.png').read_bytes()
    assert sha(original)==SOURCE_SHA256
    assert (DARK/'wizard-icon-512.png').read_bytes()==original
    assert sha(png_rgba(original)[1])==SOURCE_RGBA_SHA256
    for name,expected in p['generated_sha256'].items():
        data=(DARK/name).read_bytes(); assert sha(data)==expected,name
        (w,h),rgba=png_rgba(data); assert w==h and int(name.split('-')[-1].split('.')[0])==w
        assert sha(rgba)==p['rgba_sha256'][name],name
        # This is the approved Void background, not the old flat purple tile.
        assert rgba[:4]==bytes((11,10,16,255)),(name,rgba[:4])
    return p


def verify_icns(data):
    p=verify_sources()
    assert data[:4]==b'icns' and struct.unpack('>I',data[4:8])[0]==len(data)
    at=8; chunks=[]
    for kind,size in icon.REPRESENTATIONS:
        n=struct.unpack('>I',data[at+4:at+8])[0]
        assert data[at:at+4]==kind and n>=8
        png=data[at+8:at+n]; name=f'wizard-icon-{size}.png'
        assert png==(DARK/name).read_bytes(),(kind,size,'PNG byte drift')
        dims,rgba=png_rgba(png); assert dims==(size,size)
        assert sha(rgba)==p['rgba_sha256'][name]
        chunks.append(dict(kind=kind.decode(),size=size,png_sha256=sha(png),rgba_sha256=sha(rgba),corner=list(rgba[:4])))
        at+=n
    assert at==len(data),'Unexpected or missing ICNS chunks'
    return chunks


def release_digest(app, relative):
    data=(app/relative).read_bytes()
    if '/Contents/MacOS/' not in '/'+relative: return sha(data)
    # Match the existing release contract: native __text, not mutable signature.
    assert struct.unpack_from('<I',data)[0]==0xfeedfacf
    at=32
    for _ in range(struct.unpack_from('<I',data,16)[0]):
        command,size=struct.unpack_from('<II',data,at)
        if command==0x19:
            for i in range(struct.unpack_from('<I',data,at+64)[0]):
                section=at+72+i*80
                if data[section:section+16].split(b'\0')[0]==b'__text':
                    length=struct.unpack_from('<Q',data,section+40)[0]
                    start=struct.unpack_from('<I',data,section+48)[0]
                    assert start+length<=len(data)
                    return sha(data[start:start+length])
        assert size>=8
        at+=size
    raise AssertionError('Missing native __text: '+relative)


def verify_bundle(app, allow_qa=False):
    assert app.name=='WizardOS.app',app
    receipt={'app':str(app),'bundles':[]}
    for bundle,name,bundle_id,executable in ((app,'WizardOS',APP_ID,'Wizard'),(app/HOST,'WizardOS Host',HOST_ID,'Wizard Host')):
        info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
        for key,expected in dict(CFBundleName=name,CFBundleDisplayName=name,CFBundleIdentifier=bundle_id,CFBundleExecutable=executable,CFBundleIconFile='Wizard').items():
            assert info[key]==expected,(bundle,key,info.get(key))
        assert (bundle/'Contents/MacOS'/executable).stat().st_size>0
        resources=bundle/'Contents/Resources'
        for mark in ('wizard-mark-white.png','wizard-mark-purple.png'):
            assert (resources/mark).read_bytes()==(ASSETS/mark).read_bytes(),mark
        assert (resources/'WizardBrandProvenance.json').read_bytes()==(DARK/'provenance.json').read_bytes()
        icns=(resources/'Wizard.icns').read_bytes()
        receipt['bundles'].append(dict(name=name,bundle_id=bundle_id,icon_sha256=sha(icns),chunks=verify_icns(icns)))
    assert receipt['bundles'][0]['icon_sha256']==receipt['bundles'][1]['icon_sha256']
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    assert info['SUPublicEDKey'] and info['SURequireSignedFeed'] and info['SUVerifyUpdateBeforeExtraction']
    assert allow_qa or not info['WizardUpdateQA'],'QA hooks require explicit --allow-qa; never a release proof'
    manifest=json.loads((app/'Contents/Resources/wizard-release.json').read_text())
    assert manifest['build']==info['CFBundleVersion'] and manifest['hostProtocol']==1
    assert 'Contents/MacOS/Wizard' in manifest['files']
    assert str(HOST/'Contents/MacOS/Wizard Host') in manifest['files']
    for relative,expected in manifest['files'].items():
        assert release_digest(app,relative)==expected,relative
    host=plistlib.loads((app/HOST/'Contents/Info.plist').read_bytes())
    assert host['CFBundleVersion']==info['CFBundleVersion']
    assert (app/'Contents/Resources/bring-hermes/wizard-bring-hermes').stat().st_size>0
    assert (app/'Contents/Frameworks/Sparkle.framework/Sparkle').stat().st_size>0
    receipt.update(build=info['CFBundleVersion'],releaseID=manifest['releaseID'],source_sha256=SOURCE_SHA256,scope='static built-bundle inspection only; native launch/update/GUI not exercised')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('bundle',type=Path)
    parser.add_argument('--allow-qa',action='store_true'); args=parser.parse_args()
    print(json.dumps(verify_bundle(args.bundle,args.allow_qa),indent=2,sort_keys=True))
