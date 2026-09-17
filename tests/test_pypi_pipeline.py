
import os
import unittest
import tempfile
import tarfile
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "pythia-data-pipeline"))

from scripts.scrapers.pypi import analyze_package

class TestAnalyzePackage(unittest.TestCase):
    def test_migrations_not_generated(self):
        """Test that a package containing a migrations directory does not cause analysis error and files are not classified as generated."""
        # Create a minimal tar.gz with a migrations directory containing a .py file
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tf:
            # add a simple .py file at root
            src = b"def foo():\n    pass\n"
            info = tarfile.TarInfo(name="foo.py")
            info.size = len(src)
            tf.addfile(info, io.BytesIO(src))
            # add a migrations directory with a .py file
            src2 = b"def migrate():\n    pass\n"
            info2 = tarfile.TarInfo(name="migrations/001_initial.py")
            info2.size = len(src2)
            tf.addfile(info2, io.BytesIO(src2))
        buf.seek(0)
        # write to a temporary file
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp:
            tmp.write(buf.getvalue())
            tmp_path = Path(tmp.name)
        try:
            result = analyze_package(tmp_path, "test_package")
            # Should not raise exception
            # generated_or_vendor_count should be 0 (migrations not classified as generated)
            self.assertEqual(result["generated_or_vendor_count"], 0)
            # Should have 2 python files (foo.py and migrations/001_initial.py)
            self.assertEqual(result["python_files"], 2)
        finally:
            os.unlink(tmp_path)

if __name__ == '__main__':
    unittest.main()
