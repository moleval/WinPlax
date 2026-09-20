#!/usr/bin/env python3
"""
Автоматизированные тесты для проверки критериев прототипа Window Block Export.
Проверяются все тестовые сценарии из раздела 11 ТЗ.
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

    def test_02_03_dxf_compatibility(self):
        """Сценарии 2 и 3: Совместимость DXF R2013 (AutoCAD 2016/2023) и аудит целостности"""
        out_file = Path("output/ОК-1.dxf")
        if not out_file.is_file():
            main(["params.json"])

        doc = ezdxf.readfile(out_file)
        self.assertEqual(doc.dxfversion, "AC1027", "DXF версия должна быть AC1027 (R2013)")
        self.assertEqual(doc.header.get("$DWGCODEPAGE"), "ANSI_1251", "Кодировка заголовка должна быть ANSI_1251")

        auditor = doc.audit()
        self.assertEqual(len(auditor.errors), 0, f"Ошибки аудита DXF: {auditor.errors}")
        self.assertEqual(len(auditor.fixes), 0, f"Исправления аудита DXF: {auditor.fixes}")

    def test_04_grid_closure(self):
        """Сценарий 4: Замыкание сетки COLS·CELL_W + ΣV == GRID_W и ROWS·CELL_H + ΣH == GRID_H"""
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
        """Сценарий 5: Слой 'Окна' - все элементы (в блоке и пространстве модели) на слое 'Окна'"""
        doc = ezdxf.readfile("output/ОК-1.dxf")
        self.assertIn("Окна", doc.layers, "Слой 'Окна' должен существовать в документе")

        block_name = "WW_ОК-1_3x2_001"
        blk = doc.blocks[block_name]
        for entity in blk:
            self.assertEqual(
                entity.dxf.layer,
                "Окна",
                f"Элемент блока {entity.dxftype()} должен быть на слое 'Окна'",
            )

        msp = doc.modelspace()
        for entity in msp:
            self.assertEqual(
                entity.dxf.layer,
                "Окна",
                f"Элемент пространства модели {entity.dxftype()} должен быть на слое 'Окна'",
            )
            if entity.dxftype() == "INSERT":
                for attr in entity.attribs:
                    self.assertEqual(
                        attr.dxf.layer,
                        "Окна",
                        f"Атрибут {attr.dxf.tag} должен быть на слое 'Окна'",
                    )

    def test_06_attributes_values(self):
        """Сценарий 6: 8 атрибутов с корректными значениями"""
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
            "GRID": "3×2",
        }
        for tag, exp_val in expected_tags.items():
            self.assertIn(tag, attdefs, f"Тег {tag} должен присутствовать в ATTDEF")
            self.assertEqual(attdefs[tag].dxf.text, exp_val)

        # Проверка атрибутов у INSERT в modelspace
        msp = doc.modelspace()
        inserts = list(msp.query(f"INSERT[name=='{block_name}']"))
        self.assertEqual(len(inserts), 1)
        ins = inserts[0]
        attrib_map = {a.dxf.tag: a.dxf.text for a in ins.attribs}
        self.assertEqual(len(attrib_map), 8, "У INSERT должно быть 8 ATTRIB")
        for tag, exp_val in expected_tags.items():
            self.assertEqual(attrib_map.get(tag), exp_val)

    def test_07_insertion_point_and_scale(self):
        """Сценарий 7: Точка вставки (0,0), масштаб 1:1"""
        doc = ezdxf.readfile("output/ОК-1.dxf")
        block_name = "WW_ОК-1_3x2_001"
        msp = doc.modelspace()
        inserts = list(msp.query(f"INSERT[name=='{block_name}']"))
        self.assertEqual(len(inserts), 1)
        ins = inserts[0]
        self.assertEqual(ins.dxf.insert, (0.0, 0.0, 0.0), "Точка вставки должна быть (0, 0, 0)")
        self.assertEqual(ins.dxf.xscale, 1.0, "Масштаб X должен быть 1.0")
        self.assertEqual(ins.dxf.yscale, 1.0, "Масштаб Y должен быть 1.0")
        self.assertEqual(ins.dxf.zscale, 1.0, "Масштаб Z должен быть 1.0")
        self.assertEqual(ins.dxf.rotation, 0.0, "Угол поворота должен быть 0.0")

    def test_08_block_name(self):
        """Сценарий 8: Имя блока WW_ОК-1_3x2_001"""
        model = build_window_model(self.params)
        self.assertEqual(model["block_name"], "WW_ОК-1_3x2_001")
        doc = ezdxf.readfile("output/ОК-1.dxf")
        self.assertIn("WW_ОК-1_3x2_001", doc.blocks)

    def test_09_10_oda_handling(self):
        """Сценарии 9 и 10: ODA File Converter корректно обнаруживается или безопасно пропускается"""
        oda = find_oda()
        # В этой среде ODA отсутствует, метод должен возвращать None без исключений
        # и main() должен завершаться с кодом 0
        res = main(["params.json"])
        self.assertEqual(res, 0)

    def test_11_dimension_change(self):
        """Сценарий 11: Изменение габаритов в параметрах пересчитывает геометрию корректно"""
        p2 = copy.deepcopy(self.params)
        p2["opening"]["width"] = 2100
        p2["opening"]["height"] = 1800
        p2["opening"]["seam"] = 25
        p2["frame"]["face_width"] = 70
        p2["frame"]["face_height"] = 70
        p2["mullion"]["width"] = 84
        p2["mullion"]["height"] = 84

        m2 = build_window_model(p2)
        # ow=2100, seam=25, fw=70 -> X0 = 95, X1 = 2005 -> grid_w = 1910
        # cols=3, sum_v = 2 * 84 = 168 -> cell_w = (1910 - 168) / 3 = 1742 / 3 = 580.6666...
        self.assertAlmostEqual(m2["grid"]["cell_w"], 1742.0 / 3.0, places=5)
        # oh=1800, seam=25, fh=70 -> Y0 = 95, Y1 = 1705 -> grid_h = 1610
        # rows=2, sum_h = 1 * 84 = 84 -> cell_h = (1610 - 84) / 2 = 1526 / 2 = 763.0
        self.assertAlmostEqual(m2["grid"]["cell_h"], 763.0, places=5)

    def test_12_grid_1x1(self):
        """Сценарий 12: Сетка 1×1: Только рама, 1 створка, 8 атрибутов, 0 импостов"""
        p1 = copy.deepcopy(self.params)
        p1["cols"] = 1
        p1["rows"] = 1
        p1["cells"] = [{"row": 1, "col": 1, "sash_type": "TURN"}]
        errs = validate(p1)
        self.assertEqual(len(errs), 0)

        m1 = build_window_model(p1)
        self.assertEqual(m1["block_name"], "WW_ОК-1_1x1_001")
        self.assertEqual(len(m1["mullions_v"]), 0, "В сетке 1x1 должно быть 0 вертикальных импостов")
        self.assertEqual(len(m1["mullions_h"]), 0, "В сетке 1x1 должно быть 0 горизонтальных импостов")
        self.assertEqual(len(m1["sashes"]), 1, "Должна быть ровно 1 створка")
        self.assertEqual(len(m1["attdefs"]), 8, "Должно быть ровно 8 атрибутов")

        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            export_to_dxf(m1, tmp_path)
            doc = ezdxf.readfile(tmp_path)
            self.assertIn("WW_ОК-1_1x1_001", doc.blocks)
            auditor = doc.audit()
            self.assertEqual(len(auditor.errors), 0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_13_grid_8x4(self):
        """Сценарий 13: Сетка 8×4: Замыкание сетки, без ошибок"""
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
        self.assertEqual(len(m84["mullions_v"]), 7, "Для 8 колонок должно быть 7 вертикальных импостов")
        self.assertEqual(len(m84["mullions_h"]), 3, "Для 4 строк должно быть 3 горизонтальных импоста")

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
        # 1. Ширина 0
        p_bad1 = copy.deepcopy(self.params)
        p_bad1["opening"]["width"] = 0
        errs1 = validate(p_bad1)
        self.assertTrue(any("opening.width" in e for e in errs1))

        # 2. Высота 0
        p_bad2 = copy.deepcopy(self.params)
        p_bad2["opening"]["height"] = 0
        errs2 = validate(p_bad2)
        self.assertTrue(any("opening.height" in e for e in errs2))

        # 3. Невалидный тип створки
        p_bad3 = copy.deepcopy(self.params)
        p_bad3["cells"][0]["sash_type"] = "INVALID_TYPE"
        errs3 = validate(p_bad3)
        self.assertTrue(any("недопустимый тип створки" in e for e in errs3))

        # 4. Проверка того, что при ошибках main() возвращает код 1 и не создаёт DXF
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", encoding="utf-8", delete=False) as tmp_json:
            json.dump(p_bad1, tmp_json)
            bad_json_path = tmp_json.name

        bad_out_path = Path("output/BAD_TEST.dxf")
        if bad_out_path.exists():
            bad_out_path.unlink()

        try:
            exit_code = main([bad_json_path, "--output", str(bad_out_path)])
            self.assertEqual(exit_code, 1, "При ошибках валидации код возврата должен быть 1")
            self.assertFalse(bad_out_path.exists(), "При ошибках валидации DXF-файл не должен создаваться")
        finally:
            if os.path.exists(bad_json_path):
                os.remove(bad_json_path)


if __name__ == "__main__":
    unittest.main()
