import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from present_exchange import ExchangeView
from registered_memory import MemoryUnavailable


class ExchangeTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, user=42, number=500):
        return SimpleNamespace(id=number, user=SimpleNamespace(id=user),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    async def test_selection_exchange_and_duplicate_event(self):
        store = SimpleNamespace(exchange=Mock(return_value=(0, 1)))
        view = ExchangeView(42, store, {'magic': 3, 'rare': 10})
        self.assertNotIn('rare', [o.value for o in view.children[0].options])
        await view.choose(self.interaction(), 'source', 'magic')
        await view.choose(self.interaction(), 'target', 'food')
        self.assertFalse(view.children[2].disabled)
        await view.exchange(self.interaction())
        await view.exchange(self.interaction())
        store.exchange.assert_called_once_with(42, 500, 'magic', 'food')
        self.assertEqual(view.items, {'magic': 0, 'food': 1, 'rare': 10})
        self.assertTrue(view.children[2].disabled)
        self.assertFalse(await view.interaction_check(self.interaction(user=43)))
        view.stop()

    async def test_empty_items_and_failure_do_not_spend(self):
        empty = ExchangeView(42, None, {})
        self.assertTrue(all(child.disabled for child in empty.children))
        empty.stop()
        store = SimpleNamespace(exchange=Mock(side_effect=MemoryUnavailable('offline')))
        view = ExchangeView(42, store, {'magic': 3})
        await view.choose(self.interaction(), 'source', 'magic')
        await view.choose(self.interaction(), 'target', 'food')
        await view.exchange(self.interaction())
        self.assertEqual(view.items, {'magic': 3})
        view.message = SimpleNamespace(edit=AsyncMock())
        await view.on_timeout()
        await view.exchange(self.interaction(number=501))
        store.exchange.assert_called_once()
        self.assertTrue(all(child.disabled for child in view.children))
        view.stop()
