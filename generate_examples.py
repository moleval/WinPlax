#!/usr/bin/env python3
"""
Генерация разнообразных примеров окон — все блоки в один DXF файл.
Каждый пример — отдельный блок с уникальным именем, вставленный в ModelSpace
с шагом по X/Y. Поддерживает шаблон (ваши слои/стили).

Запуск:
  python generate_examples.py
  python generate_examples.py --template БШАБЛОН.dxf --output output/Все_примеры.dxf
  python generate_examples.py --template template.dxf --cols 4   # сетка 4 колонки

Файл с вашими примерами можно положить рядом и указать через --examples-file.
Если файл не указан — используются встроенные разнообразные примеры (12 шт).
"""
import argparse
import copy
import json
from pathlib import Path
import sys

import ezdxf

from window_export import build_window_model, export_to_dxf, _copy_template_tables
try:
    from window_export import convert_to_dwg
except Exception:
    convert_to_dwg = None

# Встроенный набор разнообразных примеров (если файла нет)
BASE_PARAMS = {
    "version": "0.2",
    "window_name": "ОК-1",
    "system": "ABSTRACT_60_80_25",
    "opening": {"width": 1500, "height": 1500, "seam": 30},
    "frame": {"face_width": 60, "face_height": 60},
    "mullion": {"width": 80, "height": 80, "continuous": "auto"},
    "bead":    {"width": 25},
    "sash": {"overlap": 15, "profile_width": 80},
    "sill": {"on": True, "height": 30},
    "addons": {"left": 0, "right": 0, "top": 0},
    "cols": 3,
    "rows": 2,
    "separators": {"vertical": [{"index": 1, "kind": "MULLION"}, {"index": 2, "kind": "MULLION"}], "horizontal": [{"index": 1, "kind": "MULLION"}]},
    "cells": [
        {"row": 1, "col": 1, "sash_type": "TURN"},
        {"row": 1, "col": 2, "sash_type": "TURN_TILT"},
        {"row": 1, "col": 3, "sash_type": "FIX"},
        {"row": 2, "col": 1, "sash_type": "TILT"},
        {"row": 2, "col": 2, "sash_type": "FIX"},
        {"row": 2, "col": 3, "sash_type": "FIX"},
    ],
    "metadata": {"object": "Тестовый объект", "window_name": "ОК-1", "color_out": "RAL 8017", "color_in": "RAL 9016", "glazing": "СПД42"},
    "view": "OUTSIDE",
}

def make_examples():
    ex = []

    # 1. 1x1 FIX без подставочника — СНАРУЖИ
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-1.1"
    p["opening"] = {"width": 900, "height": 900, "seam": 20}
    p["cols"] = 1; p["rows"] = 1
    p["cells"] = [{"row": 1, "col": 1, "sash_type": "FIX"}]
    p["sill"] = {"on": False, "height": 30}
    p["addons"] = {"left": 0, "right": 0, "top": 0}
    p["metadata"]["object"] = "Пример 01"
    p["view"] = "OUTSIDE"
    ex.append(p)

    # 2. 1x1 TURN с подставочником
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-1.2"
    p["opening"] = {"width": 1000, "height": 1200, "seam": 30}
    p["cols"] = 1; p["rows"] = 1
    p["cells"] = [{"row": 1, "col": 1, "sash_type": "TURN"}]
    p["sill"] = {"on": True, "height": 30}
    p["addons"] = {"left": 0, "right": 0, "top": 0}
    p["metadata"]["object"] = "Пример 02"
    ex.append(p)

    # 3. 2x1 с TURN+TILT, добор слева
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-2.1"
    p["opening"] = {"width": 1400, "height": 1500, "seam": 25}
    p["cols"] = 2; p["rows"] = 1
    p["cells"] = [{"row": 1, "col": 1, "sash_type": "TURN"}, {"row": 1, "col": 2, "sash_type": "TILT"}]
    p["sill"] = {"on": True, "height": 30}
    p["addons"] = {"left": 50, "right": 0, "top": 0}
    p["metadata"]["object"] = "Пример 03"
    ex.append(p)

    # 4. 2x2 все TURN, добор сверху
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-2.2"
    p["opening"] = {"width": 1800, "height": 1800, "seam": 30}
    p["cols"] = 2; p["rows"] = 2
    p["cells"] = [{"row": r, "col": c, "sash_type": "TURN"} for r in (1,2) for c in (1,2)]
    p["sill"] = {"on": True, "height": 30}
    p["addons"] = {"left": 0, "right": 0, "top": 60}
    p["metadata"]["object"] = "Пример 04"
    ex.append(p)

    # 5. 3x2 базовый (как в ТЗ)
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-3.2"
    p["metadata"]["object"] = "Пример 05"
    ex.append(p)

    # 6. 3x2 с доборами со всех сторон, без подставочника
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-3.2Д"
    p["opening"] = {"width": 1700, "height": 1700, "seam": 30}
    p["sill"] = {"on": False, "height": 30}
    p["addons"] = {"left": 70, "right": 70, "top": 50}
    p["metadata"]["object"] = "Пример 06"
    ex.append(p)

    # 7. 3x3 смешанный
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-3.3"
    p["opening"] = {"width": 2100, "height": 2100, "seam": 30}
    p["cols"] = 3; p["rows"] = 3
    p["cells"] = [
        {"row": 1, "col": 1, "sash_type": "TURN"}, {"row": 1, "col": 2, "sash_type": "FIX"}, {"row": 1, "col": 3, "sash_type": "TURN_TILT"},
        {"row": 2, "col": 1, "sash_type": "FIX"}, {"row": 2, "col": 2, "sash_type": "TURN_TILT"}, {"row": 2, "col": 3, "sash_type": "FIX"},
        {"row": 3, "col": 1, "sash_type": "TILT"}, {"row": 3, "col": 2, "sash_type": "FIX"}, {"row": 3, "col": 3, "sash_type": "TURN"},
    ]
    p["addons"] = {"left": 30, "right": 30, "top": 30}
    p["metadata"]["object"] = "Пример 07"
    ex.append(p)

    # 8. 4x3 большой
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-4.3"
    p["opening"] = {"width": 2400, "height": 1800, "seam": 30}
    p["cols"] = 4; p["rows"] = 3
    p["cells"] = [{"row": r, "col": c, "sash_type": "FIX" if (r+c)%3==0 else "TURN_TILT"} for r in range(1,4) for c in range(1,5)]
    # сделаем пару FIX
    p["sill"] = {"on": True, "height": 30}
    p["metadata"]["object"] = "Пример 08"
    ex.append(p)

    # 9. 6x3 FIX only
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-6.3"
    p["opening"] = {"width": 3600, "height": 2000, "seam": 30}
    p["cols"] = 6; p["rows"] = 3
    p["cells"] = []
    p["sill"] = {"on": True, "height": 30}
    p["metadata"]["object"] = "Пример 09"
    ex.append(p)

    # 10. 8x4 большой
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-8.4"
    p["opening"] = {"width": 4800, "height": 3000, "seam": 30}
    p["cols"] = 8; p["rows"] = 4
    p["cells"] = []
    p["sill"] = {"on": True, "height": 30}
    p["metadata"]["object"] = "Пример 10"
    ex.append(p)

    # 11. 2x2 с разными профилями рамы/импоста, шов 20
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-2.2П"
    p["opening"] = {"width": 1500, "height": 1500, "seam": 20}
    p["frame"] = {"face_width": 70, "face_height": 70}
    p["mullion"] = {"width": 100, "height": 100}
    p["cols"] = 2; p["rows"] = 2
    p["cells"] = [{"row": 1, "col": 1, "sash_type": "TURN_TILT"}, {"row": 1, "col": 2, "sash_type": "FIX"}, {"row": 2, "col": 1, "sash_type": "FIX"}, {"row": 2, "col": 2, "sash_type": "TURN"}]
    p["sill"] = {"on": True, "height": 40}
    p["metadata"]["object"] = "Пример 11"
    ex.append(p)

    # 12. 3x2 узкий высокий — ИЗНУТРИ
    p = copy.deepcopy(BASE_PARAMS)
    p["window_name"] = "ОК-УЗ"
    p["opening"] = {"width": 1200, "height": 2100, "seam": 30}
    p["cols"] = 2; p["rows"] = 3
    p["cells"] = [{"row": 1, "col": 1, "sash_type": "FIX"}, {"row": 1, "col": 2, "sash_type": "TURN"}, {"row": 2, "col": 1, "sash_type": "TURN"}, {"row": 2, "col": 2, "sash_type": "TURN_TILT"}, {"row": 3, "col": 1, "sash_type": "TILT"}, {"row": 3, "col": 2, "sash_type": "FIX"}]
    p["metadata"]["object"] = "Пример 12"
    p["view"] = "INSIDE"
    ex.append(p)

    # Проставим виды: нечётные — СНАРУЖИ, чётные — ИЗНУТРИ для разнообразия
    for i, pp in enumerate(ex):
        if i % 2 == 1:
            pp["view"] = "INSIDE"
        else:
            pp["view"] = "OUTSIDE"

    # Диверсификация сплошного импоста и штапика для наглядности
    # Пример 05 (3x2) — auto (квадрат -> vertical), Пример 07 (3x3) — vertical принудительно
    # Пример 08 (4x3) — horizontal, Пример 10 (8x4) — auto, Пример 11 — vertical широкий импост
    if len(ex) >= 11:
        ex[4]["mullion"]["continuous"] = "auto"  # 3x2 квадрат -> vertical
        ex[6]["mullion"]["continuous"] = "vertical"
        ex[7]["mullion"]["continuous"] = "horizontal"
        ex[9]["mullion"]["continuous"] = "auto"
        ex[10]["mullion"]["continuous"] = "vertical"
        # Штапик: по умолчанию 25, для примера 11 — 20 мм, пример 06 — 30 мм
        # сохраняем после переназначения системы
        bead_06 = ex[5].get("bead", {"width": 30})
        bead_11 = ex[10].get("bead", {"width": 20})

    # Три системы на старте: ABSTRACT / REHAU GRAZIO / EXPROF Profecta S571
    # 01-04 ABSTRACT, 05-08 REHAU, 09-12 EXPROF
    if len(ex) >= 12:
        for i in [0,1,2,3]:
            ex[i]["system"] = "ABSTRACT_60_80_25"
        for i in [4,5,6,7]:
            ex[i]["system"] = "REHAU_GRAZIO_70"
            ex[i]["frame"] = {"face_width": 63, "face_height": 63}
            # сохраняем continuous
            cont = ex[i]["mullion"].get("continuous", "auto")
            ex[i]["mullion"] = {"width": 76, "height": 76, "continuous": cont}
            ex[i]["sash"] = {"overlap": 5, "profile_width": 80}
            if i == 5:
                ex[i]["bead"] = {"width": 14.5}  # GRAZIO 14.5 для СП32, 06 оставим 14.5 (был 30 -> теперь 14.5)
                # но для наглядности оставим 14.5
            else:
                ex[i]["bead"] = {"width": 14.5}
        # для 06 вернем 30 как было задумано для демо разных штапиков (перекрываем REHAU 14.5)
        if len(ex) > 5:
            ex[5]["bead"] = {"width": 30}
        for i in [8,9,10,11]:
            ex[i]["system"] = "EXPROF_PROFECTA_S571_70"
            ex[i]["frame"] = {"face_width": 60, "face_height": 60}
            cont = ex[i]["mullion"].get("continuous", "auto")
            # для 11 оставим широкий 100 как демо
            if i == 10:
                # ex[10] уже vertical 100
                ex[i]["mullion"] = {"width": 100, "height": 100, "continuous": cont}
            else:
                ex[i]["mullion"] = {"width": 74, "height": 74, "continuous": cont}
            ex[i]["sash"] = {"overlap": 8, "profile_width": 80}
            ex[i]["bead"] = {"width": 20}
        # 11 отдельно 20 уже
        ex[10]["bead"] = {"width": 20}

    return ex

def export_all_to_one(models, output_path, template_path=None):
    """Создаёт один DXF с несколькими блоками, каждый вставлен с отступом."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Создаём документ
    if template_path and Path(template_path).is_file():
        print(f"Используем шаблон: {template_path}")
        # читаем шаблон для копирования таблиц
        doc = ezdxf.new("R2013")
        doc.encoding = "cp1251"
        _copy_template_tables(doc, template_path)
        try:
            doc.header["$DWGCODEPAGE"] = "ANSI_1251"
            doc.encoding = "cp1251"
        except Exception:
            pass
    else:
        doc = ezdxf.new("R2013")
        doc.encoding = "cp1251"
        doc.header["$DWGCODEPAGE"] = "ANSI_1251"
        try:
            doc.header["$LTSCALE"] = 25.0
            doc.header["$CELTSCALE"] = 1.0
        except Exception:
            pass
        # если есть автопоиск шаблона — попробуем
        if template_path is None:
            for cand in [Path("template.dxf"), Path("шаблон.dxf"), Path("Шаблон.dxf"), Path("БШАБЛОН.dxf"),
                         Path("template.dwg"), Path("шаблон.dwg"), Path("Шаблон.dwg"), Path("БШАБЛОН.dwg"),
                         Path(__file__).parent / "template.dxf", Path(__file__).parent / "шаблон.dxf", Path(__file__).parent / "Шаблон.dxf", Path(__file__).parent / "БШАБЛОН.dxf",
                         Path(__file__).parent / "template.dwg", Path(__file__).parent / "шаблон.dwg", Path(__file__).parent / "Шаблон.dwg", Path(__file__).parent / "БШАБЛОН.dwg"]:
                if cand.is_file():
                    print(f"Автоподхват шаблона: {cand}")
                    _copy_template_tables(doc, cand)
                    break

    # Обеспечим слои/стили
    for ln, col, lt in [("Окна", 7, "Continuous"), ("Штриховые", 1, "DASHED"), ("Текст", 7, "Continuous"), ("Размеры", 3, "Continuous"), ("Основной", 7, "Continuous")]:
        if ln not in doc.layers:
            try:
                doc.layers.add(ln, color=col, linetype=lt if lt!="Continuous" else "Continuous")
            except Exception:
                try:
                    doc.layers.add(ln, color=col)
                except Exception:
                    pass
    if "Основной стиль" not in doc.styles:
        try:
            doc.styles.new("Основной стиль", dxfattribs={"font": "Arial.ttf"})
        except Exception:
            pass
    if "WindowStyle" not in doc.styles:
        try:
            doc.styles.new("WindowStyle", dxfattribs={"font": "Arial.ttf"})
        except Exception:
            pass
    if "Основной стиль" not in doc.dimstyles:
        try:
            doc.dimstyles.new("Основной стиль")
        except Exception:
            pass
    try:
        ds = doc.dimstyles.get("Основной стиль")
        ds.dxf.dimtxt = 8.0
        ds.dxf.dimasz = 6.0
        ds.dxf.dimscale = 4.0
        ds.dxf.dimexe = 3.0
        ds.dxf.dimexo = 2.5
        ds.dxf.dimgap = 3.0
        try:
            ds.dxf.dimtxsty = "Основной стиль"
        except Exception:
            pass
    except Exception:
        pass
    # Выравниваем масштаб 2-й цепочки (с точками) с 1-й и 3-й
    try:
        ds2 = doc.dimstyles.get("Основной стиль с точками")
        if ds2 is not None:
            for attr, val in [("dimtxt", 8.0), ("dimasz", 6.0), ("dimscale", 4.0), ("dimexe", 3.0), ("dimexo", 2.5), ("dimgap", 3.0)]:
                try:
                    setattr(ds2.dxf, attr, val)
                except Exception:
                    pass
            try:
                if not getattr(ds2.dxf, "dimtxsty", None):
                    ds2.dxf.dimtxsty = "Основной стиль"
            except Exception:
                pass
    except Exception:
        pass

    # Параметры раскладки на листе (в мм)
    cols_on_sheet = 3
    gap_x = 800  # зазор между блоками по X
    gap_y = 800  # по Y
    # Для каждого примера строим модель и блок
    inserted = []
    max_w = 0
    max_h = 0
    # Сначала строим все модели, чтобы знать габариты
    built = []
    for idx, params in enumerate(models):
        # Уникализируем имя блока: добавляем индекс и сетку, чтобы не коллизить
        base_model = __import__("window_export").build_window_model(params)
        # Переименуем блок для уникальности в файле примеров
        obj = params.get("metadata", {}).get("object", f"Пример {idx+1}")
        wn = params.get("window_name", "ОК-1")
        ow = base_model["opening"]["width"]
        oh = base_model["opening"]["height"]
        size = f"{int(ow) if float(ow).is_integer() else ow}х{int(oh) if float(oh).is_integer() else oh}"
        grid = f"{params['cols']}x{params['rows']}"
        view = "Снаружи" if str(params.get("view","OUTSIDE")).upper()=="OUTSIDE" else "Изнутри"
        unique_name = f"{obj} {wn} {size} {grid} {view} #{idx+1:02d}"
        # ограничим 255
        if len(unique_name) > 255:
            unique_name = unique_name[:255]
        base_model["block_name"] = unique_name
        # Сохраним также для отчёта
        built.append(base_model)

    # Вычислим размещение
    # Простая сетка cols_on_sheet колонок
    positions = []
    for i, m in enumerate(built):
        col = i % cols_on_sheet
        row = i // cols_on_sheet
        # Для красоты — каждый блок вставлен в (col*(max_width+gap), -row*(max_height+gap))
        # max_width возьмём максимальный проём + доборы + 500 для размеров
        # Упростим: фиксированный шаг 3000x3000 + габариты
        x = col * 3500
        y = -row * 3500
        positions.append((x, y))

    # Теперь создаём блоки в документе (через прямую запись, не через export_to_dxf)
    from window_export import export_to_dxf as _export_single
    # Чтобы не дублировать код, используем внутреннюю логику: создадим временный doc для каждого и скопируем блок
    # Проще: для каждого built вызовем экспорт во временный файл и импортируем блок через ezdxf importer
    # Но проще — напрямую скопировать логику создания блока из window_export.export_to_dxf, но мы можем
    # переиспользовать export_to_dxf на временный doc и затем импортировать.

    # Создадим все блоки напрямую в doc (копируя логику из window_export)
    # Для упрощения — создадим каждый блок через ту же функцию, но на отдельном документе, затем importer
    from ezdxf.addons import Importer
    import tempfile, os

    for idx, model in enumerate(built):
        # Создаём временный DXF с одним блоком
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            # Временный экспорт (без шаблона — уже в doc)
            _export_single(model, tmp_path)
            tmp_doc = ezdxf.readfile(tmp_path)
            # Импортируем блок и его таблицы
            imp = Importer(tmp_doc, doc)
            # Импортируем все нужные таблицы (слои уже есть)
            imp.import_blocks([model["block_name"]])
            imp.finalize()
            # После импорта блок уже в doc.blocks
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # Теперь вставляем каждый блок в ModelSpace с позицией и атрибутами
    msp = doc.modelspace()
    for idx, model in enumerate(built):
        x, y = positions[idx]
        block_name = model["block_name"]
        # Вставка
        bref = msp.add_blockref(block_name, insert=(x, y), dxfattribs={"layer": "Окна"})
        # Атрибуты
        attrib_values = {tag: val for tag, _, val in model["attdefs"]}
        bref.add_auto_attribs(attrib_values)
        for attrib in bref.attribs:
            attrib.dxf.layer = "Текст"
            try:
                attrib.dxf.style = "Основной стиль (для надписей)"
                attrib.dxf.height = 30.0
            except Exception:
                pass
        # Подпись под блоком (для удобства чтения на листе)
        try:
            # Текст с номером примера ниже блока
            txt = f"{idx+1:02d}. {block_name}"
            msp.add_text(txt, height=40, dxfattribs={"layer": "Текст", "style": "Основной стиль (для надписей)"}).set_pos((x, y - 400), align="TOP_LEFT")
        except Exception:
            pass

    # Сохранение с обработкой занятого файла (Windows часто лочит файл при открытом превью/AutoCAD)
    try:
        if out_file.exists():
            try:
                out_file.unlink()
            except PermissionError as e_unlink:
                print(f"  Предупреждение: файл {out_file} занят другим процессом ({e_unlink}).")
                print(f"  Закройте {out_file.name} в AutoCAD/просмотрщике/проводнике и повторите, либо сохраняем под альтернативным именем.")
                alt = out_file.with_name(out_file.stem + "_new" + out_file.suffix)
                try:
                    doc.saveas(alt)
                    print(f"  Сохранено под альтернативным именем: {alt} ({len(built)} блоков)")
                    print(f"Сохранён файл со всеми примерами: {alt}  ({len(built)} блоков)")
                    out_file = alt
                except PermissionError as e2:
                    raise PermissionError(f"Не удалось сохранить ни {out_file} ни {alt}: {e2}") from e2
                # конвертация и вывод уже сделаны для alt, пропускаем общий путь
                try:
                    from window_export import convert_to_dwg as _c2d
                    dwg_res = _c2d(out_file)
                    if dwg_res and Path(dwg_res).is_file():
                        print(f"  Конвертация всех примеров в DWG: {dwg_res}")
                        try:
                            out_file.unlink()
                            print(f"  DXF удалён после конвертации (остался DWG): {dwg_res}")
                        except Exception:
                            pass
                except Exception:
                    pass
                for i, m in enumerate(built):
                    print(f"  {i+1:02d}. {m['block_name']}  at {positions[i]}  габарит {m['opening']['width']}x{m['opening']['height']}  сетка {m['grid']['cols']}x{m['grid']['rows']}")
                return out_file
            except Exception:
                # другая ошибка при удалении — пробуем сохранить поверх
                pass
        doc.saveas(out_file)
        print(f"Сохранён файл со всеми примерами: {out_file}  ({len(built)} блоков)")
    except PermissionError as e_perm:
        print(f"  Ошибка: файл {out_file} занят (Permission denied). Закройте его в AutoCAD/проводнике и запустите снова. Детали: {e_perm}")
        raise
    # Конвертация всех примеров в DWG (если ODA доступен) — один вызов, с удалением DXF при успехе
    try:
        from window_export import convert_to_dwg as _c2d
        dwg_res = _c2d(out_file)
        if dwg_res and Path(dwg_res).is_file():
            print(f"  Конвертация всех примеров в DWG: {dwg_res}")
            try:
                out_file.unlink()
                print(f"  DXF удалён после конвертации (остался DWG): {dwg_res}")
            except PermissionError:
                print(f"  Не удалось удалить DXF (занят): {out_file}")
            except Exception:
                pass
    except Exception:
        pass
    for i, m in enumerate(built):
        print(f"  {i+1:02d}. {m['block_name']}  at {positions[i]}  габарит {m['opening']['width']}x{m['opening']['height']}  сетка {m['grid']['cols']}x{m['grid']['rows']}")
    return out_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сборка всех примеров в один DXF")
    parser.add_argument("--template", "-t", default=None, help="Путь к шаблону DXF/DWG (или БШАБЛОН.dxf)")
    parser.add_argument("--output", "-o", default="output/Все_примеры.dxf", help="Выходной файл (по умолчанию output/Все_примеры.dxf)")
    parser.add_argument("--examples-file", default=None, help="JSON с массивом params (если не указан — встроенные 12 примеров)")
    parser.add_argument("--cols", type=int, default=3, help="Колонок на листе")
    args = parser.parse_args()

    if args.examples_file and Path(args.examples_file).is_file():
        data = json.loads(Path(args.examples_file).read_text(encoding="utf-8"))
        # ожидается либо {"examples": [params1, params2]} либо [params1, ...]
        if isinstance(data, dict) and "examples" in data:
            models_params = data["examples"]
        elif isinstance(data, list):
            models_params = data
        else:
            models_params = [data]
        print(f"Загружено {len(models_params)} примеров из {args.examples_file}")
    else:
        models_params = make_examples()
        # Если в репозитории есть файл с примерами, который вы закинули — попробуем найти
        for cand in [Path("examples.json"), Path("примеры.json"), Path("WinPlax/examples.json"), Path("output/examples.json")]:
            if cand.is_file():
                print(f"Найден файл примеров: {cand} — используйте --examples-file {cand} для загрузки")
                break

    export_all_to_one(models_params, args.output, template_path=args.template)
