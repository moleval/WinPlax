#!/usr/bin/env python3
"""
OK1 через qsketchmetric (2D parametric DXF, QCAD xdata + ezdxf)
Демонстрирует как qsketchmetric параметризует DXF и где он не дотягивает до WinPlax.

Идея qsketchmetric:
- Берётся "параметрический DXF" где каждому LINE проставлен XDATA QCAD c: "выражение"
  (через QCAD Professional или SemiAutomaticParameterization)
- В MTEXT хранится список переменных: "W:1500, H:1500, FW:60, MW:80 ..."
- Renderer(input_parametric.dxf, output_dxf, variables={...}).render()
  растягивает геометрию, сохраняя углы, меняя длины.

Что попробуем:
1) Создадим параметрический DXF ОК-1 вручную: рама 4 линии, 2 вертикальных импоста, 1 горизонтальный,
   атрибута "c:FW" / "c:MW" и т.д. через xdata
2) Отрендерим его в два размера, покажем что работает для прямоугольников,
   но не умеет per-cell штапик, continuous импост, створки, заполнения.

Требует: pip install qsketchmetric
"""
from pathlib import Path
import ezdxf
from ezdxf.math import Vec3

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Создаём параметрический шаблон ОК-1 3×2
# Базовая геометрия в масштабе 1 (от 0,0). Используем только LINE, чтобы qsketchmetric мог параметризовать.
# Важно: каждая LINE должна иметь QCAD xdata c:<выражение>, где c — текущая длина, выражение — новая длина.
# Переменные объявим в MTEXT: W, H, S, FW, MW, COLS, ROWS и т.д.
# Для простоты сделаем один MTEXT блок "----- custom -----" как требует Renderer.

def make_parametric_ok1(path: Path):
    doc = ezdxf.new("R2013")
    msp = doc.modelspace()
    try:
        doc.appids.new("QCAD")
    except Exception:
        pass
    doc.layers.new("Frame", dxfattribs={"color": 7})
    doc.layers.new("Mullion", dxfattribs={"color": 4})
    doc.layers.new("VIRTUAL_LAYER", dxfattribs={"color": 40})

    # Переменные — в MTEXT последней секцией после "----- custom -----"
    # Формат: MTEXT.text = ".....\\P----- custom -----\\PW:1500\\PH:1500\\PFW:60 ..."
    # Renderer парсит после custom: "W:1500" -> float(Parser().parse("1500").evaluate(variables))
    # Мы оставим дефолтные значения в файле, а при рендере переопределим через variables
    vars_text = (
        "Параметрический ОК-1 3x2\\P"
        "Базовый размер проёма 1500x1500, рама 60, импост 80\\P"
        "----- custom -----\\P"
        "W:1500\\P"
        "H:1500\\P"
        "S:30\\P"
        "FW:60\\P"
        "MW:80\\P"
        "BW:20\\P"
    )
    msp.add_mtext(vars_text, dxfattribs={"layer": "0", "char_height": 10})

    # Геометрия: упрощённо проём 0,0 -> W,H (без шва для простоты, шов — вычитается)
    # Рама: 4 линии внутреннего/внешнего? qsketchmetric не умеет LWPOLYLINE с толщиной, только LINE
    # Сделаем внешний прямоугольник рамы (4 LINE) и внутренний (4 LINE)
    # Внешний: (S, S) .. (W-S, H-S)  — но пока задаём как (0,0)-(W,0)-(W,H)-(0,H) и через выражения сдвинем на S
    # Для демо достаточно прямоугольника W x H и креста импостов

    def add_param_line(p1, p2, expr, layer="Frame"):
        e = msp.add_line(p1, p2, dxfattribs={"layer": layer})
        e.set_xdata("QCAD", [(1000, f"c:{expr}")])
        return e

    # Внешний контур проёма (для ориентации)
    W0, H0 = 1500, 1500
    # Внешний прямоугольник (проём)
    add_param_line((0,0), (W0,0), "W", "Frame")
    add_param_line((W0,0), (W0,H0), "H", "Frame")
    add_param_line((W0,H0), (0,H0), "W", "Frame")
    add_param_line((0,H0), (0,0), "H", "Frame")
    # Внутренний прямоугольник рамы (отступ FW от внешнего)
    add_param_line((60,60), (W0-60,60), "W-2*FW", "Frame")
    add_param_line((W0-60,60), (W0-60,H0-60), "H-2*FW", "Frame")
    add_param_line((W0-60,H0-60), (60,H0-60), "W-2*FW", "Frame")
    add_param_line((60,H0-60), (60,60), "H-2*FW", "Frame")
    # 45° митры рамы — диагонали углов
    add_param_line((0,0), (60,60), "FW*1.414", "Frame")
    add_param_line((W0,0), (W0-60,60), "FW*1.414", "Frame")
    add_param_line((W0,H0), (W0-60,H0-60), "FW*1.414", "Frame")
    add_param_line((0,H0), (60,H0-60), "FW*1.414", "Frame")
    # Вертикальные импосты: делим (W-2*FW) на 3 ячейки: cell_w = (W-2*FW -2*MW)/3
    # Упростим: два вертикальных отрезка на x = FW + cell_w + MW/2
    # Но qsketchmetric умеет только менять длину, не положение — поэтому нужны VIRTUAL_LAYER линии для связности графа
    # Добавим виртуальные линии для связности (они не отрисовываются)
    # Горизонтальные импосты: один на y = H/2
    mid_x1 = W0/3
    mid_x2 = 2*W0/3
    # Вертикаль 1
    add_param_line((mid_x1, 60), (mid_x1, H0-60), "H-2*FW", "Mullion")
    add_param_line((mid_x1+80, 60), (mid_x1+80, H0-60), "H-2*FW", "Mullion")
    # Вертикаль 2
    add_param_line((mid_x2, 60), (mid_x2, H0-60), "H-2*FW", "Mullion")
    add_param_line((mid_x2+80, 60), (mid_x2+80, H0-60), "H-2*FW", "Mullion")
    # Горизонталь
    add_param_line((60, H0/2), (W0-60, H0/2), "W-2*FW", "Mullion")
    add_param_line((60, H0/2+80), (W0-60, H0/2+80), "W-2*FW", "Mullion")

    # Виртуальные связи для единого графа (иначе Renderer разобьёт на подграфы и соединит случайно)
    # Соединим внешний и внутренний прямоугольники виртуалкой
    virt = msp.add_line((0,0), (60,60), dxfattribs={"layer": "VIRTUAL_LAYER"})
    virt.set_xdata("QCAD", [(1000, "c:c")])
    virt2 = msp.add_line((W0,0), (W0-60,60), dxfattribs={"layer": "VIRTUAL_LAYER"})
    virt2.set_xdata("QCAD", [(1000, "c:c")])
    # Центр
    doc.saveas(str(path))
    print(f"Parametric OK1 сохранён: {path}  entities={len(list(msp))}")

param_path = OUT_DIR / "OK1_qsketchmetric_PARAMETRIC.dxf"
make_parametric_ok1(param_path)

# 2. Рендерим два варианта через Renderer
from qsketchmetric.renderer import Renderer

def render_ok1(variables: dict, suffix: str):
    out = ezdxf.new("R2013")
    renderer = Renderer(param_path, out, variables=variables)
    points = renderer.render()
    # Добавим текст с переменными
    msp = out.modelspace()
    msp.add_text(f"qsketchmetric OK1 {suffix} {variables}", height=20, dxfattribs={"layer": "0"}).set_placement((10, -40))
    out_path = OUT_DIR / f"OK1_qsketchmetric_{suffix}.dxf"
    out.saveas(str(out_path))
    print(f"  -> {out_path}  points={points}  bbox={renderer.get_bb_dimensions()}")
    return out_path

print("\n--- Рендерим ---")
# Базовый OK1 как в WinPlax
render_ok1({"W":1500, "H":1500, "FW":60, "MW":80, "BW":20}, "1500x1500_ABSTRACT60-80")
# Уменьшенный вариант — проверим параметрику
render_ok1({"W":900, "H":900, "FW":60, "MW":80}, "0900x0900")
# EXPROF Profecta 58/77
render_ok1({"W":1500, "H":1500, "FW":58, "MW":77}, "1500x1500_S571_58-77")
# REHAU 63/76
render_ok1({"W":1500, "H":1500, "FW":63, "MW":76}, "1500x1500_REHAU_63-76")

print("\nqsketchmetric итог: параметризует длины LINE/CIRCLE/ARC через QCAD xdata, но:")
print("- не умеет LWPOLYLINE (рама как полилиния с шириной) — только LINE")
print("- не умеет per-cell штапик outer larger 20 с митрой 45° (4 полосы на ячейку)")
print("- не умеет continuous auto импост (вертикаль цельная vs горизонталь резанная)")
print("- не умеет створки/заполнения/размеры/атрибуты/блоки")
print("=> Для WinPlax — полезна как идея хранения выражений в DXF, но логику ОК-1 нужно писать вручную как сейчас в build_window_model")

