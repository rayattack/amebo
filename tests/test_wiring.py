"""Import-level wiring smoke tests.

`amebo/router.py` builds the heaven Application and registers every route at import
time, and `amebo/main.py` is the CLI entrypoint. These tests assert the modules import
cleanly and the application object is constructed — cheap coverage of the wiring that
would otherwise only be exercised by actually booting the server.
"""
import unittest


class WiringTest(unittest.TestCase):
    def test_router_builds_application(self):
        import amebo.router as r
        from heaven import Application
        self.assertIsInstance(r.router, Application)
        # the delivery daemon is wired onto the router
        self.assertTrue(hasattr(r.router, 'daemons'))

    def test_main_exposes_entrypoint(self):
        import amebo.main as m
        self.assertTrue(callable(m.execute))

    def test_package_version_exported(self):
        import amebo
        self.assertIsInstance(amebo.__version__, str)
        self.assertTrue(amebo.__version__)
