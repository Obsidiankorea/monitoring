import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def store(tmp_path, monkeypatch):
    """격자 프레임을 임시 폴더에 쓴다 — 진짜 data/cache/grid 를 건드리지 않게."""
    from app import gridstore
    monkeypatch.setattr(gridstore, "ROOT", tmp_path / "grid")
    return gridstore
