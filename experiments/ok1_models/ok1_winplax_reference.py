#!/usr/bin/env python3
"""
Референс WinPlax: строит OK1 через build_window_model и экспортирует DXF для сравнения.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from window_export import build_window_model, export_to_dxf

params = json.load(open(Path(__file__).resolve().parents[2]/"params.json", encoding="utf-8"))

# OUTSIDE и INSIDE
for view in ["OUTSIDE","INSIDE"]:
    p=dict(params)
    # deep copy
    import copy
    p=copy.deepcopy(params)
    p["view"]=view
    m=build_window_model(p)
    out=Path(__file__).parent/f"output/OK1_WINPLAX_{view}.dxf"
    export_to_dxf(m, out)
    print(f"WinPlax {view}: {out} primitives={m['primitives_count']} frame={m['frame_outer'][:1]} bead={len(m['bead_polys'])} fillings={len(m['fillings'])}")
    # print cell rects
    for c in m["cells"]:
        print(f"  cell r{c['row']}c{c['col']} {c['x1']:.1f},{c['y1']:.1f}-{c['x2']:.1f},{c['y2']:.1f} {c['sash_type']}")

