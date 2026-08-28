from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api.services.performance import (
    HeavyJobController,
    HeavyJobQueueFull,
    LatestRequestRegistry,
    SupersededRequest,
)


class LatestRequestRegistryTests(unittest.TestCase):
    def test_new_request_supersedes_old_request(self):
        registry = LatestRequestRegistry(max_clients=64)
        old = registry.register("browser-a", "request-1")
        current = registry.register("browser-a", "request-2")
        with self.assertRaises(SupersededRequest):
            registry.ensure_current(old)
        registry.ensure_current(current)

    def test_missing_headers_remain_backward_compatible(self):
        registry = LatestRequestRegistry(max_clients=64)
        token = registry.register(None, None)
        self.assertIsNone(token)
        registry.ensure_current(token)


class HeavyJobControllerTests(unittest.TestCase):
    def test_queue_limit_rejects_extra_job(self):
        env = {
            "DTA_MAX_CONCURRENT_HEAVY_JOBS": "1",
            "DTA_MAX_QUEUED_HEAVY_JOBS": "0",
            "DTA_HEAVY_JOB_QUEUE_TIMEOUT_S": "0.1",
        }
        with patch.dict(os.environ, env, clear=False):
            controller = HeavyJobController()
        with controller.slot():
            with self.assertRaises(HeavyJobQueueFull):
                with controller.slot():
                    pass
        metrics = controller.metrics()
        self.assertEqual(metrics["completed"], 1)
        self.assertEqual(metrics["rejected"], 1)


if __name__ == "__main__":
    unittest.main()
