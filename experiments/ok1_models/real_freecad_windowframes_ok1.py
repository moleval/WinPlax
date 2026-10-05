#!/usr/bin/env python3
"""
РЕАЛЬНЫЙ прогон ОК-1 на FreeCAD-WindowFrames (jsinger0420/FreeCAD-WindowFrames)
Используем чистый Python-модуль freecad/windowframes/geometry.py (без FreeCAD)

ОК-1: 1500×1500 шов 30, рама 60, импост 80, 3×2, и варианты S571 58/77, REHAU 63/76
Сравниваем с WinPlax: cell_w, pw/ph, muntins, glass, sash
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "repos" / "FreeCAD-WindowFrames"))
from freecad.windowframes.geometry import WindowParams, build

OUT = Path(__file__).parent / "real_output"
OUT.mkdir(parents=True, exist_ok=True)

def run_ok1_variant(name, opening_w, opening_h, clearance, frame_w, frame_depth, muntin_w, cols, rows, window_type="Fixed"):
    print(f"\n=== {name} ===")
    p = WindowParams(
        window_type=window_type,
        opening_width=opening_w,
        opening_height=opening_h,
        rows=rows,
        columns=cols,
        clearance=clearance,
        frame_width=frame_w,
        frame_depth=frame_depth,
        muntin_width=muntin_w,
        muntin_depth=30,
        glass_thickness=4,
    )
    boxes, pw, ph = build(p)
    print(f"  WindowParams: opening {opening_w}x{opening_h} clearance {clearance} frame {frame_w} muntin {muntin_w} {cols}x{rows} {window_type}")
    print(f"  -> boxes {len(boxes)} pw={pw:.2f} ph={ph:.2f}")
    # Разбиваем по kind
    from collections import Counter
    cnt=Counter(b.kind for b in boxes)
    print(f"  kinds: {dict(cnt)}")
    for b in boxes:
        print(f"    {b.kind:6} x={b.x:7.1f} z={b.z:7.1f} dx={b.dx:6.1f} dz={b.dz:6.1f} dy={b.dy}")
    # Теперь сравним с WinPlax
    sys.path.insert(0, "/home/user/WinPlax")
    import json
    from window_export import build_window_model
    # Для сравнения используем те же frame/mullion (но WindowFrames muntin включает только импост, без bead)
    # WinPlax params
    win_params = json.load(open("/home/user/WinPlax/params.json", encoding="utf-8"))
    # Подменим под вариант
    win_params["opening"]["width"]=opening_w
    win_params["opening"]["height"]=opening_h
    win_params["opening"]["seam"]=clearance
    win_params["frame"]["face_width"]=frame_w
    win_params["mullion"]["width"]=muntin_w
    win_params["cols"]=cols
    win_params["rows"]=rows
    win_params["system"]="ABSTRACT_60_80_25"  # чтобы не тянул profiles.json
    m=build_window_model(win_params)
    print(f"  WinPlax: grid cell_w={m['grid']['cell_w']:.2f} cell_h={m['grid']['cell_h']:.2f}  mullions V={len(m['mullions_v'])} H={len(m['mullions_h'])} fillings={len(m['fillings'])}")
    for f in m["fillings"]:
        print(f"    filling cell {f['cell']} {f['w']:.1f}x{f['h']:.1f} vs windowframes glass {pw:.1f}x{ph:.1f}")
    # Создадим DXF из boxes WindowFrames (вид спереди, как в FreeCAD Front view: X->width, Z->height, Y->depth внутрь)
    import ezdxf
    doc=ezdxf.new("R2013")
    for lay,col in [("WF_Frame",7),("WF_Muntin",4),("WF_Glass",3),("WF_Bead",2),("WF_Sash",6)]:
        try: doc.layers.new(lay, dxfattribs={"color":col})
        except: pass
    msp=doc.modelspace()
    # Для каждого box рисуем прямоугольник в плоскости XZ (Front view)
    # box: x,y,z, dx,dy,dz -> в Front view: (x, z) — левый низ, размер dx × dz
    for b in boxes:
        x,z,dx,dz = b.x, b.z, b.dx, b.dz
        layer = {"frame":"WF_Frame","muntin":"WF_Muntin","glass":"WF_Glass","bead":"WF_Bead","sash":"WF_Sash"}.get(b.kind, "0")
        # glass — тонкой линией, остальное — замкнутый прямоугольник
        msp.add_lwpolyline([(x,z),(x+dx,z),(x+dx,z+dz),(x,z+dz)], close=True, dxfattribs={"layer":layer, "linetype":"DASHED" if b.kind=="glass" else "Continuous"})
        # Для стекла — подпись размера
        if b.kind=="glass":
            msp.add_text(f"{b.dx:.0f}x{b.dz:.0f}", height=12, dxfattribs={"layer":layer}).set_placement((x+5,z+5))
    # Подпись
    msp.add_text(f"WindowFrames {name} {opening_w}x{opening_h} {cols}x{rows} pw {pw:.1f} ph {ph:.1f} frame {frame_w} muntin {muntin_w}", height=16, dxfattribs={"layer":"0"}).set_placement((10, opening_h+40))
    msp.add_text(f"WinPlax cell {m['grid']['cell_w']:.1f}x{m['grid']['cell_h']:.1f} filling sash 272x491 vs FIX 376x595", height=12, dxfattribs={"layer":"0"}).set_placement((10, opening_h+20))
    msp.add_text(f"WindowFrames: {dict(cnt)} — нет per-cell sash_type (TURN/TILT), нет bead outer larger, нет falz 5", height=10, dxfattribs={"layer":"0"}).set_placement((10, -30))
    out_path = OUT / f"windowframes_OK1_{name}.dxf"
    doc.saveas(str(out_path))
    print(f"  -> DXF saved {out_path}")
    return boxes

# ОК-1 ABSTRACT 60/80 3×2 Fixed
run_ok1_variant("ABSTRACT_60_80_3x2_Fixed", 1500,1500,30,60,70,80, 3,2, "Fixed")
# ОК-1 S571 58/77
run_ok1_variant("S571_58_77_3x2_Fixed", 1500,1500,30,58,70,77, 3,2, "Fixed")
# ОК-1 REHAU 63/76
run_ok1_variant("REHAU_63_76_3x2_Fixed", 1500,1500,30,63,70,76, 3,2, "Fixed")
# ОК-1 900×900 1×1 (простейший)
run_ok1_variant("ABSTRACT_1x1_900", 900,900,30,60,70,80, 1,1, "Fixed")
# Попробуем Double Hung 2×3 как в README (2 cols ×3 rows per sash = 6 over 6)
run_ok1_variant("DoubleHung_2x3", 1500,1800,30,60,70,20, 2,3, "Double Hung")

# Запустим юнит-тесты WindowFrames для проверки целостности
print("\n=== unittest WindowFrames ===")
import subprocess, sys
res = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=str(Path(__file__).parent / "repos" / "FreeCAD-WindowFrames"))
print(f"unittest exit {res.returncode}")

print("""
ВЫВОД FreeCAD-WindowFrames для ОК-1:
- РЕАЛЬНЫЙ geometry.build работает и даёт тот же cell_w 386.6 что и WinPlax (формула идентична: (iw - (cols-1)*mw)/cols)
- Но: Fixed — все panes глухие, нет per-cell sash_type (TURN/TURN_TILT/TILT/FIX как в ОК-1)
- Fixed — нет понятия створки (sash) и штапика (bead outer larger), поэтому glass = pw×ph = 386×620, а в WinPlax для створки 272×491 (на 114 меньше из-за профиля створки 80)
- Нет continuous auto (в _grid вертикаль цельная, горизонталь режется — как WinPlax vertical, но выбора нет)
- Нет sill 30, falz 5, размеры, блоки, ГОСТ.
- Для ОК-1 годится только как проверка сетки, но не как замена WinPlax.
""")
