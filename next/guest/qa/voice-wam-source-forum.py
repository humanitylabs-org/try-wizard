#!/usr/bin/env python3
"""Parent light-lane admission only. Exactly 31 affected tests, no VM/image/TLS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
import unittest

if not __debug__:raise SystemExit('Refusing optimized test runner')
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-sha256',required=True);p.add_argument('--preflight',action='store_true');a=p.parse_args()
    assert sha(HERE/'stage.json')==a.stage_sha256,'Stage seal drift'
    stage=json.loads((HERE/'stage.json').read_text())
    for rel,want in stage['files'].items():
        f=HERE/rel
        assert f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(HERE) and sha(f)==want and f.stat().st_mode&0o777==stage['fileModes'][rel],rel
    assert platform.system()=='Linux' and platform.machine()=='x86_64'
    import yaml
    assert yaml.__version__==stage['pyyamlVersion'],'Use existing pinned dependency environment; no installs'
    if a.preflight:
        print(json.dumps({'stageSha256':a.stage_sha256,'sourceRevision':stage['sourceRevision'],'noTestsRun':True,'noVMStarted':True,'preflightOnly':True}));return
    assert os.environ.get('WIZARD_WORKER_LANE')=='light','Parent light-worker admission required'
    assert str(HERE).startswith('/srv/work/') and shutil.disk_usage(HERE).free>10<<30
    out=HERE/'source-evidence';out.mkdir(mode=0o700)
    scratch=out/'fixtures';scratch.mkdir(mode=0o700);os.environ['TMPDIR']=str(scratch)
    result={'success':False,'runtimeAccepted':False,'sourceFakesOnly':True,'stageSha256':a.stage_sha256,'sourceRevision':stage['sourceRevision'],'started':time.time(),'failures':[],'errors':[],'skipped':0,'testsRun':0,'caseIDs':[]}
    try:
        directory=HERE/'source/next/guest/tests';sys.path.insert(0,str(directory))
        suite=unittest.TestSuite()
        for name,count in stage['testModules'].items():
            selected=unittest.defaultTestLoader.loadTestsFromName(name)
            assert selected.countTestCases()==count,(name,selected.countTestCases(),count)
            suite.addTests(selected)
        def cases(s):
            for t in s:
                if isinstance(t,unittest.TestSuite):yield from cases(t)
                else:yield t.id()
        ids=list(cases(suite));assert len(ids)==len(set(ids))==stage['focusedTestsExpected']
        result['caseIDs']=ids
        with (out/'tests.log').open('x') as log:
            row=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        result.update(testsRun=row.testsRun,failures=[{'case':t.id(),'traceback':v} for t,v in row.failures],errors=[{'case':t.id(),'traceback':v} for t,v in row.errors],skipped=len(row.skipped),testsLogSha256=sha(out/'tests.log'))
        result['success']=row.wasSuccessful() and not row.skipped and row.testsRun==stage['focusedTestsExpected']
        assert result['success'],'Focused tests failed; see source-evidence/tests.log'
    except BaseException as e:result['errorClass']=type(e).__name__;result['error']=str(e);raise
    finally:
        result['finished']=time.time()
        (out/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        # Test-owned temporary fixtures only. Preserve reports/staged sources.
        shutil.rmtree(scratch)

if __name__=='__main__':main()
