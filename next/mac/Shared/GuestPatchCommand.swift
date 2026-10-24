import Foundation

/// Fixed command for the one supported patch. No caller-supplied shell input.
/// Host runs this directly over its owned VM's private vsock, not a Mac TCP shell.
enum WizardGuestPatchCommand {
    static var script: String {
        guard let abi = try? WizardGuestABI.image(WizardUpdate.json(WizardShared.osDir.appendingPathComponent("manifest.json"))) else { return "exit 1" }
        let command = baseScript.replacingOccurrences(of: "--apply >", with: "--guest-abi \(abi) --apply >")
        return WizardShared.coldBootstrapToken == nil ? command : command.replacingOccurrences(of: "--apply >", with: "--apply --cold-bootstrap >")
    }
    static let baseScript = """
    set -e
    mkdir -p /run/wizard-update /var/lib/wizard/patches/mac-stack-v1
    mountpoint -q /run/wizard-update || mount -t virtiofs -o ro wizard-update /run/wizard-update
    python3 /run/wizard-update/source/next/guest/upgrade-mvp-stack.py /run/wizard-update --apply >/var/lib/wizard/patches/mac-stack-v1/updater.log 2>&1
    python3 - <<'PY'
    import json
    d=json.load(open('/var/lib/wizard/patches/mac-stack-v1/applied.json'))
    assert d['patch']=='mac-stack-v1' and d['permanent_identity_credentials_preserved'] is True and d['service_image'].startswith('sha256:')
    assert d['systemOwner']=='host-payload' and d['apps_untouched'] is True
    assert d['auth']['stable_identity_credentials_preserved'] is True and not d['auth']['unexpected_field_changes']
    assert d['env']['stable_credentials_preserved'] is True and d['env']['other_bytes_unchanged'] is True
    for p,v in d['protected_after_sha256'].items():
        if p.endswith('/auth.json'): continue
        if p.endswith('/.env') and d['env']['managed_terminal_key_path_migrated'] is True: continue
        assert d['protected_before_sha256'][p] == v
    print('WIZARD_PATCH_OK '+json.dumps(d,sort_keys=True))
    PY
    exit
    """
    static let appInventory = """
    python3 - <<'PY'
    import json,subprocess
    ids=subprocess.check_output(['docker','ps','-aq'],text=True).split()
    rows=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []
    system={'hermes-agent-engine','hermes-agent','wizard-shell','transcriber-engine','runtipi','runtipi-db','runtipi-queue','runtipi-reverse-proxy'}
    apps={r['Id']:{'running':r['State']['Running'],'image':r['Image'],'name':r['Name']} for r in rows if (r['Config'].get('Labels') or {}).get('com.docker.compose.service','') not in system}
    print('WIZARD_PATCH_OK '+json.dumps({'apps':apps}))
    PY
    exit
    """
}
