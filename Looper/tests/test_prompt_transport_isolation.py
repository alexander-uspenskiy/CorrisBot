import unittest
from pathlib import Path
from Looper.route_contract_utils import remove_markdown_block, extract_routing_contract_fields

class TestPromptTransportIsolation(unittest.TestCase):
    def test_remove_markdown_block_basic(self):
        text = "Hello\nRouting-Contract:\n- Version: 1\n- AppRoot: C:\\test\n\nMore text"
        expected = "Hello\nMore text"
        self.assertEqual(remove_markdown_block(text, "Routing-Contract:"), expected)

    def test_remove_markdown_block_multiple_sections(self):
        text = "Hello\nRouting-Contract:\n- Version: 1\n\nSection 2:\n- Key: Val\n\nMore text"
        expected = "Hello\nSection 2:\n- Key: Val\n\nMore text"
        self.assertEqual(remove_markdown_block(text, "Routing-Contract:"), expected)

    def test_remove_markdown_block_in_code_fence(self):
        text = "Hello\n```\nRouting-Contract:\n- Version: 1\n```\nMore text"
        self.assertEqual(remove_markdown_block(text, "Routing-Contract:"), text)

    def test_remove_markdown_block_in_quote(self):
        text = "Hello\n> Routing-Contract:\n> - Version: 1\nMore text"
        self.assertEqual(remove_markdown_block(text, "Routing-Contract:"), text)

    def test_remove_markdown_block_not_found(self):
        text = "Hello\nMore text"
        self.assertEqual(remove_markdown_block(text, "Routing-Contract:"), text)

    def test_remove_markdown_block_malformed(self):
        # Header is there but no items -> not treated as a valid block to remove
        text = "Speaking of Routing-Contract:\nWe should discuss it."
        self.assertEqual(remove_markdown_block(text, "Routing-Contract:"), text)

    def test_extract_routing_contract_malformed_fails(self):
        # Fail-closed guard for operational envelope
        text = "Routing-Contract:\n- Version: 1\n- MissingFields: true\n\nRoute-Meta:\n"
        with self.assertRaises(RuntimeError) as cm:
            extract_routing_contract_fields(text)
        self.assertIn("Routing-Contract missing required fields", str(cm.exception))

if __name__ == '__main__':
    unittest.main()
