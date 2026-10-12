#!/usr/bin/env python3
"""Put a Wizard OS feed folder (latest.json + archive or parts) on Cloudflare R2 and print a signed test feed URL.

  publish-r2.py <feed dir> [--bucket wizard-downloads] [--prefix os/<version>/] [--days 7]

Credential: CLOUDFLARE_R2_ADMIN_API_TOKEN (an R2 "Admin Read & Write" API token) from the environment or
~/.hermes/.env. One token gives both the Cloudflare API (bucket creation) and the S3 keys: Access Key ID = the
token's id, Secret Access Key = SHA-256 of the token value. Nothing is printed except bucket/object names and the
signed URLs.

The bucket stays private. For a test, the uploaded latest.json is rewritten with absolute pre-signed part URLs and
itself pre-signed, so the Mac app can download end to end without the bucket or a custom domain being public.
Making it public (custom domain such as downloads.aiwizards.com) is a separate, deliberate release step.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "92b29f2f2f8c6d5e59594884ee852913")
RCLONE = shutil.which("rclone") or str(Path.home() / ".local/bin/rclone")


def token() -> str:
    t = os.environ.get("CLOUDFLARE_R2_ADMIN_API_TOKEN")
    if not t:
        for line in (Path.home() / ".hermes/.env").read_text().splitlines():
            if line.startswith("CLOUDFLARE_R2_ADMIN_API_TOKEN="):
                t = line.split("=", 1)[1].strip().strip("'\"")
    if not t:
        sys.exit("CLOUDFLARE_R2_ADMIN_API_TOKEN is not set")
    return t


def api(method: str, path: str, tok: str, body=None):
    req = urllib.request.Request(f"https://api.cloudflare.com/client/v4{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") | {"http": e.code}


def rclone(env: dict, *args: str, capture=False) -> str:
    r = subprocess.run([RCLONE, *args], env=os.environ | env, text=True,
                       capture_output=capture, check=True)
    return (r.stdout or "").strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("feed_dir")
    ap.add_argument("--bucket", default="wizard-downloads")
    ap.add_argument("--prefix")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    feed_dir = Path(a.feed_dir)
    feed = json.loads((feed_dir / "latest.json").read_text())
    prefix = a.prefix or f"os/{feed['version']}/"
    tok = token()

    v = api("GET", f"/accounts/{ACCOUNT}/tokens/verify", tok)
    if not v.get("success"):
        v = api("GET", "/user/tokens/verify", tok)
    if not v.get("success"):
        sys.exit(f"token not accepted by Cloudflare: {v.get('errors') or v.get('http')}")
    key_id = v["result"]["id"]
    b = api("GET", f"/accounts/{ACCOUNT}/r2/buckets/{a.bucket}", tok)
    if not b.get("success"):
        c = api("POST", f"/accounts/{ACCOUNT}/r2/buckets", tok, {"name": a.bucket})
        if not c.get("success"):
            sys.exit(f"could not create bucket {a.bucket}: {c.get('errors') or c.get('http')}")
        print("created bucket", a.bucket)
    else:
        print("bucket", a.bucket, "exists")

    env = {
        "RCLONE_CONFIG_WZR2_TYPE": "s3", "RCLONE_CONFIG_WZR2_PROVIDER": "Cloudflare",
        "RCLONE_CONFIG_WZR2_ACCESS_KEY_ID": key_id,
        "RCLONE_CONFIG_WZR2_SECRET_ACCESS_KEY": hashlib.sha256(tok.encode()).hexdigest(),
        "RCLONE_CONFIG_WZR2_ENDPOINT": f"https://{ACCOUNT}.r2.cloudflarestorage.com",
        "RCLONE_CONFIG_WZR2_ACL": "private", "RCLONE_CONFIG_WZR2_NO_CHECK_BUCKET": "true",
    }
    dest = f"wzr2:{a.bucket}/{prefix}"
    names = [p["url"] for p in feed.get("parts") or []] or [feed["url"]]
    for n in names + ["latest.json"]:
        rclone(env, "copyto", "--s3-chunk-size", "64M", "--s3-upload-concurrency", "4",
               str(feed_dir / Path(n).name), dest + Path(n).name)
        print("uploaded", prefix + Path(n).name)
    # Integrity: R2 must hand back exactly the bytes we hashed.
    listing = json.loads(rclone(env, "lsjson", dest, capture=True))
    sizes = {o["Name"]: o["Size"] for o in listing}
    for n in names:
        want = next((p["bytes"] for p in feed.get("parts") or [] if p["url"] == n), feed.get("bytes"))
        if sizes.get(Path(n).name) != want:
            sys.exit(f"{n}: R2 has {sizes.get(Path(n).name)} bytes, expected {want}")
    expire = f"{a.days * 24}h"
    signed = dict(feed)
    if feed.get("parts"):
        signed["parts"] = [p | {"url": rclone(env, "link", "--expire", expire, dest + Path(p["url"]).name, capture=True)}
                           for p in feed["parts"]]
    else:
        signed["url"] = rclone(env, "link", "--expire", expire, dest + Path(feed["url"]).name, capture=True)
    with tempfile.TemporaryDirectory() as d:
        Path(d, "latest-signed.json").write_text(json.dumps(signed, indent=2))
        rclone(env, "copyto", str(Path(d, "latest-signed.json")), dest + "latest-signed.json")
    url = rclone(env, "link", "--expire", expire, dest + "latest-signed.json", capture=True)
    out = Path(feed_dir, "r2-signed-feed-url.txt")
    out.write_text(url + "\n"); os.chmod(out, 0o600)
    print(f"R2_PUBLISH_OK bucket={a.bucket} prefix={prefix} objects={len(names) + 2} signed feed URL in {out} "
          f"(valid {a.days} days)")


if __name__ == "__main__":
    main()
