import unittest
from unittest.mock import patch
import sys
import os
# Add project root to path so `scripts.*` can be imported
# The test file lives under tests/, so parent is the pipeline root.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import tokenize

from scripts.validators.ast_validator import ValidationResult, validate_python


class AstValidatorTests(unittest.TestCase):
    def test_valid_python_and_metadata(self) -> None:
        result = validate_python("def add(a, b):\n    return a + b\n")

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_type)
        self.assertEqual(result.function_count, 1)
        self.assertEqual(result.return_count, 1)
        self.assertGreater(result.node_count, 1)

    def test_invalid_syntax_is_structured(self) -> None:
        result = validate_python("def add(a, b)\n    return a + b\n")

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_type, "syntax_error")
        self.assertEqual(result.line_number, 1)
        self.assertIsNotNone(result.column_offset)

    def test_invalid_indentation_is_structured(self) -> None:
        result = validate_python("def add(a, b):\nreturn a + b\n")

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_type, "indentation_error")

    def test_empty_and_whitespace_source(self) -> None:
        for source in ("", " \n\t\n"):
            with self.subTest(source=repr(source)):
                result = validate_python(source)
                self.assertFalse(result.is_valid)
                self.assertEqual(result.error_type, "empty_source")

    def test_comments_are_not_docstrings(self) -> None:
        result = validate_python("# calculate result\nx = 1\n")

        self.assertTrue(result.is_valid)
        self.assertTrue(result.has_comments)
        self.assertEqual(result.comment_count, 1)
        self.assertFalse(result.has_docstrings)
        self.assertGreater(result.comment_ratio, 0.0)

    def test_function_and_class_docstrings(self) -> None:
        source = (
            '"""Module docs."""\n'
            "class Calculator:\n"
            '    """Class docs."""\n'
            "    def add(self, a, b):\n"
            '        """Method docs."""\n'
            "        return a + b\n"
        )
        result = validate_python(source)

        self.assertTrue(result.has_docstrings)
        self.assertEqual(result.docstring_count, 3)
        self.assertEqual(result.class_count, 1)
        self.assertEqual(result.function_count, 1)

    def test_multiple_structures_and_nested_function(self) -> None:
        source = (
            "import os\n"
            "from pathlib import Path\n"
            "def outer():\n"
            "    def inner():\n"
            "        return 1\n"
            "    for value in range(2):\n"
            "        if value:\n"
            "            return inner()\n"
        )
        result = validate_python(source)

        self.assertEqual(result.import_count, 2)
        self.assertEqual(result.function_count, 2)
        self.assertEqual(result.loop_count, 1)
        self.assertEqual(result.conditional_count, 1)
        self.assertEqual(result.return_count, 2)

    def test_unicode_identifiers_and_comments(self) -> None:
        result = validate_python("# привет\nзначение = 1\n")

        self.assertTrue(result.is_valid)
        self.assertTrue(result.has_comments)
        self.assertEqual(result.comment_count, 1)

    def test_tokenize_failure_does_not_invalidate_ast(self) -> None:
        with patch(
            "scripts.validators.ast_validator.tokenize.generate_tokens",
            side_effect=tokenize.TokenError("test failure", (1, 0)),
        ):
            result = validate_python("value = 1\n")

        self.assertTrue(result.is_valid)
        self.assertEqual(result.analysis_error_type, "tokenize_error")
        self.assertEqual(result.comment_count, 0)

    def test_validation_never_executes_source(self) -> None:
        source = "raise RuntimeError('must not execute')\n"

        result = validate_python(source)

        self.assertTrue(result.is_valid)
        self.assertIsInstance(result, ValidationResult)

    def test_malformed_input_does_not_raise(self) -> None:
        result = validate_python("def broken(:\n")

        self.assertFalse(result.is_valid)
        self.assertIn(result.error_type, {"syntax_error", "indentation_error"})


if __name__ == "__main__":
    unittest.main()
