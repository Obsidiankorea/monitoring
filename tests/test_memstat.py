"""app/memstat — 캐시 크기 재기(관리자 /api/admin/mem)."""
import numpy as np

from app import memstat


def test_deep_counts_numpy_and_nesting():
    a = np.zeros((100, 100))                     # 80000 바이트
    d = {"k": (1, [a, a]), "s": "가" * 1000}
    n = memstat.deep(d)
    assert 80_000 < n < 80_000 + 10_000          # 같은 배열은 한 번만


def test_report_shape():
    r = memstat.report(top=3)
    assert {"rss_mb", "caches", "numpy", "objects"} <= set(r) and len(r["objects"]) == 3
