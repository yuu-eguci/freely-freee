"""config の環境変数読み取りを検証するテストです。"""

import os
import unittest
from unittest.mock import patch

from app.config import load_config
from app.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_load_config_reads_target_company_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FREEE_CLIENT_ID": "client-id",
                "FREEE_CLIENT_SECRET": "client-secret",
                "FREEE_REDIRECT_URI": "urn:ietf:wg:oauth:2.0:oob",
                "TARGET_COMPANY_ID": "123",
            },
            clear=True,
        ):
            config = load_config()

        self.assertEqual(123, config.target_company_id)

    def test_load_config_rejects_non_integer_target_company_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FREEE_CLIENT_ID": "client-id",
                "FREEE_CLIENT_SECRET": "client-secret",
                "FREEE_REDIRECT_URI": "urn:ietf:wg:oauth:2.0:oob",
                "TARGET_COMPANY_ID": "abc",
            },
            clear=True,
        ), self.assertRaises(ConfigError) as exc:
            load_config()

        self.assertEqual(
            "Environment variable TARGET_COMPANY_ID is not a valid integer: 'abc'",
            str(exc.exception),
        )


if __name__ == "__main__":
    unittest.main()
