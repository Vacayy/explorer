"""Public entry must not provision or start legacy background writers."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from routers import analysis, discovery


class PublicLifecycleTests(unittest.TestCase):
    def test_public_startup_validates_without_initialization_or_bot(self):
        with patch.dict(os.environ, {'EXPLORER_ACCESS_MODE':'public'}), \
             patch.object(main,'validate_public_state',create=True) as validate, \
             patch.object(main,'init_db',side_effect=AssertionError('public init_db')), \
             patch('pipeline.bot.start_bot',side_effect=AssertionError('public bot')):
            main.startup()
            validate.assert_called_once_with()

    def test_public_router_workers_do_not_start(self):
        with patch.dict(os.environ, {'EXPLORER_ACCESS_MODE':'public'}):
            for router in (analysis,discovery):
                with patch.object(router,'service',side_effect=AssertionError('public worker')):
                    router.start_worker()

    def test_public_observation_does_not_write(self):
        response=SimpleNamespace(status_code=200)
        async def next_handler(request):return response
        with patch.dict(os.environ, {'EXPLORER_ACCESS_MODE':'public'}), \
             patch('pipeline.observe.flush',side_effect=AssertionError('public flush')), \
             patch('pipeline.observe.record_request',side_effect=AssertionError('public observe')):
            self.assertIs(asyncio.run(main._observe_requests(SimpleNamespace(scope={},headers={}),next_handler)),response)
            main._flush_observe()

    def test_private_startup_and_workers_remain(self):
        with patch.dict(os.environ, {'EXPLORER_ACCESS_MODE':'private'}), \
             patch.object(main,'init_db') as initialize,patch('pipeline.bot.start_bot') as bot:
            main.startup();initialize.assert_called_once_with();bot.assert_called_once_with()
            for router in (analysis,discovery):
                with patch.object(router,'service',return_value=Mock()) as service:
                    router.start_worker();service.assert_called_once_with()


if __name__=='__main__':unittest.main()
