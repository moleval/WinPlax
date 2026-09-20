#!/usr/bin/env python3
"""
Window Block Export (WinPlax Prototype)
Версия: 0.1
Назначение: Формирование параметрической модели окна и экспорт в DXF/DWG блок без использования AutoCAD.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import ezdxf


def load_params(path: str | Path) -> dict[str, Any]:
    """
    Загрузка параметров окна из JSON-файла.

    :param path: Путь к файлу params.json
    :return: Словарь с параметрами окна
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Файл параметров не найден: {path}")

    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def validate(params: dict[str, Any]) -> list[str]:
    """
    Валидация параметров окна перед построением модели.

    :param params: Словарь с параметрами
    :return: Список ошибок (пустой, если всё корректно)
    """
    errors: list[str] = []

    # 1. Проверка обязательных секций
    for req_key in ("opening", "frame", "cols", "rows"):
        if req_key not in params:
            errors.append(f"Отсутствует обязательная секция '{req_key}'")

    if errors:
        return errors

    # 2. Имя окна
    window_name = params.get("window_name") or params.get("metadata", {}).get("window_name", "")
    if not window_name or not str(window_name).strip():
        errors.append("Не указано имя окна ('window_name')")

    # 3. Габариты проёма
    opening = params.get("opening", {})
    ow = opening.get("width")
    oh = opening.get("height")
    seam = opening.get("seam", 0)

    if ow is None or ow <= 0:
        errors.append("Ширина проёма (opening.width) должна быть > 0")
    if oh is None or oh <= 0:
        errors.append("Высота проёма (opening.height) должна быть > 0")
    if seam is None or seam < 0:
        errors.append("Монтажный шов (opening.seam) должен быть >= 0")

    # 4. Профиль рамы
    frame = params.get("frame", {})
    fw = frame.get("face_width")
    fh = frame.get("face_height")

    if fw is None or fw <= 0:
        errors.append("Ширина профиля рамы (frame.face_width) должна быть > 0")
    if fh is None or fh <= 0:
        errors.append("Высота профиля рамы (frame.face_height) должна быть > 0")

    # 5. Проверка вхождения рамы в проём
    if ow is not None and seam is not None and fw is not None:
        if 2 * (seam + fw) >= ow:
            errors.append(
                f"Габариты рамы со швами (2 × ({seam} + {fw}) = {2*(seam+fw)}) "
                f"превышают ширину проёма ({ow})"
            )

    if oh is not None and seam is not None and fh is not None:
        if 2 * (seam + fh) >= oh:
            errors.append(
                f"Габариты рамы со швами (2 × ({seam} + {fh}) = {2*(seam+fh)}) "
                f"превышают высоту проёма ({oh})"
            )

    # 6. Сетка (колонки и строки)
    cols = params.get("cols")
    rows = params.get("rows")
    if not isinstance(cols, int) or cols < 1:
        errors.append("Количество колонок (cols) должно быть целым числом >= 1")
    if not isinstance(rows, int) or rows < 1:
        errors.append("Количество строк (rows) должно быть целым числом >= 1")

    # 7. Импосты
    mullion = params.get("mullion", {})
    mw = mullion.get("width", 0)
    mh = mullion.get("height", 0)
    if mw < 0:
        errors.append("Ширина импоста (mullion.width) должна быть >= 0")
    if mh < 0:
        errors.append("Высота импоста (mullion.height) должна быть >= 0")

    # 8. Расчётные размеры ячеек
    if ow and oh and seam is not None and fw and fh and cols and rows and cols >= 1 and rows >= 1:
        grid_w = (ow - seam - fw) - (seam + fw)
        grid_h = (oh - seam - fh) - (seam + fh)
        sum_v = (cols - 1) * mw
        sum_h = (rows - 1) * mh

        if grid_w - sum_v <= 0:
            errors.append(
                f"Ширина светового проёма сетки ({grid_w}) недостаточна для {cols} колонок "
                f"и импостов общей шириной {sum_v}"
            )
        if grid_h - sum_h <= 0:
            errors.append(
                f"Высота светового проёма сетки ({grid_h}) недостаточна для {rows} строк "
                f"и импостов общей высотой {sum_h}"
            )

    # 9. Проверка ячеек (cells)
    allowed_sash_types = {"FIX", "TURN", "TILT", "TURN_TILT"}
    cells = params.get("cells", [])
    if not isinstance(cells, list):
        errors.append("Секция 'cells' должна быть списком")
    else:
        seen_cells: set[tuple[int, int]] = set()
        for idx, cell in enumerate(cells, start=1):
            r = cell.get("row")
            c = cell.get("col")
            stype = str(cell.get("sash_type", "")).upper()

            if not isinstance(r, int) or not isinstance(c, int):
                errors.append(f"Ячейка #{idx}: индексы row и col должны быть целыми числами")
                continue

            if cols and (c < 1 or c > cols):
                errors.append(f"Ячейка #{idx}: col={c} выходит за пределы [1, {cols}]")
            if rows and (r < 1 or r > rows):
                errors.append(f"Ячейка #{idx}: row={r} выходит за пределы [1, {rows}]")

            if (r, c) in seen_cells:
                errors.append(f"Дублирующаяся ячейка row={r}, col={c}")
            seen_cells.add((r, c))

            if stype not in allowed_sash_types:
                errors.append(
                    f"Ячейка row={r}, col={c}: недопустимый тип створки '{stype}'. "
                    f"Допустимо: {', '.join(sorted(allowed_sash_types))}"
                )

    # 10. Подставочный профиль
    sill = params.get("sill", {})
    if sill.get("on", False):
        sh = sill.get("height", 0)
        if sh <= 0:
            errors.append("Высота подставочного профиля (sill.height) должна быть > 0")

    # 11. Наплав створки
    sash = params.get("sash", {})
    so = sash.get("overlap", 0)
    if so < 0:
        errors.append("Наплав створки (sash.overlap) должен быть >= 0")

    return errors


def calc_strips_x(x0: float, cell_w: float, mw: float, cols: int) -> list[tuple[float, float]]:
    """Расчёт координат колонок по оси X: [(x_start, x_end), ...]"""
    strips: list[tuple[float, float]] = []
    for i in range(cols):
        x1 = x0 + i * (cell_w + mw)
        x2 = x1 + cell_w
        strips.append((x1, x2))
    return strips


def calc_strips_y(y0: float, cell_h: float, mh: float, rows: int) -> list[tuple[float, float]]:
    """Расчёт координат строк по оси Y: [(y_start, y_end), ...] (снизу вверх)"""
    strips: list[tuple[float, float]] = []
    for j in range(rows):
        y1 = y0 + j * (cell_h + mh)
        y2 = y1 + cell_h
        strips.append((y1, y2))
    return strips


def calc_frame(ow: float, oh: float, s: float, fw: float, fh: float) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """
    Расчёт внешнего и внутреннего контуров рамы окна.
    Внешний: (S, S) .. (OW - S, OH - S)
    Внутренний: (S + FW, S + FH) .. (OW - S - FW, OH - S - FH)
    """
    frame_outer = [
        (s, s),
        (ow - s, s),
        (ow - s, oh - s),
        (s, oh - s),
    ]
    frame_inner = [
        (s + fw, s + fh),
        (ow - s - fw, s + fh),
        (ow - s - fw, oh - s - fh),
        (s + fw, oh - s - fh),
    ]
    return frame_outer, frame_inner


def calc_sill(params: dict[str, Any], ow: float, s: float) -> list[tuple[float, float]] | None:
    """
    Расчёт контура подставочного профиля (LWPOLYLINE прямоугольник).
    Располагается под нижним бруском рамы: от y = S - SH до y = S.
    """
    sill_cfg = params.get("sill", {})
    if not sill_cfg.get("on", False):
        return None

    sh = float(sill_cfg.get("height", 30))
    return [
        (s, s - sh),
        (ow - s, s - sh),
        (ow - s, s),
        (s, s),
    ]


def calc_cells(
    strips_x: list[tuple[float, float]],
    strips_y: list[tuple[float, float]],
    cells_def: list[dict[str, Any]],
    cols: int,
    rows: int,
) -> list[dict[str, Any]]:
    """Формирование полной сетки ячеек с координатами и типами створок."""
    cell_map: dict[tuple[int, int], str] = {}
    for cd in cells_def:
        r = cd.get("row")
        c = cd.get("col")
        stype = str(cd.get("sash_type", "FIX")).upper()
        if r is not None and c is not None:
            cell_map[(r, c)] = stype

    cells: list[dict[str, Any]] = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            x1, x2 = strips_x[c - 1]
            y1, y2 = strips_y[r - 1]
            stype = cell_map.get((r, c), "FIX")
            cells.append({
                "row": r,
                "col": c,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "sash_type": stype,
            })
    return cells


def calc_sashes(cells: list[dict[str, Any]], overlap: float) -> list[dict[str, Any]]:
    """
    Расчёт примитивов для створок:
    - Контур створки (4 линии с учётом наплава SO)
    - Дополнительные линии для индикации открывания (TILT, TURN_TILT)
    """
    sashes: list[dict[str, Any]] = []
    for cell in cells:
        stype = cell["sash_type"]
        if stype == "FIX":
            continue

        x1 = cell["x1"] - overlap
        y1 = cell["y1"] - overlap
        x2 = cell["x2"] + overlap
        y2 = cell["y2"] + overlap

        # 4 линии внешнего контура створки
        contour = [
            ((x1, y1), (x2, y1)),
            ((x2, y1), (x2, y2)),
            ((x2, y2), (x1, y2)),
            ((x1, y2), (x1, y1)),
        ]

        # Линии индикации открывания
        indicators: list[tuple[tuple[float, float], tuple[float, float]]] = []
        if stype == "TILT":
            # Диагональная линия откидывания
            indicators.append(((x1, y1), (x2, y2)))
        elif stype == "TURN_TILT":
            # Поворотно-откидная: средняя горизонталь + 2 наклонные линии
            y_mid = (y1 + y2) / 2.0
            indicators.append(((x1, y_mid), (x2, y_mid)))
            indicators.append(((x1, y1), (x2, y_mid)))
            indicators.append(((x1, y_mid), (x2, y2)))

        sashes.append({
            "cell": (cell["row"], cell["col"]),
            "sash_type": stype,
            "contour": contour,
            "indicators": indicators,
        })
    return sashes


def build_window_model(params: dict[str, Any]) -> dict[str, Any]:
    """
    Построение параметрической геометрической модели окна.

    :param params: Параметры окна
    :return: Модель окна (координаты контуров, импостов, ячеек, створок, атрибутов)
    """
    ow = float(params["opening"]["width"])
    oh = float(params["opening"]["height"])
    s = float(params["opening"]["seam"])

    fw = float(params["frame"]["face_width"])
    fh = float(params["frame"]["face_height"])

    mw = float(params.get("mullion", {}).get("width", 0))
    mh = float(params.get("mullion", {}).get("height", 0))

    cols = int(params["cols"])
    rows = int(params["rows"])

    so = float(params.get("sash", {}).get("overlap", 15))
    window_name = str(params.get("window_name") or params.get("metadata", {}).get("window_name", "ОК-1")).strip()

    # 1. Расчёт рамы
    frame_outer, frame_inner = calc_frame(ow, oh, s, fw, fh)

    # 2. Границы внутренней световой сетки
    x0 = s + fw
    x1 = ow - s - fw
    y0 = s + fh
    y1 = oh - s - fh

    grid_w = x1 - x0
    grid_h = y1 - y0

    sum_v = (cols - 1) * mw
    sum_h = (rows - 1) * mh

    cell_w = (grid_w - sum_v) / cols
    cell_h = (grid_h - sum_h) / rows

    # 3. Проверка замыкания сетки ТЗ 1.2 (±1e-6)
    delta_x = abs(cols * cell_w + sum_v - grid_w)
    delta_y = abs(rows * cell_h + sum_h - grid_h)
    if delta_x > 1e-6 or delta_y > 1e-6:
        raise ValueError(
            f"Ошибка замыкания сетки: dX={delta_x:.2e}, dY={delta_y:.2e}"
        )

    # 4. Расчёт полос и ячеек
    strips_x = calc_strips_x(x0, cell_w, mw, cols)
    strips_y = calc_strips_y(y0, cell_h, mh, rows)
    cells = calc_cells(strips_x, strips_y, params.get("cells", []), cols, rows)

    # 5. Импосты
    mullions_v: list[list[tuple[float, float]]] = []
    for i in range(1, cols):
        x = x0 + i * cell_w + (i - 1) * mw
        mullions_v.append([
            (x, y0),
            (x + mw, y0),
            (x + mw, y1),
            (x, y1),
        ])

    mullions_h: list[list[tuple[float, float]]] = []
    for j in range(1, rows):
        y = y0 + j * cell_h + (j - 1) * mh
        mullions_h.append([
            (x0, y),
            (x1, y),
            (x1, y + mh),
            (x0, y + mh),
        ])

    # 6. Створки
    sashes = calc_sashes(cells, so)

    # 7. Подставочный профиль
    sill_poly = calc_sill(params, ow, s)

    # 8. Атрибуты блока (8 шт. по ТЗ)
    meta = params.get("metadata", {})
    attdefs = [
        ("OBJECT", "Объект", str(meta.get("object", "Тестовый объект"))),
        ("WINDOW_NAME", "Название окна", window_name),
        ("COLOR_OUT", "Цвет снаружи", str(meta.get("color_out", "RAL 8017"))),
        ("COLOR_IN", "Цвет изнутри", str(meta.get("color_in", "RAL 9016"))),
        ("GLAZING", "Толщина заполнения", str(meta.get("glazing", "32"))),
        ("SIZE_W", "Ширина проёма", f"{int(ow) if ow.is_integer() else ow}"),
        ("SIZE_H", "Высота проёма", f"{int(oh) if oh.is_integer() else oh}"),
        ("GRID", "Сетка", f"{cols}×{rows}"),
    ]

    # Имя блока: WW_<window_name>_<cols>x<rows>_001
    block_name = f"WW_{window_name}_{cols}x{rows}_001"

    # Подсчёт примитивов для отчёта
    primitives_count = 2  # frame_outer + frame_inner (LWPOLYLINE)
    primitives_count += len(mullions_v)  # LWPOLYLINE
    primitives_count += len(mullions_h)  # LWPOLYLINE
    if sill_poly:
        primitives_count += 1  # LWPOLYLINE
    for sash in sashes:
        primitives_count += len(sash["contour"]) + len(sash["indicators"])  # LINEs
    primitives_count += len(attdefs)  # ATTDEF

    return {
        "params": params,
        "window_name": window_name,
        "block_name": block_name,
        "opening": {"width": ow, "height": oh, "seam": s},
        "frame_dim": {"width": ow - 2 * s, "height": oh - 2 * s},
        "grid": {"cols": cols, "rows": rows, "cell_w": cell_w, "cell_h": cell_h},
        "frame_outer": frame_outer,
        "frame_inner": frame_inner,
        "strips_x": strips_x,
        "strips_y": strips_y,
        "mullions_v": mullions_v,
        "mullions_h": mullions_h,
        "cells": cells,
        "sashes": sashes,
        "sill": sill_poly,
        "attdefs": attdefs,
        "primitives_count": primitives_count,
    }


def export_to_dxf(model: dict[str, Any], output_path: str | Path) -> None:
    """
    Экспорт геометрической модели окна в файл DXF версии R2013.

    :param model: Модель окна от build_window_model
    :param output_path: Путь для сохранения файла .dxf
    """
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Создание документа DXF версии R2013 (AutoCAD 2013+)
    doc = ezdxf.new("R2013")
    doc.encoding = "cp1251"
    doc.header["$DWGCODEPAGE"] = "ANSI_1251"

    # 2. Создание слоя 'Окна'
    layer_name = "Окна"
    if layer_name not in doc.layers:
        doc.layers.add(layer_name, color=7)

    # 3. Создание определения блока
    blk = doc.blocks.new(model["block_name"])

    # 4. Добавление рамы (наружный и внутренний контуры)
    blk.add_lwpolyline(
        model["frame_outer"],
        close=True,
        dxfattribs={"layer": layer_name},
    )
    blk.add_lwpolyline(
        model["frame_inner"],
        close=True,
        dxfattribs={"layer": layer_name},
    )

    # 5. Добавление вертикальных импостов
    for poly in model["mullions_v"]:
        blk.add_lwpolyline(
            poly,
            close=True,
            dxfattribs={"layer": layer_name},
        )

    # 6. Добавление горизонтальных импостов
    for poly in model["mullions_h"]:
        blk.add_lwpolyline(
            poly,
            close=True,
            dxfattribs={"layer": layer_name},
        )

    # 7. Добавление подставочного профиля
    if model["sill"]:
        blk.add_lwpolyline(
            model["sill"],
            close=True,
            dxfattribs={"layer": layer_name},
        )

    # 8. Добавление створок (линии контура и индикации)
    for sash in model["sashes"]:
        for p1, p2 in sash["contour"]:
            blk.add_line(p1, p2, dxfattribs={"layer": layer_name})
        for p1, p2 in sash["indicators"]:
            blk.add_line(p1, p2, dxfattribs={"layer": layer_name})

    # 9. Добавление 8 ATTDEF в блок
    oh = model["opening"]["height"]
    y_offset = oh + 100.0
    for tag, prompt, value in model["attdefs"]:
        blk.add_attdef(
            tag=tag,
            insert=(-100.0, y_offset),
            text=value,
            height=50.0,
            dxfattribs={
                "prompt": prompt,
                "layer": layer_name,
            },
        )
        y_offset -= 80.0

    # 10. Вставка BlockReference в пространство модели (ModelSpace) в точке (0, 0)
    msp = doc.modelspace()
    bref = msp.add_blockref(
        model["block_name"],
        insert=(0.0, 0.0),
        dxfattribs={"layer": layer_name},
    )

    # Привязка атрибутов к вхождению блока (ATTRIB)
    attrib_values = {tag: value for tag, _, value in model["attdefs"]}
    bref.add_auto_attribs(attrib_values)

    # Убеждаемся, что все ATTRIB на слое 'Окна'
    for attrib in bref.attribs:
        attrib.dxf.layer = layer_name

    # 11. Сохранение DXF
    doc.saveas(out_file)


def find_oda() -> str | None:
    """Поиск установленного ODA File Converter в стандартных путях и PATH."""
    oda_paths = [
        r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
        r"C:\Program Files\ODA\ODAFileConverter 25.4.0\ODAFileConverter.exe",
        r"C:\Program Files\ODA\ODAFileConverter 24.12.0\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
    ]
    for p in oda_paths:
        if os.path.exists(p):
            return p

    for name in ("ODAFileConverter", "odafileconverter"):
        found = shutil.which(name)
        if found:
            return found

    return None


def convert_to_dwg(dxf_path: str | Path) -> str | None:
    """
    Конвертация .dxf в .dwg через ODA File Converter (если установлен).

    :param dxf_path: Путь к файлу DXF
    :return: Путь к файлу DWG или None, если ODA недоступен
    """
    oda = find_oda()
    if not oda:
        print("  ODA File Converter не найден — пропускаем конвертацию.")
        return None

    dxf_file = Path(dxf_path).resolve()
    out_dir = dxf_file.parent

    cmd = [
        oda,
        str(out_dir),
        str(out_dir),
        "ACAD2018",
        "DWG",
        "0",
        "1",
        dxf_file.name,
    ]

    try:
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        dwg_file = dxf_file.with_suffix(".dwg")
        if dwg_file.exists():
            print(f"  Конвертация DWG выполнена: {dwg_file}")
            return str(dwg_file)
        else:
            print("  ODA File Converter отработал, но DWG-файл не найден.")
            return None
    except Exception as e:
        print(f"  Ошибка вызова ODA File Converter: {e}")
        return None


def main(argv: list[str] | None = None) -> int:
    """Точка входа скрипта."""
    parser = argparse.ArgumentParser(
        description="Генерация блока окна и экспорт в DXF/DWG (WinPlax Prototype v0.1)"
    )
    parser.add_argument(
        "params",
        nargs="?",
        default="params.json",
        help="Путь к JSON-файлу параметров (по умолчанию: params.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Путь к результирующему DXF-файлу (по умолчанию: output/<window_name>.dxf)",
    )
    args = parser.parse_args(argv)

    # 1. Поиск и загрузка params.json
    params_path = Path(args.params)
    if not params_path.is_file():
        script_dir_params = Path(__file__).parent / args.params
        if script_dir_params.is_file():
            params_path = script_dir_params
        else:
            print(f"Ошибка: файл параметров '{args.params}' не найден.")
            return 1

    try:
        print("[1/6] Загрузка параметров... OK")
        params = load_params(params_path)
    except Exception as e:
        print(f"[1/6] Загрузка параметров... ОШИБКА: {e}")
        return 1

    # 2. Валидация
    errors = validate(params)
    if errors:
        print(f"[2/6] Валидация... НАЙДЕНЫ ОШИБКИ ({len(errors)}):")
        for err in errors:
            print(f"      - {err}")
        return 1
    print("[2/6] Валидация... OK")

    # 3. Расчёт геометрии
    try:
        model = build_window_model(params)
        ow = model["opening"]["width"]
        oh = model["opening"]["height"]
        fw = model["frame_dim"]["width"]
        fh = model["frame_dim"]["height"]
        cols = model["grid"]["cols"]
        rows = model["grid"]["rows"]
        cell_w = model["grid"]["cell_w"]
        cell_h = model["grid"]["cell_h"]

        print("[3/6] Расчёт геометрии... OK")
        print(f"      Проём:      {ow:g} × {oh:g} мм")
        print(f"      Рама:       {fw:g} × {fh:g} мм (наружный)")
        print(f"      Сетка:      {cols} × {rows}")
        print(f"      Ширина ячейки: {cell_w:.2f} мм")
        print(f"      Высота ячейки: {cell_h:.2f} мм")
        print("      Проверка замыкания: OK")
    except Exception as e:
        print(f"[3/6] Расчёт геометрии... ОШИБКА: {e}")
        return 1

    # 4. Построение модели
    print("[4/6] Построение модели... OK")
    print(f"      Примитивов: {model['primitives_count']}")

    # 5. Создание блока
    print("[5/6] Создание блока... OK")
    print(f"      Имя блока:  {model['block_name']}")

    # 6. Экспорт в DXF
    if args.output:
        out_dxf_path = Path(args.output)
    else:
        out_dxf_path = Path("output") / f"{model['window_name']}.dxf"

    try:
        export_to_dxf(model, out_dxf_path)
        size_bytes = out_dxf_path.stat().st_size
        size_kb = size_bytes / 1024.0

        rel_path = f"./{out_dxf_path.as_posix()}" if not str(out_dxf_path).startswith(".") else str(out_dxf_path)
        print("[6/6] Экспорт DXF... OK")
        print(f"      Файл:       {rel_path}")
        print(f"      Размер:     {size_kb:.1f} KB")
    except Exception as e:
        print(f"[6/6] Экспорт DXF... ОШИБКА: {e}")
        return 1

    # Опциональная конвертация в DWG
    convert_to_dwg(out_dxf_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
