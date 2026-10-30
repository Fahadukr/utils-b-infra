import unittest
from unittest.mock import patch

from utils_b_infra.generic import retry_with_timeout


class RetryPredicateTest(unittest.TestCase):
    @patch("utils_b_infra.generic.time.sleep")
    def test_existing_callers_without_predicate_still_retry(self, sleep):
        calls = []

        @retry_with_timeout(retries=2, initial_delay=0)
        def operation():
            calls.append(True)
            if len(calls) == 1:
                raise ValueError("temporary")
            return "recovered"

        self.assertEqual(operation(), "recovered")
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(0)

    @patch("utils_b_infra.generic.time.sleep")
    def test_predicate_preserves_original_exception(self, sleep):
        error = ValueError("permanent")

        @retry_with_timeout(retry_if=lambda exc: False)
        def operation():
            raise error

        with self.assertRaises(ValueError) as caught:
            operation()
        self.assertIs(caught.exception, error)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
