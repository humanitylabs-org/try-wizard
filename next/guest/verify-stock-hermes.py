#!/usr/bin/env python3
"""Compare stock upstream Python source against the actually running Hermes engine."""
import hashlib,json,subprocess,tarfile
from pathlib import Path
R=Path('/mnt/stack'); upstream=json.loads((R/'hermes-upstream.json').read_text())
expected={}
with tarfile.open(R/'hermes-upstream.tar.gz') as t:
 for m in t.getmembers():
  if m.isfile() and m.name.endswith('.py'):
   rel=m.name.split('/',1)[1];expected[rel]=hashlib.sha256(t.extractfile(m).read()).hexdigest()
probe='import sys,json,hashlib;from pathlib import Path;r=Path("/opt/hermes");expected=json.load(sys.stdin); print(json.dumps({f:hashlib.sha256((r/f).read_bytes()).hexdigest() if (r/f).is_file() else None for f in expected}))'
actual=json.loads(subprocess.check_output(['docker','exec','-i','hermes-agent_wizardapps-hermes-agent-engine-1','python3','-c',probe],input=json.dumps(expected).encode()))
missing=[f for f,v in actual.items() if v is None];changed=[f for f,v in actual.items() if v is not None and v!=expected[f]]
runtime=[f for f in expected if not f.startswith(('tests/','scripts/','benchmarks/','examples/','apps/','evals/','website/'))]
r={'upstream':upstream,'tracked_python_files':len(expected),'matching_files':sum(actual[f]==v for f,v in expected.items()),'missing':missing,'changed':changed,'runtime_python_files':len(runtime),'runtime_missing':[f for f in runtime if actual[f] is None],'runtime_changed':[f for f in runtime if actual[f] is not None and actual[f]!=expected[f]]}
r['verified']=not r['runtime_missing'] and not r['runtime_changed'];(R/'hermes-source-verification.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2));assert r['verified']
