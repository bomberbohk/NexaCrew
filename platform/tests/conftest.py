"""Test isolation: route every test run to a throwaway SQLite database.

Must run before any test module imports app.db (pytest imports conftest
first), otherwise tests write into the LIVE platform/data/platform.db —
polluting production data and triggering multi-company license enforcement.
"""
import os
import tempfile
import uuid

os.environ.setdefault("NEXACREW_TESTING", "1")
os.environ.setdefault(
    "NEXACREW_DB_PATH",
    os.path.join(tempfile.gettempdir(), f"nexacrew_test_{uuid.uuid4().hex}.db"),
)
