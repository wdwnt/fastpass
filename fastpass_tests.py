import unittest
from datetime import datetime

import fastpass


class TestFunctions(unittest.TestCase):
    def setup(self):
        fastpass.app.config['TESTING'] = True
        self.app = fastpass.app.test_client()

        # Test of Output functions

    def test_output(self):
        with fastpass.app.test_request_context():
            # Mock object
            for func in ('posts', 'youtube', 'podcasts', 'radio'):
                # t1 = datetime.now()
                t1_start = datetime.now()
                out = getattr(fastpass, func)()
                t1_end = datetime.now()
                t1 = t1_end - t1_start
                self.assertEqual(out.status_code, 200, '200 returns for {}'.format(func))
                self.assertIsNotNone(out.json, 'JSON retuns for {}'.format(func))

                t2_start = datetime.now()
                getattr(fastpass, func)()
                t2_end = datetime.now()
                t2 = t2_end - t2_start
                self.assertGreater(t1, t2, 'Cached for {}'.format(func))


if __name__ == '__main__':
    unittest.main(verbosity=2)
