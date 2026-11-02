"""Run every contract against the fixed pipeline (must pass) and the naive baseline (must fail)."""
import unittest

import helpers  # noqa: F401  (sets sys.path)
from contracts import CONTRACTS
from docmatch import DocMatch, NaiveDocMatch


class FixedPassesContracts(unittest.TestCase):
    pass


class NaiveFailsContracts(unittest.TestCase):
    pass


def _fixed(fn):
    def t(self):
        fn(DocMatch)
    return t


def _naive(fn):
    def t(self):
        try:
            fn(NaiveDocMatch)
        except AssertionError:
            return  # only a real assertion failure counts: a crash would not show the contract is violated
        self.fail("naive baseline unexpectedly satisfied this contract")
    return t


for _name, _fn in CONTRACTS:
    setattr(FixedPassesContracts, f"test_fixed_{_name}", _fixed(_fn))
    setattr(NaiveFailsContracts, f"test_naive_fails_{_name}", _naive(_fn))


class ContractInventory(unittest.TestCase):
    def test_at_least_fifteen_contracts(self):
        self.assertGreaterEqual(len(CONTRACTS), 15)


if __name__ == "__main__":
    unittest.main()
