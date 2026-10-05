#!/usr/bin/env python3
"""
OK1 через CadQuery / build123d / FreeCAD WindowFrames (3D B-Rep, OCCT)

CadQuery / build123d:
- Pythonic OCCT, B-Rep solids: Workplane().box().faces().workplane().rect().extrude().cut()
- Для ОК-1: экструзия профилей (рама 60×70, импост 80×70, створка 80×70, штапик 20×15) вдоль периметра

FreeCAD WindowFrames:
- Rough opening W×H, panes rows×cols, Fixed / DoubleHung
- geometry.py: box layout — нарезает проём на панели через simple offsets
- scaling.py: масштаб RR 1:22.5..1:220, утолщение <0.3мм, stl_writer.py — экспорт для ЧПУ

Сделаем мок DXF + STEP-заглушка в стиле этих движков:
- Покажем что CadQuery умеет 3D, а WinPlax — 2D DXF фасад
- Сравним box layout vs WinPlax strips_x/strips_y

Если CadQuery/build123d не установлены — делаем ezdxf мок, иначе пробуем реальную сборку.
"""
from pathlib import Path
import math

OUT = Path(__file__).parent / "output"
OUT.mkdir(parents=True, exist_ok=True)

# Проверка наличия
try:
    import cadquery as cq
    HAS_CQ = True
    print(f"CadQuery {cq.__version__} найден")
except Exception as e:
    HAS_CQ = False
    print(f"CadQuery не установлен: {e}")

try:
    import build123d as bd
    HAS_BD = True
    print(f"build123d {bd.__version__ if hasattr(bd,'__version__') else 'found'} найден")
except Exception as e:
    HAS_BD = False
    print(f"build123d не установлен: {e}")

# Мок DXF в стиле CadQuery / FreeCAD
import ezdxf
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json, copy
from window_export import build_window_model

params=json.load(open(Path(__file__).resolve().parents[2]/"params.json", encoding="utf-8"))
m=build_window_model(params)
ow, oh = 1440, 1440
FRAME_W, MULLION_W, BEAD_W = 60, 80, 20
DEPTH = 70  # монтажная глубина из profiles.json

def draw_cadquery_style(path: Path):
    doc = ezdxf.new("R2013")
    for lay,col in [("CQ_Frame",7),("CQ_Mullion",4),("CQ_Sash",6),("CQ_Glass",3),("CQ_Bead",2),("CQ_Dim",1)]:
        try: doc.layers.new(lay, dxfattribs={"color":col})
        except: pass
    msp = doc.modelspace()
    # Вид сверху (план) — как в FreeCAD: рама как экструдированный профиль 60×70
    # На плане покажем профиль рамы как прямоугольник толщиной 60, глубиной 70 (в разрез)
    # Упростим: фасад как в WinPlax, но добавим изометрию-подпись глубины
    # Фасад
    msp.add_lwpolyline(m["frame_outer"], close=True, dxfattribs={"layer":"CQ_Frame"})
    msp.add_lwpolyline(m["frame_inner"], close=True, dxfattribs={"layer":"CQ_Frame"})
    for a,b in m["frame_mitres"]: msp.add_line(a,b, dxfattribs={"layer":"CQ_Frame"})
    for poly in m["mullions_v"]: msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"CQ_Mullion"})
    for poly in m["mullions_h"]: msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"CQ_Mullion"})
    for f in m["fillings"]:
        x1,y1,x2,y2=f["rect"]
        msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True, dxfattribs={"layer":"CQ_Glass"})
        msp.add_text(f["text"], height=10, dxfattribs={"layer":"CQ_Glass"}).set_placement((x1+5,y1+5))
    # Depth indicator — сбоку показать глубину 70
    # Нарисуем профиль рамы в разрезе: 60 (лицо) ×70 (глубина)
    depth_x = ow + 100
    msp.add_lwpolyline([(depth_x,0),(depth_x+FRAME_W,0),(depth_x+FRAME_W,DEPTH),(depth_x,DEPTH)], close=True, dxfattribs={"layer":"CQ_Frame"})
    msp.add_text(f"Рама 60×{DEPTH}", height=10, dxfattribs={"layer":"CQ_Frame"}).set_placement((depth_x, DEPTH+5))
    msp.add_lwpolyline([(depth_x, DEPTH+40),(depth_x+MULLION_W, DEPTH+40),(depth_x+MULLION_W, DEPTH+40+DEPTH),(depth_x, DEPTH+40+DEPTH)], close=True, dxfattribs={"layer":"CQ_Mullion"})
    msp.add_text(f"Импост 80×{DEPTH}", height=10, dxfattribs={"layer":"CQ_Mullion"}).set_placement((depth_x, DEPTH+40+DEPTH+5))
    # Подписи
    msp.add_text(f"ОК-1 CadQuery/build123d style — 3D B-Rep (рама 60×70 экструзия по периметру)", height=16, dxfattribs={"layer":"0"}).set_placement((0, oh+70))
    msp.add_text(f"FreeCAD WindowFrames: Rough opening 1500×1500, panes 3×2, Fixed/DoubleHung — box layout как strips_x/strips_y", height=12, dxfattribs={"layer":"0"}).set_placement((0, oh+50))
    msp.add_text(f"WinPlax: 2D LWPOLYLINE фасад, CadQuery: solid.box(1440,1440,70).cut(inner).union(mullions) → STEP/STL", height=12, dxfattribs={"layer":"0"}).set_placement((0, -40))
    doc.saveas(str(path))
    print(f"CadQuery mock: {path}")

draw_cadquery_style(OUT / "OK1_CadQuery_FreeCAD_mock.dxf")

# Попытка реальной CadQuery сборки (falls back to mock solids description)
if HAS_CQ:
    try:
        import cadquery as cq
        # Рама как 4 коробки (упрощённо без митры 45° — в CadQuery mitre делается через cut углом)
        # Внешняя коробка минус внутренняя = рафа
        frame_outer = cq.Workplane("XY").box(ow, oh, DEPTH, centered=False)
        frame_inner = cq.Workplane("XY").box(ow-2*FRAME_W, oh-2*FRAME_W, DEPTH, centered=False).translate((FRAME_W, FRAME_W, 0))
        frame = frame_outer.cut(frame_inner)
        # Импосты — 2 вертикальных + 1 горизонтальный (continuous vertical)
        # Вертикальные на всю высоту между рамами
        # cell_w = 386.666, используем m["grid"]
        cell_w = m["grid"]["cell_w"]
        cell_h = m["grid"]["cell_h"]
        # Позиции как в WinPlax
        # Первый вертикальный: x = FRAME_W + cell_w = 60+386.666=446.666, ширина 80 → до 526.666, но реально mullions_v x1=476.6?
        # Возьмём из m
        for poly in m["mullions_v"]:
            x1,y1,x2,y2 = poly[0][0], poly[0][1], poly[2][0], poly[2][1]
            w = x2-x1
            h = y2-y1
            mull = cq.Workplane("XY").box(w,h,DEPTH, centered=False).translate((x1,y1,0))
            frame = frame.union(mull)
        for poly in m["mullions_h"]:
            x1,y1,x2,y2 = poly[0][0], poly[0][1], poly[2][0], poly[2][1]
            w = x2-x1
            h = y2-y1
            mull = cq.Workplane("XY").box(w,h,DEPTH, centered=False).translate((x1,y1,0))
            # horizontal уже порезан, не пересекает вертикаль — ок
            frame = frame.union(mull)
        # Стёкла — 6 пластин толщиной 42? Но рама 70, стекло 42 внутри фальца
        out_step = OUT / "OK1_CadQuery_real.step"
        try:
            cq.exporters.export(frame, str(out_step))
            print(f"CadQuery STEP экспортирован: {out_step}  solids={frame.vals()}")
        except Exception as e:
            print(f"STEP export failed: {e}")
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    print("CadQuery не установлен — пропускаем реальную 3D сборку (нужен pip install cadquery)")

print("""
Итог CadQuery / build123d / FreeCAD WindowFrames для ОК-1:
+ FreeCAD WindowFrames geometry.py — почти 1:1 box layout как WinPlax: 
  strips_x = [FRAME_W + i*(cell_w+MULLION_W)], strips_y аналогично — совпадает
+ CadQuery может собрать тот же проём в 3D (экструзия 70) и отдать STEP для завода
- Но ни один не знает про ТЗ WinPlax: bead 20 outer larger 45°, sash overlap 8+20=28,
  falz 5, continuous auto, ГОСТ размеры, атрибуты блока, DXF R2013 cp1251
- Для WinPlax — полезны как валидатор геометрии (проверить замыкание) и для генерации STEP/STL
  из той же модели build_window_model (достаточно extrude frame/mullions)
""")
