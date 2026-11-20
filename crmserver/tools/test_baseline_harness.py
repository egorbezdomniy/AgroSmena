"""Small safety/statistics tests; these do not substitute for HTTP/PG measurements."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from baseline_server import Profile
from scaling_baseline import Experiment, summarize


class HarnessTests(unittest.TestCase):
    def test_existing_output_refused_before_any_process(self):
        folder = Path(__file__).resolve().parent
        args = SimpleNamespace(output=folder, postgres_bin=folder, max_seconds=120)
        with patch('subprocess.run') as run, patch('subprocess.Popen') as popen:
            with self.assertRaises(FileExistsError):
                Experiment(args)
        run.assert_not_called()
        popen.assert_not_called()

    def test_percentile_requires_twenty_successes_and_errors_remain_visible(self):
        five = [{'status': 200, 'client_ms': i} for i in range(5)]
        self.assertIsNone(summarize(five)['client_ms']['p95'])
        rows = [{'status': 200, 'client_ms': i} for i in range(1, 21)]
        rows.append({'status': 0, 'client_ms': 45000})
        result = summarize(rows)
        self.assertEqual(result['n'], 21)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['client_ms']['median'], 10.5)
        self.assertEqual(result['client_ms']['p95'], 19)

    def test_profile_limit_never_changes_result_or_suppresses_business_exception(self):
        profile = Profile()
        profile.groups = {str(i): {'count': 0, 'duration_ms': 0} for i in range(150)}
        execute = Mock(return_value=42)
        self.assertEqual(profile(execute, 'SELECT new_template', [], False, {}), 42)
        execute.assert_called_once()
        execute.side_effect = ValueError('synthetic failure')
        with self.assertRaises(ValueError):
            profile(execute, 'SELECT another_template', [], False, {})


if __name__ == '__main__':
    unittest.main()
