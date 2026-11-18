#!/usr/bin/env python3
"""Stage a Mac release for the GitHub release workflow; signs and publishes nothing.

Runs in the build job, which has no secrets. It writes, into <out>:
  Wizard-<build>.zip        Sparkle update archive (ditto, same layout as make-update-feed.py)
  Wizard-<version>.dmg      first-install disk image (copied from build.sh's output)
  appcast.template.xml      the feed with the archive signature left as a placeholder
  index.html                the downloads.aiwizards.com landing page for this version
  release-stage.json        what the sign and publish jobs check against

The sign job (environment mac-sign) puts the archive's Ed25519 signature into the placeholder and signs the whole feed
with Sparkle's sign_update; it runs no project code, this file included.
"""
import argparse
import hashlib
import html
import json
import pathlib
import plistlib
import shutil
import subprocess
import xml.etree.ElementTree as X

PLACEHOLDER = '@ED_SIGNATURE@'
SPARKLE_NS = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
WIZARD_NS = 'https://humanitylabs.co/wizard-updates/v1'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def appcast_template(version, build, manifest, archive_url, archive_bytes):
    """The complete feed, except the enclosure's edSignature, which is PLACEHOLDER."""
    X.register_namespace('sparkle', SPARKLE_NS)
    X.register_namespace('wizard', WIZARD_NS)
    rss = X.Element('rss', version='2.0')
    channel = X.SubElement(rss, 'channel')
    X.SubElement(channel, 'title').text = 'WizardOS updates'
    item = X.SubElement(channel, 'item')
    X.SubElement(item, 'title').text = 'WizardOS ' + version
    for key, value in [('version', str(build)), ('shortVersionString', version),
                       ('minimumSystemVersion', '14.0.0'), ('hardwareRequirements', 'arm64')]:
        X.SubElement(item, '{%s}%s' % (SPARKLE_NS, key)).text = value
    X.SubElement(item, '{%s}contract' % WIZARD_NS).text = json.dumps(manifest, sort_keys=True, separators=(',', ':'))
    X.SubElement(item, 'enclosure', {'url': archive_url, 'type': 'application/octet-stream',
                                     'length': str(archive_bytes), '{%s}edSignature' % SPARKLE_NS: PLACEHOLDER})
    body = X.tostring(rss, encoding='unicode')
    text = '<?xml version="1.0" encoding="utf-8"?>\n' + body + '\n'
    assert text.count(PLACEHOLDER) == 1
    return text


def landing_page(version, build, dmg_url, dmg_bytes, dmg_sha256):
    size = '%.0f MB' % (dmg_bytes / 1e6) if dmg_bytes < 1e9 else '%.1f GB' % (dmg_bytes / 1e9)
    e = html.escape
    return (
        '<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width"><title>WizardOS downloads</title>\n'
        '<style>body{background:#0b0a12;color:#eee;font:16px system-ui;max-width:640px;margin:10vh auto;padding:0 20px}'
        'a{color:#a78bfa}.btn{display:inline-block;background:#7c3aed;color:#fff;padding:12px 20px;border-radius:10px;'
        'text-decoration:none;font-weight:600}small{color:#aaa}</style>\n'
        '<h1>WizardOS for Mac</h1>\n'
        f'<p><a class=btn href="{e(dmg_url)}">Download WizardOS {e(version)} for Mac</a></p>\n'
        f'<p><small>Apple silicon Mac, macOS 14 or later · {e(size)} · build {build}<br>\n'
        f'SHA-256 {e(dmg_sha256)}<br>\n'
        'WizardOS downloads its system (about 10 GB) during setup and needs about 60 GB free.<br>\n'
        'First open: if macOS says it cannot check the app, open System Settings, Privacy &amp; Security, '
        'and choose Open Anyway.</small></p>\n'
        '<p><a href="https://aiwizards.com">aiwizards.com</a></p>\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--app', type=pathlib.Path, required=True)
    p.add_argument('--dmg', type=pathlib.Path, required=True)
    p.add_argument('--out', type=pathlib.Path, required=True)
    p.add_argument('--base-url', required=True, help='public folder of this channel, e.g. https://downloads.aiwizards.com/mac')
    p.add_argument('--version', required=True)
    p.add_argument('--build', type=int, required=True)
    a = p.parse_args()

    info = plistlib.loads((a.app / 'Contents/Info.plist').read_bytes())
    manifest = json.loads((a.app / 'Contents/Resources/wizard-release.json').read_text())
    assert info['CFBundleVersion'] == str(a.build) == manifest['build'], 'build number mismatch'
    assert info['CFBundleShortVersionString'] == a.version, 'version mismatch'
    assert manifest['arch'] == 'arm64' and manifest['hostProtocol'] == 1
    base = a.base_url.rstrip('/') + '/' + str(a.build) + '/'

    a.out.mkdir(parents=True, exist_ok=True)
    archive = a.out / f'Wizard-{a.build}.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(a.app), str(archive)], check=True)
    dmg = a.out / f'Wizard-{a.version}.dmg'
    shutil.copyfile(a.dmg, dmg)

    stage = {
        'version': a.version, 'build': a.build, 'releaseID': manifest['releaseID'],
        'publicKey': info['SUPublicEDKey'], 'feedURL': info['SUFeedURL'],
        'archive': {'name': archive.name, 'url': base + archive.name, 'bytes': archive.stat().st_size, 'sha256': sha256(archive)},
        'dmg': {'name': dmg.name, 'url': base + dmg.name, 'bytes': dmg.stat().st_size, 'sha256': sha256(dmg)},
    }
    (a.out / 'appcast.template.xml').write_text(
        appcast_template(a.version, a.build, manifest, stage['archive']['url'], stage['archive']['bytes']))
    (a.out / 'index.html').write_text(
        landing_page(a.version, a.build, stage['dmg']['url'], stage['dmg']['bytes'], stage['dmg']['sha256']))
    (a.out / 'release-stage.json').write_text(json.dumps(stage, indent=2) + '\n')
    print(json.dumps(stage, indent=2))


if __name__ == '__main__':
    main()
