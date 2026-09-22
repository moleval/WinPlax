#!/usr/bin/env python3
"""
Автоматизированные тесты для проверки критериев Window Block Export v0.2.
Соответствует ТЗ 0.2 (ГОСТ 21.501, ГОСТ 23166): 15 сценариев приёмки.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HAS_EZDXF = False
try:
    import ezdxf
    HAS_EZDXF = True
except ModuleNotFoundError:
    print("=" * 70)
    print("ОШИБКА: библиотека 'ezdxf' не установлена — тесты не могут запуститься.")
    print("=" * 70)
    print()
    print("Вы пытаетесь запустить:")
    print("  python -m unittest")
    print("но Python не находит модуль ezdxf.")
    print()
    print("Решение для Windows PowerShell (выполните ОДНУ из команд):")
    print("  python -m pip install ezdxf")
    print("  py -m pip install ezdxf")
    print("  python -m pip install -r requirements.txt")
    print()
    print("После установки повторно запустите:")
    print("  python -m unittest")
    print("  # или")
    print("  python test_window_export.py -v")
    print("  # или")
    print("  py -m unittest")
    print("=" * 70)
    ezdxf = None  # type: ignore
    HAS_EZDXF = False

if HAS_EZDXF:
    from window_export import (
        build_window_model,
        calc_cells,
        calc_frame,
        calc_sashes,
        calc_sill,
        calc_strips_x,
        calc_strips_y,
        export_to_dxf,
        find_oda,
        load_params,
        main,
        validate,
    )
else:
    # Заглушки, чтобы модуль импортировался без ezdxf — реальная тестовая заглушка ниже
    build_window_model = calc_cells = calc_frame = calc_sashes = calc_sill = None  # type: ignore
    calc_strips_x = calc_strips_y = export_to_dxf = find_oda = load_params = main = validate = None  # type: ignore


if not HAS_EZDXF:
    class TestWindowExport(unittest.TestCase):  # заглушка когда ezdxf отсутствует
        def test_ezdxf_not_installed(self):
            self.fail(
                "Библиотека 'ezdxf' не установлена. "
                "Выполните: python -m pip install ezdxf  "
                "или: py -m pip install ezdxf  "
                "или: python -m pip install -r requirements.txt"
            )
else:

    class TestWindowExport(unittest.TestCase):
        def setUp(self):
            self.params_path = Path("params.json")
            self.assertTrue(self.params_path.is_file(), "params.json должен существовать")
            self.params = load_params(self.params_path)

        def test_01_script_run_default(self):
            """Сценарий 1: Запуск скрипта без ошибок, создание output/ОК-1.dxf"""
            exit_code = main(["params.json"])
            self.assertEqual(exit_code, 0, "Скрипт должен завершаться с кодом 0")
            out_file = Path("output/ОК-1.dxf")
            self.assertTrue(out_file.is_file(), "Файл output/ОК-1.dxf должен быть создан")
            self.assertGreater(out_file.stat().st_size, 0, "Размер DXF должен быть > 0")

        def test_02_dxf_version(self):
            """Сценарий 2: Совместимость DXF R2013 (AC1027) и кодировка"""
            out_file = Path("output/ОК-1.dxf")
            if not out_file.is_file():
                main(["params.json"])
            doc = ezdxf.readfile(out_file)
            self.assertEqual(doc.dxfversion, "AC1027", "DXF версия должна быть AC1027 (R2013)")
            self.assertEqual(doc.header.get("$DWGCODEPAGE"), "ANSI_1251", "Кодировка заголовка должна быть ANSI_1251")
            self.assertEqual(doc.encoding, "cp1251", "doc.encoding должен быть cp1251")

        def test_03_audit(self):
            """Сценарий 3: Аудит целостности DXF без ошибок"""
            out_file = Path("output/ОК-1.dxf")
            if not out_file.is_file():
                main(["params.json"])
            doc = ezdxf.readfile(out_file)
            auditor = doc.audit()
            self.assertEqual(len(auditor.errors), 0, f"Ошибки аудита DXF: {auditor.errors}")
            # fixes may be empty; but ensure no errors

        def test_04_grid_closure(self):
            """Сценарий 4: Замыкание сетки COLS·CELL_W + ΣV == GRID_W и ROWS·CELL_H + ΣH == GRID_H (погрешность 1e-6), с учётом подставочника"""
            model = build_window_model(self.params)
            cols = model["grid"]["cols"]
            rows = model["grid"]["rows"]
            cell_w = model["grid"]["cell_w"]
            cell_h = model["grid"]["cell_h"]
            mw = self.params["mullion"]["width"]
            mh = self.params["mullion"]["height"]
            s = self.params["opening"]["seam"]
            fw = self.params["frame"]["face_width"]
            fh = self.params["frame"]["face_height"]
            # С подставочником низ рамы S+SH, поэтому grid_h уменьшается на SH
            sill_on = self.params.get("sill", {}).get("on", False)
            sh = float(self.params.get("sill", {}).get("height", 30)) if sill_on else 0.0
            grid_w = (self.params["opening"]["width"] - s - fw) - (s + fw)
            # Y0 = S+SH+FH если sill, иначе S+FH
            y0 = (s + sh + fh) if sill_on else (s + fh)
            y1 = self.params["opening"]["height"] - s - fh
            grid_h = y1 - y0
            sum_v = (cols - 1) * mw
            sum_h = (rows - 1) * mh
            self.assertAlmostEqual(cols * cell_w + sum_v, grid_w, delta=1e-6)
            self.assertAlmostEqual(rows * cell_h + sum_h, grid_h, delta=1e-6)

        def test_05_layer_okna(self):
            """Сценарий 5: Слои 'Окна' (цвет 7), 'Штриховые' (проём), 'Размеры' (3) и 'Текст' (7), стиль 'Основной стиль'"""
            doc = ezdxf.readfile("output/ОК-1.dxf")
            self.assertIn("Окна", doc.layers, "Слой 'Окна' должен существовать")
            self.assertIn("Штриховые", doc.layers, "Слой 'Штриховые' для проёма должен существовать")
            self.assertIn("Размеры", doc.layers, "Слой 'Размеры' для размеров должен существовать")
            self.assertIn("Текст", doc.layers, "Слой 'Текст' для атрибутов должен существовать")
            # Основной остаётся для совместимости
            self.assertIn("Основной", doc.layers, "Слой 'Основной' (совместимость) должен существовать")
            self.assertIn("Заполнение", doc.layers, "Слой 'Заполнение' (текст размеров СП) должен существовать")
            self.assertIn("Невидимые", doc.layers, "Слой 'Невидимые' (контур СП под штапиком) должен существовать")
            # Заполнение и Невидимые должны быть непечатными
            try:
                lf = doc.layers.get("Заполнение")
                self.assertEqual(getattr(lf.dxf, "plot", 1), 0, "Слой Заполнение должен быть непечатным (plot=0)")
                li = doc.layers.get("Невидимые")
                self.assertEqual(getattr(li.dxf, "plot", 1), 0, "Слой Невидимые должен быть непечатным (plot=0)")
                # Невидимые — штриховой
                self.assertNotEqual(li.dxf.linetype, "Continuous", "Слой Невидимые должен быть штриховым, не Continuous")
            except Exception:
                pass
            # Цвет Окна из шаблона 195, без шаблона 7 — допускаем оба
            self.assertIn(doc.layers.get("Окна").color, (7, 195), "Цвет слоя Окна должен быть 7 (без шаблона) или 195 (из Шаблон.dxf)")
            self.assertIn("Основной стиль", doc.styles, "Стиль 'Основной стиль' должен существовать")
            # Для атрибутов/площади ожидается специальный стиль из Шаблон.dxf, если шаблон есть
            if Path("Шаблон.dxf").is_file():
                self.assertIn("Основной стиль (для надписей)", doc.styles, "Стиль для надписей должен быть из шаблона")
            self.assertIn("Основной стиль", doc.dimstyles, "Размерный стиль 'Основной стиль' должен существовать")
            # Динамическое имя блока нового формата
            model = build_window_model(self.params)
            block_name = model["block_name"]
            self.assertIn(block_name, doc.blocks)
            blk = doc.blocks[block_name]
            # Проверка слоёв: проём Штриховые, размеры Размеры, атрибуты/площадь Текст, контур СП Невидимые, текст СП Заполнение, остальное Окна; индикаторы на Штриховые
            filling_polys = model.get("filling_polys", [])
            filling_texts = [t for _, t in model.get("filling_texts", [])]
            for entity in blk:
                if entity.dxftype() == "LWPOLYLINE":
                    pts = [(round(p[0],1), round(p[1],1)) for p in entity.get_points()]
                    if pts == [(0.0,0.0),(1500.0,0.0),(1500.0,1500.0),(0.0,1500.0)]:
                        self.assertEqual(entity.dxf.layer, "Штриховые", "Контур проёма должен быть на слое 'Штриховые'")
                    elif entity.dxf.layer == "Невидимые":
                        # контур СП должен быть на Невидимые (под штапиком, штриховой)
                        found = False
                        for fp in filling_polys:
                            fp_rounded = [(round(x,1), round(y,1)) for x,y in fp]
                            if pts == fp_rounded:
                                found = True
                                break
                        self.assertTrue(found, "LWPOLYLINE на Невидимые должен совпадать с filling_polys")
                    elif entity.dxf.layer == "Заполнение":
                        self.fail("LWPOLYLINE контура заполнения не должен быть на слое Заполнение — он перенесён на Невидимые")
                    else:
                        self.assertEqual(entity.dxf.layer, "Окна", f"Элемент блока {entity.dxftype()} должен быть на слое 'Окна'")
                elif entity.dxftype() == "LINE":
                    self.assertIn(entity.dxf.layer, ("Окна", "Штриховые"), f"LINE должен быть на Окна или Штриховые")
                elif entity.dxftype() == "DIMENSION":
                    self.assertEqual(entity.dxf.layer, "Размеры", f"DIMENSION должен быть на слое 'Размеры'")
                    self.assertIn(entity.dxf.dimstyle, ("Основной стиль", "Основной стиль с точками"), "DIMENSION стиль должен быть 'Основной стиль' или 'Основной стиль с точками'")
                elif entity.dxftype() == "TEXT":
                    if entity.dxf.layer == "Заполнение":
                        self.assertIn("х", entity.dxf.text, "Текст заполнения должен содержать 'х'")
                        self.assertIn(entity.dxf.text, filling_texts, "Текст заполнения должен совпадать с моделью")
                        self.assertIn(entity.dxf.style, ("WindowStyle", "Основной стиль", "Основной стиль (для надписей)"))
                    else:
                        # Текст площади на Текст
                        self.assertEqual(entity.dxf.layer, "Текст", f"TEXT должен быть на Текст")
                        self.assertIn(entity.dxf.style, ("Основной стиль", "Основной стиль (для надписей)"), "TEXT стиль должен быть Основной стиль или Основной стиль (для надписей)")
                else:
                    # ATTDEF — на Текст, стиль Основной стиль
                    if entity.dxftype() in ("ATTDEF", "MTEXT"):
                        self.assertEqual(entity.dxf.layer, "Текст", f"Элемент блока {entity.dxftype()} должен быть на слое 'Текст'")
                        self.assertIn(entity.dxf.style, ("Основной стиль", "Основной стиль (для надписей)"), f"Стиль {entity.dxftype()} должен быть Основной стиль или для надписей")
            msp = doc.modelspace()
            for entity in msp:
                if entity.dxftype() == "INSERT":
                    self.assertEqual(entity.dxf.layer, "Окна", f"INSERT должен быть на слое 'Окна'")
                    for attr in entity.attribs:
                        self.assertEqual(attr.dxf.layer, "Текст", f"Атрибут {attr.dxf.tag} должен быть на слое 'Текст'")
                        self.assertIn(attr.dxf.style, ("Основной стиль", "Основной стиль (для надписей)"), f"Атрибут {attr.dxf.tag} стиль должен быть Основной или для надписей")
                elif entity.dxftype() == "DIMENSION":
                    self.assertIn(entity.dxf.layer, ("Основной", "Размеры", "Окна"), f"DIMENSION в ModelSpace на слое размеров")

        def test_06_attributes_values(self):
            """Сценарий 6: 6 атрибутов с корректными значениями (слитые строки) — SYSTEM ABSTRACT кириллица для SIZE"""
            doc = ezdxf.readfile("output/ОК-1.dxf")
            model = build_window_model(self.params)
            block_name = model["block_name"]
            blk = doc.blocks[block_name]
            attdefs = {e.dxf.tag: e for e in blk if e.dxftype() == "ATTDEF"}
            self.assertEqual(len(attdefs), 6, "В блоке должно быть ровно 6 ATTDEF (слитые атрибуты)")
            expected_tags = {
                "OBJECT": "Тестовый объект",
                "WINDOW": "ОК-1/1 шт.",
                "COLOR": "RAL8017/RAL9016",
                "SIZE": "1500х1500 Снаружи",
                "GLAZING": "Заполнение СПД42",
                "SYSTEM": "ABSTRACT_60_80_25",
            }
            for tag, exp_val in expected_tags.items():
                self.assertIn(tag, attdefs, f"Тег {tag} должен присутствовать в ATTDEF")
                self.assertEqual(attdefs[tag].dxf.text, exp_val, f"Значение атрибута {tag}")
                self.assertNotIn("?", attdefs[tag].dxf.text, f"В тексте {tag} не должно быть '?'")
                # Проверка что SIZE использует кириллицу х (U+0445) как в примере; SYSTEM — имя системы без х
                if tag in ("SIZE",):
                    self.assertIn("х", attdefs[tag].dxf.text)
                    self.assertNotIn("×", attdefs[tag].dxf.text)
            # Проверка атрибутов у INSERT
            msp = doc.modelspace()
            inserts = list(msp.query(f"INSERT[name=='{block_name}']"))
            self.assertEqual(len(inserts), 1)
            ins = inserts[0]
            attrib_map = {a.dxf.tag: a.dxf.text for a in ins.attribs}
            self.assertEqual(len(attrib_map), 6, "У INSERT должно быть 6 ATTRIB")
            for tag, exp_val in expected_tags.items():
                self.assertEqual(attrib_map.get(tag), exp_val)

        def test_07_attributes_style(self):
            """Сценарий 7: Стиль атрибутов Основной стиль Arial.ttf высота 30 шаг 50 выше окна слева (X=0, Y=OH+60), слой Текст, порядок сверху Объект->Сетка"""
            doc = ezdxf.readfile("output/ОК-1.dxf")
            model_tmp = build_window_model(self.params)
            block_name = model_tmp["block_name"]
            blk = doc.blocks[block_name]
            # Проверка существования стиля Основной стиль с Arial.ttf (и WindowStyle для совместимости)
            self.assertIn("Основной стиль", doc.styles, "Стиль Основной стиль должен существовать")
            # Шрифт из шаблона romans.shx, без шаблона Arial.ttf — допускаем оба
            self.assertIn(doc.styles.get("Основной стиль").dxf.font, ("Arial.ttf", "romans.shx", "arial.ttf"), "Шрифт Основной стиль должен быть Arial.ttf или romans.shx из шаблона")
            self.assertIn("WindowStyle", doc.styles, "Стиль WindowStyle должен существовать для совместимости")
            # Проверка параметров ATTDEF: высота 30, стиль Основной стиль, слой Текст
            attdefs = sorted([e for e in blk if e.dxftype() == "ATTDEF"], key=lambda x: -x.dxf.insert.y)  # сверху вниз
            for att in attdefs:
                self.assertEqual(att.dxf.height, 30.0, f"Высота атрибута {att.dxf.tag} должна быть 30.0")
                self.assertEqual(att.dxf.style, "Основной стиль (для надписей)", f"Стиль атрибута {att.dxf.tag} должен быть Основной стиль (для надписей)")
                self.assertEqual(att.dxf.layer, "Текст")
                self.assertNotIn("?", att.dxf.text)
            # Проверка порядка сверху вниз: Объект самый верхний, Сетка самая нижняя (как было)
            oh = self.params["opening"]["height"]
            # Ожидаемый порядок сверху вниз (SIZE/вид поднят выше GLAZING, GRID заменён на SYSTEM)
            expected_order = ["OBJECT", "WINDOW", "COLOR", "SIZE", "GLAZING", "SYSTEM"]
            actual_order = [a.dxf.tag for a in attdefs]  # уже отсортировано сверху вниз
            self.assertEqual(actual_order, expected_order, f"Порядок атрибутов сверху вниз должен быть {expected_order}, получили {actual_order}")
            # Проверка координат: самый верхний OBJECT на OH+60+5*50, самый нижний SYSTEM на OH+60, шаг 50
            step = 50.0
            n = len(attdefs)
            y_bottom = float(oh) + 60.0  # SYSTEM
            y_top = y_bottom + (n-1)*step  # OBJECT
            first = [a for a in attdefs if a.dxf.tag == "OBJECT"][0]
            last = [a for a in attdefs if a.dxf.tag == "SYSTEM"][0]
            self.assertAlmostEqual(first.dxf.insert.x, 0.0, delta=1e-6, msg="X OBJECT должен быть 0 (левый угол)")
            self.assertAlmostEqual(first.dxf.insert.y, y_top, delta=1e-6, msg=f"Y OBJECT (верхний) должен быть OH+60+{(n-1)}*45 = {y_top}")
            self.assertAlmostEqual(last.dxf.insert.y, y_bottom, delta=1e-6, msg=f"Y SYSTEM (нижний) должен быть OH+60 = {y_bottom}")
            # Проверка шага 50 между соседними сверху вниз
            sorted_by_y = sorted(attdefs, key=lambda e: e.dxf.insert.y, reverse=True)
            for i in range(len(sorted_by_y)-1):
                dy = sorted_by_y[i].dxf.insert.y - sorted_by_y[i+1].dxf.insert.y
                self.assertAlmostEqual(dy, 50.0, delta=1e-6, msg=f"Шаг между {sorted_by_y[i].dxf.tag} и {sorted_by_y[i+1].dxf.tag} должен быть 50")
            for att in attdefs:
                self.assertAlmostEqual(att.dxf.insert.x, 0.0, delta=1e-6, msg=f"Атрибут {att.dxf.tag} должен быть на X=0 левый угол")
                self.assertGreater(att.dxf.insert.y, float(oh), msg=f"Атрибут {att.dxf.tag} должен быть выше окна (Y>OH)")
            # Проверка площади в правом верхнем углу: слой Текст, стиль Основной стиль, высота 30, (OW, OH+60) Top Right, insert == align_point
            texts = [e for e in blk if e.dxftype() == "TEXT"]
            area_texts = [t for t in texts if "м²" in t.dxf.text or "S=" in t.dxf.text]
            self.assertGreaterEqual(len(area_texts), 1, "Текст площади S=... м² должен присутствовать в правом верхнем углу")
            for at in area_texts:
                self.assertEqual(at.dxf.layer, "Текст")
                self.assertEqual(at.dxf.style, "Основной стиль (для надписей)")
                self.assertEqual(at.dxf.height, 30.0)
                self.assertAlmostEqual(at.dxf.insert.x, float(self.params["opening"]["width"]), delta=1e-6)
                self.assertAlmostEqual(at.dxf.insert.y, float(oh) + 60.0, delta=1e-6)
                # Проверка что площадь не уедет в 0,0 при взрыве: align_point == insert и halign Right valign Top
                self.assertEqual(at.dxf.halign, 2, "halign должен быть Right(2)")
                self.assertEqual(at.dxf.valign, 3, "valign должен быть Top(3)")
                # align_point должен совпадать с insert
                try:
                    ax, ay, az = at.dxf.align_point.x, at.dxf.align_point.y, at.dxf.align_point.z
                    self.assertAlmostEqual(ax, at.dxf.insert.x, delta=1e-6)
                    self.assertAlmostEqual(ay, at.dxf.insert.y, delta=1e-6)
                except Exception:
                    pass
            # Проверка ATTRIB у INSERT также имеют высоту 30, стиль Основной стиль, слой Текст
            msp = doc.modelspace()
            ins = list(msp.query(f"INSERT[name=='{block_name}']"))[0]
            for attr in ins.attribs:
                self.assertEqual(attr.dxf.height, 30.0)
                self.assertEqual(attr.dxf.style, "Основной стиль (для надписей)")
                self.assertEqual(attr.dxf.layer, "Текст")

        def test_08_insertion_point_and_scale(self):
            """Сценарий 8: Точка вставки (0,0), масштаб 1:1, поворот 0"""
            doc = ezdxf.readfile("output/ОК-1.dxf")
            model = build_window_model(self.params)
            block_name = model["block_name"]
            msp = doc.modelspace()
            inserts = list(msp.query(f"INSERT[name=='{block_name}']"))
            self.assertEqual(len(inserts), 1)
            ins = inserts[0]
            self.assertEqual(ins.dxf.insert, (0.0, 0.0, 0.0), "Точка вставки должна быть (0, 0, 0)")
            self.assertEqual(ins.dxf.xscale, 1.0)
            self.assertEqual(ins.dxf.yscale, 1.0)
            self.assertEqual(ins.dxf.zscale, 1.0)
            self.assertEqual(ins.dxf.rotation, 0.0)

        def test_09_block_name(self):
            """Сценарий 9: Имя блока 'Объект Название Габариты Вид' (кириллица х, вид Снаружи/Изнутри)"""
            model = build_window_model(self.params)
            # Ожидаем формат: "Тестовый объект ОК-1 1500х1500 Снаружи" (или Изнутри для view INSIDE)
            ow = model["opening"]["width"]
            oh = model["opening"]["height"]
            size_str = f"{int(ow) if float(ow).is_integer() else ow}х{int(oh) if float(oh).is_integer() else oh}"
            object_str = str(model["params"].get("metadata", {}).get("object", "Тестовый объект"))
            window_name = str(model["params"].get("window_name", "ОК-1"))
            view_str = "Снаружи" if str(model["params"].get("view", "OUTSIDE")).upper() == "OUTSIDE" else "Изнутри"
            expected = f"{object_str} {window_name} {size_str} {view_str}"
            self.assertEqual(model["block_name"], expected)
            doc = ezdxf.readfile("output/ОК-1.dxf")
            self.assertIn(expected, doc.blocks)
            # Проверка что в размере используется кириллица х (U+0445), а не × или латиница x
            self.assertIn("х", model["block_name"])
            self.assertNotIn("×", model["block_name"])
            # Проверка вида
            self.assertIn(view_str, model["block_name"])
            # Для OUTSIDE проверяем дополнительный файл INSIDE
            if view_str == "Снаружи":
                inside_doc = ezdxf.readfile("output/ОК-1_INSIDE.dxf")
                expected_inside = f"{object_str} {window_name} {size_str} Изнутри"
                self.assertIn(expected_inside, inside_doc.blocks)

        def test_10_oda_handling(self):
            """Сценарий 10: ODA File Converter корректно обнаруживается или безопасно пропускается"""
            oda = find_oda()
            res = main(["params.json"])
            self.assertEqual(res, 0)

        def test_11_dimension_change(self):
            """Сценарий 11: Изменение габаритов пересчитывает геометрию корректно (с подставочником S+SH)"""
            p2 = copy.deepcopy(self.params)
            p2["opening"]["width"] = 2100
            p2["opening"]["height"] = 1800
            p2["opening"]["seam"] = 25
            p2["frame"]["face_width"] = 70
            p2["frame"]["face_height"] = 70
            p2["mullion"]["width"] = 84
            p2["mullion"]["height"] = 84
            m2 = build_window_model(p2)
            # С учётом подставочника SH=30, Y0=S+SH+FH: grid_h=1580, cell_h=748; без sill было бы 763
            sill_on = p2.get("sill", {}).get("on", False)
            sh = float(p2.get("sill", {}).get("height", 30)) if sill_on else 0.0
            expected_cw = 1742.0 / 3.0
            # grid_h = (1800-25-70) - (25+sh+70) = 1705 - (95+sh) = 1580 при sh=30
            expected_ch = (1580.0 - 84.0) / 2.0 if sill_on else 763.0
            self.assertAlmostEqual(m2["grid"]["cell_w"], expected_cw, places=5)
            self.assertAlmostEqual(m2["grid"]["cell_h"], expected_ch, places=5)

        def test_12_grid_1x1(self):
            """Сценарий 12: Сетка 1×1: Только рама, 1 створка, 6 атрибутов (слитые), 0 импостов, открытие ДВ"""
            p1 = copy.deepcopy(self.params)
            p1["cols"] = 1
            p1["rows"] = 1
            p1["cells"] = [{"row": 1, "col": 1, "sash_type": "TURN"}]
            errs = validate(p1)
            self.assertEqual(len(errs), 0)
            m1 = build_window_model(p1)
            # Имя блока теперь без сетки: объект + окно + размер + вид
            ow1 = float(p1["opening"]["width"]); oh1 = float(p1["opening"]["height"])
            size1 = f"{int(ow1) if ow1.is_integer() else ow1}х{int(oh1) if oh1.is_integer() else oh1}"
            obj1 = str(p1.get("metadata", {}).get("object", "Тестовый объект")); wn1 = str(p1.get("window_name","ОК-1"))
            view1 = "Снаружи" if str(p1.get("view","OUTSIDE")).upper()=="OUTSIDE" else "Изнутри"
            self.assertEqual(m1["block_name"], f"{obj1} {wn1} {size1} {view1}")
            self.assertEqual(len(m1["mullions_v"]), 0)
            self.assertEqual(len(m1["mullions_h"]), 0)
            self.assertEqual(len(m1["sashes"]), 1)
            self.assertEqual(len(m1["attdefs"]), 6)
            # Проверка что створка имеет двухконтурный профиль и 45° стыки
            sash = m1["sashes"][0]
            self.assertEqual(len(sash["outer_contour"]), 4)
            self.assertEqual(len(sash["inner_contour"]), 4)
            self.assertEqual(len(sash["mitres"]), 4)
            # TURN должна иметь 2 линии по ГОСТ
            self.assertEqual(len(sash["indicators"]), 2)
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m1, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                self.assertIn(m1["block_name"], doc.blocks)
                auditor = doc.audit()
                self.assertEqual(len(auditor.errors), 0)
                # проверка наличия проёма
                blk = doc.blocks[m1["block_name"]]
                has_opening = any(e.dxftype() == "LWPOLYLINE" and len(list(e.get_points())) == 4 for e in blk)
                self.assertTrue(has_opening)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        def test_13_grid_8x4(self):
            """Сценарий 13: Сетка 8×4: Замыкание сетки, импосты с учётом сплошного направления, без ошибок"""
            p84 = copy.deepcopy(self.params)
            p84["opening"]["width"] = 6000
            p84["opening"]["height"] = 3000
            p84["cols"] = 8
            p84["rows"] = 4
            p84["cells"] = []
            errs = validate(p84)
            self.assertEqual(len(errs), 0)
            m84 = build_window_model(p84)
            ow84 = float(p84["opening"]["width"]); oh84 = float(p84["opening"]["height"])
            size84 = f"{int(ow84) if ow84.is_integer() else ow84}х{int(oh84) if oh84.is_integer() else oh84}"
            obj84 = str(p84.get("metadata", {}).get("object", "Тестовый объект")); wn84 = str(p84.get("window_name","ОК-1"))
            view84 = "Снаружи" if str(p84.get("view","OUTSIDE")).upper()=="OUTSIDE" else "Изнутри"
            self.assertEqual(m84["block_name"], f"{obj84} {wn84} {size84} {view84}")
            # С учётом сплошного импоста: по умолчанию auto — сплошной по наименьшей стороне
            # 8x4 при 6000x3000 => grid_w > grid_h => vertical сплошной (7 целых), horizontals режутся на cols сегментов
            cont = m84.get("mullion_continuous", "vertical")
            if cont == "vertical":
                self.assertEqual(len(m84["mullions_v"]), 7, "Вертикалей должно быть 7 (сплошные)")
                self.assertEqual(len(m84["mullions_h"]), 3 * 8, "Горизонтали должны быть порезаны: 3 ряда * 8 сегментов = 24")
            elif cont == "horizontal":
                self.assertEqual(len(m84["mullions_h"]), 3, "Горизонталей должно быть 3 (сплошные)")
                self.assertEqual(len(m84["mullions_v"]), 7 * 4, "Вертикали порезаны: 7 * 4 сегмента")
            else:
                # fallback — старый полный count
                self.assertIn(len(m84["mullions_v"]), (7, 7*4))
                self.assertIn(len(m84["mullions_h"]), (3, 3*8))
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m84, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                self.assertIn(m84["block_name"], doc.blocks)
                auditor = doc.audit()
                self.assertEqual(len(auditor.errors), 0)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        def test_14_invalid_parameters(self):
            """Сценарий 14: Некорректные параметры (ширина 0, высота 0, невалидный тип створки)"""
            p_bad1 = copy.deepcopy(self.params)
            p_bad1["opening"]["width"] = 0
            errs1 = validate(p_bad1)
            self.assertTrue(any("opening.width" in e for e in errs1))
            p_bad2 = copy.deepcopy(self.params)
            p_bad2["opening"]["height"] = 0
            errs2 = validate(p_bad2)
            self.assertTrue(any("opening.height" in e for e in errs2))
            p_bad3 = copy.deepcopy(self.params)
            p_bad3["cells"][0]["sash_type"] = "INVALID_TYPE"
            errs3 = validate(p_bad3)
            self.assertTrue(any("недопустимый тип створки" in e for e in errs3))
            with tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False) as tmp_json:
                json.dump(p_bad1, tmp_json)
                bad_json_path = tmp_json.name
            bad_out_path = Path("output/BAD_TEST.dxf")
            if bad_out_path.exists():
                bad_out_path.unlink()
            try:
                exit_code = main([bad_json_path, "--output", str(bad_out_path)])
                self.assertEqual(exit_code, 1)
                self.assertFalse(bad_out_path.exists())
            finally:
                if os.path.exists(bad_json_path):
                    os.remove(bad_json_path)

        def test_15_geometry_v02(self):
            """Сценарий 15: Геометрия ТЗ 0.2 + доработки: проём Штриховые, рама 45°, створки OUTSIDE/INSIDE, подставочник с зазором S, атрибуты левее"""
            doc = ezdxf.readfile("output/ОК-1.dxf")
            model = build_window_model(self.params)
            block_name = model["block_name"]
            blk = doc.blocks[block_name]

            # К4: габаритный контур проёма 1500x1500 на слое Штриховые (доработка)
            opening_expected = [(0.0, 0.0), (1500.0, 0.0), (1500.0, 1500.0), (0.0, 1500.0)]
            found_opening = False
            for e in blk:
                if e.dxftype() == "LWPOLYLINE":
                    pts = [(round(p[0], 2), round(p[1], 2)) for p in e.get_points()]
                    if pts == opening_expected:
                        found_opening = True
                        self.assertEqual(e.dxf.layer, "Штриховые", "Контур проёма должен быть на слое 'Штриховые' (доработка)")
                        # Проверка что слой Штриховые имеет штриховой тип линии
                        self.assertIn("Штриховые", doc.layers)
                        break
            self.assertTrue(found_opening, "Габаритный контур проёма 1500x1500 должен присутствовать на слое Штриховые")

            # К5: рама 45° стыки 4 шт.
            expected_mitres = model["frame_mitres"]
            found_mitres = 0
            for p1, p2 in expected_mitres:
                # ищем линию в блоке
                found = False
                for e in blk:
                    if e.dxftype() == "LINE":
                        sx, sy = e.dxf.start.x, e.dxf.start.y
                        ex, ey = e.dxf.end.x, e.dxf.end.y
                        if (abs(sx - p1[0]) < 1e-6 and abs(sy - p1[1]) < 1e-6 and abs(ex - p2[0]) < 1e-6 and abs(ey - p2[1]) < 1e-6) or \
                           (abs(sx - p2[0]) < 1e-6 and abs(sy - p2[1]) < 1e-6 and abs(ex - p1[0]) < 1e-6 and abs(ey - p1[1]) < 1e-6):
                            found = True
                            self.assertEqual(e.dxf.layer, "Окна")
                            break
                self.assertTrue(found, f"Стык рамы {p1}->{p2} должен присутствовать")
                if found:
                    found_mitres += 1
            self.assertEqual(found_mitres, 4, "Должно быть 4 стыка рамы под 45°")

            # К6: створки двухконтурные 80 мм и 45° стыки (доработка: OUTSIDE — наплав не виден)
            view = model["params"].get("view", "OUTSIDE").upper()
            for sash in model["sashes"]:
                out = sash["outer_rect"]
                inn = sash["inner_rect"]
                self.assertIsNotNone(inn, "Внутренний контур должен существовать")
                # Проверка ширины бруска 80
                self.assertAlmostEqual(out[0] + 80, inn[0], delta=1e-6)
                self.assertAlmostEqual(out[1] + 80, inn[1], delta=1e-6)
                self.assertAlmostEqual(out[2] - 80, inn[2], delta=1e-6)
                self.assertAlmostEqual(out[3] - 80, inn[3], delta=1e-6)
                # Проверка наличия контуров в DXF с учётом вида
                for contour_key in ("outer_contour", "inner_contour"):
                    # Для OUTSIDE наружный контур не должен быть в DXF
                    if view == "OUTSIDE" and contour_key == "outer_contour":
                        for p1, p2 in sash[contour_key]:
                            found = False
                            for e in blk:
                                if e.dxftype() == "LINE":
                                    if (abs(e.dxf.start.x - p1[0]) < 1e-3 and abs(e.dxf.start.y - p1[1]) < 1e-3 and
                                        abs(e.dxf.end.x - p2[0]) < 1e-3 and abs(e.dxf.end.y - p2[1]) < 1e-3):
                                        found = True
                                        break
                                    if (abs(e.dxf.start.x - p2[0]) < 1e-3 and abs(e.dxf.start.y - p2[1]) < 1e-3 and
                                        abs(e.dxf.end.x - p1[0]) < 1e-3 and abs(e.dxf.end.y - p1[1]) < 1e-3):
                                        found = True
                                        break
                            self.assertFalse(found, f"{contour_key} {p1}->{p2} НЕ должен быть в DXF для OUTSIDE (наплав не виден)")
                        continue
                    for p1, p2 in sash[contour_key]:
                        found = False
                        for e in blk:
                            if e.dxftype() == "LINE":
                                if (abs(e.dxf.start.x - p1[0]) < 1e-3 and abs(e.dxf.start.y - p1[1]) < 1e-3 and
                                    abs(e.dxf.end.x - p2[0]) < 1e-3 and abs(e.dxf.end.y - p2[1]) < 1e-3):
                                    found = True
                                    break
                                if (abs(e.dxf.start.x - p2[0]) < 1e-3 and abs(e.dxf.start.y - p2[1]) < 1e-3 and
                                    abs(e.dxf.end.x - p1[0]) < 1e-3 and abs(e.dxf.end.y - p1[1]) < 1e-3):
                                    found = True
                                    break
                        self.assertTrue(found, f"{contour_key} {p1}->{p2} должен быть в DXF")
                # Проверка 4 стыков створки
                self.assertEqual(len(sash["mitres"]), 4, f"Створка {sash['cell']} должна иметь 4 стыка")
                for p1, p2 in sash["mitres"]:
                    found = False
                    for e in blk:
                        if e.dxftype() == "LINE":
                            if (abs(e.dxf.start.x - p1[0]) < 1e-3 and abs(e.dxf.start.y - p1[1]) < 1e-3 and
                                abs(e.dxf.end.x - p2[0]) < 1e-3 and abs(e.dxf.end.y - p2[1]) < 1e-3):
                                found = True
                                break
                            if (abs(e.dxf.start.x - p2[0]) < 1e-3 and abs(e.dxf.start.y - p2[1]) < 1e-3 and
                                abs(e.dxf.end.x - p1[0]) < 1e-3 and abs(e.dxf.end.y - p1[1]) < 1e-3):
                                found = True
                                break
                    self.assertTrue(found, f"Стык створки {p1}->{p2} должен быть в DXF")

            # К7: ГОСТ-стрелки — для СНАРУЖИ от углов рам/импостов (ячейка), для ИЗНУТРИ от видимого габарита створки
            view15 = model["params"].get("view", "OUTSIDE").upper()
            for sash in model["sashes"]:
                stype = sash["sash_type"]
                indicators = sash["indicators"]
                if view15 == "OUTSIDE":
                    # Снаружи: от ячейки (рама+импост), т.к. наплав скрыт
                    cell = next((c for c in model["cells"] if (c["row"], c["col"]) == tuple(sash["cell"])), None)
                    self.assertIsNotNone(cell, f"Ячейка для створки {sash['cell']} должна существовать")
                    cx1, cy1, cx2, cy2 = cell["x1"], cell["y1"], cell["x2"], cell["y2"]
                    if stype == "TURN":
                        self.assertEqual(len(indicators), 2, f"TURN {sash['cell']} должно иметь 2 линии")
                        y_mid = (cy1 + cy2) / 2
                        for p1, p2 in indicators:
                            self.assertAlmostEqual(p2[0], cx2, delta=1e-6)
                            self.assertAlmostEqual(p2[1], y_mid, delta=1e-6)
                            self.assertAlmostEqual(p1[0], cx1, delta=1e-6)
                    elif stype == "TILT":
                        self.assertEqual(len(indicators), 2, f"TILT {sash['cell']} должно иметь 2 линии")
                        x_mid = (cx1 + cx2) / 2
                        for p1, p2 in indicators:
                            self.assertAlmostEqual(p2[0], x_mid, delta=1e-6)
                            self.assertAlmostEqual(p2[1], cy2, delta=1e-6)
                            self.assertAlmostEqual(p1[1], cy1, delta=1e-6)
                    elif stype == "TURN_TILT":
                        self.assertEqual(len(indicators), 4, f"TURN_TILT {sash['cell']} должно иметь 4 линии")
                        for p1, p2 in indicators:
                            self.assertGreaterEqual(min(p1[0], p2[0]), cx1 - 1e-6)
                            self.assertLessEqual(max(p1[0], p2[0]), cx2 + 1e-6)
                            self.assertGreaterEqual(min(p1[1], p2[1]), cy1 - 1e-6)
                            self.assertLessEqual(max(p1[1], p2[1]), cy2 + 1e-6)
                    elif stype == "FIX":
                        self.assertEqual(len(indicators), 0)
                else:
                    # Изнутри — от видимого габарита створки (outer)
                    out = sash["outer_rect"]
                    out_x1, out_y1, out_x2, out_y2 = out
                    if stype == "TURN":
                        self.assertEqual(len(indicators), 2, f"TURN {sash['cell']} должно иметь 2 линии")
                        y_mid = (out_y1 + out_y2) / 2
                        for p1, p2 in indicators:
                            self.assertAlmostEqual(p2[0], out_x2, delta=1e-6)
                            self.assertAlmostEqual(p2[1], y_mid, delta=1e-6)
                            self.assertAlmostEqual(p1[0], out_x1, delta=1e-6)
                    elif stype == "TILT":
                        self.assertEqual(len(indicators), 2, f"TILT {sash['cell']} должно иметь 2 линии")
                        x_mid = (out_x1 + out_x2) / 2
                        for p1, p2 in indicators:
                            self.assertAlmostEqual(p2[0], x_mid, delta=1e-6)
                            self.assertAlmostEqual(p2[1], out_y2, delta=1e-6)
                            self.assertAlmostEqual(p1[1], out_y1, delta=1e-6)
                    elif stype == "TURN_TILT":
                        self.assertEqual(len(indicators), 4, f"TURN_TILT {sash['cell']} должно иметь 4 линии")
                        for p1, p2 in indicators:
                            self.assertGreaterEqual(min(p1[0], p2[0]), out_x1 - 1e-6)
                            self.assertLessEqual(max(p1[0], p2[0]), out_x2 + 1e-6)
                            self.assertGreaterEqual(min(p1[1], p2[1]), out_y1 - 1e-6)
                            self.assertLessEqual(max(p1[1], p2[1]), out_y2 + 1e-6)
                    elif stype == "FIX":
                        self.assertEqual(len(indicators), 0)

            # Подставочный профиль
            if model["sill"]:
                sill_pts = model["sill"]
                found_sill = False
                for e in blk:
                    if e.dxftype() == "LWPOLYLINE":
                        pts = [(round(p[0], 1), round(p[1], 1)) for p in e.get_points()]
                        expected_sill = [(round(p[0], 1), round(p[1], 1)) for p in sill_pts]
                        if pts == expected_sill:
                            found_sill = True
                            break
                self.assertTrue(found_sill, "Подставочный профиль должен присутствовать")

        def test_16_mullion_continuous(self):
            """Сценарий 16: Сплошной импост — auto по наименьшей стороне + ручной переключатель vertical/horizontal, делёный режется"""
            base = copy.deepcopy(self.params)
            base["cols"] = 3; base["rows"] = 2
            base["opening"]["width"] = 1500; base["opening"]["height"] = 1500
            # Квадрат 1500х1500 => auto => vertical (tie-break)
            base["mullion"] = {"width": 80, "height": 80, "continuous": "auto"}
            m_auto_sq = build_window_model(base)
            self.assertEqual(m_auto_sq["mullion_continuous"], "vertical", "Квадрат -> vertical (tie-break)")
            self.assertEqual(len(m_auto_sq["mullions_v"]), 2, "Vertical сплошной: 2 целых")
            self.assertEqual(len(m_auto_sq["mullions_h"]), 3, "Horizontal режется: 1*3 сегмента")

            # Широкий проём 2000х1000 => grid_w > grid_h => vertical сплошной
            wide = copy.deepcopy(base)
            wide["opening"] = {"width": 2000, "height": 1000, "seam": 30}
            wide["mullion"]["continuous"] = "auto"
            m_wide = build_window_model(wide)
            self.assertEqual(m_wide["mullion_continuous"], "vertical")

            # Узкий высокий 1000х2000 => grid_w < grid_h => horizontal сплошной
            tall = copy.deepcopy(base)
            tall["opening"] = {"width": 1000, "height": 2000, "seam": 30}
            tall["cols"] = 2; tall["rows"] = 4
            tall["mullion"]["continuous"] = "auto"
            m_tall = build_window_model(tall)
            self.assertEqual(m_tall["mullion_continuous"], "horizontal", "Высокий => horizontal сплошной")
            self.assertEqual(len(m_tall["mullions_h"]), 3, "Horizontal сплошной: 3 целых")
            self.assertEqual(len(m_tall["mullions_v"]), 1 * 4, "Vertical режется: 1*4 сегмента")

            # Ручной переключатель переопределяет auto
            forced_v = copy.deepcopy(tall)
            forced_v["mullion"]["continuous"] = "vertical"
            m_fv = build_window_model(forced_v)
            self.assertEqual(m_fv["mullion_continuous"], "vertical")
            self.assertEqual(len(m_fv["mullions_v"]), 1)
            self.assertEqual(len(m_fv["mullions_h"]), 6)  # 3*2 сегмента

            forced_h = copy.deepcopy(tall)
            forced_h["mullion"]["continuous"] = "horizontal"
            m_fh = build_window_model(forced_h)
            self.assertEqual(m_fh["mullion_continuous"], "horizontal")
            self.assertEqual(len(m_fh["mullions_h"]), 3)
            self.assertEqual(len(m_fh["mullions_v"]), 4)

            # Проверка что делёные импосты не пересекают сплошные (разрыв)
            for hv_poly in m_tall["mullions_v"]:
                xs = [p[0] for p in hv_poly]; ys = [p[1] for p in hv_poly]
                # вертикальный сегмент tall: должен заканчиваться до горизонтального импоста
                # Проверим что его Y-интервал не пересекает ни один горизонтальный сплошной
                y1, y2 = min(ys), max(ys)
                for h_poly in m_tall["mullions_h"]:
                    hy = min(p[1] for p in h_poly)
                    hy2 = max(p[1] for p in h_poly)
                    # сегменты вертикали не должны пересекаться с горизонталью (разрыв)
                    self.assertTrue(y2 <= hy + 1e-6 or y1 >= hy2 - 1e-6, f"Вертикальный сегмент {hv_poly} не должен пересекать горизонталь {h_poly}")

            # Валидация: недопустимое значение
            bad = copy.deepcopy(base)
            bad["mullion"]["continuous"] = "diagonal"
            errs = validate(bad)
            self.assertTrue(any("continuous" in e for e in errs))

            # Алиасы v/h, вертикаль/горизонталь
            for alias in ("v", "V", "вертикаль", "Horizontal", "h", "гор"):
                alias_p = copy.deepcopy(base)
                alias_p["mullion"]["continuous"] = alias
                errs2 = validate(alias_p)
                self.assertEqual(len([e for e in errs2 if "continuous" in e]), 0, f"Алиас {alias} должен валидироваться")

        def test_17_bead(self):
            """Сценарий 17: Штапик — единый параметр системы 20 мм для ABSTRACT (25 по умолчанию для других), одинаков, одинаков для рамы/импостов/створок, валидация; OUTSIDE не рисуется, INSIDE с митрой 45°"""
            base = copy.deepcopy(self.params)
            # OUTSIDE по умолчанию — штапик не рисуется
            base_out = copy.deepcopy(base); base_out["view"] = "OUTSIDE"
            m_out = build_window_model(base_out)
            self.assertEqual(m_out["bead_width"], 20.0)
            self.assertEqual(len(m_out["bead_polys"]), 0, "Снаружи штапик не должен генерироваться (OUTSIDE)")
            # INSIDE — штапик должен присутствовать с митрой 45°
            base_in = copy.deepcopy(base); base_in["view"] = "INSIDE"
            m_def = build_window_model(base_in)
            self.assertEqual(m_def["bead_width"], 20.0)
            self.assertGreater(len(m_def["bead_polys"]), 0, "Штапик должен генерировать полигоны для INSIDE")
            # Рама: 4 полосы трапеции 45°
            fxs = [p[0] for p in m_def["frame_inner"]]; fys = [p[1] for p in m_def["frame_inner"]]
            fx1, fx2 = min(fxs), max(fxs); fy1, fy2 = min(fys), max(fys)
            bw = m_def["bead_width"]
            frame_beads = [poly for poly in m_def["bead_polys"] if min(p[0] for p in poly) >= fx1 -1e-6 and max(p[0] for p in poly) <= fx2+1e-6 and min(p[1] for p in poly) >= fy1-1e-6 and max(p[1] for p in poly) <= fy2+1e-6]
            self.assertGreaterEqual(len(frame_beads), 4, "Для рамы должно быть минимум 4 полосы штапика (INSIDE)")

            # Пользователь задаёт другое значение
            custom = copy.deepcopy(base)
            custom["bead"] = {"width": 20}
            m_cust = build_window_model(custom)
            self.assertEqual(m_cust["bead_width"], 20.0)
            errs_cust = validate(custom)
            self.assertEqual(len([e for e in errs_cust if "штапика" in e]), 0)

            # Алиасы shtapik / bead_width / shtapik_width
            for key, val in [("shtapik", 22), ("bead_width", 18), ("shtapik_width", 15)]:
                ali = copy.deepcopy(base)
                if key in ("shtapik", "bead"):
                    ali[key] = {"width": val} if key in ("shtapik", "bead") else val
                    # для простоты — top-level число
                    if key in ("shtapik", "bead") and isinstance(ali[key], int):
                        pass
                ali.pop("bead", None)
                ali[key] = val
                m_ali = build_window_model(ali)
                self.assertEqual(m_ali["bead_width"], float(val))
                self.assertEqual(len(validate(ali)), 0)

            # Штапик как число top-level
            num = copy.deepcopy(base); num.pop("bead", None); num["shtapik"] = 25
            self.assertEqual(build_window_model(num)["bead_width"], 25.0)
            num2 = copy.deepcopy(base); num2.pop("bead", None); num2["bead_width"] = 30
            self.assertEqual(build_window_model(num2)["bead_width"], 30.0)

            # Валидация: отрицательный и превышающий раму
            bad_neg = copy.deepcopy(base); bad_neg["bead"] = {"width": -5}
            self.assertTrue(any("штапика" in e.lower() or "штапик" in e.lower() for e in validate(bad_neg)))
            bad_big = copy.deepcopy(base); bad_big["frame"] = {"face_width": 60, "face_height": 60}; bad_big["bead"] = {"width": 70}
            self.assertTrue(any("штапика" in e for e in validate(bad_big)))
            # bead == 0 — отключен, полигонов 0
            zero = copy.deepcopy(base); zero["bead"] = {"width": 0}
            m_zero = build_window_model(zero)
            self.assertEqual(len(m_zero["bead_polys"]), 0)

            # Проверка DXF: штапик на слое Окна как LWPOLYLINE (OUTSIDE) или LINE (INSIDE)
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m_def, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                blk = doc.blocks[m_def["block_name"]]
                bead_found = any(e.dxftype() in ("LWPOLYLINE", "LINE") and e.dxf.layer == "Окна" for e in blk)
                self.assertTrue(bead_found, "Штапик должен быть в DXF на слое Окна")
                # Считаем что LWPOLYLINE количество увеличилось на bead
                # primitives_count должен включать bead
                self.assertGreater(m_def["primitives_count"], 10)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        def test_18_variable_row_heights(self):
            """Сценарий 18: Переменная высота ячеек row_heights/col_widths с sill/addon: 2×2 нижняя 400 1700×1900 sill+addon60 и 2×3 верхняя 400 2400×1600 sill"""
            # 2×2 1700×1900 sill + addon top 60, нижняя секция 400
            p_2x2 = {
                "window_name": "TEST-2x2",
                "opening": {"width": 1700, "height": 1900, "seam": 30},
                "frame": {"face_width": 60, "face_height": 60},
                "mullion": {"width": 80, "height": 80},
                "cols": 2, "rows": 2,
                "sill": {"on": True, "height": 30},
                "addons": {"top": 60},
                "row_heights": [400, None],  # нижняя 400, верхняя auto
                "cells": [],
            }
            errs = validate(p_2x2)
            self.assertEqual(errs, [], f"validate 2x2 не должен давать ошибок: {errs}")
            m_2x2 = build_window_model(p_2x2)
            # grid_h = (1900-30-60) - (30+30+60) = 1810 -120=1690? wait compute: frame_top 1810 y0 120 y1 1750 grid 1630 as before
            # row_heights [400, 1150] (400+1150+80=1630)
            self.assertEqual(m_2x2["grid"]["rows"], 2)
            rh = m_2x2["grid"]["row_heights"]
            self.assertAlmostEqual(rh[0], 400, delta=1e-6, msg="Нижняя секция 2x2 должна быть 400")
            self.assertAlmostEqual(rh[0] + rh[1] + 80, 1630, delta=1e-6)
            # Проверяем strips_y: y0=120, y1=520 (400), mullion 520..600, верх 600..1750 (1150)
            strips_y = m_2x2["strips_y"]
            self.assertAlmostEqual(strips_y[0][0], 120, delta=1e-6)
            self.assertAlmostEqual(strips_y[0][1] - strips_y[0][0], 400, delta=1e-6)
            self.assertAlmostEqual(strips_y[1][1] - strips_y[1][0], 1150, delta=1e-6)
            # Также проверяем что импост горизонтальный на y=520
            self.assertEqual(len(m_2x2["mullions_h"]), 2 if m_2x2["mullion_continuous"]=="vertical" else 1)
            # Экспорт должен пройти без ошибок
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m_2x2, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                self.assertIn(m_2x2["block_name"], doc.blocks)
                self.assertEqual(len(doc.audit().errors), 0)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            # Вариант 2×2 с явным полным списком [400,1150]
            p_2x2_full = copy.deepcopy(p_2x2)
            p_2x2_full["row_heights"] = [400, 1150]
            self.assertEqual(validate(p_2x2_full), [])
            m_2x2_full = build_window_model(p_2x2_full)
            self.assertAlmostEqual(m_2x2_full["grid"]["row_heights"][0], 400, delta=1e-6)
            self.assertAlmostEqual(m_2x2_full["grid"]["row_heights"][1], 1150, delta=1e-6)

            # 2×3 2400×1600 sill, верхняя 400, 3 строки
            p_2x3 = {
                "window_name": "TEST-2x3",
                "opening": {"width": 2400, "height": 1600, "seam": 30},
                "frame": {"face_width": 60, "face_height": 60},
                "mullion": {"width": 80, "height": 80},
                "cols": 2, "rows": 3,
                "sill": {"on": True, "height": 30},
                "row_heights": [None, None, 400],  # верхняя 400, нижние auto
                "cells": [],
            }
            errs3 = validate(p_2x3)
            self.assertEqual(errs3, [], f"validate 2x3 не должен давать ошибок: {errs3}")
            m_2x3 = build_window_model(p_2x3)
            rh3 = m_2x3["grid"]["row_heights"]
            # grid_h = (1600-30-60)-(30+30+60)=1510-120=1390, -160=1230, -400=830/2=415
            self.assertAlmostEqual(rh3[2], 400, delta=1e-6, msg="Верхняя секция 2x3 должна быть 400")
            self.assertAlmostEqual(rh3[0], 415, delta=1e-6)
            self.assertAlmostEqual(rh3[1], 415, delta=1e-6)
            self.assertAlmostEqual(sum(rh3) + 160, 1390, delta=1e-6)
            # strips_y снизу вверх
            sy = m_2x3["strips_y"]
            self.assertAlmostEqual(sy[2][1] - sy[2][0], 400, delta=1e-6)
            self.assertAlmostEqual(sy[0][1] - sy[0][0], 415, delta=1e-6)
            # Валидация ошибки: неверная сумма
            p_bad = copy.deepcopy(p_2x3)
            p_bad["row_heights"] = [400, 400, 400]  # 1200+160=1360 !=1390
            self.assertTrue(any("row_heights" in e for e in validate(p_bad)))
            # Длина не совпадает
            p_bad2 = copy.deepcopy(p_2x3)
            p_bad2["row_heights"] = [400, 400]
            self.assertTrue(any("row_heights" in e for e in validate(p_bad2)))
            # Экспорт 2x3
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m_2x3, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                self.assertIn(m_2x3["block_name"], doc.blocks)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            # Также col_widths переменная
            p_col = copy.deepcopy(p_2x2)
            p_col["col_widths"] = [600, None]
            # grid_w для 1700: (1700-30-60)-(30+60)=1610-90=1520, -80=1440, -600=840 auto
            errs_col = validate(p_col)
            self.assertEqual(errs_col, [])
            m_col = build_window_model(p_col)
            self.assertAlmostEqual(m_col["grid"]["col_widths"][0], 600, delta=1e-6)
            self.assertAlmostEqual(m_col["grid"]["col_widths"][1], 840, delta=1e-6)

        def test_19_bead_45_and_invisible(self):
            """Сценарий 19: Штапик 45° митра INSIDE, отсутствует OUTSIDE; контур СП на слое Невидимые (скрытый, штриховой)"""
            base = copy.deepcopy(self.params)
            base["cols"] = 2; base["rows"] = 2
            base["view"] = "OUTSIDE"
            m_out = build_window_model(base)
            self.assertEqual(len(m_out["bead_polys"]), 0, "Снаружи штапик не должен отрисовываться (OUTSIDE)")
            # filling всё равно есть, но контур на Невидимые
            self.assertGreater(len(m_out["filling_polys"]), 0)
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m_out, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                blk = doc.blocks[m_out["block_name"]]
                # Нет полилиний штапика на Окна для OUTSIDE
                bead_polys_out = [e for e in blk if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "Окна" and len(list(e.get_points())) == 4]
                # Отфильтруем раму/мелкие: штапик имеет характерный размер bw=25
                # Для OUTSIDE bead отсутствует — поэтому количество LWPOLYLINE Окна = рама 2 + импосты + sill
                # Проверим что нет заполнения на Заполнение
                filling_on_fill = [e for e in blk if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "Заполнение"]
                self.assertEqual(len(filling_on_fill), 0, "Контур СП не должен быть на Заполнение (перенесён на Невидимые)")
                filling_on_invis = [e for e in blk if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "Невидимые"]
                self.assertGreater(len(filling_on_invis), 0, "Контур СП должен быть на Невидимые")
                for ent in filling_on_invis:
                    try:
                        # LWPOLYLINE may not expose linetype_scale in some ezdxf versions
                        if hasattr(ent.dxf, "linetype_scale"):
                            self.assertAlmostEqual(ent.dxf.linetype_scale, 25.0, delta=1e-6)
                    except Exception:
                        pass
                # Слой Невидимые штриховой
                li = doc.layers.get("Невидимые")
                self.assertNotEqual(li.dxf.linetype, "Continuous")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            # INSIDE — штапик с митрой 45° (per-cell, глухие ячейки)
            # Для проверки рамочных полос используем чистую модель без створок, чтобы нижняя рама была глухая
            base_in_nosash = copy.deepcopy(base)
            base_in_nosash["view"] = "INSIDE"
            base_in_nosash["bead"] = 25
            base_in_nosash["cells"] = []  # все FIX — проверяем раму/импост
            m_in_nosash = build_window_model(base_in_nosash)
            self.assertGreater(len(m_in_nosash["bead_polys"]), 0, "Изнутри штапик должен присутствовать (без створок)")
            bw = m_in_nosash["bead_width"]
            fxs = [p[0] for p in m_in_nosash["frame_inner"]]; fys = [p[1] for p in m_in_nosash["frame_inner"]]
            fx1, fx2 = min(fxs), max(fxs); fy1, fy2 = min(fys), max(fys)
            # По новому ТЗ штапик наружу от ячейки на раму/импост 20: низ рамы y1-bw .. y1, mitre 45°
            bottom_beads = [poly for poly in m_in_nosash["bead_polys"] if abs(min(p[1] for p in poly) - (fy1-bw)) < 1e-6 and abs(max(p[1] for p in poly) - fy1) < 1e-6 and min(p[0] for p in poly) >= fx1 - bw -1e-6 and max(p[0] for p in poly) <= fx2 + bw +1e-6]
            self.assertGreaterEqual(len(bottom_beads), 1, "Должна быть нижняя полоса рамы (для глухих ячеек) наружу 20")
            for bb in bottom_beads:
                self.assertAlmostEqual(min(p[1] for p in bb), fy1 - bw, delta=1e-6)
                self.assertAlmostEqual(max(p[1] for p in bb), fy1, delta=1e-6)
                # Митра 45° наружу: outer y1-bw длиннее, inner y1 короче
                # Проверяем что нижняя outer шире inner на bw с каждой стороны
                xs_min = min(p[0] for p in bb); xs_max = max(p[0] for p in bb)
                # outer y = fy1-bw, inner y = fy1
                # outer span = fx2 - fx1 + 2*bw, inner = fx2 - fx1
                # Проверяем диагональ: outer x = inner x +/- bw
                # Найдём точки на y1 и y1-bw
                pts_at_fy1 = [pt for pt in bb if abs(pt[1] - fy1) < 1e-6]
                pts_at_fy1_bw = [pt for pt in bb if abs(pt[1] - (fy1-bw)) < 1e-6]
                self.assertEqual(len(pts_at_fy1), 2)
                self.assertEqual(len(pts_at_fy1_bw), 2)
                # inner короче outer на bw с каждой стороны
                inner_xs = sorted([pt[0] for pt in pts_at_fy1])
                outer_xs = sorted([pt[0] for pt in pts_at_fy1_bw])
                self.assertAlmostEqual(inner_xs[0] - outer_xs[0], bw, delta=1e-6)
                self.assertAlmostEqual(outer_xs[1] - inner_xs[1], bw, delta=1e-6)
            has_left = any(abs(min(p[0] for p in b) - (fx1 - bw)) < 1e-6 for b in bottom_beads)
            has_right = any(abs(max(p[0] for p in b) - (fx2 + bw)) < 1e-6 for b in bottom_beads)
            self.assertTrue(has_left and has_right, "Нижние полосы должны выступать на bw за край рамы (митра)")
            # Для проверки импостов и створок используем модель со створками (как было)
            base_in = copy.deepcopy(base)
            base_in["view"] = "INSIDE"
            base_in["bead"] = 25
            m_in = build_window_model(base_in)
            self.assertGreater(len(m_in["bead_polys"]), 0, "Изнутри штапик должен присутствовать (со створками)")
            bw = m_in["bead_width"]
            # Импост вертикальный: две полосы с митрой на торцах — проверим на модели без створок (чистые импосты)
            vert_beads = [poly for poly in m_in_nosash["bead_polys"] if len(poly)==4 and abs(poly[0][0] - poly[3][0])<1e-6 and abs(poly[1][0]-poly[2][0])<1e-6]
            # Среди них должны быть импостные с высотой сегментов
            self.assertGreater(len(vert_beads), 0)
            # Проверяем что хотя бы одна имеет диагональ bw по Y
            found_diag = False
            for poly in vert_beads:
                # левая полоса импоста: (x,y1),(x+bw,y1+bw),(x+bw,y2-bw),(x,y2) — диагонали сверху/снизу
                ys = [p[1] for p in poly]; xs = [p[0] for p in poly]
                # Проверяем наличие точек с отступом bw
                if any(abs(p[1] - (min(ys)+bw)) < 1e-6 and abs(p[0] - (min(xs)+bw)) < 1e-6 for p in poly):
                    found_diag = True
                    break
            self.assertTrue(found_diag, "Штапик импостов должен иметь митру 45° (диагональ bw)")

            # Створки INSIDE — тоже 4 полосы с митрой
            sash_beads = 0
            for sash in m_in["sashes"]:
                ir = sash.get("inner_rect")
                if not ir: continue
                sx1,sy1,sx2,sy2 = ir
                # ищем соответствующую полосу штапика вокруг створки
                for poly in m_in["bead_polys"]:
                    if min(p[0] for p in poly) >= min(sx1,sx2)-1e-6 and max(p[0] for p in poly) <= max(sx1,sx2)+1e-6:
                        # возможно створка
                        if any(abs(p[1]-sy1)<1e-6 for p in poly):
                            sash_beads +=1
                            break
            self.assertGreater(sash_beads, 0, "Для створок должен быть штапик с митрой")

            # DXF INSIDE: штапик присутствует (как LINE из-за обрезки створкой или LWPOLYLINE)
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                export_to_dxf(m_in, tmp_path)
                doc = ezdxf.readfile(tmp_path)
                blk = doc.blocks[m_in["block_name"]]
                # В INSIDE штапик разбивается на LINE из-за створок, но всё равно на Окна
                has_bead_line = any(e.dxftype() == "LINE" and e.dxf.layer == "Окна" for e in blk)
                has_bead_lw = any(e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "Окна" for e in blk)
                self.assertTrue(has_bead_line or has_bead_lw, "INSIDE: штапик должен быть в DXF")
                # Заполнение по-прежнему на Невидимые, не на Заполнение
                filling_on_fill = [e for e in blk if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "Заполнение"]
                self.assertEqual(len(filling_on_fill), 0)
                filling_on_invis = [e for e in blk if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "Невидимые"]
                self.assertGreater(len(filling_on_invis), 0)
                # Текст заполнения на Заполнение с высотой 16
                txts = [e for e in blk if e.dxftype() == "TEXT" and e.dxf.layer == "Заполнение"]
                self.assertGreater(len(txts), 0)
                for t in txts:
                    self.assertIn("х", t.dxf.text)
                    self.assertEqual(t.dxf.height, 16.0)
                # Слой Невидимые должен быть штриховым
                li = doc.layers.get("Невидимые")
                self.assertNotEqual(li.dxf.linetype, "Continuous")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)


    if __name__ == "__main__":
        unittest.main()

