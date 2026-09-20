#!/usr/bin/env python3
"""
Window Block Export (WinPlax)
Версия: 0.2 (Скорректированная по итогам тестирования v0.1)
Назначение: Формирование параметрической модели окна и экспорт в DXF/DWG блок без использования AutoCAD.
Соответствует ТЗ 0.2: ГОСТ 21.501 / 23166, проём, рама 45°, створки двухконтурные 80 мм, ГОСТ-стрелки, атрибуты Arial 18 мм.
"""

from __future__ import annotations

import argparse
import copy
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

    # 12. Ширина бруска створки (profile_width) по ТЗ 0.2
    pw = sash.get("profile_width", 80)
    if pw is not None:
        try:
            pw_f = float(pw)
            if pw_f < 0:
                errors.append("Ширина бруска створки (sash.profile_width) должна быть >= 0")
            elif pw_f == 0:
                # 0 допустимо только для FIX? но лучше требовать >0 если есть створки
                pass
        except (TypeError, ValueError):
            errors.append("Ширина бруска створки (sash.profile_width) должна быть числом")

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


def calc_opening(ow: float, oh: float) -> list[tuple[float, float]]:
    """
    Расчёт габаритного контура проёма в стене.
    По ТЗ 0.2: прямоугольник (0,0) .. (OW, OH)
    """
    return [
        (0.0, 0.0),
        (float(ow), 0.0),
        (float(ow), float(oh)),
        (0.0, float(oh)),
    ]


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


def calc_frame_mitres(ow: float, oh: float, s: float, fw: float, fh: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Расчёт косых стыков коробки рамы под 45° (4 диагонали между внешним и внутренним углами).
    По ТЗ 0.2 п.3.3:
      Левый нижний: (S,S) -> (S+FW, S+FH)
      Правый нижний: (OW-S,S) -> (OW-S-FW, S+FH)
      Правый верхний: (OW-S,OH-S) -> (OW-S-FW, OH-S-FH)
      Левый верхний: (S,OH-S) -> (S+FW, OH-S-FH)
    """
    return [
        ((s, s), (s + fw, s + fh)),
        ((ow - s, s), (ow - s - fw, s + fh)),
        ((ow - s, oh - s), (ow - s - fw, oh - s - fh)),
        ((s, oh - s), (s + fw, oh - s - fh)),
    ]


def calc_sill(params: dict[str, Any], ow: float, s: float) -> list[tuple[float, float]] | None:
    """
    Расчёт контура подставочного профиля (LWPOLYLINE прямоугольник).
    Доработка по замечанию: профиль съехал в отрицательную Y, правильно:
      без подставочника: рама с y=S (30)
      с подставочником: sill  y=S .. S+SH (30..60), рама с y=S+SH (60)
    Т.е. зазор S между проёмом (y=0) и низом подставочника (y=S), высота SH, рама над ним.
    Прямоугольник: [(S, S), (OW-S, S), (OW-S, S+SH), (S, S+SH)]  при sill.on
    (Ранее ошибочно было ниже 0)
    """
    sill_cfg = params.get("sill", {})
    if not sill_cfg.get("on", False):
        return None

    sh = float(sill_cfg.get("height", 30))
    sill_bottom = float(s)
    sill_top = sill_bottom + sh
    return [
        (s, sill_bottom),
        (ow - s, sill_bottom),
        (ow - s, sill_top),
        (s, sill_top),
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


def calc_sashes(
    cells: list[dict[str, Any]],
    overlap: float,
    profile_width: float = 80.0,
) -> list[dict[str, Any]]:
    """
    Расчёт примитивов для створок по ТЗ 0.2.

    Для каждой ячейки с sash_type != FIX:
      - Наружный контур: [(x1-SO,y1-SO) .. (x2+SO,y2+SO)]
      - Внутренний контур (брусок SW): [(x1-SO+SW, y1-SO+SW) .. (x2+SO-SW, y2+SO-SW)]
      - 4 диагональных стыка под 45° между наружным и внутренним углами
      - Линии открывания по ГОСТ 21.501 / 23166 по световому проёму створки [in_x1,in_x2] x [in_y1,in_y2]:
          TURN:  две линии из углов стороны петель к центру ручки: (in_x1,in_y1)->(in_x2,ymid) и (in_x1,in_y2)->(in_x2,ymid)
          TILT:  две линии из нижних углов к центру верхней ручки: (in_x1,in_y1)->(xmid,in_y2) и (in_x2,in_y1)->(xmid,in_y2)
          TURN_TILT: совмещение TURN + TILT (4 линии)
          FIX: линий нет

    Сохраняет совместимость со старым API calc_sashes(cells, overlap) -> profile_width по умолчанию 80.
    Возвращает список словарей с ключами:
      cell, sash_type, outer_contour, inner_contour, mitres, indicators,
      а также для совместимости contour (=outer_contour)
    """
    sashes: list[dict[str, Any]] = []
    for cell in cells:
        stype = cell["sash_type"]
        if stype == "FIX":
            continue

        x1 = float(cell["x1"]) - float(overlap)
        y1 = float(cell["y1"]) - float(overlap)
        x2 = float(cell["x2"]) + float(overlap)
        y2 = float(cell["y2"]) + float(overlap)

        sw = float(profile_width)

        # Наружный контур створки (4 линии)
        outer_contour: list[tuple[tuple[float, float], tuple[float, float]]] = [
            ((x1, y1), (x2, y1)),
            ((x2, y1), (x2, y2)),
            ((x2, y2), (x1, y2)),
            ((x1, y2), (x1, y1)),
        ]

        # Внутренний контур (световой проём стеклопакета) с отступом SW
        in_x1 = x1 + sw
        in_y1 = y1 + sw
        in_x2 = x2 - sw
        in_y2 = y2 - sw

        # Защита от вырожденного контура (если SW слишком велик) - не валидируем жестко, но пропускаем если вырожден
        if in_x2 <= in_x1 or in_y2 <= in_y1:
            # Тогда внутренний контур вырожден - пропускаем створку как ошибку геометрии, но лучше создать пустой?
            # Для совместимости оставим inner_contour пустым, но mitres и indicators тоже пустые
            inner_contour: list[tuple[tuple[float, float], tuple[float, float]]] = []
            mitres: list[tuple[tuple[float, float], tuple[float, float]]] = []
            indicators: list[tuple[tuple[float, float], tuple[float, float]]] = []
        else:
            inner_contour = [
                ((in_x1, in_y1), (in_x2, in_y1)),
                ((in_x2, in_y1), (in_x2, in_y2)),
                ((in_x2, in_y2), (in_x1, in_y2)),
                ((in_x1, in_y2), (in_x1, in_y1)),
            ]

            # 4 диагональных стыка под 45° в углах створки (между наружным и внутренним углами)
            mitres = [
                ((x1, y1), (in_x1, in_y1)),  # левый нижний
                ((x2, y1), (in_x2, in_y1)),  # правый нижний
                ((x2, y2), (in_x2, in_y2)),  # правый верхний
                ((x1, y2), (in_x1, in_y2)),  # левый верхний
            ]

            # Линии открывания по ГОСТ (по световому проёму)
            indicators = []
            y_mid = (in_y1 + in_y2) / 2.0
            x_mid = (in_x1 + in_x2) / 2.0

            if stype == "TURN":
                # Поворотная: две линии из углов стороны петель (левой) к центру ручки на противоположной (правой) стороне
                indicators.append(((in_x1, in_y1), (in_x2, y_mid)))
                indicators.append(((in_x1, in_y2), (in_x2, y_mid)))
            elif stype == "TILT":
                # Откидная/фрамуга: две линии из нижних углов к центру верхней ручки
                indicators.append(((in_x1, in_y1), (x_mid, in_y2)))
                indicators.append(((in_x2, in_y1), (x_mid, in_y2)))
            elif stype == "TURN_TILT":
                # Поворотно-откидная: совмещение TURN + TILT = 4 линии
                indicators.append(((in_x1, in_y1), (in_x2, y_mid)))
                indicators.append(((in_x1, in_y2), (in_x2, y_mid)))
                indicators.append(((in_x1, in_y1), (x_mid, in_y2)))
                indicators.append(((in_x2, in_y1), (x_mid, in_y2)))
            else:
                # FIX уже отфильтрован, но для безопасности
                indicators = []

        sashes.append({
            "cell": (cell["row"], cell["col"]),
            "sash_type": stype,
            "contour": outer_contour,  # совместимость с v0.1 (outer)
            "outer_contour": outer_contour,
            "inner_contour": inner_contour,
            "mitres": mitres,
            "indicators": indicators,
            # для удобства храним координаты
            "outer_rect": (x1, y1, x2, y2),
            "inner_rect": (in_x1, in_y1, in_x2, in_y2) if 'in_x1' in locals() else None,
        })
    return sashes


def _clip_line_to_rect(
    x0: float, y0: float, x1: float, y1: float,
    rx1: float, ry1: float, rx2: float, ry2: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """
    Клип линии к прямоугольнику (rx1,ry1)-(rx2,ry2) по Liang-Barsky.
    Возвращает обрезанный отрезок внутри прямоугольника или None если вне.
    Используется для вида снаружи: рама/импост обрезают створку и засечки.
    """
    # Нормализуем прямоугольник
    xmin = min(rx1, rx2)
    xmax = max(rx1, rx2)
    ymin = min(ry1, ry2)
    ymax = max(ry1, ry2)
    dx = x1 - x0
    dy = y1 - y0
    p = [-dx, dx, -dy, dy]
    q = [x0 - xmin, xmax - x0, y0 - ymin, ymax - y0]
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
        else:
            t = qi / pi if pi != 0 else 0
            # pi <0 -> entering, pi>0 -> leaving
            if pi < 0:
                if t > u1:
                    u1 = t
            else:
                if t < u2:
                    u2 = t
            if u1 > u2:
                return None
    if u1 > 1 or u2 < 0:
        return None
    # Обрезанные точки
    nx0 = x0 + u1 * dx
    ny0 = y0 + u1 * dy
    nx1 = x0 + u2 * dx
    ny1 = y0 + u2 * dy
    return ((nx0, ny0), (nx1, ny1))


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
    sw = float(params.get("sash", {}).get("profile_width", 80))

    window_name = str(params.get("window_name") or params.get("metadata", {}).get("window_name", "ОК-1")).strip()

    # Доработка: подставочник с зазором S — рама сдвигается вверх
    sill_cfg_tmp = params.get("sill", {})
    sill_on_tmp = bool(sill_cfg_tmp.get("on", False))
    sh_tmp = float(sill_cfg_tmp.get("height", 30)) if sill_on_tmp else 0.0

    # 0. Габаритный контур проёма (ТЗ 0.2 обязателен)
    opening_poly = calc_opening(ow, oh)

    # 1. Расчёт рамы с учётом подставочника (доработка: 0-рамка 30-подставочник 60-рама)
    if sill_on_tmp:
        # С подставочником: низ рамы на S+SH (60), верх как обычно OH-S
        frame_outer = [
            (s, s + sh_tmp),
            (ow - s, s + sh_tmp),
            (ow - s, oh - s),
            (s, oh - s),
        ]
        frame_inner = [
            (s + fw, s + sh_tmp + fh),
            (ow - s - fw, s + sh_tmp + fh),
            (ow - s - fw, oh - s - fh),
            (s + fw, oh - s - fh),
        ]
        # 45° стыки с учётом сдвига низа
        frame_mitres = [
            ((s, s + sh_tmp), (s + fw, s + sh_tmp + fh)),  # левый нижний
            ((ow - s, s + sh_tmp), (ow - s - fw, s + sh_tmp + fh)),  # правый нижний
            ((ow - s, oh - s), (ow - s - fw, oh - s - fh)),  # правый верхний
            ((s, oh - s), (s + fw, oh - s - fh)),  # левый верхний
        ]
    else:
        frame_outer, frame_inner = calc_frame(ow, oh, s, fw, fh)
        frame_mitres = calc_frame_mitres(ow, oh, s, fw, fh)

    # 2. Границы внутренней световой сетки (с учётом подставочника)
    x0 = s + fw
    x1 = ow - s - fw
    y0 = (s + sh_tmp + fh) if sill_on_tmp else (s + fh)
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

    # 6. Створки (двухконтурные + ГОСТ-стрелки)
    sashes = calc_sashes(cells, so, sw)

    # 6b. Доработка: для вида снаружи рама/импосты обрезают створку и косые засечки
    # Т.е. видимая часть створки ограничена ячейкой (cell), наружный контур и 45° засечки
    # обрезаются по границе ячейки (которая совпадает с внутр. гранью рамы/импоста)
    view_tmp = str(params.get("view", "OUTSIDE")).upper()
    if view_tmp == "OUTSIDE":
        for sash in sashes:
            # Найти ячейку створки
            cell = next((c for c in cells if (c["row"], c["col"]) == tuple(sash["cell"])), None)
            if cell is None:
                continue
            rx1, ry1, rx2, ry2 = cell["x1"], cell["y1"], cell["x2"], cell["y2"]
            # Обрезаем 45° засечки к ячейке
            new_mitres: list[tuple[tuple[float, float], tuple[float, float]]] = []
            for (x0, y0), (x1, y1) in sash.get("mitres", []):
                clipped = _clip_line_to_rect(x0, y0, x1, y1, rx1, ry1, rx2, ry2)
                if clipped is not None:
                    # clipped уже внутри ячейки; но нужно сохранить только видимую часть
                    # Для засечек обычно одна точка внутри (inner), вторая снаружи -> clipped даёт отрезок от границы ячейки до inner
                    # Если линия полностью внутри (редкий случай) — оставляем как есть
                    new_mitres.append(clipped)
                else:
                    # Линия полностью вне — не рисуем (обрезана рамой)
                    pass
            sash["mitres"] = new_mitres
            # Для OUTSIDE наружный контур уже скрывается в export_to_dxf, но для модели тоже пометим обрезанным
            # (не используется в примитивах для OUTSIDE)

    # 7. Подставочный профиль
    sill_poly = calc_sill(params, ow, s)

    # 8. Атрибуты блока — доработка: сливаем в одну строку (6 шт.)
    # Было 8: OBJECT, WINDOW_NAME, COLOR_OUT, COLOR_IN, GLAZING, SIZE_W, SIZE_H, GRID
    # Стало 6: Тестовый объект / ОК-1/1 шт. / RAL8017/RAL9016 / Заполнение СПД42 / 1500х1500 / 3х2
    meta = params.get("metadata", {})
    # Количество — по умолчанию 1 шт., можно задать quantity в metadata или params
    qty_raw = meta.get("quantity", params.get("quantity", "1 шт."))
    qty_str = str(qty_raw).strip()
    # Если quantity уже содержит "/", не дублируем
    window_combined = f"{window_name}/{qty_str}" if "/" not in qty_str else f"{window_name}{qty_str}"
    # Цвета — сливаем без пробелов как в примере RAL8017/RAL9016
    color_out_raw = str(meta.get("color_out", "RAL 8017"))
    color_in_raw = str(meta.get("color_in", "RAL 9016"))
    # Убираем пробелы для формата RAL8017
    color_out_nospace = color_out_raw.replace(" ", "")
    color_in_nospace = color_in_raw.replace(" ", "")
    colors_combined = f"{color_out_nospace}/{color_in_nospace}"
    # Заполнение — формат "Заполнение СПД42"
    glazing_raw = meta.get("glazing", "СПД42")
    if isinstance(glazing_raw, (int, float)):
        # числовое -> СПД{число}
        glazing_num = int(glazing_raw) if float(glazing_raw).is_integer() else glazing_raw
        glazing_val = f"Заполнение СПД{glazing_num}"
    else:
        g_str = str(glazing_raw).strip()
        if not g_str:
            glazing_val = "Заполнение СПД42"
        elif "Заполнение" in g_str:
            glazing_val = g_str
        elif "СПД" in g_str:
            glazing_val = f"Заполнение {g_str}" if not g_str.startswith("СПД") else f"Заполнение {g_str}"
            # если уже СПД42 -> Заполнение СПД42
            if g_str.startswith("СПД"):
                glazing_val = f"Заполнение {g_str}"
        else:
            # например "42" -> СПД42
            glazing_val = f"Заполнение СПД{g_str}"
    # Габарит — сливаем WхH кириллицей х (U+0445) как в примере 1500х1500
    size_combined = f"{int(ow) if ow.is_integer() else ow}х{int(oh) if oh.is_integer() else oh}"
    grid_combined = f"{cols}х{rows}"
    object_val = str(meta.get("object", "Тестовый объект"))
    attdefs = [
        ("OBJECT", "Объект", object_val),
        ("WINDOW", "Окно / кол-во", window_combined),
        ("COLOR", "Цвет", colors_combined),
        ("GLAZING", "Заполнение", glazing_val),
        ("SIZE", "Габарит", size_combined),
        ("GRID", "Сетка", grid_combined),
    ]

    # Имя блока: WW_<window_name>_<cols>x<rows>_001 (латинская x)
    block_name = f"WW_{window_name}_{cols}x{rows}_001"

    # Подсчёт примитивов для отчёта
    # opening 1 (слой Штриховые), frame outer+inner 2, frame mitres 4, mullions, sill, sashes
    # Доработка: для OUTSIDE наружный контур створки не виден -> не считаем
    view = str(params.get("view", "OUTSIDE")).upper()
    primitives_count = 1  # opening
    primitives_count += 2  # frame_outer + frame_inner (LWPOLYLINE)
    primitives_count += len(frame_mitres)  # 4 LINE
    primitives_count += len(mullions_v)  # LWPOLYLINE
    primitives_count += len(mullions_h)  # LWPOLYLINE
    if sill_poly:
        primitives_count += 1  # LWPOLYLINE
    for sash in sashes:
        if view != "OUTSIDE":
            primitives_count += len(sash["outer_contour"])  # 4 LINE только для INSIDE
        primitives_count += len(sash["inner_contour"])  # 4 LINE
        primitives_count += len(sash["mitres"])  # 4 LINE
        primitives_count += len(sash["indicators"])  # 2 или 4 LINE
    primitives_count += len(attdefs)  # ATTDEF

    return {
        "params": params,
        "window_name": window_name,
        "block_name": block_name,
        "opening": {"width": ow, "height": oh, "seam": s},
        "opening_poly": opening_poly,
        "frame_dim": {"width": ow - 2 * s, "height": oh - 2 * s},
        "grid": {"cols": cols, "rows": rows, "cell_w": cell_w, "cell_h": cell_h},
        "frame_outer": frame_outer,
        "frame_inner": frame_inner,
        "frame_mitres": frame_mitres,
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

    # 2. Создание слоёв 'Окна' и 'Штриховые' (для контура проёма)
    layer_name = "Окна"
    if layer_name not in doc.layers:
        doc.layers.add(layer_name, color=7)
    layer_opening = "Штриховые"
    if layer_opening not in doc.layers:
        try:
            # Штриховая линия для проёма
            doc.layers.add(layer_opening, color=1, linetype="DASHED")
        except Exception:
            try:
                doc.layers.add(layer_opening, color=1)
                # попытаться назначить тип линии
                doc.layers.get(layer_opening).dxf.linetype = "DASHED"
            except Exception:
                doc.layers.add(layer_opening, color=1)

    # 2b. Создание текстового стиля WindowStyle с Arial.ttf (ТЗ 0.2)
    style_name = "WindowStyle"
    if style_name not in doc.styles:
        try:
            doc.styles.new(style_name, dxfattribs={"font": "Arial.ttf"})
        except Exception:
            # Фолбэк: если шрифт не доступен, пробуем создать без него
            doc.styles.new(style_name)
    else:
        # Обновляем шрифт если уже существует но не Arial
        try:
            style = doc.styles.get(style_name)
            if style.dxf.font != "Arial.ttf":
                style.dxf.font = "Arial.ttf"
        except Exception:
            pass

    # 3. Создание определения блока
    blk = doc.blocks.new(model["block_name"])

    # 4. Добавление габаритного контура проёма (ТЗ 0.2 обязателен) - LWPOLYLINE 0,0 .. OW,OH на слое Штриховые
    blk.add_lwpolyline(
        model["opening_poly"],
        close=True,
        dxfattribs={"layer": layer_opening},
    )

    # 5. Добавление рамы (наружный и внутренний контуры)
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

    # 5b. Добавление косых стыков коробки рамы под 45° (4 LINE)
    for p1, p2 in model["frame_mitres"]:
        blk.add_line(p1, p2, dxfattribs={"layer": layer_name})

    # 6. Добавление вертикальных импостов
    for poly in model["mullions_v"]:
        blk.add_lwpolyline(
            poly,
            close=True,
            dxfattribs={"layer": layer_name},
        )

    # 7. Добавление горизонтальных импостов
    for poly in model["mullions_h"]:
        blk.add_lwpolyline(
            poly,
            close=True,
            dxfattribs={"layer": layer_name},
        )

    # 8. Добавление подставочного профиля
    if model["sill"]:
        blk.add_lwpolyline(
            model["sill"],
            close=True,
            dxfattribs={"layer": layer_name},
        )

    # 9. Добавление створок (двухконтурные + 45° стыки + ГОСТ-стрелки)
    # Доработка: вид OUTSIDE — контур наплава (наружный) не виден; вид INSIDE — наплав виден и обрезает раму
    view = str(model.get("params", {}).get("view", "OUTSIDE")).upper()
    for sash in model["sashes"]:
        # Наружный контур (наплав) — только для INSIDE, для OUTSIDE не виден
        if view != "OUTSIDE":
            for p1, p2 in sash.get("outer_contour", []):
                blk.add_line(p1, p2, dxfattribs={"layer": layer_name})
        # Внутренний контур (брусок 80 мм) — всегда
        for p1, p2 in sash.get("inner_contour", []):
            blk.add_line(p1, p2, dxfattribs={"layer": layer_name})
        # Диагональные стыки створки 45° (4) — всегда (связывают наружный и внутренний, но если наружный скрыт — всё равно рисуем)
        # Для OUTSIDE стыки всё равно нужны, т.к. они видны как часть бруска
        for p1, p2 in sash.get("mitres", []):
            blk.add_line(p1, p2, dxfattribs={"layer": layer_name})
        # Линии открывания по ГОСТ — всегда, но по доработке на слое Штриховые
        for p1, p2 in sash.get("indicators", []):
            blk.add_line(p1, p2, dxfattribs={"layer": layer_opening})
        # Совместимость: если в модели только старый contour без деления
        if not sash.get("outer_contour") and sash.get("contour"):
            # Для OUTSIDE старый контур считаем наружным и скрываем
            if view != "OUTSIDE":
                for p1, p2 in sash["contour"]:
                    blk.add_line(p1, p2, dxfattribs={"layer": layer_name})

    # 9b. Количество теперь в атрибуте WINDOW (ОК-1/1 шт.), отдельный TEXT не нужен
    # Оставлено для совместимости: если понадобится отдельный текст — раскомментировать
    pass

    # 10. Добавление 6 ATTDEF в блок (слитые строки, доработка ТЗ 0.2)
    # Доработка: сместить левее (X=-200) и крупнее (высота 22), шаг 35, чтобы не наезжали на окно
    # Ранее было X=-80, высота 18, шаг 30 — текст мог наезжать на окно при ширине проёма
    # Атрибуты: OBJECT / WINDOW(ОК-1/1 шт.) / COLOR(RAL8017/RAL9016) / GLAZING(Заполнение СПД42) / SIZE(1500х1500) / GRID(3х2)
    oh = model["opening"]["height"]
    x_attr = -200.0  # левее, гарантированно левее окна (окно с 0, текст шириной ~185 при 22мм -> до -15, не наезжает)
    y_start = float(oh)  # ТЗ: Y = OH (1500.0)
    step = 35.0  # увеличенный шаг под крупнее шрифт
    height = 22.0  # крупнее (было 18)

    for idx, (tag, prompt, value) in enumerate(model["attdefs"]):
        y = y_start - idx * step
        blk.add_attdef(
            tag=tag,
            insert=(x_attr, y),
            text=value,
            height=height,
            dxfattribs={
                "prompt": prompt,
                "layer": layer_name,
                "style": style_name,
            },
        )

    # 11. Вставка BlockReference в пространство модели (ModelSpace) в точке (0, 0)
    msp = doc.modelspace()
    bref = msp.add_blockref(
        model["block_name"],
        insert=(0.0, 0.0),
        dxfattribs={"layer": layer_name},
    )

    # Привязка атрибутов к вхождению блока (ATTRIB)
    attrib_values = {tag: value for tag, _, value in model["attdefs"]}
    bref.add_auto_attribs(attrib_values)

    # Убеждаемся, что все ATTRIB на слое 'Окна' и стиль/высота корректны
    for attrib in bref.attribs:
        attrib.dxf.layer = layer_name
        # Стиль и высота атрибута должны наследоваться, но явно выставим для надёжности
        try:
            attrib.dxf.style = style_name
            attrib.dxf.height = height
        except Exception:
            pass

    # 12. Сохранение DXF
    doc.saveas(out_file)


def find_oda() -> str | None:
    """Поиск установленного ODA File Converter в стандартных путях и PATH (поддержка winget, любые версии)."""
    import glob as _glob
    # Статичные пути + glob для любых версий (включая winget 27.1)
    oda_patterns = [
        r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
        r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
        r"C:\Program Files\ODA\*\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
        r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
    ]
    for pat in oda_patterns:
        # если без wildcards — просто проверить
        if "*" not in pat:
            if os.path.exists(pat):
                return pat
        else:
            for cand in _glob.glob(pat):
                if os.path.isfile(cand):
                    return cand

    # Также проверить winget Packages (иногда ставит туда)
    winget_glob = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\ODA.ODAFileConverter*\*")
    for cand in _glob.glob(winget_glob):
        # искать exe внутри
        for exe in _glob.glob(os.path.join(cand, "ODAFileConverter.exe")):
            if os.path.isfile(exe):
                return exe
        for exe in _glob.glob(os.path.join(cand, "**", "ODAFileConverter.exe"), recursive=True):
            if os.path.isfile(exe):
                return exe

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

    # Доработка: для совместимости с AutoCAD 2016/2023 используем ACAD2013 (R2013, AC1027)
    # ACAD2018 (R2018) не читается в 2016 (макс. R2013), а DXF у нас R2013 — оставляем единый формат 2013
    cmd = [
        oda,
        str(out_dir),
        str(out_dir),
        "ACAD2013",
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
        description="Генерация блока окна и экспорт в DXF/DWG (WinPlax v0.2)"
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
        import traceback; traceback.print_exc()
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
        import traceback; traceback.print_exc()
        return 1

    # Опциональная конвертация в DWG
    convert_to_dwg(out_dxf_path)

    # Дополнительно: вид изнутри для отработки ошибок (если основной OUTSIDE)
    try:
        current_view = str(params.get("view", "OUTSIDE")).upper()
        if current_view == "OUTSIDE":
            inside_params = copy.deepcopy(params)
            inside_params["view"] = "INSIDE"
            inside_model = build_window_model(inside_params)
            # Имя файла с суффиксом _INSIDE (для отработки)
            inside_path = out_dxf_path.parent / f"{inside_model['window_name']}_INSIDE.dxf"
            export_to_dxf(inside_model, inside_path)
            isize = inside_path.stat().st_size / 1024.0
            print(f"  Вид изнутри (для отработки): ./{inside_path.as_posix()} ({isize:.1f} KB)")
            convert_to_dwg(inside_path)
    except Exception as e:
        print(f"  Не удалось сформировать вид изнутри: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
