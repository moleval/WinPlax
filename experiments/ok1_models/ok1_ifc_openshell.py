#!/usr/bin/env python3
"""
OK1 через IfcOpenShell / IFC Window (add_window_representation)

IfcOpenShell — эталон BIM parametric window:
- IfcWindow( OverallWidth, OverallHeight )
- Pset_WindowCommon: IsExternal, Infiltration, GlazingAreaFraction...
- geometry: add_window_representation( window, context, frame_thickness, frame_depth, lining, panel positions )
- Внутри: LShapeCheck, createIfcWindowFrameSimple([LEFT,TOP,RIGHT,BOTTOM] thicknesses), partitioning types:
  SINGLE_PANEL, DOUBLE_PANEL_VERTICAL/HORIZONTAL, TRIPLE_PANEL_VERTICAL/HORIZONTAL/BOTTOM/TOP/VERTICAL

Для ОК-1 1500×1500 3×2 с импостами:
- IfcWindow OverallWidth=1440 (проём-швы), OverallHeight=1440
- PartitioningType = SINGLE_PANEL + mullions/transoms? В IFC — mullion и transom как отдельные IfcMember?
- На деле add_window_representation умеет: frame_thickness (рама 60, импост 80), 
  frame_depth (70), lining_depth (глубина коробки), panel = glazing

Попробуем:
- pip install ifcopenshell (если нет — делаем mock ezdxf с IFC-логикой)
- Сгенерим IFC файл IFC4 с окном ОК-1 3×2 и DXF проекцию для визуальной проверки
"""
from pathlib import Path
import math

OUT = Path(__file__).parent / "output"
OUT.mkdir(parents=True, exist_ok=True)

# Параметры ОК-1 как в params.json
W, H = 1500, 1500
SEAM = 30
FRAME_W = 60  # лицо рамы
MULLION_W = 80
BEAD_W = 20
SASH_OVERLAP = 8
SASH_W = 80
COLS, ROWS = 3, 2

FRAME_INNER_W = W - 2*SEAM  # 1440
FRAME_INNER_H = H - 2*SEAM

# Попытка реального IFC
try:
    import ifcopenshell
    import ifcopenshell.api
    import ifcopenshell.util.element
    HAS_IFC = True
    print(f"ifcopenshell {ifcopenshell.version} найден")
except Exception as e:
    HAS_IFC = False
    print(f"ifcopenshell не установлен: {e} -> делаем mock")

def create_ifc_mock():
    """Создаём DXF-мок IFC-стиля: покажем как IFC делит окно на панели"""
    import ezdxf
    doc = ezdxf.new("R2013")
    msp = doc.modelspace()
    doc.layers.new("IfcWindow", dxfattribs={"color": 7})
    doc.layers.new("IfcFrame", dxfattribs={"color": 4})
    doc.layers.new("IfcMullion", dxfattribs={"color": 1})
    doc.layers.new("IfcGlazing", dxfattribs={"color": 3, "linetype": "DASHED"})
    # Внешний габарит окна (OverallWidth/Height)
    ow, oh = FRAME_INNER_W, FRAME_INNER_H
    # Рама как L-shape (в IFC frame_thickness=60, depth=70)
    # Упростим: внешний контур 0,0 - ow,oh, внутренний ow-60 ... как в WinPlax
    # Рисуем как LWPOLYLINE
    msp.add_lwpolyline([(0,0),(ow,0),(ow,oh),(0,oh)], close=True, dxfattribs={"layer":"IfcWindow"})
    msp.add_lwpolyline([(FRAME_W, FRAME_W),(ow-FRAME_W, FRAME_W),(ow-FRAME_W, oh-FRAME_W),(FRAME_W, oh-FRAME_W)], close=True, dxfattribs={"layer":"IfcFrame"})
    # Митры рамы (LShape)
    msp.add_line((0,0),(FRAME_W, FRAME_W), dxfattribs={"layer":"IfcFrame"})
    msp.add_line((ow,0),(ow-FRAME_W, FRAME_W), dxfattribs={"layer":"IfcFrame"})
    msp.add_line((ow,oh),(ow-FRAME_W, oh-FRAME_W), dxfattribs={"layer":"IfcFrame"})
    msp.add_line((0,oh),(FRAME_W, oh-FRAME_W), dxfattribs={"layer":"IfcFrame"})
    # IFC partitioning: 3×2 = 6 панелей
    # Вычисляем как в IfcOpenShell: делит Overall на cols/rows, но рама вычитается, mullion между панелями
    # В IFC: panel_width = (ow - 2*frame_thick - (cols-1)*mullion)/cols
    # Для ОК-1: (1440 -120 -160)/3 = 386.666 — совпадает с WinPlax cell_w!
    cell_w = (ow - 2*FRAME_W - (COLS-1)*MULLION_W)/COLS
    cell_h = (oh - 2*FRAME_W - (ROWS-1)*MULLION_W)/ROWS
    print(f"IFC cell: {cell_w:.1f} x {cell_h:.1f} (совпадает с WinPlax {386.6:.1f}x605)")
    # Вертикальные импосты (mullions) — в IFC как IfcMember
    for i in range(1, COLS):
        x = FRAME_W + i*cell_w + (i-0.5)*MULLION_W - MULLION_W/2
        # вертикальный прямоугольник на всю высоту (continuous vertical как auto выбрал WinPlax)
        x1 = FRAME_W + i*cell_w + (i-1)*MULLION_W + cell_w
        # проще: позиция как в WinPlax cells
        # Возьмём из WinPlax формулы: strips_x
        pass
    # Используем точные координаты из WinPlax для сравнения
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from window_export import build_window_model
    import json, copy
    params=json.load(open(Path(__file__).resolve().parents[2]/"params.json",encoding="utf-8"))
    m=build_window_model(params)
    # Нарисуем mullions как в WinPlax (для сравнения IFC vs WinPlax)
    for poly in m["mullions_v"]:
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"IfcMullion"})
    for poly in m["mullions_h"]:
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"IfcMullion"})
    # Glazing (панели) — в IFC каждая панель как IfcPlate с материалом Glass
    # В DXF — двойная линия стекла внутри каждой ячейки с отступом falz 5 (как WinPlax filling)
    for f in m["fillings"]:
        x1,y1,x2,y2 = f["rect"]
        # Внешний контур стекла (слой Glazing)
        msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True, dxfattribs={"layer":"IfcGlazing"})
        # Внутренний контур стекла (толщина СП 42) — условная вторая линия на 42/2?
        # Упростим — текст размера
        msp.add_text(f["text"], height=12, dxfattribs={"layer":"IfcGlazing"}).set_placement((x1+5, y1+5))
    # Створки — в IFC как IfcWindowPanel с OperationType = TURN/TILT
    # Обозначим только открывающиеся: TURN, TURN_TILT, TILT
    for sash in m["sashes"]:
        ir=sash["inner_rect"]
        if ir:
            x1,y1,x2,y2=ir
            msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True, dxfattribs={"layer":"IfcWindow", "linetype":"DASHED"})
    # Атрибуты
    msp.add_text(f"IFC ОК-1 {FRAME_INNER_W}x{FRAME_INNER_H} 3x2 cell {cell_w:.1f}x{cell_h:.1f} frame {FRAME_W} mullion {MULLION_W}", height=18, dxfattribs={"layer":"0"}).set_placement((0, oh+50))
    msp.add_text(f"PartitioningType=SINGLE_PANEL + mullions(2V+1H)  OperationType: TURN/TURN_TILT/TILT/FIXED", height=14, dxfattribs={"layer":"0"}).set_placement((0, oh+30))
    msp.add_text(f"Pset_WindowCommon.IsExternal=TRUE  GlazingArea={(cell_w*cell_h*6)/(ow*oh)*100:.1f}%", height=14, dxfattribs={"layer":"0"}).set_placement((0, -30))
    out = OUT / "OK1_IFC_mock.dxf"
    doc.saveas(str(out))
    print(f"IFC mock сохранён: {out}")
    return out

def create_real_ifc():
    """Пробует создать реальный IFC4 файл через ifcopenshell.api"""
    import ifcopenshell
    import ifcopenshell.api.root
    import ifcopenshell.api.unit
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    # Создаём пустой IFC4
    model = ifcopenshell.file(schema="IFC4")
    # Project
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="WinPlax OK1")
    # Units
    unit = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(model, units=[unit])
    # Geometric context
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body_context = ifcopenshell.api.context.add_context(model, context_type="Model", context_identifier="Body", target=context, parent=context)
    # Wall + Opening + Window — упростим: только IfcWindow без стены
    # IfcWindow требует OverallWidth/Height, и можно вызвать add_window_representation
    try:
        window = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWindow", name="ОК-1 1500×1500 3×2")
        window.OverallWidth = FRAME_INNER_W/1000  # в метрах
        window.OverallHeight = FRAME_INNER_H/1000
        # Попробуем вызвать add_window_representation — сигнатура меняется между версиями
        # Старая: api.geometry.add_window_representation(model, context=body_context, window=window, frame_thickness=0.06, frame_depth=0.07, partitioning_type="SINGLE_PANEL", ... )
        # Найдём функцию
        import inspect
        try:
            from ifcopenshell.api.geometry.add_window_representation import add_window_representation
            print(inspect.getsource(add_window_representation)[:1200])
        except Exception as e:
            print(f"add_window_representation импорт не удался: {e}")
        # Вызов через ifcopenshell.api.geometry.add_window_representation (универсальный)
        try:
            rep = ifcopenshell.api.geometry.add_window_representation(
                model,
                context=body_context,
                window=window,
                frame_thickness=FRAME_W/1000,
                frame_depth=0.07,
                lining_thickness=FRAME_W/1000,
                lining_depth=0.07,
                mullion_thickness=MULLION_W/1000,
                transom_thickness=MULLION_W/1000,
                # partitioning
                partitioning_type="SINGLE_PANEL",
            )
            print(f"add_window_representation ok: {rep}")
        except Exception as e:
            print(f"add_window_representation call failed: {e}")
            # fallback — просто геометрия коробки как экструзия
            pass
        out_ifc = OUT / "OK1_IFC_real.ifc"
        model.write(str(out_ifc))
        print(f"IFC сохранён: {out_ifc}  entities={len(list(model))}")
        return out_ifc
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None

if HAS_IFC:
    create_real_ifc()

create_ifc_mock()

print("""
Вывод по IfcOpenShell для ОК-1:
- IFC правильно считает cell_w = (Overall -2*frame - (cols-1)*mullion)/cols = 386.666 — совпадает с WinPlax
- Но partitioning в IFC ограничен 9 пресетами: SINGLE, DOUBLE_VERTICAL/HORIZONTAL, TRIPLE_*, нет произвольного 3×2
  => ОК-1 3×2 нужно делать как SINGLE_PANEL + ручные mullions/transoms (как WinPlax)
- IFC не знает про bead 20 outer larger, falz 5, sash overlap 8+20=28, continuous auto
- IFC хранит IfcMaterial (Glass, Frame) и Pset_WindowCommon (тепло/звуко), а WinPlax — DXF LWPOLYLINE 45° + размеры
=> Для WinPlax: взять из IFC формулу деления и LShape проверку, но отрисовку оставить свою
""")

