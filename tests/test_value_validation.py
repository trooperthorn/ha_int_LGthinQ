"""Profile-gated refrigerator control values."""

import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[1] / "custom_components/lg_thinq_extended/value_validation.py"
spec = importlib.util.spec_from_file_location("lg_value_validation_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProfileValueTests(unittest.TestCase):
    def test_fridge_and_freezer_ranges(self):
        for value in (33, 36, 43):
            self.assertEqual(module.validate_profile_number(value, 33, 43, 1), value)
        for value in (-7, -1, 5):
            self.assertEqual(module.validate_profile_number(value, -7, 5, 1), value)

    def test_rejects_outside_range_or_bad_increment_before_post(self):
        for value, low, high, step in ((32, 33, 43, 1), (6, -7, 5, 1), (35.5, 33, 43, 1), (float("nan"), 33, 43, 1), (35, None, 43, 1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.validate_profile_number(value, low, high, step)


if __name__ == "__main__":
    unittest.main()

