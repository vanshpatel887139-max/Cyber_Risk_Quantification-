"""Shared test fixtures. Every test runs against a throwaway SQLite file."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="crp-tests-")
os.environ["CRP_DATA_DIR"] = _TMP
os.environ["CRP_LLM_ENABLED"] = "0"

from app import ai, config, db, demo_data, ingest, optimize, reports, risk  # noqa: E402

_SEEDED: dict[str, object] = {}
_TMP_DB = Path(config.DB_PATH)


def _bootstrap() -> None:
    db.init_db()
    with db.connect() as conn:
        demo_data.seed(conn)
        _SEEDED["model"] = risk.load_model(conn)
    _TMP_DB.replace(_TMP_DB.with_suffix(".template"))


_bootstrap()


def seed() -> dict:
    return _SEEDED["model"]


def fresh_connection():
    return db.connect()


class EngineTestCase(unittest.TestCase):
    """Base class giving each test its own copy of the seeded database.

    Copying the file per test keeps tests that deliberately corrupt data (an
    unknown asset id, a decommissioned asset) from leaking into the next test.
    """

    def setUp(self) -> None:
        import shutil
        from app import config as app_config
        self._template = _TMP_DB.with_suffix(".template")
        self._target = _TMP_DB.with_suffix(f".{self.id().replace('.', '_')}.db")
        shutil.copyfile(self._template, self._target)
        self._original_db_path = app_config.DB_PATH
        app_config.DB_PATH = self._target
        self._ctx = db.connect()
        self.conn = self._ctx.__enter__()
        self.model = risk.load_model(self.conn)

    def tearDown(self) -> None:
        from app import config as app_config
        self._ctx.__exit__(None, None, None)
        app_config.DB_PATH = self._original_db_path
        self._target.unlink(missing_ok=True)

    def assess(self, **kwargs):
        return risk.assess(self.model, **kwargs)

    def reload_model(self):
        self.model = risk.load_model(self.conn)
        return self.model
