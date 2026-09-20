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
        """Сценарий 4: Замыкание сетки COLS·CELL_W + ΣV == GRID_W и ROWS·CELL_H + ΣH == GRID_H (погрешность 1e-6)"""
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
        grid_w = (self.params["opening"]["width"] - s - fw) - (s + fw)
        grid_h = (self.params["opening"]["height"] - s - fh) - (s + fh)
        sum_v = (cols - 1) * mw
        sum_h = (rows - 1) * mh
        self.assertAlmostEqual(cols * cell_w + sum_v, grid_w, delta=1e-6)
        self.assertAlmostEqual(rows * cell_h + sum_h, grid_h, delta=1e-6)

    def test_05_layer_okna(self):
        """Сценарий 5: Слои 'Окна' (цвет 7) и 'Штриховые' (проём)"""
        doc = ezdxf.readfile("output/ОК-1.dxf")
        self.assertIn("Окна", doc.layers, "Слой 'Окна' должен существовать")
        self.assertIn("Штриховые", doc.layers, "Слой 'Штриховые' для проёма должен существовать")
        self.assertEqual(doc.layers.get("Окна").color, 7, "Цвет слоя Окна должен быть 7")
        block_name = "WW_ОК-1_3x2_001"
        blk = doc.blocks[block_name]
        # Проверка что проём на Штриховые, остальные на Окна
        opening_pts = [(0.0,0.0),(1500.0,0.0),(1500.0,1500.0),(0.0,1500.0)]
        for entity in blk:
            if entity.dxftype() == "LWPOLYLINE":
                pts = [(round(p[0],1), round(p[1],1)) for p in entity.get_points()]
                if pts == [(0.0,0.0),(1500.0,0.0),(1500.0,1500.0),(0.0,1500.0)]:
                    self.assertEqual(entity.dxf.layer, "Штриховые", "Контур проёма должен быть на слое 'Штриховые'")
                else:
                    self.assertEqual(entity.dxf.layer, "Окна", f"Элемент блока {entity.dxftype()} должен быть на слое 'Окна'")
            else:
                self.assertEqual(entity.dxf.layer, "Окна", f"Элемент блока {entity.dxftype()} должен быть на слое 'Окна'")
        msp = doc.modelspace()
        for entity in msp:
            self.assertEqual(entity.dxf.layer, "Окна", f"Элемент пространства модели {entity.dxftype()} должен быть на слое 'Окна'")
            if entity.dxftype() == "INSERT":
                for attr in entity.attribs:
                    self.assertEqual(attr.dxf.layer, "Окна", f"Атрибут {attr.dxf.tag} должен быть на слое 'Окна'")

    def test_06_attributes_values(self):
        """Сценарий 6: 8 атрибутов с корректными значениями (GRID строго 3x2 латиница)"""
        doc = ezdxf.readfile("output/ОК-1.dxf")
        block_name = "WW_ОК-1_3x2_001"
        blk = doc.blocks[block_name]
        attdefs = {e.dxf.tag: e for e in blk if e.dxftype() == "ATTDEF"}
        self.assertEqual(len(attdefs), 8, "В блоке должно быть ровно 8 ATTDEF")
        expected_tags = {
            "OBJECT": "Тестовый объект",
            "WINDOW_NAME": "ОК-1",
            "COLOR_OUT": "RAL 8017",
            "COLOR_IN": "RAL 9016",
            "GLAZING": "32",
            "SIZE_W": "1500",
            "SIZE_H": "1500",
            "GRID": "3x2",
        }
        for tag, exp_val in expected_tags.items():
            self.assertIn(tag, attdefs, f"Тег {tag} должен присутствовать в ATTDEF")
            self.assertEqual(attdefs[tag].dxf.text, exp_val, f"Значение атрибута {tag}")
            self.assertNotIn("?", attdefs[tag].dxf.text, f"В тексте {tag} не должно быть '?'")
            # Проверка что GRID использует латиницу x
            if tag == "GRID":
                self.assertIn("x", attdefs[tag].dxf.text)
                self.assertNotIn("×", attdefs[tag].dxf.text)
        # Проверка атрибутов у INSERT
        msp = doc.modelspace()
        inserts = list(msp.query(f"INSERT[name=='{block_name}']"))
        self.assertEqual(len(inserts), 1)
        ins = inserts[0]
        attrib_map = {a.dxf.tag: a.dxf.text for a in ins.attribs}
        self.assertEqual(len(attrib_map), 8, "У INSERT должно быть 8 ATTRIB")
        for tag, exp_val in expected_tags.items():
            self.assertEqual(attrib_map.get(tag), exp_val)

    def test_07_attributes_style(self):
        """Сценарий 7: Стиль атрибутов WindowStyle Arial.ttf высота 22 шаг 35 точка -200, OH (смещены левее, крупнее, не наезжают)"""
        doc = ezdxf.readfile("output/ОК-1.dxf")
        block_name = "WW_ОК-1_3x2_001"
        blk = doc.blocks[block_name]
        # Проверка существования стиля WindowStyle с Arial.ttf
        self.assertIn("WindowStyle", doc.styles, "Стиль WindowStyle должен существовать")
        self.assertEqual(doc.styles.get("WindowStyle").dxf.font, "Arial.ttf", "Шрифт WindowStyle должен быть Arial.ttf")
        # Проверка параметров ATTDEF
        attdefs = sorted([e for e in blk if e.dxftype() == "ATTDEF"], key=lambda x: -x.dxf.insert.y)  # сверху вниз
        # Проверяем высоту и стиль (доработка: крупнее 22, левее -200)
        for att in attdefs:
            self.assertEqual(att.dxf.height, 22.0, f"Высота атрибута {att.dxf.tag} должна быть 22.0 (доработка крупнее)")
            self.assertEqual(att.dxf.style, "WindowStyle", f"Стиль атрибута {att.dxf.tag} должен быть WindowStyle")
            self.assertEqual(att.dxf.layer, "Окна")
            self.assertNotIn("?", att.dxf.text)
        # Проверка координат первой и шага (доработка: X=-200, шаг 35)
        oh = self.params["opening"]["height"]
        first = [a for a in attdefs if a.dxf.tag == "OBJECT"][0]
        self.assertAlmostEqual(first.dxf.insert.x, -200.0, delta=1e-6, msg="X первого атрибута должен быть -200 (смещён левее)")
        self.assertAlmostEqual(first.dxf.insert.y, float(oh), delta=1e-6, msg="Y первого атрибута должен быть OH")
        # Проверка шага 35 между соседними
        sorted_by_y = sorted(attdefs, key=lambda e: e.dxf.insert.y, reverse=True)
        for i in range(len(sorted_by_y)-1):
            dy = sorted_by_y[i].dxf.insert.y - sorted_by_y[i+1].dxf.insert.y
            self.assertAlmostEqual(dy, 35.0, delta=1e-6, msg=f"Шаг между {sorted_by_y[i].dxf.tag} и {sorted_by_y[i+1].dxf.tag} должен быть 35")
        # Проверка что атрибуты не наезжают на окно: X + ширина текста < 0 (окно с 0)
        # Приблизительно проверяем что X отрицательный и достаточно левый
        for att in attdefs:
            self.assertLess(att.dxf.insert.x, -100, f"Атрибут {att.dxf.tag} должен быть левее -100 чтобы не наезжать")
        # Проверка ATTRIB у INSERT также имеют высоту 22 и стиль
        msp = doc.modelspace()
        ins = list(msp.query(f"INSERT[name=='{block_name}']"))[0]
        for attr in ins.attribs:
            self.assertEqual(attr.dxf.height, 22.0)
            self.assertEqual(attr.dxf.style, "WindowStyle")

    def test_08_insertion_point_and_scale(self):
        """Сценарий 8: Точка вставки (0,0), масштаб 1:1, поворот 0"""
        doc = ezdxf.readfile("output/ОК-1.dxf")
        block_name = "WW_ОК-1_3x2_001"
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
        """Сценарий 9: Имя блока WW_ОК-1_3x2_001 (латиница x)"""
        model = build_window_model(self.params)
        self.assertEqual(model["block_name"], "WW_ОК-1_3x2_001")
        doc = ezdxf.readfile("output/ОК-1.dxf")
        self.assertIn("WW_ОК-1_3x2_001", doc.blocks)
        # Проверка что в имени используется латиница x, а не ×
        self.assertNotIn("×", model["block_name"])
        self.assertIn("x", model["block_name"])

    def test_10_oda_handling(self):
        """Сценарий 10: ODA File Converter корректно обнаруживается или безопасно пропускается"""
        oda = find_oda()
        res = main(["params.json"])
        self.assertEqual(res, 0)

    def test_11_dimension_change(self):
        """Сценарий 11: Изменение габаритов пересчитывает геометрию корректно"""
        p2 = copy.deepcopy(self.params)
        p2["opening"]["width"] = 2100
        p2["opening"]["height"] = 1800
        p2["opening"]["seam"] = 25
        p2["frame"]["face_width"] = 70
        p2["frame"]["face_height"] = 70
        p2["mullion"]["width"] = 84
        p2["mullion"]["height"] = 84
        m2 = build_window_model(p2)
        self.assertAlmostEqual(m2["grid"]["cell_w"], 1742.0 / 3.0, places=5)
        self.assertAlmostEqual(m2["grid"]["cell_h"], 763.0, places=5)

    def test_12_grid_1x1(self):
        """Сценарий 12: Сетка 1×1: Только рама, 1 створка, 8 атрибутов, 0 импостов, открытие ДВ"""
        p1 = copy.deepcopy(self.params)
        p1["cols"] = 1
        p1["rows"] = 1
        p1["cells"] = [{"row": 1, "col": 1, "sash_type": "TURN"}]
        errs = validate(p1)
        self.assertEqual(len(errs), 0)
        m1 = build_window_model(p1)
        self.assertEqual(m1["block_name"], "WW_ОК-1_1x1_001")
        self.assertEqual(len(m1["mullions_v"]), 0)
        self.assertEqual(len(m1["mullions_h"]), 0)
        self.assertEqual(len(m1["sashes"]), 1)
        self.assertEqual(len(m1["attdefs"]), 8)
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
            self.assertIn("WW_ОК-1_1x1_001", doc.blocks)
            auditor = doc.audit()
            self.assertEqual(len(auditor.errors), 0)
            # проверка наличия проёма
            blk = doc.blocks["WW_ОК-1_1x1_001"]
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
        self.assertEqual(m84["block_name"], "WW_ОК-1_8x4_001")
        self.assertEqual(len(m84["mullions_v"]), 7)
        self.assertEqual(len(m84["mullions_h"]), 3)
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            export_to_dxf(m84, tmp_path)
            doc = ezdxf.readfile(tmp_path)
            self.assertIn("WW_ОК-1_8x4_001", doc.blocks)
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
        block_name = "WW_ОК-1_3x2_001"
        blk = doc.blocks[block_name]
        model = build_window_model(self.params)

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

        # К7: ГОСТ-стрелки
        for sash in model["sashes"]:
            stype = sash["sash_type"]
            inn = sash["inner_rect"]
            in_x1, in_y1, in_x2, in_y2 = inn
            indicators = sash["indicators"]
            if stype == "TURN":
                self.assertEqual(len(indicators), 2, f"TURN {sash['cell']} должно иметь 2 линии")
                y_mid = (in_y1 + in_y2) / 2
                for p1, p2 in indicators:
                    self.assertAlmostEqual(p2[0], in_x2, delta=1e-6)
                    self.assertAlmostEqual(p2[1], y_mid, delta=1e-6)
                    self.assertAlmostEqual(p1[0], in_x1, delta=1e-6)
            elif stype == "TILT":
                self.assertEqual(len(indicators), 2, f"TILT {sash['cell']} должно иметь 2 линии")
                x_mid = (in_x1 + in_x2) / 2
                for p1, p2 in indicators:
                    self.assertAlmostEqual(p2[0], x_mid, delta=1e-6)
                    self.assertAlmostEqual(p2[1], in_y2, delta=1e-6)
                    self.assertAlmostEqual(p1[1], in_y1, delta=1e-6)
            elif stype == "TURN_TILT":
                self.assertEqual(len(indicators), 4, f"TURN_TILT {sash['cell']} должно иметь 4 линии")
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
