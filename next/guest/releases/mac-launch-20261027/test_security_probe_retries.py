"""Guest TLS probe retry policy: temporary DNS failures are retried longer, verdicts never.
Regression: factory trial failed when files-engine hit EAI_AGAIN ('Try again') on one bad-host lookup."""
import importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('security_probe',Path(__file__).with_name('security-probe.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def failing(detail,succeed_after=None):
    calls=[0]
    def call():
        calls[0]+=1
        if succeed_after is not None and calls[0]>succeed_after:return 'ok'
        raise AssertionError(detail)
    return call,calls

DNS=('system','https://dv-g3c-emudhra.we-have-a-problem.com/','<urlopen error [Errno -3] Try again>')
EOF_=('system','https://example.com/','<urlopen error EOF occurred in violation of protocol>')
VERDICT=('system','https://example.com/','<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>')

class Retries(unittest.TestCase):
    def test_dns_temporary_failure_recovers_after_more_than_five_attempts(self):
        call,calls=failing(DNS,succeed_after=6);sleeps=[]
        self.assertEqual(m.with_transport_retries(call,sleeps.append),'ok')
        self.assertEqual(calls[0],7);self.assertLessEqual(max(sleeps),30)
    def test_persistent_dns_failure_still_fails_closed(self):
        call,calls=failing(DNS)
        with self.assertRaises(AssertionError):m.with_transport_retries(call,lambda s:None)
        self.assertEqual(calls[0],8)
    def test_other_transport_failures_keep_five_attempts(self):
        call,calls=failing(EOF_)
        with self.assertRaises(AssertionError):m.with_transport_retries(call,lambda s:None)
        self.assertEqual(calls[0],5)
    def test_certificate_verdict_and_accepted_bad_chain_never_retry(self):
        for detail in (VERDICT,'compromised chain accepted: https://x/'):
            call,calls=failing(detail)
            with self.assertRaises(AssertionError):m.with_transport_retries(call,lambda s:None)
            self.assertEqual(calls[0],1)

if __name__=='__main__':unittest.main()
