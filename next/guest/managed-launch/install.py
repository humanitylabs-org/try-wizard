#!/usr/bin/env python3
"""Install an external executable admission boundary. No stock .py changes.
Run once as root while assembling a derived code-only runtime image, not live.
"""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path('/opt/wizard-managed')
BASES=['/usr/bin','/usr/local/bin','/opt/uv-python','/opt/hermes/.venv/bin']


def interpreter_paths(bases=BASES, required=Path('/opt/hermes/.venv/bin/python')):
    # Resolve aliases so each executable is guarded once. Stock may use system
    # Python or a versioned, architecture-specific uv tree.
    paths={p.resolve() for base in bases for p in Path(base).rglob('python*')
           if p.is_file() and os.access(p,os.X_OK) and p.read_bytes()[:4]==b'\x7fELF'}
    assert paths and required.resolve() in paths
    return sorted(paths)


def install(root=ROOT, paths=None):
    assert os.getuid()==0
    if paths is None:paths=interpreter_paths()
    receipts=[]
    for i,p in enumerate(paths):
        private=root/'private'/str(i)/'bin'/p.name;private.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,private)
        lib=p.parent.parent/'lib'
        if lib.exists():(private.parent.parent/'lib').symlink_to(lib)
        os.chmod(root/'private',0o700)
        output=root/f'guard-{i}'
        subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-DREAL_PATH='+json.dumps(str(private)),str(root/'launch-guard.c'),'-o',str(output)],check=True)
        receipts.append({'path':str(p),'stock_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'private':str(private)})
        # Replace inode rather than overwrite the running build interpreter.
        os.chmod(output,0o4755);os.replace(output,p)
        # Export only discovered guard executables as a root-relative tree.
        # Aliases/venv and libraries stay unchanged in the identical final base.
        staged=root/'interpreter-overlay'/p.relative_to('/')
        staged.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,staged)
    (root/'interpreters.json').write_text(json.dumps(receipts,indent=2)+'\n')
    print(json.dumps({'guarded_interpreters':len(receipts),'paths':[x['path'] for x in receipts]}))


if __name__=='__main__':install()
