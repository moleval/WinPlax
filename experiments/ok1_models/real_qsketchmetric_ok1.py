#!/usr/bin/env python3
"""
РЕАЛЬНЫЙ прогон ОК-1 на qsketchmetric (MadScrewdriver/qsketchmetric)

Берём реальный пример из репо: docs/_static/DXF/tutorial.dxf (параметрический с QCAD xdata)
и tutorial_param.dxf — показываем как работает Renderer, затем строим СВОЙ parametric ОК-1
аналогично тому, как делает qsketchmetric, и рендерим его для ОК-1 1500×1500 S571/REHAU.

Вход ОК-1: проём 1500×1500 шов 30 → окно 1440×1440, рама 60/58/63, импост 80/77/76, 3×2
"""
from pathlib import Path
import ezdxf
from ezdxf import units

ROOT = Path(__file__).parent
REPO = ROOT / "repos" / "qsketchmetric"
OUT = ROOT / "real_output"
OUT.mkdir(parents=True, exist_ok=True)

print(f"qsketchmetric repo: {REPO} exists={REPO.exists()}")
# 1. Проверим реальные файлы из репо
for p in [REPO / "docs/_static/DXF/tutorial.dxf", REPO / "docs/_static/DXF/tutorial_param.dxf"]:
    if p.exists():
        d = ezdxf.readfile(str(p))
        print(f"  {p.name}: {len(list(d.modelspace()))} entities, has MTEXT={'MTEXT' in str(list(d.modelspace()))}")
        # Посмотрим xdata
        for e in d.modelspace():
            if e.has_xdata("QCAD"):
                print(f"    {e.dxftype()} layer={e.dxf.layer} xdata={e.get_xdata('QCAD')[:1]}")
                break
        # Посмотрим MTEXT custom
        for e in d.modelspace():
            if e.dxftype() == "MTEXT":
                txt = e.text[:300].replace("\n"," ")
                print(f"    MTEXT: {txt[:200]}")
                break

# 2. Рендерим tutorial пример реальным Renderer (как в README)
from qsketchmetric.renderer import Renderer
from ezdxf import new

for vars_demo, suffix in [ ({"h":50}, "tutorial_h50"), ({"h":100}, "tutorial_h100") ]:
    out_dxf = new()
    out_dxf.units = units.MM
    src = REPO / "docs/_static/DXF/tutorial.dxf"
    if src.exists():
        r = Renderer(src, out_dxf, variables=vars_demo)
        points = r.render()
        out_path = OUT / f"qsketchmetric_tutorial_{suffix}.dxf"
        out_dxf.saveas(str(out_path))
        print(f"  tutorial render {suffix} -> {out_path} points={points} bbox={r.get_bb_dimensions()}")

# 3. Строим PARAMETRIC ОК-1 по методике qsketchmetric (QCAD Professional-style)
# В qsketchmetric параметризация — это проставление XDATA QCAD c:<выражение> каждой LINE
# Переменные объявляются в MTEXT после "----- custom -----" вида "W:1500"
# Мы создадим parametric DXF ОК-1 вручную (без QCAD GUI) — точно так же как это делает SemiAutomaticParameterization
import math
from ezdxf.math import Vec3

def make_ok1_parametric(path: Path, W=1500, H=1500, FW=60, MW=80):
    doc = ezdxf.new("R2013")
    msp = doc.modelspace()
    try:
        doc.appids.new("QCAD")
    except Exception:
        pass
    doc.layers.new("FRAME", dxfattribs={"color":7})
    doc.layers.new("MULLION", dxfattribs={"color":4})
    doc.layers.new("VIRTUAL_LAYER", dxfattribs={"color":40})
    # MTEXT с переменными — как в qsketchmetric docs
    vars_text = (
        "OK-1 3x2 Parametric (qsketchmetric style)\\P"
        "W=opening 1500 H=1500 FW=frame 60 MW=mullion 80\\P"
        "----- custom -----\\P"
        f"W:{W}\\P"
        f"H:{H}\\P"
        f"FW:{FW}\\P"
        f"MW:{MW}\\P"
        "COLS:3\\P"
        "ROWS:2\\P"
    )
    msp.add_mtext(vars_text, dxfattribs={"char_height":10})
    def add_line(p1,p2,expr,layer="FRAME"):
        e=msp.add_line(p1,p2, dxfattribs={"layer":layer})
        e.set_xdata("QCAD", [(1000, f"c:{expr}")])
        return e
    # Внешний прямоугольник проёма
    add_line((0,0),(W,0),"W","FRAME")
    add_line((W,0),(W,H),"H","FRAME")
    add_line((W,H),(0,H),"W","FRAME")
    add_line((0,H),(0,0),"H","FRAME")
    # Внутренний прямоугольник рамы (отступ FW)
    add_line((FW,FW),(W-FW,FW),"W-2*FW","FRAME")
    add_line((W-FW,FW),(W-FW,H-FW),"H-2*FW","FRAME")
    add_line((W-FW,H-FW),(FW,H-FW),"W-2*FW","FRAME")
    add_line((FW,H-FW),(FW,FW),"H-2*FW","FRAME")
    # Митры 45° рамы
    diag="FW*1.414"
    add_line((0,0),(FW,FW),diag,"FRAME")
    add_line((W,0),(W-FW,FW),diag,"FRAME")
    add_line((W,H),(W-FW,H-FW),diag,"FRAME")
    add_line((0,H),(FW,H-FW),diag,"FRAME")
    # Импосты: 2 вертикальных +1 горизонтальный
    # Вертикаль: на x = FW + (W-2*FW -2*MW)/3 + MW/2 ? Упростим: делим равномерно
    # В qsketchmetric положение задаётся координатами точек, а длина — выражением, поэтому точное положение не параметризуется — только длина!
    # Это ограничение: нельзя сдвинуть импост выражением, только растянуть.
    # Демо: ставим импосты в серединах W/3 и 2W/3
    add_line((W/3,FW),(W/3,H-FW),"H-2*FW","MULLION")
    add_line((W/3+MW,FW),(W/3+MW,H-FW),"H-2*FW","MULLION")
    add_line((2*W/3,FW),(2*W/3,H-FW),"H-2*FW","MULLION")
    add_line((2*W/3+MW,FW),(2*W/3+MW,H-FW),"H-2*FW","MULLION")
    add_line((FW,H/2),(W-FW,H/2),"W-2*FW","MULLION")
    add_line((FW,H/2+MW),(W-FW,H/2+MW),"W-2*FW","MULLION")
    # Виртуальные связи для единого графа (иначе Renderer разобьёт)
    v=msp.add_line((0,0),(FW,FW), dxfattribs={"layer":"VIRTUAL_LAYER"})
    v.set_xdata("QCAD", [(1000,"c:c")])
    v2=msp.add_line((W,0),(W-FW,FW), dxfattribs={"layer":"VIRTUAL_LAYER"})
    v2.set_xdata("QCAD", [(1000,"c:c")])
    doc.saveas(str(path))
    print(f"  parametric OK-1 saved {path} entities={len(list(msp))}")

param_path = OUT / "qsketchmetric_OK1_PARAMETRIC.dxf"
make_ok1_parametric(param_path, W=1500, H=1500, FW=60, MW=80)

# 4. Рендерим ОК-1 для 3 систем как в WinPlax profiles.json
for vars_cfg, name in [
    ({"W":1500,"H":1500,"FW":60,"MW":80}, "ABSTRACT_60_80"),
    ({"W":1500,"H":1500,"FW":58,"MW":77}, "S571_58_77"),
    ({"W":1500,"H":1500,"FW":63,"MW":76}, "REHAU_63_76"),
    ({"W":900,"H":900,"FW":60,"MW":80}, "ABSTRACT_900"),
]:
    out = new()
    out.units=units.MM
    try:
        r=Renderer(param_path, out, variables=vars_cfg)
        pts=r.render()
        out_path=OUT / f"qsketchmetric_OK1_{name}.dxf"
        # Подпись
        out.modelspace().add_text(f"qsketchmetric OK1 {name} vars={vars_cfg}", height=20, dxfattribs={"layer":"0"}).set_placement((10,-40))
        out.saveas(str(out_path))
        print(f"  render {name} -> {out_path} bbox={r.get_bb_dimensions()} points={pts}")
    except Exception as e:
        import traceback
        print(f"  render {name} FAILED {e}")
        traceback.print_exc()

print("""
ВЫВОД qsketchmetric для ОК-1:
- Реальный Renderer работает только с LINE/CIRCLE/ARC/POINT + INSERT (LWPOLYLINE через INSERT)
- Длины параметризуются выражением c:W-2*FW, но ПОЛОЖЕНИЕ импостов (x=W/3) — константа, не выражение!
  → При изменении W с 1500 на 900 импост остаётся на x=500 (1/3 от 1500), а должен быть 300 → разъезжается.
- Нет поняти  я continuous auto, bead per-cell, sash, filling falz 5, размеры, блоки.
- Пригоден только для простых деталей (стойка, ригель), но не для окна 3×2.
""")
