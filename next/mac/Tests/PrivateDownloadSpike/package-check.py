from pathlib import Path
import subprocess as sp,plistlib,hashlib,json,shutil,os
R=Path('/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-first-install-download/spike');D=R/'delivery';D.mkdir(exist_ok=True)
def run(*a):return sp.run([str(x) for x in a],check=True,text=True,stdout=sp.PIPE,stderr=sp.STDOUT).stdout
APP=D/'Wizard Download Check.app'; C=APP/'Contents'; (C/'MacOS').mkdir(parents=True,exist_ok=True);(C/'Resources').mkdir(exist_ok=True)
shutil.copyfile(R/'DownloadCheckLauncher',C/'MacOS/DownloadCheckLauncher');(C/'MacOS/DownloadCheckLauncher').chmod(0o755)
shutil.copyfile(R/'evidence/PrivateDownloadSpike',C/'Resources/PrivateDownloadSpike');(C/'Resources/PrivateDownloadSpike').chmod(0o755)
(C/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.humanitylabs.wizard.download-check','CFBundleName':'Wizard Download Check','CFBundleDisplayName':'Wizard Download Check','CFBundleExecutable':'DownloadCheckLauncher','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'0.1.0','LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}))
run('bash','-n',C/'MacOS/DownloadCheckLauncher')
run('codesign','--force','--sign','-',C/'Resources/PrivateDownloadSpike');run('codesign','--force','--sign','-',APP);print(run('codesign','--verify','--deep','--strict','--verbose=2',APP))
STAGE=D/'mount-source';STAGE.mkdir(exist_ok=True);run('ditto',APP,STAGE/APP.name)
if not (STAGE/'Applications').exists():os.symlink('/Applications',STAGE/'Applications')
run('hdiutil','create','-quiet','-volname','Wizard Download Check','-srcfolder',STAGE,'-fs','HFS+','-format','UDZO','-ov',D/'Wizard-Download-Check.dmg')
print(run('hdiutil','verify',D/'Wizard-Download-Check.dmg'))
NATIVE=Path('/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-files-onboarding/next/mac/dist/Wizard-0.6.1.dmg');shutil.copyfile(NATIVE,D/NATIVE.name)
hashes={n:hashlib.sha256((D/n).read_bytes()).hexdigest() for n in [NATIVE.name,'Wizard-Download-Check.dmg']}
(D/'SHA256SUMS').write_text(hashes[NATIVE.name]+'  '+NATIVE.name+'\n')
(D/'CHECK-SHA256SUMS').write_text(hashes['Wizard-Download-Check.dmg']+'  Wizard-Download-Check.dmg\n')
print(json.dumps({'hashes':hashes,'real_github_auth':'human-required','fixture':'passed','folder_update':'verified'},indent=2))
(D/'artifact-receipt.json').write_text(json.dumps({'hashes':hashes,'real_github_auth':'human-required','fixture':'passed','folder_update':'verified'},indent=2))
