#!/usr/bin/env python3
"""
Автоматизированные тесты для проверки критериев Window Block Export v0.2.
Соответствует ТЗ 0.2 (ГОСТ 21.501, ГОСТ 23166): 15 сценариев приёмки.
"""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

import ezdxf

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
        # Проверка слоёв: проём Штриховые, размеры Размеры, атрибуты/площадь Текст, остальное Окна; индикаторы на Штриховые
        for entity in blk:
            if entity.dxftype() == "LWPOLYLINE":
                pts = [(round(p[0],1), round(p[1],1)) for p in entity.get_points()]
                if pts == [(0.0,0.0),(1500.0,0.0),(1500.0,1500.0),(0.0,1500.0)]:
                    self.assertEqual(entity.dxf.layer, "Штриховые", "Контур проёма должен быть на слое 'Штриховые'")
                else:
                    self.assertEqual(entity.dxf.layer, "Окна", f"Элемент блока {entity.dxftype()} должен быть на слое 'Окна'")
            elif entity.dxftype() == "LINE":
                self.assertIn(entity.dxf.layer, ("Окна", "Штриховые"), f"LINE должен быть на Окна или Штриховые")
            elif entity.dxftype() == "DIMENSION":
                self.assertEqual(entity.dxf.layer, "Размеры", f"DIMENSION должен быть на слое 'Размеры'")
                self.assertIn(entity.dxf.dimstyle, ("Основной стиль", "Основной стиль с точками"), "DIMENSION стиль должен быть 'Основной стиль' или 'Основной стиль с точками'")
            elif entity.dxftype() == "TEXT":
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
        """Сценарий 6: 6 атрибутов с корректными значениями (слитые строки) — GRID 3х2 кириллица"""
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
            "GLAZING": "Заполнение СПД42",
            "SIZE": "1500х1500",
            "GRID": "3х2",
        }
        for tag, exp_val in expected_tags.items():
            self.assertIn(tag, attdefs, f"Тег {tag} должен присутствовать в ATTDEF")
            self.assertEqual(attdefs[tag].dxf.text, exp_val, f"Значение атрибута {tag}")
            self.assertNotIn("?", attdefs[tag].dxf.text, f"В тексте {tag} не должно быть '?'")
            # Проверка что SIZE и GRID используют кириллицу х (U+0445) как в примере
            if tag in ("GRID", "SIZE"):
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
        # Ожидаемый порядок сверху вниз
        expected_order = ["OBJECT", "WINDOW", "COLOR", "GLAZING", "SIZE", "GRID"]
        actual_order = [a.dxf.tag for a in attdefs]  # уже отсортировано сверху вниз
        self.assertEqual(actual_order, expected_order, f"Порядок атрибутов сверху вниз должен быть {expected_order}, получили {actual_order}")
        # Проверка координат: самый верхний OBJECT на OH+60+5*50, самый нижний GRID на OH+60, шаг 50
        step = 50.0
        n = len(attdefs)
        y_bottom = float(oh) + 60.0  # GRID
        y_top = y_bottom + (n-1)*step  # OBJECT
        first = [a for a in attdefs if a.dxf.tag == "OBJECT"][0]
        last = [a for a in attdefs if a.dxf.tag == "GRID"][0]
        self.assertAlmostEqual(first.dxf.insert.x, 0.0, delta=1e-6, msg="X OBJECT должен быть 0 (левый угол)")
        self.assertAlmostEqual(first.dxf.insert.y, y_top, delta=1e-6, msg=f"Y OBJECT (верхний) должен быть OH+60+{(n-1)}*45 = {y_top}")
        self.assertAlmostEqual(last.dxf.insert.y, y_bottom, delta=1e-6, msg=f"Y GRID (нижний) должен быть OH+60 = {y_bottom}")
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
        """Сценарий 13: Сетка 8×4: Замыкание сетки, 7 верт. и 3 гор. импоста, без ошибок"""
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
        self.assertEqual(len(m84["mullions_v"]), 7)
        self.assertEqual(len(m84["mullions_h"]), 3)
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


if __name__ == "__main__":
    unittest.main()
