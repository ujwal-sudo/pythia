import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.scrapers import python_docs


FIXTURE_HTML = """
<html>
  <head><title>Fixture Python Docs</title></head>
  <body>
    <h1>Tutorial</h1>
    <p>Useful documented function.</p>
    <div class="highlight-python notranslate"><pre>
def documented_add(a, b):
    \"\"\"Add two numbers.\"\"\"
    # return the result
    return a + b
</pre></div>
    <h2>Console</h2>
    <p>A doctest example.</p>
    <div class="highlight-pycon notranslate"><pre>
>>> def documented_square(value):
...     \"\"\"Square a value.\"\"\"
...     # keep metadata
...     return value * value
>>> documented_square(3)
9
</pre></div>
    <h2>Shell</h2>
    <div class="highlight-bash notranslate"><pre>python -m pip install sample</pre></div>
    <h2>Broken</h2>
    <div class="highlight-python notranslate"><pre>def broken(:</pre></div>
  </body>
</html>
"""


class PythonDocsScraperTests(unittest.TestCase):
    def test_python_code_block_extraction_and_non_python_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docs_dir = Path(temp_dir)
            (docs_dir / "tutorial.html").write_text(FIXTURE_HTML, encoding="utf-8")

            blocks = list(python_docs.iter_python_doc_blocks(docs_dir, "https://docs.python.org/3.14/"))

        self.assertEqual(len(blocks), 3)
        self.assertTrue(any("documented_add" in block.code for block in blocks))
        self.assertFalse(any("pip install" in block.code for block in blocks))

    def test_doctest_detection_strips_prompts(self) -> None:
        block = python_docs.strip_doctest_prompts(">>> value = 1\n>>> value\n1\n")

        self.assertEqual(block, "value = 1\nvalue")

    def test_processing_integrates_ast_validation_and_handles_malformed_examples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docs_dir = Path(temp_dir) / "python-3.14-docs-html"
            docs_dir.mkdir()
            (docs_dir / "tutorial.html").write_text(FIXTURE_HTML, encoding="utf-8")
            output = Path(temp_dir) / "out.jsonl"
            manifest = Path(temp_dir) / "manifest.json"
            report = Path(temp_dir) / "report.json"

            result = python_docs.process_documentation(
                raw_path=docs_dir,
                output_path=output,
                manifest_path=manifest,
                report_path=report,
                min_tokens=1,
                min_comment_ratio=0.0,
            )

            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            report_data = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(result["stats"]["python_candidates"], 3)
        self.assertEqual(result["stats"]["syntax_invalid"], 1)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(record["syntax_valid"] for record in records))
        self.assertTrue(all(record["kg_validation_status"] == "pending" for record in records))
        self.assertEqual(manifest_data["retained_count"], 2)
        self.assertEqual(report_data["retained"], 2)

    def test_comment_docstring_metadata_and_pep8_measurement(self) -> None:
        code = 'def sample():\n    """Docs."""\n    # comment\n    return 1\n'
        validation = python_docs.validate_python(code)

        self.assertEqual(validation.comment_count, 1)
        self.assertEqual(validation.docstring_count, 1)
        self.assertGreater(validation.comment_ratio, 0.0)
        self.assertEqual(python_docs.measure_pep8_violations(code), 0)

    def test_exact_deduplication(self) -> None:
        duplicated_html = """
        <div class="highlight-python"><pre>
def repeated():
    \"\"\"Docs.\"\"\"
    # comment
    return 1
</pre></div>
        <div class="highlight-python"><pre>
def repeated():
    \"\"\"Docs.\"\"\"
    # comment
    return 1
</pre></div>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            docs_dir = Path(temp_dir)
            (docs_dir / "library.html").write_text(duplicated_html, encoding="utf-8")
            result = python_docs.process_documentation(
                raw_path=docs_dir,
                output_path=Path(temp_dir) / "out.jsonl",
                manifest_path=Path(temp_dir) / "manifest.json",
                report_path=Path(temp_dir) / "report.json",
                min_tokens=1,
                min_comment_ratio=0.0,
            )

        self.assertEqual(result["stats"]["exact_duplicates"], 1)
        self.assertEqual(result["stats"]["retained"], 1)

    def test_jsonl_serialization_and_manifest_generation_from_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "python-3.14-docs-html.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("python-3.14-docs-html/tutorial/index.html", FIXTURE_HTML)
            output = Path(temp_dir) / "out.jsonl"
            manifest = Path(temp_dir) / "manifest.json"

            python_docs.process_documentation(
                raw_path=archive_path,
                output_path=output,
                manifest_path=manifest,
                report_path=Path(temp_dir) / "report.json",
                min_tokens=1,
                min_comment_ratio=0.0,
            )

            first_record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))

        self.assertIn("code", first_record)
        self.assertIn("source_url", first_record)
        self.assertEqual(first_record["documentation_version"], "3.14")
        self.assertEqual(manifest_data["source"], "python_docs")
        self.assertEqual(manifest_data["documentation_version"], "3.14")

    def test_ast_validation_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docs_dir = Path(temp_dir)
            (docs_dir / "tutorial.html").write_text(FIXTURE_HTML, encoding="utf-8")
            with patch("scripts.scrapers.python_docs.validate_python", wraps=python_docs.validate_python) as mocked:
                python_docs.process_documentation(
                    raw_path=docs_dir,
                    output_path=Path(temp_dir) / "out.jsonl",
                    manifest_path=Path(temp_dir) / "manifest.json",
                    report_path=Path(temp_dir) / "report.json",
                    min_tokens=1,
                    min_comment_ratio=0.0,
                )

        self.assertGreaterEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
