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

# --- Шаблонные слои/стили: копирование из пользовательского DXF/DWG ---
def _copy_template_tables(doc, template_path: str | Path):
    """Копирует слои, типы линий, текстовые и размерные стили, а также заголовок из шаблона.
    Если шаблон — DXF/DWG, читает его через ezdxf и переносит таблицы в doc.
    Возвращает словарь с исходными параметрами для отладки.
    """
    tpl_path = Path(template_path)
    if not tpl_path.is_file():
        print(f"  Шаблон не найден: {tpl_path} — используем встроенные стили")
        return {}
    try:
        # DWG напрямую ezdxf не читает R2013 (AC1027) — пробуем как DXF, для DWG просим DXF
        if tpl_path.suffix.lower() == '.dwg':
            # Попытка через ezdxf DWG addon (только до R2000) — сразу подсказываем
            try:
                from ezdxf.addons.dwg import readfile as dwg_read
                tpl = dwg_read(str(tpl_path))
            except Exception as e_dwg:
                print(f"  Шаблон DWG {tpl_path.name} не удалось прочитать напрямую (ezdxf DWG до R2000, файл R2013 AC1027): {e_dwg}")
                print(f"  → Экспортируйте шаблон в DXF R2013 (AC1027) как Шаблон.dxf/БШАБЛОН.dxf и укажите --template Шаблон.dxf, либо конвертируйте DWG→DXF через ODA File Converter.")
                return {}
        else:
            tpl = ezdxf.readfile(str(tpl_path))
    except Exception as e:
        print(f"  Не удалось прочитать шаблон {tpl_path}: {e} — используем встроенные")
        # Для DWG подсказка
        if tpl_path.suffix.lower() == '.dwg':
            print(f"  → Для DWG: экспортируйте в DXF R2013 и используйте Шаблон.dxf")
        return {}
    info = {"layers": [], "styles": [], "dimstyles": [], "header": {}}
    # Копируем типы линий, которые встречаются в слоях шаблона
    for lt in tpl.linetypes:
        if lt.dxf.name not in doc.linetypes:
            try:
                # ezdxf не имеет прямого копирования, создаём по имени
                # Попробуем взять из шаблона pattern если есть
                doc.linetypes.add(lt.dxf.name, pattern=lt.pattern, description=lt.dxf.description)
            except Exception:
                try:
                    doc.linetypes.new(lt.dxf.name)
                except Exception:
                    pass
    # Слои
    for layer in tpl.layers:
        name = layer.dxf.name
        info["layers"].append((name, layer.color, layer.dxf.linetype, layer.dxf.lineweight))
        if name not in doc.layers:
            try:
                doc.layers.add(name, color=layer.color, linetype=layer.dxf.linetype, lineweight=layer.dxf.lineweight)
            except Exception:
                try:
                    doc.layers.add(name, color=layer.color)
                    # попробовать установить тип линии отдельно
                    try:
                        doc.layers.get(name).dxf.linetype = layer.dxf.linetype
                    except Exception:
                        pass
                except Exception:
                    pass
        else:
            # Обновляем существующий слой параметрами из шаблона (цвет, тип линии)
            try:
                dst = doc.layers.get(name)
                dst.color = layer.color
                try:
                    dst.dxf.linetype = layer.dxf.linetype
                except Exception:
                    pass
                try:
                    dst.dxf.lineweight = layer.dxf.lineweight
                except Exception:
                    pass
            except Exception:
                pass
    # Текстовые стили
    for s in tpl.styles:
        name = s.dxf.name
        info["styles"].append((name, s.dxf.font, s.dxf.width, getattr(s.dxf, "oblique", 0), getattr(s.dxf, "is_vertical", 0)))
        if name not in doc.styles:
            try:
                doc.styles.new(name, dxfattribs={"font": s.dxf.font})
                # ширина/наклон
                try:
                    ns = doc.styles.get(name)
                    ns.dxf.width = s.dxf.width
                    for attr in ("oblique", "is_vertical", "is_backward", "is_upside_down", "last_height"):
                        if hasattr(s.dxf, attr):
                            try:
                                setattr(ns.dxf, attr, getattr(s.dxf, attr))
                            except Exception:
                                pass
                except Exception:
                    pass
            except Exception:
                pass
        else:
            # обновляем шрифт если отличается
            try:
                dst = doc.styles.get(name)
                dst.dxf.font = s.dxf.font
            except Exception:
                pass
    # Размерные стили
    for ds in tpl.dimstyles:
        name = ds.dxf.name
        info["dimstyles"].append(name)
        if name not in doc.dimstyles:
            try:
                nds = doc.dimstyles.new(name)
                # копируем все доступные атрибуты dim*
                for attr in dir(ds.dxf):
                    if attr.startswith("dim"):
                        try:
                            setattr(nds.dxf, attr, getattr(ds.dxf, attr))
                        except Exception:
                            pass
                # также dimtxsty
                try:
                    nds.dxf.dimtxsty = ds.dxf.dimtxsty
                except Exception:
                    pass
            except Exception:
                pass
        else:
            # обновляем существующий? не трогаем, чтобы не ломать наши размеры, но можно скопировать если шаблон приоритет
            pass
    # Заголовок — копируем ключевые переменные, если они заданы в шаблоне и отличны от дефолта
    header_keys = ["$LTSCALE", "$CELTSCALE", "$LTSORT", "$LWDEFAULT", "$INSUNITS", "$MEASUREMENT", "$DIMSTYLE", "$TEXTSTYLE", "$CLAYER", "$CELTYPE", "$CELTSCALE", "$CECOLOR", "$DIMASZ", "$DIMTXT", "$DIMSCALE", "$DIMGAP", "$DIMEXE", "$DIMEXO"]
    for key in header_keys:
        try:
            if key in tpl.header:
                val = tpl.header.get(key)
                # не перезаписываем DWGCODEPAGE/ACADVER
                if key not in ("$ACADVER", "$DWGCODEPAGE", "$HANDSEED"):
                    try:
                        doc.header[key] = val
                        info["header"][key] = val
                    except Exception:
                        pass
        except Exception:
            pass
    # Также копируем $LTSCALE отдельно если есть
    try:
        if "$LTSCALE" in tpl.header:
            info["header"]["$LTSCALE"] = tpl.header["$LTSCALE"]
    except Exception:
        pass
    # Копируем блоки-стрелки для размерных стилей (_DotSmall и т.п.), иначе ошибка Block does not exist при сохранении
    try:
        from ezdxf.addons import Importer
        arrow_blocks = [b.name for b in tpl.blocks if b.name.startswith("_")]
        # также блоки типа *D* — не нужны, но для полноты можно, но пропустим анонимные *D
        to_import = [n for n in arrow_blocks if n not in doc.blocks]
        if to_import:
            imp = Importer(tpl, doc)
            imp.import_blocks(to_import)
            imp.finalize()
            if to_import:
                print(f"    Блоки стрелок скопированы: {', '.join(to_import)}")
    except Exception as e_blocks:
        print(f"  Предупреждение: не удалось скопировать блоки стрелок: {e_blocks}")
    print(f"  Шаблон {tpl_path.name}: скопировано слоёв {len(info['layers'])}, стилей {len(info['styles'])}, размерных {len(info['dimstyles'])}")
    if info["layers"]:
        print(f"    Слои: " + ", ".join([f"{n}({c}/{lt})" for n,c,lt,_ in info["layers"][:8]]) + (" ..." if len(info["layers"])>8 else ""))
    if info["styles"]:
        print(f"    Стили: " + ", ".join([f"{n}:{f}" for n,f,_,_,_ in info["styles"][:6]]) + (" ..." if len(info["styles"])>6 else ""))
    if info["dimstyles"]:
        print(f"    Размерные: " + ", ".join(info["dimstyles"][:6]) + (" ..." if len(info["dimstyles"])>6 else ""))
    return info

def inspect_template(template_path: str | Path):
    """Читает шаблон и выводит подробные параметры слоёв/стилей для сверки (для пользователя)."""
    tpl_path = Path(template_path)
    if not tpl_path.is_file():
        print(f"Файл шаблона не найден: {tpl_path}")
        return
    try:
        tpl = ezdxf.readfile(str(tpl_path))
    except Exception as e:
        print(f"Ошибка чтения шаблона: {e}")
        return
    print(f"=== Инспекция шаблона {tpl_path} ===")
    print(f"DXF версия: {tpl.dxfversion}  Кодовая страница: {tpl.header.get('$DWGCODEPAGE','?')}  LTSCALE: {tpl.header.get('$LTSCALE','?')}")
    print(f"\nСлои ({len(list(tpl.layers))}):")
    for l in tpl.layers:
        print(f"  {l.dxf.name:20} цвет={l.color:3} тип линии={l.dxf.linetype:12} вес={l.dxf.lineweight}  {'(выкл)' if l.is_off() else ''} {'(заморожен)' if l.is_frozen() else ''}")
    print(f"\nТекстовые стили ({len(list(tpl.styles))}):")
    for s in tpl.styles:
        print(f"  {s.dxf.name:20} шрифт={s.dxf.font:20} width={s.dxf.width} last_height={getattr(s.dxf, 'last_height', '?')} flags={getattr(s.dxf, 'flags', '?')}")
    print(f"\nРазмерные стили ({len(list(tpl.dimstyles))}):")
    for ds in tpl.dimstyles:
        # выводим ключевые параметры
        vals = []
        for k in ("dimtxt","dimasz","dimexe","dimexo","dimgap","dimscale","dimtxsty","dimclrt","dimclre","dimclrd"):
            try:
                vals.append(f"{k}={getattr(ds.dxf, k)}")
            except Exception:
                pass
        print(f"  {ds.dxf.name:20} " + " ".join(vals))
    print(f"\nЗаголовок (ключевые):")
    for k in ["$LTSCALE","$CELTSCALE","$INSUNITS","$MEASUREMENT","$DIMSTYLE","$TEXTSTYLE","$CLAYER"]:
        try:
            if k in tpl.header:
                print(f"  {k} = {tpl.header.get(k)}")
        except Exception:
            pass
    print("=== Конец инспекции ===")



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

            # Линии открывания по ГОСТ — ПРИВЯЗКА К ВИДИМОМУ ГАБАРИТУ СТВОРКИ (а не к внутреннему проёму)
            # Видимый габарит: для OUTSIDE створка видна по внутреннему контуру (наплав скрыт, но створка ограничена ячейкой),
            # для INSIDE — по наружному контуру. Чтобы выполнить требование "видимый габарит", используем наружный
            # прямоугольник створки (x1,y1)-(x2,y2) как основу для индикации, а не in_x1..in_x2.
            # Для OUTSIDE наружный выходит за ячейку на overlap, но видимая часть — это ячейка, поэтому индикатор
            # всё равно привязываем к наружному, но при отрисовке он будет в пределах видимого.
            indicators = []
            # Видимый габарит — наружный прямоугольник створки
            vx1, vy1, vx2, vy2 = x1, y1, x2, y2
            vy_mid = (vy1 + vy2) / 2.0
            vx_mid = (vx1 + vx2) / 2.0

            if stype == "TURN":
                # Поворотная: две линии из углов стороны петель (левой) к центру ручки на противоположной (правой) стороне — по видимому габариту
                indicators.append(((vx1, vy1), (vx2, vy_mid)))
                indicators.append(((vx1, vy2), (vx2, vy_mid)))
            elif stype == "TILT":
                # Откидная/фрамуга: две линии из нижних углов к центру верхней ручки — по видимому габариту
                indicators.append(((vx1, vy1), (vx_mid, vy2)))
                indicators.append(((vx2, vy1), (vx_mid, vy2)))
            elif stype == "TURN_TILT":
                # Поворотно-откидная: совмещение TURN + TILT = 4 линии по видимому габариту
                indicators.append(((vx1, vy1), (vx2, vy_mid)))
                indicators.append(((vx1, vy2), (vx2, vy_mid)))
                indicators.append(((vx1, vy1), (vx_mid, vy2)))
                indicators.append(((vx2, vy1), (vx_mid, vy2)))
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


def _subtract_rect_from_line(
    x0: float, y0: float, x1: float, y1: float,
    rx1: float, ry1: float, rx2: float, ry2: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Вычитание прямоугольника из линии: возвращает отрезки линии вне прямоугольника.
    Для вида изнутри: створка обрезает раму/импост.
    Если линия полностью вне — возвращает исходную, если внутри — [], если пересекает — 1-2 отрезка.
    """
    # Нормализуем прямоугольник
    xmin, xmax = (rx1, rx2) if rx1 < rx2 else (rx2, rx1)
    ymin, ymax = (ry1, ry2) if ry1 < ry2 else (ry2, ry1)
    # Проверка: линия полностью вне по bbox
    # Используем клип чтобы найти внутри часть
    clipped = _clip_line_to_rect(x0, y0, x1, y1, xmin, ymin, xmax, ymax)
    if clipped is None:
        # полностью вне — остаётся
        return [((x0, y0), (x1, y1))]
    (cx0, cy0), (cx1, cy1) = clipped
    # Если clipped совпадает с исходной — полностью внутри
    if abs(cx0 - x0) < 1e-9 and abs(cy0 - y0) < 1e-9 and abs(cx1 - x1) < 1e-9 and abs(cy1 - y1) < 1e-9:
        return []
    # Если clipped - точка, линия касается — считаем как вне?
    # Разбиваем на до и после
    res: list[tuple[tuple[float, float], tuple[float, float]]] = []
    # Отрезок до входа
    if abs(cx0 - x0) > 1e-9 or abs(cy0 - y0) > 1e-9:
        res.append(((x0, y0), (cx0, cy0)))
    # Отрезок после выхода
    if abs(cx1 - x1) > 1e-9 or abs(cy1 - y1) > 1e-9:
        res.append(((cx1, cy1), (x1, y1)))
    return res


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

    # 1. Расчёт рамы с учётом подставочника и ДОБОРОВ (если есть доборы — уменьшаем размеры конструкций)
    # Доборы уменьшают габарит рамы: проём - шов - добор - рама
    addons_cfg_tmp = params.get("addons", {}) or {}
    addon_left_tmp = float(addons_cfg_tmp.get("left", 0) or 0)
    addon_right_tmp = float(addons_cfg_tmp.get("right", 0) or 0)
    addon_top_tmp = float(addons_cfg_tmp.get("top", 0) or 0)
    # Границы рамы с учётом доборов (если добор есть — рама отодвигается от шва на величину добора)
    frame_left = s + addon_left_tmp
    frame_right = ow - s - addon_right_tmp
    frame_bottom_sill = s + sh_tmp if sill_on_tmp else s
    frame_top = oh - s - addon_top_tmp
    if sill_on_tmp:
        # С подставочником: низ рамы на S+SH+добор, верх с учётом верхнего добора
        frame_outer = [
            (frame_left, frame_bottom_sill),
            (frame_right, frame_bottom_sill),
            (frame_right, frame_top),
            (frame_left, frame_top),
        ]
        frame_inner = [
            (frame_left + fw, frame_bottom_sill + fh),
            (frame_right - fw, frame_bottom_sill + fh),
            (frame_right - fw, frame_top - fh),
            (frame_left + fw, frame_top - fh),
        ]
        # 45° стыки с учётом сдвига низа и доборов
        frame_mitres = [
            ((frame_left, frame_bottom_sill), (frame_left + fw, frame_bottom_sill + fh)),  # левый нижний
            ((frame_right, frame_bottom_sill), (frame_right - fw, frame_bottom_sill + fh)),  # правый нижний
            ((frame_right, frame_top), (frame_right - fw, frame_top - fh)),  # правый верхний
            ((frame_left, frame_top), (frame_left + fw, frame_top - fh)),  # левый верхний
        ]
    else:
        # Без подставочника, но с доборами
        if addon_left_tmp > 1e-9 or addon_right_tmp > 1e-9 or addon_top_tmp > 1e-9:
            frame_outer = [
                (frame_left, s),
                (frame_right, s),
                (frame_right, frame_top),
                (frame_left, frame_top),
            ]
            frame_inner = [
                (frame_left + fw, s + fh),
                (frame_right - fw, s + fh),
                (frame_right - fw, frame_top - fh),
                (frame_left + fw, frame_top - fh),
            ]
            frame_mitres = [
                ((frame_left, s), (frame_left + fw, s + fh)),
                ((frame_right, s), (frame_right - fw, s + fh)),
                ((frame_right, frame_top), (frame_right - fw, frame_top - fh)),
                ((frame_left, frame_top), (frame_left + fw, frame_top - fh)),
            ]
        else:
            frame_outer, frame_inner = calc_frame(ow, oh, s, fw, fh)
            frame_mitres = calc_frame_mitres(ow, oh, s, fw, fh)

    # 2. Границы внутренней световой сетки (с учётом подставочника и доборов)
    x0 = frame_left + fw
    x1 = frame_right - fw
    y0 = frame_bottom_sill + fh
    y1 = frame_top - fh

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
            # Обрезаем 45° засечки к ячейке (они выходят на наплав, который скрыт) — оставляем как есть
            new_mitres: list[tuple[tuple[float, float], tuple[float, float]]] = []
            for (x0, y0), (x1, y1) in sash.get("mitres", []):
                clipped = _clip_line_to_rect(x0, y0, x1, y1, rx1, ry1, rx2, ry2)
                if clipped is not None:
                    new_mitres.append(clipped)
                else:
                    pass
            sash["mitres"] = new_mitres
            # Для вида СНАРУЖИ: наплав створки невидим, обрезается рамой и импостом.
            # Линии открывания должны начинаться от углов рам и импостов, т.е. от углов ячейки (cell),
            # а не от наплава (sash outer). Поэтому пересоздаём индикацию от ячейки.
            stype = sash.get("sash_type")
            # Ячейка как видимый габарит (рама/импост)
            vx1, vy1, vx2, vy2 = rx1, ry1, rx2, ry2
            vy_mid = (vy1 + vy2) / 2.0
            vx_mid = (vx1 + vx2) / 2.0
            new_indicators: list[tuple[tuple[float, float], tuple[float, float]]] = []
            if stype == "TURN":
                new_indicators.append(((vx1, vy1), (vx2, vy_mid)))
                new_indicators.append(((vx1, vy2), (vx2, vy_mid)))
            elif stype == "TILT":
                new_indicators.append(((vx1, vy1), (vx_mid, vy2)))
                new_indicators.append(((vx2, vy1), (vx_mid, vy2)))
            elif stype == "TURN_TILT":
                new_indicators.append(((vx1, vy1), (vx2, vy_mid)))
                new_indicators.append(((vx1, vy2), (vx2, vy_mid)))
                new_indicators.append(((vx1, vy1), (vx_mid, vy2)))
                new_indicators.append(((vx2, vy1), (vx_mid, vy2)))
            # Для FIX оставляем пусто
            sash["indicators"] = new_indicators
            # Обновим outer_rect для консистентности? Оставляем как есть для других нужд, но индикация теперь от ячейки
            # sash["outer_rect"] остаётся старым (с наплавом), но для OUTSIDE видимый — ячейка

    # 6c. Зеркальность: вид снаружи и изнутри зеркальны по вертикальной оси (сейчас нет)
    # При виде изнутри окно зеркалится относительно вертикальной оси проёма (X -> OW - X)
    # Атрибуты, размеры и т.п. не зеркалятся, только геометрия окна
    if str(params.get("view", "OUTSIDE")).upper() == "INSIDE":
        def _mirror_pt(pt: tuple[float, float]) -> tuple[float, float]:
            return (float(ow) - float(pt[0]), float(pt[1]))
        def _mirror_line(a: tuple[float, float], b: tuple[float, float]):
            return (_mirror_pt(a), _mirror_pt(b))
        # Открытие
        opening_poly = [_mirror_pt(p) for p in opening_poly]
        # Рама
        frame_outer = [_mirror_pt(p) for p in frame_outer]
        frame_inner = [_mirror_pt(p) for p in frame_inner]
        frame_mitres = [_mirror_line(a, b) for a, b in frame_mitres]
        # Импосты
        mullions_v = [[_mirror_pt(p) for p in poly] for poly in mullions_v]
        mullions_h = [[_mirror_pt(p) for p in poly] for poly in mullions_h]
        # Стрипы и ячейки
        strips_x = [(float(ow) - x2, float(ow) - x1) for x1, x2 in strips_x]
        strips_x.sort(key=lambda v: v[0])
        for cell in cells:
            ox1, ox2 = cell["x1"], cell["x2"]
            cell["x1"] = float(ow) - ox2
            cell["x2"] = float(ow) - ox1
        # Створки
        for sash in sashes:
            if sash.get("outer_rect"):
                x1, y1, x2, y2 = sash["outer_rect"]
                sash["outer_rect"] = (float(ow) - x2, y1, float(ow) - x1, y2)
            if sash.get("inner_rect"):
                x1, y1, x2, y2 = sash["inner_rect"]
                sash["inner_rect"] = (float(ow) - x2, y1, float(ow) - x1, y2)
            for key in ("outer_contour", "inner_contour", "contour", "mitres", "indicators"):
                if key in sash and sash[key]:
                    sash[key] = [((float(ow) - x0, y0), (float(ow) - x1, y1)) for (x0, y0), (x1, y1) in sash[key]]
        # Подставочник будет зеркалиться ниже, но он симметричен — продублируем
        # (фактически sill_poly зеркалится так же, но результат тот же прямоугольник)


    # 7. Подставочный профиль (зеркалится для INSIDE как и остальная геометрия)
    sill_poly = calc_sill(params, ow, s)
    if str(params.get("view", "OUTSIDE")).upper() == "INSIDE" and sill_poly:
        sill_poly = [(float(ow) - x, y) for x, y in sill_poly]

    # 7b. Доборы (расширители) — слева/справа/сверху, толщина как в params.addons
    # Геометрия: прямоугольники, примыкающие к раме снаружи (с учётом подставочника)
    addons_cfg = params.get("addons", {}) or {}
    addon_left = float(addons_cfg.get("left", 0) or 0)
    addon_right = float(addons_cfg.get("right", 0) or 0)
    addon_top = float(addons_cfg.get("top", 0) or 0)
    addons = []  # список полигонов [(x,y)...]
    # Для зеркала INSIDE левый/правый меняются местами
    view_addon = str(params.get("view", "OUTSIDE")).upper()
    # Исходные без зеркала
    addon_left_rect = None
    addon_right_rect = None
    addon_top_rect = None
    if addon_left > 1e-9:
        # левый добор: между швом (S) и рамой (frame_left), y от низа рамы до верха рамы (с учётом верхнего добора)
        y0_a = frame_bottom_sill
        y1_a = frame_top
        addon_left_rect = [(s, y0_a), (frame_left, y0_a), (frame_left, y1_a), (s, y1_a)]
        addons.append(addon_left_rect)
    if addon_right > 1e-9:
        y0_a = frame_bottom_sill
        y1_a = frame_top
        addon_right_rect = [(frame_right, y0_a), (ow - s, y0_a), (ow - s, y1_a), (frame_right, y1_a)]
        addons.append(addon_right_rect)
    if addon_top > 1e-9:
        # верхний добор: от y = frame_top до OH-S, x от S до OW-S (на всю ширину проёма за вычетом шва)
        x0_t = s
        x1_t = ow - s
        addon_top_rect = [(x0_t, frame_top), (x1_t, frame_top), (x1_t, oh - s), (x0_t, oh - s)]
        # Если есть боковые доборы, верхний добор идёт над ними? Для простоты — на всю ширину, боковые уже учтены по y1_a = frame_top
        addons.append(addon_top_rect)
    # Зеркало для INSIDE: отражаем все доборы по X
    if view_addon == "INSIDE" and addons:
        addons = [[(float(ow) - x, y) for x, y in poly] for poly in addons]
        # также обновим отдельные rect для размеров
        if addon_left_rect:
            addon_left_rect = [(float(ow) - x, y) for x, y in addon_left_rect]
        if addon_right_rect:
            addon_right_rect = [(float(ow) - x, y) for x, y in addon_right_rect]
        if addon_top_rect:
            addon_top_rect = [(float(ow) - x, y) for x, y in addon_top_rect]
        # для INSIDE левый и правый меняются местами визуально, но для размеров нам нужны внешние границы
        # сохраняем как есть, но помним что left/right поменялись
        # для простоты пересчитаем overall левый/правый по min/max
    # Сохраняем для модели
    addons_info = {
        "left": addon_left,
        "right": addon_right,
        "top": addon_top,
        "polys": addons,
        "left_rect": addon_left_rect,
        "right_rect": addon_right_rect,
        "top_rect": addon_top_rect,
    }

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

    # Имя блока: "Объект Название окна Габаритные размеры Вид"
    # Пример: "Тестовый объект ОК-1 1500х1500 Снаружи" / "Тестовый объект ОК-1 1500х1500 Изнутри"
    view_for_name = str(params.get("view", "OUTSIDE")).upper()
    view_str = "Снаружи" if view_for_name == "OUTSIDE" else "Изнутри"
    size_str_for_name = f"{int(ow) if ow.is_integer() else ow}х{int(oh) if oh.is_integer() else oh}"
    object_str_for_name = str(meta.get("object", "Тестовый объект")).strip()
    block_name = f"{object_str_for_name} {window_name} {size_str_for_name} {view_str}"
    # Ограничим длину и заменим недопустимые символы если вдруг
    # DXF блок имя не должно содержать * ? и т.п., но наши данные безопасны
    if len(block_name) > 255:
        block_name = block_name[:255]

    # Подсчёт примитивов для отчёта
    # opening 1 (слой Штриховые), frame outer+inner 2, frame mitres 4, mullions, sill, sashes, addons
    # Доработка: для OUTSIDE наружный контур створки не виден -> не считаем
    view = str(params.get("view", "OUTSIDE")).upper()
    primitives_count = 1  # opening
    primitives_count += 2  # frame_outer + frame_inner (LWPOLYLINE)
    primitives_count += len(frame_mitres)  # 4 LINE
    primitives_count += len(mullions_v)  # LWPOLYLINE
    primitives_count += len(mullions_h)  # LWPOLYLINE
    if sill_poly:
        primitives_count += 1  # LWPOLYLINE
    primitives_count += len(addons)  # доборы
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
        "addons": addons,
        "addons_info": addons_info,
        "attdefs": attdefs,
        "primitives_count": primitives_count,
    }


def export_to_dxf(model: dict[str, Any], output_path: str | Path, template_path: str | Path | None = None) -> None:
    """
    Экспорт геометрической модели окна в файл DXF версии R2013.

    :param model: Модель окна от build_window_model
    :param output_path: Путь для сохранения файла .dxf
    """
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Создание документа DXF версии R2013 (AutoCAD 2013+)
    # Если указан шаблон — берём его таблицы/заголовок, иначе создаём с нуля
    # Приоритет: явный template_path > params['template'] > автопоиск template.dxf рядом с params/output
    tpl_candidate = template_path
    if tpl_candidate is None:
        tpl_candidate = model.get("params", {}).get("template") or model.get("params", {}).get("template_path")
    if tpl_candidate is None:
        # автопоиск: template.dxf / шаблон.dxf / БШАБЛОН.dxf / .dwg рядом с output или рядом с window_export.py
        for cand in [Path("template.dxf"), Path("шаблон.dxf"), Path("Шаблон.dxf"), Path("БШАБЛОН.dxf"),
                     Path("template.dwg"), Path("шаблон.dwg"), Path("Шаблон.dwg"), Path("БШАБЛОН.dwg"),
                     Path(__file__).parent / "template.dxf", Path(__file__).parent / "шаблон.dxf", Path(__file__).parent / "Шаблон.dxf", Path(__file__).parent / "БШАБЛОН.dxf",
                     Path(__file__).parent / "template.dwg", Path(__file__).parent / "шаблон.dwg", Path(__file__).parent / "Шаблон.dwg", Path(__file__).parent / "БШАБЛОН.dwg",
                     out_file.parent / "template.dxf", out_file.parent / "шаблон.dxf", out_file.parent / "Шаблон.dxf", out_file.parent / "БШАБЛОН.dxf",
                     out_file.parent / "template.dwg", out_file.parent / "шаблон.dwg", out_file.parent / "Шаблон.dwg", out_file.parent / "БШАБЛОН.dwg"]:
            if cand.is_file():
                tpl_candidate = cand
                break
    if tpl_candidate and Path(tpl_candidate).is_file():
        print(f"  Используем шаблон: {tpl_candidate}")
        # Читаем шаблон как основу (сохраняет его LTSCALE, слои, стили и т.п.), но очищаем модель
        try:
            tpl_doc = ezdxf.readfile(str(tpl_candidate))
            # Пробуем использовать шаблон как основу: копируем заголовок и таблицы через новый документ?
            # Проще: создаём новый doc, затем копируем таблицы из шаблона
            doc = ezdxf.new("R2013")
            doc.encoding = "cp1251"
            # Скопировать заголовок/таблицы из шаблона
            _copy_template_tables(doc, tpl_candidate)
            # Обеспечить что DWGCODEPAGE/encoding остаются cp1251 для кириллицы (перекрывает шаблон если нужно)
            try:
                doc.header["$DWGCODEPAGE"] = "ANSI_1251"
                doc.encoding = "cp1251"
            except Exception:
                pass
            # Если в шаблоне свой LTSCALE, он уже скопирован и сохраняется как есть (по ТЗ: считать все настройки заголовка)
            # Ставим 25 только если в шаблоне нет LTSCALE (нет шаблона) — уже обработано в ветках else
            pass
        except Exception as e:
            print(f"  Не удалось использовать шаблон как основу: {e} — создаём с нуля")
            doc = ezdxf.new("R2013")
            doc.encoding = "cp1251"
            doc.header["$DWGCODEPAGE"] = "ANSI_1251"
            try:
                doc.header["$LTSCALE"] = 25.0
                doc.header["$CELTSCALE"] = 1.0
            except Exception:
                pass
            _copy_template_tables(doc, tpl_candidate)
    else:
        doc = ezdxf.new("R2013")
        doc.encoding = "cp1251"
        doc.header["$DWGCODEPAGE"] = "ANSI_1251"
        # Масштаб линий для штриховых — 25 (LTSCALE)
        try:
            doc.header["$LTSCALE"] = 25.0
            doc.header["$CELTSCALE"] = 1.0
        except Exception:
            pass

    # 2. Создание слоёв 'Окна' и 'Штриховые' (для контура проёма)
    layer_name = "Окна"
    if layer_name not in doc.layers:
        doc.layers.add(layer_name, color=7)
    layer_opening = "Штриховые"
    if layer_opening not in doc.layers:
        try:
            # Штриховая линия для проёма, масштаб 25
            doc.layers.add(layer_opening, color=1, linetype="DASHED")
        except Exception:
            try:
                doc.layers.add(layer_opening, color=1)
                doc.layers.get(layer_opening).dxf.linetype = "DASHED"
            except Exception:
                doc.layers.add(layer_opening, color=1)
    # Установить масштаб линий для слоя Штриховые — 25 (через CELTSCALE у примитивов)
    # Глобальный LTSCALE уже 25, дополнительно для каждого примитива на этом слое ставим ltscale 25

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

    # 4. Добавление габаритного контура проёма (ТЗ 0.2 обязателен) - LWPOLYLINE 0,0 .. OW,OH на слое Штриховые, масштаб 25
    ent_opening = blk.add_lwpolyline(
        model["opening_poly"],
        close=True,
        dxfattribs={"layer": layer_opening},
    )
    try:
        ent_opening.dxf.linetype_scale = 25.0
    except Exception:
        pass

    # 5. Добавление рамы (наружный и внутренний контуры)
    # Для вида изнутри створка (с учётом наплава) обрезает контуры рам и импостов
    view_frame = str(model.get("params", {}).get("view", "OUTSIDE")).upper()
    sash_rects = [s.get("outer_rect") for s in model.get("sashes", []) if s.get("outer_rect")]
    if view_frame == "INSIDE" and sash_rects:
        # Обрезаем внутренний контур рамы и импосты створками
        # Наружный контур рамы не трогаем (створка не доходит до наружного края)
        blk.add_lwpolyline(
            model["frame_outer"],
            close=True,
            dxfattribs={"layer": layer_name},
        )
        # Внутренний контур рамы — разбиваем на 4 отрезка и вычитаем sash
        frame_inner_pts = model["frame_inner"]
        # frame_inner — 4 точки прямоугольника, делаем 4 линии
        frame_inner_lines = [
            (frame_inner_pts[0], frame_inner_pts[1]),
            (frame_inner_pts[1], frame_inner_pts[2]),
            (frame_inner_pts[2], frame_inner_pts[3]),
            (frame_inner_pts[3], frame_inner_pts[0]),
        ]
        for (x0, y0), (x1, y1) in frame_inner_lines:
            segs = [((x0, y0), (x1, y1))]
            for rx1, ry1, rx2, ry2 in sash_rects:
                new_segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
                for (sx0, sy0), (sx1, sy1) in segs:
                    # sash_rect: (x1,y1,x2,y2) -> прямоугольник
                    new_segs.extend(_subtract_rect_from_line(sx0, sy0, sx1, sy1, rx1, ry1, rx2, ry2))
                segs = new_segs
                if not segs:
                    break
            for (sx0, sy0), (sx1, sy1) in segs:
                blk.add_line((sx0, sy0), (sx1, sy1), dxfattribs={"layer": layer_name})
        # 5b. Косые стыки рамы — тоже обрезаются створкой (если створка перекрывает угол)
        for p1, p2 in model["frame_mitres"]:
            segs = [ (p1, p2) ]
            for rx1, ry1, rx2, ry2 in sash_rects:
                new_segs = []
                for (sx0, sy0), (sx1, sy1) in segs:
                    new_segs.extend(_subtract_rect_from_line(sx0, sy0, sx1, sy1, rx1, ry1, rx2, ry2))
                segs = new_segs
                if not segs:
                    break
            for (sx0, sy0), (sx1, sy1) in segs:
                blk.add_line((sx0, sy0), (sx1, sy1), dxfattribs={"layer": layer_name})
        # 6-7. Импосты — обрезаются створками
        for poly in model["mullions_v"] + model["mullions_h"]:
            # poly — 4 точки прямоугольника, делаем 4 линии
            m_lines = [
                (poly[0], poly[1]),
                (poly[1], poly[2]),
                (poly[2], poly[3]),
                (poly[3], poly[0]),
            ]
            for (x0, y0), (x1, y1) in m_lines:
                segs = [((x0, y0), (x1, y1))]
                for rx1, ry1, rx2, ry2 in sash_rects:
                    new_segs = []
                    for (sx0, sy0), (sx1, sy1) in segs:
                        new_segs.extend(_subtract_rect_from_line(sx0, sy0, sx1, sy1, rx1, ry1, rx2, ry2))
                    segs = new_segs
                    if not segs:
                        break
                for (sx0, sy0), (sx1, sy1) in segs:
                    blk.add_line((sx0, sy0), (sx1, sy1), dxfattribs={"layer": layer_name})
    else:
        # Обычный вид снаружи или нет створок — без обрезки
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
        for p1, p2 in model["frame_mitres"]:
            blk.add_line(p1, p2, dxfattribs={"layer": layer_name})
        for poly in model["mullions_v"]:
            blk.add_lwpolyline(
                poly,
                close=True,
                dxfattribs={"layer": layer_name},
            )
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

    # 8b. Добавление доборов
    for poly in model.get("addons", []):
        try:
            blk.add_lwpolyline(
                poly,
                close=True,
                dxfattribs={"layer": layer_name},
            )
        except Exception:
            pass

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
        # Линии открывания по ГОСТ — всегда, но по доработке на слое Штриховые, масштаб 25
        for p1, p2 in sash.get("indicators", []):
            ent_ind = blk.add_line(p1, p2, dxfattribs={"layer": layer_opening})
            try:
                ent_ind.dxf.linetype_scale = 25.0
            except Exception:
                pass
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
    # Доработка: вынести выше окна, выровнять по левому углу (x=0, y=OH+...)
    # Атрибуты: OBJECT / WINDOW(ОК-1/1 шт.) / COLOR(RAL8017/RAL9016) / GLAZING(Заполнение СПД42) / SIZE(1500х1500) / GRID(3х2)
    oh = model["opening"]["height"]
    ow = model["opening"]["width"]
    # Слой для размеров — Размеры, стиль — Основной стиль (увеличенные габариты)
    layer_dim = "Размеры"
    dim_layer = "Размеры"
    dim_style_name = "Основной стиль"
    text_layer = "Текст"
    text_style_name = "Основной стиль (для надписей)"
    if dim_layer not in doc.layers:
        try:
            doc.layers.add(dim_layer, color=3)
        except Exception:
            pass
    if text_layer not in doc.layers:
        try:
            doc.layers.add(text_layer, color=7)
        except Exception:
            pass
    # Также создаём слой Основной для совместимости
    if "Основной" not in doc.layers:
        try:
            doc.layers.add("Основной", color=7)
        except Exception:
            pass
    # Создаём текстовый стиль Основной стиль (Arial) если нет — но если шаблон уже дал его, оставляем шаблонный
    use_tpl = tpl_candidate is not None and Path(tpl_candidate).is_file()
    if text_style_name not in doc.styles:
        try:
            doc.styles.new(text_style_name, dxfattribs={"font": "Arial.ttf"})
        except Exception:
            try:
                doc.styles.new(text_style_name)
            except Exception:
                pass
    else:
        if not use_tpl:
            try:
                st = doc.styles.get(text_style_name)
                if st.dxf.font != "Arial.ttf":
                    st.dxf.font = "Arial.ttf"
            except Exception:
                pass
        # если шаблон — оставляем его шрифт как есть
    # Создаём размерный стиль Основной стиль — если шаблон уже есть, не перезаписываем его параметры
    if dim_style_name not in doc.dimstyles:
        try:
            # если шаблон дал свой стиль, он уже скопирован; иначе создаём
            if use_tpl and "Основной стиль" in [ds.dxf.name for ds in doc.dimstyles]:
                pass
            else:
                try:
                    base = doc.dimstyles.get("EZDXF")
                    ds_new = doc.dimstyles.new(dim_style_name)
                    for attr in ("dimtxt", "dimasz", "dimexe", "dimexo", "dimgap", "dimscale"):
                        try:
                            setattr(ds_new.dxf, attr, getattr(base.dxf, attr))
                        except Exception:
                            pass
                except Exception:
                    doc.dimstyles.new(dim_style_name)
        except Exception:
            pass
    # Устанавливаем габариты: увеличенный масштаб для размеров (по просьбе)
    # Для всех случаев — увеличиваем, даже с шаблоном (шаблонный dimscale 4 → 10, dimtxt 2.5 → 8)
    try:
        ds = doc.dimstyles.get(dim_style_name)
        if ds is not None:
            # Увеличиваем масштаб и текст, сохраняя стиль шрифта из шаблона если есть
            try:
                ds.dxf.dimtxt = max(float(getattr(ds.dxf, "dimtxt", 2.5)), 8.0)  # было 2.5/8, стало минимум 8
            except Exception:
                ds.dxf.dimtxt = 8.0
            try:
                ds.dxf.dimasz = max(float(getattr(ds.dxf, "dimasz", 2.5)), 6.0)
            except Exception:
                ds.dxf.dimasz = 6.0
            try:
                ds.dxf.dimexe = 3.0
                ds.dxf.dimexo = 2.5
                ds.dxf.dimgap = 3.0
                # Масштаб увеличиваем: было 4, стало 10 (шаблонный 4 → 10, 25/75 не трогаем если больше)
                cur_scale = float(getattr(ds.dxf, "dimscale", 4.0))
                ds.dxf.dimscale = max(cur_scale, 10.0)  # минимум 10 для видимости
            except Exception:
                pass
            try:
                # Для размеров оставляем "Основной стиль" как текстовый стиль размеров, но шрифт уже из шаблона
                if not getattr(ds.dxf, "dimtxsty", None):
                    ds.dxf.dimtxsty = dim_style_name
            except Exception:
                pass
    except Exception:
        pass
    # Для случая без шаблона — если стиль только что создан, он уже получил 10, иначе шаблонный тоже 10
    # Старый else для шаблона теперь не нужен, объединено выше
    # Для совместимости также оставляем WindowStyle
    if "WindowStyle" not in doc.styles:
        try:
            doc.styles.new("WindowStyle", dxfattribs={"font": "Arial.ttf"})
        except Exception:
            pass
    # Атрибуты — выше окна, по левому углу (x=0), слой Текст, стиль Основной стиль, увеличенный размер
    # Порядок сверху вниз: Объект, Окно, Цвет, Заполнение, Габарит, Сетка (как было до перестановки)
    # Чтобы Объект был самым верхним, инвертируем Y: первый в списке (OBJECT) — самый высокий
    x_attr = 0.0  # левый угол проёма
    y_attr_start = float(oh) + 60.0  # нижний уровень (ближайший к окну) — для Сетка
    step = 50.0  # увеличенный шаг (было 45, стало 50 по просьбе)
    height_attr = 30.0  # увеличенный размер текста атрибутов (было 22)
    n_attrs = len(model["attdefs"])
    for idx, (tag, prompt, value) in enumerate(model["attdefs"]):
        # idx 0 = OBJECT -> самый верхний (y_start + (n-1)*step), idx 5 = GRID -> самый нижний (y_start)
        y = y_attr_start + (n_attrs - 1 - idx) * step
        blk.add_attdef(
            tag=tag,
            insert=(x_attr, y),
            text=value,
            height=height_attr,
            dxfattribs={
                "prompt": prompt,
                "layer": text_layer,
                "style": text_style_name,
            },
        )

    # 10b. Площадь конструкции в правом верхнем углу — увеличенный размер, корректная привязка
    # Чтобы при копировании/взрыве не уезжала в 0,0, используем явные координаты и выравнивание
    try:
        area_m2 = (float(ow) * float(oh)) / 1_000_000.0  # м²
        area_text = f"S={area_m2:.2f} м²"
        area_x = float(ow)
        area_y = float(oh) + 60.0  # отодвинуто как и атрибуты
        area_height = 30.0  # увеличенный размер площади (было 20)
        # Создаём TEXT с выравниванием TOP_RIGHT, явно задаём оба пункта
        area_ent = blk.add_text(
            area_text,
            height=area_height,
            dxfattribs={"layer": text_layer, "style": text_style_name},
        )
        # Явно устанавливаем insert и align_point в одну точку для корректного взрывания
        area_ent.dxf.insert = (area_x, area_y, 0.0)
        area_ent.dxf.halign = 2  # Right
        area_ent.dxf.valign = 3  # Top
        try:
            area_ent.dxf.align_point = (area_x, area_y, 0.0)
        except Exception:
            pass
        # Дополнительно для ezdxf set_pos
        try:
            area_ent.set_pos((area_x, area_y), align="TOP_RIGHT")
            # Переопределяем align_point после set_pos чтобы гарантировать
            area_ent.dxf.align_point = (area_x, area_y, 0.0)
            area_ent.dxf.insert = (area_x, area_y, 0.0)
        except Exception:
            pass
    except Exception:
        pass

    # 10c. Размерные цепочки справа и снизу (вертикальные только справа)
    # Слой — Размеры, стиль — Основной, увеличенные габариты
    # Учитывает: подставочник (цепляем горизонтальные по его низу), доборы (отдельный размер), монтажные швы
    # Индикация открывания привязана к видимому габариту створки (inner_rect, clipped к ячейке)
    try:
        s = float(model["opening"]["seam"])
        fw = float(model["params"]["frame"]["face_width"])
        cols = int(model["grid"]["cols"])
        rows = int(model["grid"]["rows"])
        cell_w = float(model["grid"]["cell_w"])
        cell_h = float(model["grid"]["cell_h"])
        mw = float(model["params"].get("mullion", {}).get("width", 0))
        mh = float(model["params"].get("mullion", {}).get("height", 0))
        addons_info = model.get("addons_info", {}) or {}
        addon_left = float(addons_info.get("left", 0) or 0)
        addon_right = float(addons_info.get("right", 0) or 0)
        addon_top = float(addons_info.get("top", 0) or 0)
        sill = model.get("sill")
        # Рама с учётом зеркала: берём min/max
        xs = [p[0] for p in model["frame_outer"]]
        ys = [p[1] for p in model["frame_outer"]]
        frame_left = float(min(xs))
        frame_right = float(max(xs))
        frame_bottom = float(min(ys))
        frame_top = float(max(ys))
        # Габарит с доборами: внешние границы с учётом доборов (зеркало уже учтено)
        overall_left = frame_left - addon_left if addon_left > 1e-9 else frame_left
        overall_right = frame_right + addon_right if addon_right > 1e-9 else frame_right
        overall_top = frame_top + addon_top if addon_top > 1e-9 else frame_top
        # Низ для горизонтальных размеров: если есть подставочник — его низ (S), иначе frame_bottom
        if sill:
            # sill = [(S,S),(OW-S,S),(OW-S,S+SH),(S,S+SH)] или зеркало
            sill_ys = [p[1] for p in sill]
            sill_bottom = float(min(sill_ys))
            sill_top = float(max(sill_ys))
            horiz_ref_y = sill_bottom  # цепляем по подставочнику
        else:
            horiz_ref_y = frame_bottom
            sill_bottom = frame_bottom
            sill_top = frame_bottom
        # Центры импостов — из модели (уже зеркалены если INSIDE)
        vert_centers: list[float] = []
        for poly in model.get("mullions_v", []):
            # центр вертикального импоста по X
            xs_m = [p[0] for p in poly]
            vert_centers.append((min(xs_m) + max(xs_m)) / 2.0)
        vert_centers.sort()
        horiz_centers: list[float] = []
        for poly in model.get("mullions_h", []):
            ys_m = [p[1] for p in poly]
            horiz_centers.append((min(ys_m) + max(ys_m)) / 2.0)
        horiz_centers.sort()

        def _add_dim(p1, p2, base, angle=0):
            try:
                dim = blk.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=dim_style_name)
                try:
                    dim.render()
                except Exception:
                    pass
                try:
                    dim.dimension.dxf.layer = dim_layer
                except Exception:
                    try:
                        dim.dxf.layer = dim_layer
                    except Exception:
                        pass
                # Установить масштаб линий 25 для штриховых? Для размеров не нужно, но увеличим
                try:
                    dim.dimension.dxf.linetype_scale = 1.0
                except Exception:
                    pass
                return dim
            except Exception:
                try:
                    blk.add_line(p1, p2, dxfattribs={"layer": dim_layer})
                except Exception:
                    pass
                return None

        # Горизонтальные снизу: привязка к нижнему краю блока (y = horiz_ref_y для окна, y=0 для проёма)
        # Отступы увеличены: 60, 120, 180 (было 30,60,90) — отодвинуто от проёма, масштаб 4
        # Детализация по ячейкам — по ширине светового проёма (между импостами) на уровне рамы
        horiz_points = [frame_left] + vert_centers + [frame_right]
        base_y_detailed = -60.0
        for i in range(len(horiz_points) - 1):
            x_a, x_b = horiz_points[i], horiz_points[i+1]
            if abs(x_b - x_a) < 1e-6:
                continue
            _add_dim(p1=(x_a, horiz_ref_y), p2=(x_b, horiz_ref_y), base=(0, base_y_detailed), angle=0)
        base_y_window = -120.0
        # Габарит окна с доборами (если есть) — от overall_left до overall_right на уровне horiz_ref_y
        _add_dim(p1=(overall_left, horiz_ref_y), p2=(overall_right, horiz_ref_y), base=(0, base_y_window), angle=0)
        base_y_opening = -180.0
        _add_dim(p1=(0, 0), p2=(float(ow), 0), base=(0, base_y_opening), angle=0)
        # Отдельный размер для доборов слева/справа (горизонтально) если есть
        if addon_left > 1e-9:
            _add_dim(p1=(overall_left, horiz_ref_y), p2=(frame_left, horiz_ref_y), base=(0, base_y_detailed), angle=0)
        if addon_right > 1e-9:
            _add_dim(p1=(frame_right, horiz_ref_y), p2=(overall_right, horiz_ref_y), base=(0, base_y_detailed), angle=0)
        # Монтажные швы горизонтальные — во второй цепочке (base -120), как и подставочник/доборы
        base_y_seam = -120.0
        if abs(overall_left) > 1e-9:
            _add_dim(p1=(0, 0), p2=(overall_left, 0), base=(0, base_y_seam), angle=0)
        if abs(float(ow) - overall_right) > 1e-9:
            _add_dim(p1=(overall_right, 0), p2=(float(ow), 0), base=(0, base_y_seam), angle=0)
        # Размер подставочного профиля горизонтально? — ширина как окно, уже есть, дополнительно не нужно
        # Доборы уже имеют отдельный размер на базе -60, швы теперь на -120 во второй цепочке

        # Вертикальные только справа: привязка к правому краю блока (x = overall_right для окна с доборами, иначе frame_right)
        vert_ref_x = overall_right if (addon_right > 1e-9 or addon_left > 1e-9) else frame_right
        vert_points = [frame_bottom] + horiz_centers + [frame_top]
        base_x_detailed_r = float(ow) + 60.0
        for i in range(len(vert_points) - 1):
            y_a, y_b = vert_points[i], vert_points[i+1]
            if abs(y_b - y_a) < 1e-6:
                continue
            _add_dim(p1=(vert_ref_x, y_a), p2=(vert_ref_x, y_b), base=(base_x_detailed_r, 0), angle=90)
        base_x_window_r = float(ow) + 120.0
        _add_dim(p1=(vert_ref_x, frame_bottom), p2=(vert_ref_x, frame_top), base=(base_x_window_r, 0), angle=90)
        # Размер подставочного профиля (вертикально) — во второй цепочке (base 120)
        if sill and abs(sill_top - sill_bottom) > 1e-9:
            _add_dim(p1=(vert_ref_x, sill_bottom), p2=(vert_ref_x, sill_top), base=(base_x_window_r, 0), angle=90)
        # Доборы вертикальные — во второй цепочке
        if addon_top > 1e-9:
            _add_dim(p1=(vert_ref_x, frame_top), p2=(vert_ref_x, overall_top), base=(base_x_window_r, 0), angle=90)
            # общий с добором уже есть как window overall, дополнительно не нужно
        base_x_opening_r = float(ow) + 180.0
        _add_dim(p1=(float(ow), 0), p2=(float(ow), float(oh)), base=(base_x_opening_r, 0), angle=90)
        # Монтажные швы вертикальные — во второй цепочке (base 120), горизонтальные — тоже во второй (-120)
        # Нижний шов: 0 .. horiz_ref_y
        if abs(horiz_ref_y) > 1e-9:
            _add_dim(p1=(float(ow), 0), p2=(float(ow), horiz_ref_y), base=(base_x_window_r, 0), angle=90)
        # Верхний шов: overall_top .. OH
        if abs(float(oh) - overall_top) > 1e-9:
            _add_dim(p1=(float(ow), overall_top), p2=(float(ow), float(oh)), base=(base_x_window_r, 0), angle=90)

    except Exception as e:
        print(f"  Предупреждение: не удалось создать размерные цепочки: {e}")
        import traceback; traceback.print_exc()

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

    # Атрибуты блока должны быть на слое Текст, стиль Основной стиль, увеличенный размер
    for attrib in bref.attribs:
        attrib.dxf.layer = text_layer
        try:
            attrib.dxf.style = text_style_name
            attrib.dxf.height = height_attr
        except Exception:
            pass
        # Также выравнивание по левому углу — не наезжать
        try:
            attrib.dxf.halign = 0
            attrib.dxf.valign = 0
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
    parser.add_argument(
        "--template",
        "-t",
        default=None,
        help="Путь к DXF/DWG-шаблону с вашими слоями/стилями (если не указан — берётся template.dxf/шаблон.dxf или params['template'])",
    )
    parser.add_argument(
        "--inspect-template",
        default=None,
        help="Показать параметры шаблона (слои/стили) и выйти, не генерируя окно",
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

    # 0. Инспекция шаблона (по запросу)
    if args.inspect_template:
        inspect_template(args.inspect_template)
        return 0
    # Также поддержка --template без генерации? нет

    # 6. Экспорт в DXF
    if args.output:
        out_dxf_path = Path(args.output)
    else:
        out_dxf_path = Path("output") / f"{model['window_name']}.dxf"

    # Определяем путь к шаблону: CLI > params.json > автопоиск
    tpl_path = args.template or params.get("template") or params.get("template_path")

    try:
        export_to_dxf(model, out_dxf_path, template_path=tpl_path)
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

    # Опциональная конвертация в DWG — после успеха удалять DXF
    dwg_res = convert_to_dwg(out_dxf_path)
    if dwg_res and Path(dwg_res).is_file():
        try:
            Path(out_dxf_path).unlink()
            print(f"  DXF удалён после конвертации (остался DWG): {dwg_res}")
        except Exception as e:
            print(f"  Не удалось удалить DXF {out_dxf_path}: {e}")

    # Дополнительно: вид изнутри для отработки ошибок (если основной OUTSIDE)
    try:
        current_view = str(params.get("view", "OUTSIDE")).upper()
        if current_view == "OUTSIDE":
            inside_params = copy.deepcopy(params)
            inside_params["view"] = "INSIDE"
            inside_model = build_window_model(inside_params)
            inside_path = out_dxf_path.parent / f"{inside_model['window_name']}_INSIDE.dxf"
            export_to_dxf(inside_model, inside_path, template_path=tpl_path)
            isize = inside_path.stat().st_size / 1024.0
            print(f"  Вид изнутри (для отработки): ./{inside_path.as_posix()} ({isize:.1f} KB)")
            dwg_inside = convert_to_dwg(inside_path)
            if dwg_inside and Path(dwg_inside).is_file():
                try:
                    Path(inside_path).unlink()
                    print(f"  DXF изнутри удалён после конвертации (остался DWG): {dwg_inside}")
                except Exception as e:
                    print(f"  Не удалось удалить DXF {inside_path}: {e}")
    except Exception as e:
        print(f"  Не удалось сформировать вид изнутри: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
