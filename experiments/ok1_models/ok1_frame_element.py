#!/usr/bin/env python3
"""
OK1 через frame element / ProFrame / open-pdf-studio
Это самый близкий к WinPlax подход: "один элемент вдоль линии стены, делится полями"

open-pdf-studio:
- Frame element — это линия на плане стены. Задаёшь length, height, выбираешь preset
  (curtain wall или window frame 67×114 с фальцем, double glazing)
- Поля (panels) = участки между mullions. Mullion ставится на границе полей.
- Операции: add/remove/move/swap mullion, setPanel, divide, stretch
- Отрисовка: outer frame (профиль 67), mullions как filled rect, glass double line, sash dashed arc

ProFrame (Srusht22):
- OpeningModel(DesignRegions) → RegionSolver → mm geometry → 2D elevation/3D assembly/price
- Параметры: frame face/depth, sash face/depth, mullion face, bead, infill thickness

Сравним с WinPlax:
- WinPlax: build_window_model -> frame_outer/inner (45°), mullions_v/h (segmented continuous auto),
  cells (x1,y1,x2,y2), sashes (outer/inner + mitres), bead per-cell outer larger, filling inset 5
- Frame element: аналогично, но mullion continuous выбирается вручную (нет auto по наименьшей стороне)
  и bead — одна профильная линия, не 4 полосы outer larger.

Создадим DXF-мок frame-element для ОК-1 3×2 в стиле open-pdf-studio + ProFrame
"""
from pathlib import Path
import ezdxf

OUT = Path(__file__).parent / "output"
OUT.mkdir(parents=True, exist_ok=True)

W, H, S = 1500, 1500, 30
FRAME_W, FRAME_H = 60, 60
MULLION_W = 80
BEAD_W = 20
COLS, ROWS = 3, 2

# Координаты как в WinPlax (для честного сравнения)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import json
from window_export import build_window_model
params=json.load(open(Path(__file__).resolve().parents[2]/"params.json", encoding="utf-8"))
m=build_window_model(params)
# mullions_v/h уже сегментаированы continuous auto (vertical)

def draw_frame_element_style(path: Path, title: str):
    doc = ezdxf.new("R2013")
    doc.layers.new("FrameElement_Outer", dxfattribs={"color": 7})
    doc.layers.new("FrameElement_Mullion", dxfattribs={"color": 4})
    doc.layers.new("FrameElement_Panel", dxfattribs={"color": 8})
    doc.layers.new("FrameElement_Glass", dxfattribs={"color": 3})
    doc.layers.new("FrameElement_Bead", dxfattribs={"color": 2})
    doc.layers.new("FrameElement_Sash", dxfattribs={"color": 6})
    msp = doc.modelspace()

    # Внешний контур frame element — как в open-pdf-studio: length 1440 вдоль стены
    # На плане — это вид сверху: outer frame 67×114, mullion 67×114
    # На фасаде — это прямоугольник проёма минус шов
    ow, oh = 1440, 1440  # как в WinPlax
    # Outer frame
    frame_outer = m["frame_outer"]
    frame_inner = m["frame_inner"]
    msp.add_lwpolyline(frame_outer, close=True, dxfattribs={"layer":"FrameElement_Outer"})
    msp.add_lwpolyline(frame_inner, close=True, dxfattribs={"layer":"FrameElement_Outer"})
    # Митры
    for a,b in m["frame_mitres"]:
        msp.add_line(a,b, dxfattribs={"layer":"FrameElement_Outer"})
    # Mullions — в open-pdf-studio каждый mullion — это поле между панелями
    # Отрисовка: filled rect (заливка) + две линии границ панели
    # WinPlax делает mullions_v как 2 сегмента на всю высоту (vertical continuous), mullions_h как 3 сегмента порезанных
    # open-pdf-studio делает также, но continuous выбирает пользователь (нет auto)
    for poly in m["mullions_v"]:
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"FrameElement_Mullion"})
        # Заливка — штриховка
        # Добавим диагональ для визуализации filled
        # msp.add_hatch(...)  # пропустим
    for poly in m["mullions_h"]:
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"FrameElement_Mullion"})

    # Panels (поля) — в open-pdf-studio каждое поле — это panel с типом: glass / solid / door
    # Для ОК-1 все поля — glass (СПД42)
    # Отрисовка: glass double line (две параллельные линии на 42мм) — упростим как inset 5 + 42
    for cell in m["cells"]:
        x1,y1,x2,y2 = cell["x1"],cell["y1"],cell["x2"],cell["y2"]
        # Panel border — тонкая линия
        msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True, dxfattribs={"layer":"FrameElement_Panel", "linetype":"DASHED"})
        # Glass — двойная линия с отступом 15 (защемление) как у S571
        # В WinPlax filling: x1+5 .. x2-5 (falz 5)
        f = next(f for f in m["fillings"] if f["cell"]==(cell["row"],cell["col"]))
        fx1,fy1,fx2,fy2 = f["rect"]
        msp.add_lwpolyline([(fx1,fy1),(fx2,fy1),(fx2,fy2),(fx1,fy2)], close=True, dxfattribs={"layer":"FrameElement_Glass"})
        # Вторая линия стекла (толщина СП 42) — внутрь ещё на 2 (условно)
        msp.add_lwpolyline([(fx1+2,fy1+2),(fx2-2,fy1+2),(fx2-2,fy2-2),(fx1+2,fy2-2)], close=True, dxfattribs={"layer":"FrameElement_Glass"})
        msp.add_text(f["text"], height=10, dxfattribs={"layer":"FrameElement_Glass"}).set_placement((fx1+8,fy1+8))

    # Bead — в open-pdf-studio kozijnprofiel.js: профиль 67×114 с фальцем, bead как отдельная деталь 20
    # В WinPlax bead INSIDE — 4 полосы outer larger per cell (сейчас 0 для OUTSIDE)
    # Для frame-element стиля покажем bead как одну рамку вокруг каждой панели (упрощённо)
    # Возьмём только для INSIDE-демо: покажем все 6 ячеек
    import copy
    p_inside = copy.deepcopy(params)
    p_inside["view"]="INSIDE"
    m_in = build_window_model(p_inside)
    for poly in m_in["bead_polys"]:
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"FrameElement_Bead"})

    # Sash — в open-pdf-studio sash как дополнительный контур 80 + 20 bead на створке, с ручкой
    for sash in m_in["sashes"]:
        outer=sash["outer_contour"]
        inner=sash["inner_contour"]
        if outer:
            # outer виден только INSIDE
            pass
        for seg in inner:
            # inner_contour — 4 линии створки (LWPOLYLINE сегмента?)
            # В нашей модели inner_contour — list of 4 lines? Проверим
            pass
        # Нарисуем inner_rect створки
        ir=sash["inner_rect"]
        if ir:
            x1,y1,x2,y2=ir
            msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True, dxfattribs={"layer":"FrameElement_Sash"})
            # Митры створки
            for a,b in sash["mitres"]:
                msp.add_line(a,b, dxfattribs={"layer":"FrameElement_Sash"})
            # Индикаторы открывания (поворот/откид)
            for a,b in sash["indicators"]:
                msp.add_line(a,b, dxfattribs={"layer":"FrameElement_Sash", "linetype":"DASHED"})

    # Подписи
    msp.add_text(f"{title} — frame {FRAME_W} mullion {MULLION_W} 3×2 {ow}×{oh}", height=18, dxfattribs={"layer":"0"}).set_placement((0, oh+70))
    msp.add_text(f"open-pdf-studio style: outer frame + mullions as filled rect + panels (glass double line) + bead 20 per cell", height=12, dxfattribs={"layer":"0"}).set_placement((0, oh+50))
    msp.add_text(f"WinPlax continuous={m['mullion_continuous']}  (vertical цельная, horizontal режется на 3)", height=12, dxfattribs={"layer":"0"}).set_placement((0, -40))
    msp.add_text(f"ProFrame style: OpeningModel → RegionSolver → mm → 2D/3D/price — аналогично WinPlax build_window_model", height=12, dxfattribs={"layer":"0"}).set_placement((0, -60))

    doc.saveas(str(path))
    print(f"Frame element {title}: {path}  mullions V={len(m['mullions_v'])} H={len(m['mullions_h'])} panels={len(m['cells'])}")

draw_frame_element_style(OUT / "OK1_FrameElement_OpenPDFStudio.dxf", "ОК-1 FrameElement (open-pdf-studio/ProFrame)")
# Вариант EXPROF 58/77 (как в S571)
params_exprof = json.load(open(Path(__file__).resolve().parents[2]/"params.json", encoding="utf-8"))
params_exprof["frame"]={"face_width":58,"face_height":58}
params_exprof["mullion"]={"width":77,"height":77,"continuous":"auto"}
params_exprof["system"]="EXPROF_PROFECTA_S571_70"
m2=build_window_model(params_exprof)
def draw_exprof():
    doc=ezdxf.new("R2013")
    msp=doc.modelspace()
    for lay,col in [("FrameElement_Outer",7),("FrameElement_Mullion",4),("FrameElement_Glass",3)]:
        try: doc.layers.new(lay, dxfattribs={"color":col})
        except: pass
    msp.add_lwpolyline(m2["frame_outer"], close=True, dxfattribs={"layer":"FrameElement_Outer"})
    msp.add_lwpolyline(m2["frame_inner"], close=True, dxfattribs={"layer":"FrameElement_Outer"})
    for poly in m2["mullions_v"]: msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"FrameElement_Mullion"})
    for poly in m2["mullions_h"]: msp.add_lwpolyline(poly, close=True, dxfattribs={"layer":"FrameElement_Mullion"})
    for f in m2["fillings"]:
        x1,y1,x2,y2=f["rect"]
        msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True, dxfattribs={"layer":"FrameElement_Glass"})
        msp.add_text(f["text"], height=10, dxfattribs={"layer":"FrameElement_Glass"}).set_placement((x1+5,y1+5))
    msp.add_text(f"ОК-1 S571 58/77  {m2['frame_outer'][0]} {m2['grid']}", height=14, dxfattribs={"layer":"0"}).set_placement((0,1440+40))
    doc.saveas(str(OUT / "OK1_FrameElement_S571_58-77.dxf"))
    print(f"S571 58/77: {OUT / 'OK1_FrameElement_S571_58-77.dxf'}")

draw_exprof()

print("""
Итог frame element (open-pdf-studio / ProFrame) vs WinPlax:
+ Одинаковая декомпозиция: outer frame + mullions (filled rect) + panels (glass)
+ Continuous логика совпадает: vertical цельная / horizontal режется — но в open-pdf-studio это ручной выбор, в WinPlax — auto по наименьшей стороне + переключатель
+ Размеры стекол совпадают: filling = cell inset 5 (falz) → 272.7×491 и т.д.
- Bead в open-pdf-studio — часть профиля kozijnprofiel.js (выступ 20), в WinPlax — 4 отдельные полосы per-cell outer larger с митрой 45° (острая к острой) и обрезкой створкой
- Sash в open-pdf-studio — door panel 40мм + dashed arc поворота, в WinPlax — двухконтурная створка 80+20 с overlap 28 и Inner/Outer
=> Frame element — лучший донор для WinPlax: можно взять их panel catalogue и indentation.js для каталога заполнений
""")
