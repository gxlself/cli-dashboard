import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

import claude_statusline as statusline


class StatuslineTests(unittest.TestCase):
    def run_statusline(self, payload):
        output = io.StringIO()
        with patch.object(statusline.sys, "stdin", io.StringIO(json.dumps(payload))), \
                patch.object(statusline.urllib.request, "urlopen") as urlopen, \
                redirect_stdout(output):
            urlopen.return_value.read.return_value = b""
            statusline.main()
        request = urlopen.call_args.args[0]
        return output.getvalue().strip(), json.loads(request.data)

    def test_displays_five_hour_and_weekly_limits_without_context(self):
        line, event = self.run_statusline({
            "session_id": "session-1",
            "model": {"display_name": "Sonnet"},
            "rate_limits": {
                "five_hour": {"used_percentage": 29},
                "seven_day": {"used_percentage": 61},
            },
            "context_window": {"used_percentage": 53},
        })
        self.assertEqual(line, "Sonnet  5h 29%  week 61%")
        self.assertEqual(event["usage"], "5h 29%  week 61%")
        self.assertNotIn("ctx", event["usage"])

    def test_accepts_used_percent_fallback(self):
        line, event = self.run_statusline({
            "rate_limits": {
                "five_hour": {"used_percent": 12.4},
                "seven_day": {"used_percent": "7.6"},
            },
        })
        self.assertEqual(line, "5h 12%  week 8%")
        self.assertEqual(event["usage"], "5h 12%  week 8%")


if __name__ == "__main__":
    unittest.main()
