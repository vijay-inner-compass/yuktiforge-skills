import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_contract_reviewer  # noqa: E402
import _assertions  # noqa: E402

EXAMPLES = sorted(p for p in (ROOT / "examples").iterdir() if p.is_dir())


class ExamplesHold(unittest.TestCase):
    def test_there_are_examples(self):
        self.assertTrue(EXAMPLES, "the skill ships no worked examples")

    def test_every_example_meets_its_expectations(self):
        for ex in EXAMPLES:
            with self.subTest(example=ex.name):
                out = api_contract_reviewer.run_file(ex / "input.txt")
                expect = json.loads((ex / "expect.json").read_text(encoding="utf-8"))
                self.assertTrue(expect, "example has no expectations")
                for a in expect:
                    problem = _assertions.check(out, a["path"], a["op"], a.get("value"))
                    self.assertIsNone(problem, problem)

    def test_unreadable_input_is_an_input_error(self):
        with self.assertRaises(api_contract_reviewer.InputError):
            api_contract_reviewer.run_file(ROOT / "does-not-exist.txt")


if __name__ == "__main__":
    unittest.main()
