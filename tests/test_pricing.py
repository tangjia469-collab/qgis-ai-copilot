"""Official-price estimates must not masquerade as router bills."""

import importlib
import unittest

from qgis_ai_copilot.storage import _sanitize_usage, sanitized_conversation


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("qgis_ai_copilot.pricing"), "Missing official-price calculator"
        )
        self.pricing = importlib.import_module("qgis_ai_copilot.pricing")

    def test_exact_astra_cost_counts_cache_writes_and_reasoning_once(self):
        result = self.pricing.estimate_cost(
            "gpt-6-astra",
            [
                {
                    "input_tokens": 1000,
                    "cached_tokens": 200,
                    "cache_write_tokens": 300,
                    "output_tokens": 100,
                    "reasoning_tokens": 60,
                }
            ],
        )
        self.assertEqual(result["min_usd"], "0.01395")
        self.assertEqual(result["max_usd"], "0.01395")
        self.assertEqual(result["currency"], "USD")

    def test_missing_cache_writes_give_an_honest_range(self):
        result = self.pricing.estimate_cost(
            "gpt-6-astra",
            [
                {
                    "input_tokens": 1000,
                    "cached_tokens": 200,
                    "output_tokens": 100,
                }
            ],
        )
        self.assertEqual(result["min_usd"], "0.0132")
        self.assertEqual(result["max_usd"], "0.0152")

    def test_missing_cache_detail_is_not_assumed_to_be_zero(self):
        result = self.pricing.estimate_cost(
            "gpt-4.1", [{"prompt_tokens": 1000, "completion_tokens": 100}]
        )
        self.assertEqual(result["min_usd"], "0.0013")
        self.assertEqual(result["max_usd"], "0.0028")

    def test_long_context_is_decided_per_round_not_on_the_sum(self):
        short = {
            "input_tokens": 200000,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 100,
        }
        result = self.pricing.estimate_cost("gpt-6-astra", [short, short])
        self.assertEqual(result["min_usd"], "4.01")
        at_cutoff = dict(short, input_tokens=272000)
        over_cutoff = dict(short, input_tokens=272001)
        self.assertEqual(self.pricing.estimate_cost("gpt-6-astra", [at_cutoff])["min_usd"], "2.725")
        self.assertEqual(
            self.pricing.estimate_cost("gpt-6-astra", [over_cutoff])["min_usd"], "5.44752"
        )

    def test_unknown_models_and_incomplete_or_invalid_usage_have_no_fake_cost(self):
        valid = {
            "input_tokens": 10,
            "output_tokens": 2,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
        }
        for model, rounds in [
            ("gpt-6-astra-router-custom", [valid]),
            ("unknown", [valid]),
            ("gpt-6-astra", []),
            ("gpt-6-astra", [valid, {}]),
            ("gpt-6-astra", [{"total_tokens": 12}]),
            ("gpt-6-astra", [dict(valid, cached_tokens=11)]),
            ("gpt-6-astra", [dict(valid, input_tokens=True)]),
            ("gpt-6-astra", [dict(valid, input_tokens=1.5)]),
            ("gpt-6-astra", [dict(valid, total_tokens=999)]),
        ]:
            with self.subTest(model=model, rounds=rounds):
                self.assertEqual(self.pricing.estimate_cost(model, rounds)["status"], "unavailable")

    def test_price_snapshot_is_preserved_and_secrets_are_dropped(self):
        estimate = self.pricing.estimate_cost(
            "gpt-5.6-terra",
            [
                {
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                }
            ],
        )
        estimate["secret"] = "not-to-be-saved"
        saved = sanitized_conversation(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "cost_estimate": estimate,
                        "usage_rounds": [
                            {"input_tokens": 1000, "output_tokens": 100, "secret": "private"}
                        ],
                    }
                ]
            }
        )
        record = saved["messages"][0]
        self.assertNotIn("secret", record["cost_estimate"])
        self.assertEqual(record["cost_estimate"]["min_usd"], "0.0032")
        self.assertEqual(record["usage_rounds"], [{"input_tokens": 1000, "output_tokens": 100}])

    def test_cache_write_accounting_survives_storage(self):
        safe = _sanitize_usage(
            {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300},
                "completion_tokens_details": {"cached_tokens": 999},
            }
        )
        self.assertEqual(safe.get("cached_tokens"), 200)
        self.assertEqual(safe.get("cache_write_tokens"), 300)
        result = self.pricing.estimate_cost("gpt-6-astra", [safe])
        self.assertEqual(result["min_usd"], "0.01395")

    def test_history_fallback_and_partial_messages_are_honest(self):
        message = {
            "role": "assistant",
            "status": "complete",
            "request": {"model": "gpt-6-astra", "inspect": True},
            "usage": {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 200},
        }
        label, tooltip = self.pricing.cost_display(message)
        self.assertIn("Est. $", label)
        self.assertNotIn("tokens", label)
        self.assertIn("Standard", tooltip)
        self.assertIn("not", tooltip.lower())
        message["status"] = "stopped"
        self.assertEqual(self.pricing.cost_display(message)[0], "Cost unavailable")
        message["status"] = "complete"
        message["usage"]["input_tokens"] = 300000
        self.assertEqual(self.pricing.cost_display(message)[0], "Cost unavailable")

    def test_tiny_nonzero_cost_is_not_shown_as_zero(self):
        message = {
            "status": "complete",
            "request": {"model": "gpt-5-nano"},
            "usage": {"input_tokens": 1, "output_tokens": 1, "cached_tokens": 0},
        }
        self.assertEqual(self.pricing.cost_display(message)[0], "Est. <$0.0001")

    def test_untrusted_saved_amounts_and_models_are_rejected(self):
        valid = self.pricing.estimate_cost(
            "gpt-6-astra",
            [{"input_tokens": 10, "output_tokens": 2, "cached_tokens": 0, "cache_write_tokens": 0}],
        )
        for changes in (
            {"min_usd": "1e-4"},
            {"model": []},
            {"max_usd": "NaN"},
            {"source_url": "https://unverified.example"},
            {"pricing_date": "2099-01-01"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.pricing.sanitize_cost_estimate(dict(valid, **changes))["status"],
                    "unavailable",
                )
        self.assertEqual(
            self.pricing.estimate_cost([], [{"input_tokens": 1, "output_tokens": 1}])["status"],
            "unavailable",
        )


if __name__ == "__main__":
    unittest.main()
