import Foundation

/// Fixed command for the one supported patch. No caller-supplied shell input.
/// Host runs this directly over its owned VM's private vsock, not a Mac TCP shell.
enum WizardGuestPatchCommand {
    static var script: String {
        let command = baseScript
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
}
