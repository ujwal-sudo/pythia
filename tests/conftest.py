import sys
import os
# Ensure the project root (parent of 'scripts') is on sys.path for all tests
_project_root = os.path.join(os.path.dirname(__file__), '..')
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)