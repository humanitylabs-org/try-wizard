#!/usr/bin/env python3
"""Image-build/empty-guest only: patch system, every certifi/vendor copy and CPython 3.13.
No credentials, application-source edits, lazy runtime downloads or version relabelling.
"""
import argparse, hashlib, json, os, re, shutil, ssl, subprocess, zipfile
from pathlib import Path

# Primary advisory roots.json, including direct issuers not in Mozilla's bundle.
BLOCKED={
 '7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d',
 'f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5',
 'd7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4',
 '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b'}
PEM=re.compile(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',re.S)
ROOTS=['/etc/ssl','/usr/share/ca-certificates','/usr/local/share/ca-certificates','/opt','/app','/usr/local/lib','/usr/lib','/home/wizard','/root']

def clean(data):
    removed=[]
    def replace(m):
        fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(m[0].decode())).hexdigest()
        if fingerprint in BLOCKED:removed.append(fingerprint);return b''
        return m[0]
    return PEM.sub(replace,data),removed

def candidates(roots):
    seen=set()
    for root in roots:
        for parent,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','__pycache__'}]
            for name in files:
                p=Path(parent)/name
                if p.suffix in {'.pem','.crt'} and p.is_file():
                    real=p.resolve()
                    if real not in seen:seen.add(real);yield real

def patch_certifi(wheel,roots):
    with zipfile.ZipFile(wheel) as z:
        members={n.removeprefix('certifi/'):z.read(n) for n in z.namelist() if n.startswith('certifi/') and not n.endswith('/')}
        metadata={n:z.read(n) for n in z.namelist() if n.startswith('certifi-') and '.dist-info/' in n and not n.endswith('/')}
    assert '__init__.py' in members and b'2026.10.19' in members['__init__.py']
    patched=[]
    for root in roots:
        for parent,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','__pycache__'}]
            p=Path(parent)
            if p.name=='certifi' and 'cacert.pem' in files:
                assert not p.is_symlink()
                for name,data in members.items():
                    target=p/name;assert not target.is_symlink();target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644)
                if metadata and (p.parent.name in {'site-packages','dist-packages'} or any(p.parent.glob('certifi-*.dist-info'))):
                    for old in p.parent.glob('certifi-*.dist-info'):
                        if old.name!='certifi-2026.10.19.dist-info':shutil.rmtree(old)
                    for name,data in metadata.items():
                        target=p.parent/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644)
                # Cached old version imports must not survive an overlay.
                shutil.rmtree(p/'__pycache__',ignore_errors=True)
                patched.append(str(p))
    return patched

def patch_pip(wheel, roots):
    with zipfile.ZipFile(wheel) as z:
        members={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    assert b'26.2.2' in members['pip/__init__.py']
    copies=[];ensurepip=[]
    for root in roots:
        for parent,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','__pycache__'}]
            p=Path(parent)
            if p.name=='pip' and '__init__.py' in files:
                for name,data in members.items():
                    target=p.parent/name;assert not target.is_symlink();target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644)
                for meta in p.parent.glob('pip-*.dist-info'):
                    if meta.name!='pip-26.2.2.dist-info':shutil.rmtree(meta)
                shutil.rmtree(p/'__pycache__',ignore_errors=True);copies.append(str(p))
            if p.name=='ensurepip' and '__init__.py' in files:
                init=p/'__init__.py';text=init.read_text()
                text,count=re.subn(r'_PIP_VERSION\s*=\s*[\'"][^\'"]+[\'"]','_PIP_VERSION = "26.2.2"',text)
                assert count==1,'unknown ensurepip contract: '+str(init)
                bundle=p/'_bundled';bundle.mkdir(exist_ok=True)
                for old in bundle.glob('pip-*.whl'):old.unlink()
                shutil.copyfile(wheel,bundle/'pip-26.2.2-py3-none-any.whl');init.write_text(text)
                shutil.rmtree(p/'__pycache__',ignore_errors=True);ensurepip.append(str(p))
    return {'pipCopies':copies,'ensurepipCopies':ensurepip,'pipVersion':'26.2.2'}

def patch_uv():
    fixed={name:Path('/usr/local/bin')/name for name in ['uv','uvx']}
    if not all(p.is_file() for p in fixed.values()):return []
    data={name:p.read_bytes() for name,p in fixed.items()};patched=[];seen=set()
    for root in ['/usr/local','/usr/bin','/opt','/root','/home/wizard']:
        for parent,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'.git','__pycache__'}]
            for name in {'uv','uvx'}.intersection(files):
                target=(Path(parent)/name).resolve()
                if target in seen or not target.is_file():continue
                seen.add(target)
                with target.open('rb') as handle:magic=handle.read(4)
                if magic!=b'\x7fELF':continue # Preserve stock dispatch scripts; replace their executable target, not source code.
                target.write_bytes(data[name]);target.chmod(0o755);patched.append(str(target))
    return patched

def main():
    p=argparse.ArgumentParser();p.add_argument('--wheel',type=Path,required=True);p.add_argument('--pip-wheel',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert os.geteuid()==0
    config=Path('/etc/ca-certificates.conf')
    if config.exists():
        names={'mozilla/emSign_ECC_Root_CA_-_G3.crt','mozilla/Comodo_AAA_Services_root.crt'}
        config.write_text('\n'.join('!'+line if line in names else line for line in config.read_text().splitlines())+'\n')
        if shutil.which('update-ca-certificates'):subprocess.run(['update-ca-certificates','--fresh'],check=True)
    # Patch all standalone cert files too: hashed CAPATH can otherwise re-admit a removed root.
    removed=[]
    for f in list(candidates(ROOTS)):
        data=f.read_bytes();new,bad=clean(data)
        if bad:
            if PEM.search(new):f.write_bytes(new)
            else:f.unlink()
            removed.append({'path':str(f),'fingerprints':bad})
    # CPython's expedited releases changed bundled pip, not the Linux SSL implementation.
    # Apply that exact hash-locked upstream pip fix to installed and ensurepip-wheel copies without
    # changing interpreter ABI/paths (the managed-launch guard must still cover the exact stock paths).
    pip=patch_pip(a.pip_wheel,ROOTS)
    copies=patch_certifi(a.wheel,ROOTS)
    uv=patch_uv()
    for f in candidates(ROOTS):assert not clean(f.read_bytes())[1],str(f)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({'certifiVersion':'2026.10.19','certifiCopies':copies,'removedRoots':removed,'pipRemediation':pip,'uvBinaryCopies':uv},indent=2)+'\n')

if __name__=='__main__':main()
