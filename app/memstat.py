"""메모리 어디에 쓰나 — 관리자 /api/admin/mem. 모듈에 붙은 캐시마다 개수 · 대강 크기(numpy 는 nbytes), 객체 종류별 개수, RSS.

크기는 따라가며 더한 값이라 대강이다(같은 객체를 여러 캐시가 쥐면 캐시마다 센다 — '이 캐시를 비우면 풀릴 수 있는 양'의 윗값).
"""
import gc
import sys
from collections import Counter

# (모듈, 이름) — 한도가 있어도 하나가 큰 것 · 한도 없이 열쇠가 느는 것
CACHES = (
    ("app.judge", "_C"), ("app.judge", "_BC"), ("app.judge", "_BL"), ("app.judge", "SEEN"), ("app.main", "_JZ"),
    ("app.ai", "_GET"), ("app.ai", "_LK"), ("app.aireport", "_TTL"), ("app.bivar", "_CACHE"),
    ("app.gridview", "_DAYC"), ("app.gridview", "_AWS_CACHE"), ("app.gridview", "_ACC_CACHE"), ("app.gridview", "_SUM_CACHE"),
    ("app.gridview", "_WIN_CACHE"), ("app.gridview", "_ANTE_CACHE"), ("app.gridview", "_STAT"),
    ("app.river", "_HIST"), ("app.aiwatch", "_GAP"), ("app.collectors.qpf", "_legend_cache"), ("app.auth", "_SEEN"),
)
LRU = (("app.gridcase", "obs"), ("app.gridcase", "acc"), ("app.gridview", "_synth"), ("app.aireport", "page"))


def deep(o, seen=None, limit=3_000_000) -> int:
    """따라가며 더한 바이트 — numpy 는 nbytes, 컨테이너는 안까지. 객체 limit 개에서 멈춘다(느려지지 않게)."""
    seen = set() if seen is None else seen
    total, stack = 0, [o]
    while stack and len(seen) < limit:
        x = stack.pop()
        if id(x) in seen:
            continue
        seen.add(id(x))
        nb = getattr(x, "nbytes", None)
        if isinstance(nb, int) and type(x).__module__ == "numpy":
            total += nb + 112
            continue
        total += sys.getsizeof(x, 0)
        if isinstance(x, dict):
            stack.extend(x.keys())
            stack.extend(x.values())
        elif isinstance(x, (list, tuple, set, frozenset)):
            stack.extend(x)
        elif isinstance(x, (str, bytes, bytearray, int, float, bool)) or x is None:
            pass
        elif hasattr(x, "__dict__") and not isinstance(x, type):
            stack.append(vars(x))
    return total


def rss_mb() -> float | None:
    try:
        with open("/proc/self/status") as f:
            return next(int(ln.split()[1]) for ln in f if ln.startswith("VmRSS")) / 1024
    except (OSError, StopIteration):
        return None


def trim() -> bool:
    """glibc 가 쥔 빈 힙을 OS 에 돌려준다(malloc_trim). glibc 가 아니면 False."""
    try:
        import ctypes
        return bool(ctypes.CDLL("libc.so.6").malloc_trim(0))
    except (OSError, AttributeError):
        return False


def report(top: int = 15, do_trim: bool = False) -> dict:
    before = rss_mb()
    if do_trim:
        gc.collect()
        trim()
    caches = []
    for mod, name in CACHES:
        m = sys.modules.get(mod)
        c = getattr(m, name, None) if m else None
        if c is None:
            continue
        caches.append({"name": f"{mod}.{name}", "n": len(c), "mb": round(deep(c) / 2**20, 1)})
    for mod, name in LRU:
        m = sys.modules.get(mod)
        f = getattr(m, name, None) if m else None
        if f is None or not hasattr(f, "cache_info"):
            continue
        i = f.cache_info()
        caches.append({"name": f"{mod}.{name}()", "n": i.currsize, "max": i.maxsize})
    caches.sort(key=lambda x: -x.get("mb", 0))
    gc.collect()
    kinds = Counter(type(o).__name__ for o in gc.get_objects())
    arrays = [o for o in gc.get_objects() if type(o).__module__ == "numpy" and hasattr(o, "nbytes") and getattr(o, "base", None) is None]
    big = sorted(arrays, key=lambda a: -a.nbytes)[:top]
    out = {"rss_mb": rss_mb(), "caches": caches,
            "numpy": {"n": len(arrays), "mb": round(sum(a.nbytes for a in arrays) / 2**20, 1),
                      "big": [{"shape": list(a.shape), "dtype": str(a.dtype), "mb": round(a.nbytes / 2**20, 1)} for a in big]},
            "objects": kinds.most_common(top)}
    if do_trim:
        out["rss_before_trim_mb"] = before
    return out
