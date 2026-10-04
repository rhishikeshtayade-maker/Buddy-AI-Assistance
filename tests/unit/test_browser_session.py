"""Unit tests for BrowserSession and TabManager.

Tests session lifecycle, status transitions, timeout enforcement,
and multi-tab management with quota enforcement.
"""

import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserTabError, BrowserTimeoutError
from app.browser.models import BrowserSessionStatus, BrowserTabStatus
from app.browser.session import BrowserSession
from app.browser.tabs import BrowserTab, TabManager


class TestBrowserSession(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = BrowserConfig(
            browser_session_timeout_seconds=2.0,
            browser_max_tabs=3,
        )

    def test_tab_manager_lifecycle(self):
        mgr = TabManager(max_tabs=3)
        tab1 = BrowserTab(tab_id="t1", url="https://example.com/1")
        tab2 = BrowserTab(tab_id="t2", url="https://example.com/2")
        tab3 = BrowserTab(tab_id="t3", url="https://example.com/3")

        mgr.add_tab(tab1)
        self.assertEqual(mgr.active_tab_id, "t1")
        self.assertEqual(len(mgr.list_tabs()), 1)

        mgr.add_tab(tab2, set_active=True)
        self.assertEqual(mgr.active_tab_id, "t2")
        self.assertEqual(tab1.status, BrowserTabStatus.BACKGROUND)

        mgr.add_tab(tab3, set_active=False)
        self.assertEqual(mgr.active_tab_id, "t2")
        self.assertEqual(len(mgr.list_tabs()), 3)

        # Exceeding max tabs
        tab4 = BrowserTab(tab_id="t4")
        with self.assertRaises(BrowserTabError):
            mgr.add_tab(tab4)

        # Switch active tab
        mgr.set_active_tab("t3")
        self.assertEqual(mgr.active_tab_id, "t3")

        # Close tab
        mgr.remove_tab("t3")
        self.assertEqual(len(mgr.list_tabs()), 2)
        self.assertIn(mgr.active_tab_id, ["t1", "t2"])

    async def test_session_lifecycle(self):
        mock_bm = MagicMock()
        mock_bm.create_isolated_context = AsyncMock(return_value=None)
        mock_bm.stop = AsyncMock()

        session = BrowserSession(config=self.config, browser_manager=mock_bm)
        self.assertEqual(session.status, BrowserSessionStatus.CREATED)

        await session.start()
        self.assertEqual(session.status, BrowserSessionStatus.RUNNING)
        self.assertEqual(len(session.tab_manager.list_tabs()), 1)

        # Touch updates activity
        old_act = session.last_activity
        session.touch()
        self.assertGreaterEqual(session.last_activity, old_act)

        # New tab
        tab2 = await session.new_tab("https://example.com")
        self.assertEqual(len(session.tab_manager.list_tabs()), 2)

        # Close tab
        await session.close_tab(tab2.tab_id)
        self.assertEqual(len(session.tab_manager.list_tabs()), 1)

        # Close session
        await session.close()
        self.assertEqual(session.status, BrowserSessionStatus.CLOSED)

    def test_session_inactivity_timeout(self):
        session = BrowserSession(config=self.config)
        session.status = BrowserSessionStatus.RUNNING
        # Artificially age session
        session.last_activity = time.time() - 10.0

        self.assertTrue(session.is_expired)
        with self.assertRaises(BrowserTimeoutError):
            session.touch()


if __name__ == "__main__":
    unittest.main()
