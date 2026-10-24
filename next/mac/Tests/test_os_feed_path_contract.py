import json, re, unittest
from pathlib import Path
MAC = Path(__file__).resolve().parents[1]

class FeedPathContract(unittest.TestCase):
    def test_app_reads_epoch_feed_not_frozen_legacy_feed(self):
        src = (MAC / 'App/main.swift').read_text()
        m = re.search(r'Store\.downloadsBase \+ "(os/[^"]+)"', src)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), 'os/index.json')
        self.assertIn('https://downloads.aiwizards.com/os/p1/latest.json', src)
        self.assertNotIn('"os/latest.json"', src)

    def test_release_metadata_matches(self):
        rel = json.loads((MAC / 'release-0.7.1.json').read_text())
        self.assertEqual(rel['imageFeed'], 'https://downloads.aiwizards.com/os/p1/latest.json')

if __name__ == '__main__':
    unittest.main()
