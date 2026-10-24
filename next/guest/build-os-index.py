#!/usr/bin/env python3
"""Build/validate an OS index offline. Never uploads or writes a legacy feed."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


def validate(image):
    if type(image.get('guestABI')) is not int or image['guestABI'] < 0:
        raise ValueError('Integer guestABI required')
    if not isinstance(image.get('imageBuild'), str) or not image['imageBuild']:
        raise ValueError('imageBuild required')
    for key in ('bytes', 'installBytes'):
        if type(image.get(key)) is not int or image[key] <= 0:
            raise ValueError('Positive size required')
    if not re.fullmatch('[a-fA-F0-9]{64}', image.get('sha256', '')):
        raise ValueError('Archive sha256 required')
    parts = image.get('parts')
    if not isinstance(parts, list) or not parts:
        raise ValueError('Immutable parts required (a single archive is one part)')
    for part in parts:
        url = urlsplit(part['url'])
        path = url.path.split('/')
        if (url.scheme != 'https' or url.netloc != 'downloads.aiwizards.com' or url.query or url.fragment or
                len(path) < 4 or path[1] != 'os' or path[2] in ('p1', 'latest.json', 'index.json') or
                '..' in url.path or '%' in url.path or not path[2]):
            raise ValueError('Part URL must be an immutable absolute os/<version>/ URL')
        if type(part.get('bytes')) is not int or part['bytes'] <= 0 or not re.fullmatch('[a-fA-F0-9]{64}', part.get('sha256', '')):
            raise ValueError('Part size and sha256 required')
    if sum(p['bytes'] for p in parts) != image['bytes']:
        raise ValueError('Part sizes disagree with archive size')
    return image


def select(images, low=0, high=1):
    compatible = [i for i in images if type(i.get('guestABI')) is int and low <= i['guestABI'] <= high]
    if not compatible:
        raise ValueError('No compatible Wizard OS image; update Wizard first')
    # Same numeric imageBuild ordering as Foundation .numeric for release tokens.
    def key(image):
        return [(1, int(t)) if t.isdigit() else (0, t) for t in re.split(r'(\d+)', image.get('imageBuild', ''))]
    return validate(max(compatible, key=key))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('feeds', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    images = []
    for feed in args.feeds:
        image = json.loads(feed.read_text())
        if not image.get('parts') and image.get('url'):
            image['parts'] = [{k: image[k] for k in ('url', 'bytes', 'sha256')}]
        images.append(validate(image))
    if len({i['imageBuild'] for i in images}) != len(images):
        parser.error('Duplicate imageBuild')
    if args.output.name != 'index.json':
        parser.error('Output must be index.json; frozen feeds are never a target')
    args.output.write_text(json.dumps({'schema': 1, 'images': images}, indent=2) + '\n')


if __name__ == '__main__':
    main()
