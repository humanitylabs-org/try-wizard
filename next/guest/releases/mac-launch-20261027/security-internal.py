#!/usr/bin/env python3
"""Network-free equivalence proof for intentionally isolated infrastructure only.

The immutable image must already have passed the complete online positive/negative
TLS probe. Compare the running container's actual effective trust inputs, runtime
binaries and linked libraries against that exact image, and independently reject
all advisory roots offline. DNS failure is never rejection or an exemption.
No network attachment, proxy, trust-store write or application restart is needed.
"""
import hashlib, json, os, re, shutil, ssl, subprocess, sys, tempfile
from pathlib import Path

BLOCKED = {
    '7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d',
    'f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5',
    'd7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4',
    '86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b',
}
TRUST_ENV = ['SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE',
             'NODE_EXTRA_CA_CERTS', 'OPENSSL_CONF', 'OPENSSL_MODULES', 'LD_PRELOAD',
             'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP']

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def snapshot(evidence):
    # This deliberately narrow proof does not claim equivalence for vendored Node,
    # browser or native CLI stores. Those must keep their full runtime TLS probes.
    for name in ['node', 'bun', 'claude', 'headless-shell', 'headless_shell', 'chromium', 'chromium-browser', 'google-chrome']:
        assert not shutil.which(name), 'offline infrastructure proof refuses runtime: ' + name
    certs = json.loads(evidence)['roots']['data']
    assert len(certs) == len(BLOCKED)
    assert {hashlib.sha256(ssl.PEM_cert_to_DER_cert(c['pem'])).hexdigest() for c in certs} == BLOCKED
    paths = ssl.get_default_verify_paths()
    contexts = [('system', ssl.create_default_context())]
    roots = ['/etc/ssl', '/usr/share/ca-certificates', '/usr/local/share/ca-certificates', '/opt/openssl/ssl']
    trust_files = {}
    def record(p):
        if p.is_symlink():
            trust_files[str(p)] = {'link': os.readlink(p), 'resolved': str(p.resolve())}
        if p.is_file():
            trust_files[str(p.resolve())] = {'sha256': sha(p)}
    for f in [paths.cafile, paths.capath, paths.openssl_cafile, paths.openssl_capath, '/etc/ca-certificates.conf']:
        if f and f not in roots: roots.append(f)
    for name in TRUST_ENV:
        if os.environ.get(name) and name in {'SSL_CERT_FILE', 'SSL_CERT_DIR', 'CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE', 'OPENSSL_CONF'}:
            roots.append(os.environ[name])
    for root in roots:
        p = Path(root)
        record(p)
        if p.is_dir():
            for f in p.rglob('*'): record(f)
    for root in ['/opt', '/app', '/usr/local/lib', '/usr/lib', '/home/wizard', '/root']:
        for parent, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__'}]
            if Path(parent).name == 'certifi' and 'cacert.pem' in names:
                f = Path(parent) / 'cacert.pem'; record(f); record(f.parent / '__init__.py')
                raw = (f.parent / '__init__.py').read_text()
                version = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)', raw)
                assert version and tuple(map(int, version[1].split('.'))) >= (2026, 10, 19)
                contexts.append((str(f), ssl.create_default_context(cafile=str(f))))
    for name in ['CURL_CA_BUNDLE', 'REQUESTS_CA_BUNDLE', 'SSL_CERT_FILE']:
        if os.environ.get(name): contexts.append((name, ssl.create_default_context(cafile=os.environ[name])))
    context_roots = {}
    for name, ctx in contexts:
        fingerprints = sorted(hashlib.sha256(c).hexdigest() for c in ctx.get_ca_certs(binary_form=True))
        assert fingerprints and not BLOCKED.intersection(fingerprints), (name, 'empty or distrusted CA store')
        context_roots[name] = fingerprints
    runtimes = {}
    # /proc maps binds the interpreter's actually loaded libssl/libcrypto, avoiding
    # musl ldd's expected unresolved Python C symbols on a loadable extension.
    for line in Path('/proc/self/maps').read_text().splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[5].startswith('/'):
            f = Path(fields[5]); runtimes[str(f.resolve())] = sha(f)
    for binary in [shutil.which('curl'), shutil.which('openssl')]:
        assert binary
        p = Path(binary).resolve(); runtimes[str(p)] = sha(p)
        linked = subprocess.run(['ldd', str(p)], capture_output=True, text=True, timeout=30)
        assert linked.returncode == 0, linked.stderr
        for lib in re.findall(r'(/[\w/+.@-]+)', linked.stdout):
            f = Path(lib)
            if f.is_file(): runtimes[str(f.resolve())] = sha(f)
    curl = subprocess.check_output(['curl', '-V'], text=True)
    assert 'OpenSSL/' in curl, 'unknown curl trust backend'
    rejected = []
    with tempfile.TemporaryDirectory() as t:
        for c in certs:
            p = Path(t) / 'advisory.pem'; p.write_text(c['pem'])
            proc = subprocess.run(['openssl', 'verify', '-purpose', 'sslserver', str(p)], capture_output=True, text=True, timeout=30)
            assert proc.returncode != 0 and re.search(r'error (18|19|20|21) at', proc.stdout + proc.stderr), ('advisory root accepted or inconclusive', proc.stdout, proc.stderr)
            rejected.append(c['sha256'].lower())
    return {'schema': 1, 'environment': {n: os.environ.get(n) for n in TRUST_ENV},
            'defaultPaths': paths._asdict(), 'contexts': context_roots, 'trustFiles': trust_files,
            'runtimes': runtimes, 'curl': curl, 'rejectedAdvisoryRoots': sorted(rejected)}

if __name__ == '__main__':
    print(json.dumps(snapshot(sys.stdin.read()), sort_keys=True))
