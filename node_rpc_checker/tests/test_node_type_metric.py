import unittest

from node_rpc_checker.config import Config, Node
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class NodeTypeMetricTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake("NEAR")
        self.checker = Checker(Config("NEAR", {"n": Node("node")}, "trusted"), self.fake)

    def sample(self, node_type: str) -> str:
        return (
            'node_rpc_checker_node_type_info{chain="NEAR",node="n",'
            f'type="{node_type}"}} 1'
        )

    def test_type_is_absent_until_a_deep_check_passes(self):
        self.checker.cycle("n", mode="readyz")
        self.assertNotIn("node_rpc_checker_node_type_info{", self.checker.metrics())

    def test_prune_after_successful_pruning_check(self):
        self.checker.cycle("n", mode="pruning")
        metrics = self.checker.metrics()
        self.assertIn(self.sample("prune"), metrics)
        self.assertNotIn(self.sample("archive"), metrics)

    def test_archive_takes_priority_after_successful_archive_check(self):
        self.checker.cycle("n", mode="pruning")
        self.fake.archive = True
        self.checker.cycle("n", mode="archive")
        metrics = self.checker.metrics()
        self.assertIn(self.sample("archive"), metrics)
        self.assertNotIn(self.sample("prune"), metrics)

    def test_failed_archive_falls_back_to_fresh_prune_proof(self):
        self.checker.cycle("n", mode="pruning")
        self.checker.cycle("n", mode="archive")
        metrics = self.checker.metrics()
        self.assertIn(self.sample("prune"), metrics)
        self.assertNotIn(self.sample("archive"), metrics)


if __name__ == "__main__":
    unittest.main()
