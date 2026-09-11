"""Fenced-code extraction keeps copy payloads separate from render-only markers."""

import unittest

from qgis_ai_copilot.code_rendering import protect_fenced_code


class FencedCodeTests(unittest.TestCase):
    def test_fenced_code_keeps_exact_copy_payload(self):
        code = "\t\"name\" = 'a & b'  \n\nnext_line"
        rendered, blocks = protect_fenced_code("Before\n\n```qgis\n" + code + "\n```\n\nAfter")
        self.assertEqual(list(blocks.values()), [("qgis", code)])
        self.assertNotIn(code, rendered)
        self.assertIn("Before", rendered)
        self.assertIn("After", rendered)

    def test_adjacent_same_language_blocks_are_not_merged(self):
        _, blocks = protect_fenced_code("```qgis\nA\n```\n```qgis\nB\n```")
        self.assertEqual(list(blocks.values()), [("qgis", "A"), ("qgis", "B")])

    def test_tilde_fence_keeps_literal_backticks(self):
        code = "```text\nnot another block\n```"
        _, blocks = protect_fenced_code("~~~~text\n" + code + "\n~~~~")
        self.assertEqual(list(blocks.values()), [("text", code)])

    def test_inline_unfinished_and_quoted_fences_keep_qt_fallback(self):
        for source in ("Use `x` here", "```qgis\nunfinished", "> ```qgis\n> x\n> ```"):
            self.assertEqual(protect_fenced_code(source), (source, {}))

    def test_indented_and_list_nested_fences_use_native_qt_structure(self):
        for source in ("  ```python\n    print(1)\n  ```", '- Steps:\n  ```qgis\n  "field" = 1\n  ```\n- Continue\n'):
            self.assertEqual(protect_fenced_code(source), (source, {}))

    def test_crlf_and_blank_lines_are_not_silently_reformatted(self):
        _, blocks = protect_fenced_code("```qgis\r\nA\r\n\r\nB\r\n```")
        self.assertEqual(list(blocks.values()), [("qgis", "A\r\n\r\nB")])


if __name__ == "__main__":
    unittest.main()
