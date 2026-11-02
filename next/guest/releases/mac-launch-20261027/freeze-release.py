#!/usr/bin/env python3
"""Freeze a LOCAL, UNPUBLISHED RC from the fetched stable record and source pins.
This is an assembly input record, deliberately NOT a get.sh-compatible release:
new Service/UX image digests cannot honestly exist before their candidate builds.
Never copy stable image provenance onto a different source commit.
"""
import copy
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def freeze(pins,stable,stable_bytes,origin):
    defaults=copy.deepcopy(stable['default_apps'])
    components=copy.deepcopy(stable['components'])
    for key,app in [('wam','wizard-app-manager'),('ux','wizard-ux'),('service','wizard-agent-service')]:
        components[app]={'repo':'humanitylabs-org/'+app,'commit':pins['finalPins'][key], 'review':'draft candidate; not promoted'}
    for slot,key in [('shell','ux'),('agent-service','service')]:
        defaults[slot]['commit']=pins['finalPins'][key]
        defaults[slot]['note']='RC source selection; replacement candidate image must be built before provisioning'
    defaults['recorder']={'app':pins['recorderImage']['appId'],'repo':pins['sourceInputs']['recorder']['repo'],
                         'index_version':'0.3.5', # runtipi/config.json at frozen Recorder 0f31e272
                         'commit':pins['finalPins']['recorder'],'install':'portable-app',
                         'image':pins['recorderImage']['arm64Image'],'note':'optional hardware access explicit; no capture permission implied'}
    for row in defaults.values():
        if row is not None:
            assert len(row['commit'])==40
    return {'schema':'wizard-mac-unpublished-source-rc-v1', 'version':stable['version']+'-mac.20261027-rc.1',
            'status':'blocked-assembly-and-image-gates','promote':False,'publish':False,
            'baseRelease':{'version':stable['version'],'snapshot':'wizard-os-current-stable.json',
                           'sha256':hashlib.sha256(stable_bytes).hexdigest(),'github':origin},
            'components':components,'default_apps':defaults,'hermes':copy.deepcopy(stable['hermes']),
            'bootstrapImages':copy.deepcopy(stable['images']),
            'candidateImagePolicy':{
                'wizard-app-manager':{'mode':'build-from-pinned-source-with-trust-remediation',
                    'sourceCommit':pins['finalPins']['wam'],'digest':None},
                'wizard-agent-service':{'mode':'build-from-pinned-source','sourceCommit':pins['finalPins']['service'],'digest':None},
                'wizard-ux':{'mode':'build-from-pinned-source','sourceCommit':pins['finalPins']['ux'],'digest':None}},
            'factoryPolicy':{'noMutableStablePointer':True,'noMutableMain':True,
                'mustEmitValidatedRuntimeReleaseBeforeBootstrap':True,
                'getShInput':'generated get.sh release record with built candidate image digests; not this source RC',
                'installer':pins['osInstaller'],'signing':'unsigned; signing remains pluggable'},
            'notSelected':'Private/local apps, optional licensing and device grants are not auto-installed from queue prose.'}


def main():
    p=json.loads((HERE/'pins.json').read_text()); raw=(HERE/'wizard-os-current-stable.json').read_bytes()
    result=freeze(p,json.loads(raw),raw,json.loads((HERE/'stable-origin.json').read_text()))
    target=HERE/'wizard-os-release-candidate.json';target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'record':target.name,'version':result['version'],'defaultApps':len(result['default_apps']),
                      'status':result['status'],'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))


if __name__=='__main__':main()
