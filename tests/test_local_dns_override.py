import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from novel_writer.application import custom_protocols


class LocalDnsOverrideTests(unittest.TestCase):
    def test_only_configured_hostname_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'dns.json'
            config.write_text(json.dumps({'api.odys.work':'64.204.27.16'}),encoding='utf-8')
            with patch.object(custom_protocols,'LOCAL_DNS_OVERRIDES',config):
                self.assertEqual(custom_protocols._resolution_host('api.odys.work'),'64.204.27.16')
                self.assertEqual(custom_protocols._resolution_host('example.com'),'example.com')

    def test_private_override_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'dns.json'
            config.write_text(json.dumps({'api.odys.work':'127.0.0.1'}),encoding='utf-8')
            with patch.object(custom_protocols,'LOCAL_DNS_OVERRIDES',config):
                with self.assertRaises(ValueError):custom_protocols._resolution_host('api.odys.work')
