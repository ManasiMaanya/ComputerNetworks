import copy
import json
import unittest

from .helpers import tmp_dir

from src.config import load_config, output_dir, resolve_path, validate_config
from src.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_default_config_is_valid_and_keeps_p0_keys(self):
        self.assertEqual(self.cfg["bind"], "127.0.0.1")
        self.assertEqual(self.cfg["k_candidate_paths"], 5)
        self.assertEqual(self.cfg["max_hops"], 8)
        self.assertEqual(self.cfg["ospf_cost"], "delay")
        self.assertTrue(resolve_path(self.cfg["sample_topology"]).is_file())

    def bad(self, mutate, fragment):
        cfg = copy.deepcopy(self.cfg)
        mutate(cfg)
        with self.assertRaises(ConfigError) as ctx:
            validate_config(cfg)
        self.assertIn(fragment, str(ctx.exception))

    def test_missing_key(self):
        self.bad(lambda c: c.pop("max_hops"), "max_hops")

    def test_non_positive_k(self):
        self.bad(lambda c: c.update(k_candidate_paths=0), "k_candidate_paths")

    def test_bool_is_not_an_int(self):
        self.bad(lambda c: c.update(max_hops=True), "max_hops")

    def test_bad_ospf_cost(self):
        self.bad(lambda c: c.update(ospf_cost="hopcount"), "ospf_cost")

    def test_bad_candidate_strategy(self):
        self.bad(lambda c: c.update(candidate_strategy="random"), "candidate_strategy")

    def test_negative_weight(self):
        self.bad(lambda c: c["scoring"]["weights"].update(delay=-1), "delay")

    def test_unknown_weight_term(self):
        self.bad(lambda c: c["scoring"]["weights"].update(jitter=0.1), "jitter")

    def test_all_zero_weights(self):
        self.bad(lambda c: c["scoring"].update(weights={k: 0 for k in c["scoring"]["weights"]}), "weight")

    def test_zero_reference(self):
        self.bad(lambda c: c["scoring"]["reference"].update(delay_ms=0), "delay_ms")

    def test_test_size_range(self):
        self.bad(lambda c: c["training"].update(test_size=1.5), "test_size")

    def test_bad_compare_pair(self):
        self.bad(lambda c: c["compare"].update(pairs=[["R1"]]), "pairs")

    def test_missing_file_and_invalid_json(self):
        work = tmp_dir()
        with self.assertRaises(ConfigError) as ctx:
            load_config(work / "nope.json")
        self.assertIn("not found", str(ctx.exception))
        broken = work / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            load_config(broken)
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_load_from_explicit_path(self):
        work = tmp_dir()
        path = work / "c.json"
        path.write_text(json.dumps(self.cfg), encoding="utf-8")
        self.assertEqual(load_config(path)["max_hops"], 8)

    def test_output_dir_created(self):
        cfg = copy.deepcopy(self.cfg)
        work = tmp_dir()
        cfg["paths"]["outputs_dir"] = str(work / "out")
        path = output_dir(cfg, "routes")
        self.assertTrue(path.is_dir())
        self.assertEqual(path, work / "out" / "routes")


    def test_training_label_and_traffic_keys(self):
        self.bad(lambda c: c["training"].update(labels="snapshot"), "labels")
        self.bad(lambda c: c["training"].update(horizon_steps=0), "horizon_steps")
        self.bad(lambda c: c["training"].update(test_time_fraction=1.2), "test_time_fraction")
        self.bad(lambda c: c["training"].update(blackbox_hidden_layers=[]), "blackbox_hidden_layers")
        self.bad(lambda c: c.pop("traffic"), "traffic")
        self.bad(lambda c: c["traffic"].update(burst_prob=2), "burst_prob")


if __name__ == "__main__":
    unittest.main()
