"""예보 격자 표(gyeongnam_grids.json)에 빠진 읍면동을 채운다 — 읍면동 안쪽 점이 놓인 5km 칸을 준다(같은 칸을 여러 읍면동이 함께 쓴다)."""
import json, sys, collections
import numpy as np
G = json.load(open("data/geo/grids.json", encoding="utf-8"))
P = "data/gyeongnam_grids.json"
S = json.load(open(P, encoding="utf-8"))
a = G["dfs_to_hr"]
M = np.array([[a["col"][0], a["col"][1]], [a["row"][0], a["row"][1]]]); c0 = np.array([a["col"][2], a["row"][2]])
def cell(c):
    x, y = np.linalg.solve(M, np.array(c) - c0)
    return [int(round(x)) + 1, int(round(y)) + 1]
have = {sg: {it["emd"]: it["xy"] for it in its} for sg, its in S["sigun_grids"].items()}
ok = bad = 0; add = collections.defaultdict(list)
for e in G["emd"]:
    xy = cell(e["c"]); cur = have.get(e["sigun"], {}).get(e["name"])
    if cur:
        if max(abs(cur[0] - xy[0]), abs(cur[1] - xy[1])) <= 1: ok += 1
        else: bad += 1; print("어긋남", e["sigun"], e["name"], cur, xy)
    else:
        add[e["sigun"]].append({"xy": xy, "emd": e["name"]})
print("기존과 한 칸 안", ok, "어긋남", bad, "빠진 읍면동", sum(map(len, add.values())), {k: [x["emd"] for x in v] for k, v in add.items()})
if "--write" in sys.argv:
    for sg, its in add.items():
        S["sigun_grids"].setdefault(sg, []).extend(its)
    json.dump(S, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
