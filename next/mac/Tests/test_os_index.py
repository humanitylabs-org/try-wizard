import copy
import importlib.util
import unittest
from test_guest_abi import MAC

spec = importlib.util.spec_from_file_location('os_index', MAC.parent / 'guest/build-os-index.py')
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


def image(build, abi=1):
    return {'version': 'display-only', 'imageBuild': build, 'guestABI': abi,
            'sha256': 'a' * 64, 'bytes': 10, 'installBytes': 100,
            'parts': [{'url': f'https://downloads.aiwizards.com/os/{build}/image.part00', 'bytes': 10, 'sha256': 'b' * 64}]}


class ImageIndexContract(unittest.TestCase):
    def test_newest_compatible_numeric_build(self):
        self.assertEqual(index.select([image('0.4.9'), image('0.4.10'), image('9.0.0', 2)])['imageBuild'], '0.4.10')
        self.assertEqual(index.select([image('0.3.0', 0), image('0.4.1')], 0, 0)['guestABI'], 0)
        with self.assertRaises(ValueError):
            index.select([image('9', 2)])
        with self.assertRaises(ValueError):
            index.select([])

    def test_parts_and_digests_required(self):
        for field, value in [('sha256', 'bad'), ('parts', []), ('bytes', 11), ('imageBuild', '')]:
            bad = image('0.4.2'); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                index.validate(bad)
        for url in ('../0.4.2/a', 'https://downloads.aiwizards.com/os/p1/a', 'http://downloads.aiwizards.com/os/0.4.2/a',
                    'https://evil.example/os/0.4.2/a', 'https://downloads.aiwizards.com/os/0.4.2/a?mutable=1'):
            bad = image('0.4.2'); bad['parts'][0]['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                index.validate(bad)

    def test_app_selection_and_absent_only_fallback(self):
        source = (MAC / 'App/main.swift').read_text()
        self.assertIn('os/index.json', source)
        self.assertIn('!legacy && [404, 410].contains(code ?? 0)', source)
        self.assertIn('fetch(Store.legacyOSFeedURL, legacy: true)', source)
        self.assertIn('WizardGuestABI.supportedGuestABI.contains', source)
        self.assertIn('options: .numeric', source)
        self.assertIn('Self.downloadList(feed, base: base)', source)
        self.assertIn('relativeTo: base', source)
        self.assertIn('OSInstaller.resolveFeed { result in', source)
        for marker in ('url.scheme == "https"', 'part.sha256.range', 'sum == bytes'):
            self.assertIn(marker, source)


if __name__ == '__main__':
    unittest.main()
