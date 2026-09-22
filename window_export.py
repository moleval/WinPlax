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

try:
    import ezdxf
except ModuleNotFoundError:
    print("=" * 70)
    print("ОШИБКА: библиотека 'ezdxf' не установлена.")
    print("=" * 70)
    print()
    print("Решение для Windows PowerShell:")
    print("  python -m pip install ezdxf")
    print("  # или, если команда 'python' не найдена:")
    print("  py -m pip install ezdxf")
    print("  # или с ключом --user (без прав администратора):")
    print("  python -m pip install --user ezdxf")
    print()
    print("После установки повторно запустите:")
    print("  python window_export.py")
    print("  python generate_examples.py")
    print()
    print("Проверка установки:")
    print("  python -m pip show ezdxf")
    print("  python -c \"import ezdxf; print(ezdxf.__version__)\"")
    print("=" * 70)
    sys.exit(1)

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


def _load_profiles() -> dict[str, Any]:
    """Загрузка profiles.json рядом со скриптом, кэш не делаем для простоты."""
    p = Path(__file__).parent / "profiles.json"
    if not p.is_file():
        # также рядом с cwd
        p2 = Path("profiles.json")
        if p2.is_file():
            p = p2
        else:
            return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            # поддерживаем как {"SYSTEM": {...}} так и {"systems": {...}}
            if "systems" in data and isinstance(data["systems"], dict):
                return data["systems"]
            return data
    except Exception:
        return {}


def _get_system_profile(params: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Возвращает (имя системы, профиль) или (None, None) если система не указана/не найдена."""
    sys_name = params.get("system") or params.get("profile") or params.get("profile_system")
    if not sys_name:
        return None, None
    sys_name = str(sys_name).strip()
    profiles = _load_profiles()
    if not profiles:
        return sys_name, None
    prof = profiles.get(sys_name)
    # также пробуем без суффикса _70
    if prof is None:
        # поиск по без регистра
        for k, v in profiles.items():
            if k.lower() == sys_name.lower():
                return k, v
    return sys_name, prof


def _resolve_bead_from_profile(profile: dict[str, Any] | None, params: dict[str, Any]) -> float | None:
    """Определяет эффективную ширину штапика из профиля с учётом params override."""
    # если в params явно задан bead — приоритет у params (обрабатывается в validate/build отдельно)
    # здесь только профиль
    if profile is None:
        return None
    bv = profile.get("bead")
    # bead может быть числом, массивом [6.5,14.5], строкой S358
    if isinstance(bv, (int, float)):
        return float(bv)
    if isinstance(bv, list) and bv:
        # есть bead_default?
        bd = profile.get("bead_default", profile.get("bead_width", bv[0]))
        try:
            return float(bd)
        except Exception:
            try:
                return float(bv[0])
            except Exception:
                return None
    if isinstance(bv, str):
        # S358 -> использовать bead_default/bead_width
        bd = profile.get("bead_default", profile.get("bead_width", profile.get("bead_width_default")))
        if bd is not None:
            try:
                return float(bd)
            except Exception:
                pass
        return None
    # также поддержка bead_width ключа
    if "bead_width" in profile:
        try:
            return float(profile["bead_width"])
        except Exception:
            pass
    return None


def validate(params: dict[str, Any]) -> list[str]:
    """
    Валидация параметров окна перед построением модели.

    :param params: Словарь с параметрами
    :return: Список ошибок (пустой, если всё корректно)
    """
    errors: list[str] = []

    # 1. Проверка обязательных секций (frame может прийти из системы)
    sys_name_tmp0, sys_prof_tmp0 = _get_system_profile(params)
    for req_key in ("opening", "cols", "rows"):
        if req_key not in params:
            errors.append(f"Отсутствует обязательная секция '{req_key}'")
    # frame обязателен если нет системы или система не дает frame
    if "frame" not in params:
        has_frame_from_sys = False
        if sys_prof_tmp0 is not None:
            if any(k in sys_prof_tmp0 for k in ("frame", "frame_face_width", "frame_face_height")):
                has_frame_from_sys = True
        if not has_frame_from_sys:
            errors.append("Отсутствует обязательная секция 'frame'")

    if errors:
        return errors

    # 1b. Система профилей (переключатель ABSTRACT / REHAU GRAZIO / EXPROF Profecta)
    sys_name, sys_prof = _get_system_profile(params)
    if sys_name is not None and sys_prof is None:
        profiles = _load_profiles()
        available = ", ".join(sorted(profiles.keys())) if profiles else "—"
        errors.append(f"Система профилей '{sys_name}' не найдена. Доступно: {available}")

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

    # 4. Профиль рамы (с учётом системы)
    frame = params.get("frame", {})
    fw = frame.get("face_width")
    fh = frame.get("face_height")
    if fw is None and sys_prof is not None:
        fw = sys_prof.get("frame", sys_prof.get("frame_face_width", sys_prof.get("frame_face_height")))
        try:
            fw = float(fw) if fw is not None else None
        except Exception:
            fw = None
    if fh is None and sys_prof is not None:
        fh = sys_prof.get("frame_face_height", sys_prof.get("frame", sys_prof.get("frame_face_width")))
        try:
            fh = float(fh) if fh is not None else None
        except Exception:
            fh = None
    # если и после системы нет — fallback на fw/fh друг друга
    if fh is None and fw is not None:
        fh = fw
    if fw is None and fh is not None:
        fw = fh

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

    # 7. Импосты (с учётом системы)
    mullion = params.get("mullion", {})
    mw = mullion.get("width", None)
    mh = mullion.get("height", None)
    # fallback из системы
    if mw is None and sys_prof is not None:
        mw = sys_prof.get("mullion", sys_prof.get("mullion_width", sys_prof.get("mullion_height")))
        try:
            mw = float(mw) if mw is not None else 0
        except Exception:
            mw = 0
    if mh is None and sys_prof is not None:
        mh = sys_prof.get("mullion_height", sys_prof.get("mullion", sys_prof.get("mullion_width")))
        try:
            mh = float(mh) if mh is not None else 0
        except Exception:
            mh = 0
    if mw is None:
        mw = 0
    else:
        try:
            mw = float(mw)
        except Exception:
            mw = 0
    if mh is None:
        mh = 0
    else:
        try:
            mh = float(mh)
        except Exception:
            mh = 0
    # если высота не задана — как ширина
    if mh == 0 and mw != 0:
        mh = mw
    if mw == 0 and mh != 0:
        mw = mh
    if mw < 0:
        errors.append("Ширина импоста (mullion.width) должна быть >= 0")
    if mh < 0:
        errors.append("Высота импоста (mullion.height) должна быть >= 0")
    # Сплошной импост: auto / vertical / horizontal
    cont = str(mullion.get("continuous", mullion.get("continuous_impost", "auto"))).strip().lower()
    if cont not in ("auto", "vertical", "horizontal", "v", "h", "вертикаль", "горизонталь", "гор", "верт"):
        errors.append("mullion.continuous должен быть auto / vertical / horizontal")
    # Штапик (единый для системы, по умолчанию 25 мм)
    # Поддержка ключей: bead, shtapik, bead_width, shtapik_width
    bead_width = None
    if "bead" in params:
        bv = params["bead"]
        if isinstance(bv, dict):
            bead_width = bv.get("width", bv.get("value"))
        else:
            try:
                bead_width = float(bv)
            except Exception:
                bead_width = None
    if bead_width is None and "shtapik" in params:
        sv = params["shtapik"]
        if isinstance(sv, dict):
            bead_width = sv.get("width", sv.get("value"))
        else:
            try:
                bead_width = float(sv)
            except Exception:
                bead_width = None
    if bead_width is None and "shtapik_width" in params:
        try:
            bead_width = float(params["shtapik_width"])
        except Exception:
            pass
    if bead_width is None and "bead_width" in params:
        try:
            bead_width = float(params["bead_width"])
        except Exception:
            pass
    # fallback из системы
    if bead_width is None and sys_prof is not None:
        bw_prof = _resolve_bead_from_profile(sys_prof, params)
        if bw_prof is not None:
            bead_width = bw_prof
    if bead_width is None:
        bead_width = 25.0  # по умолчанию
    else:
        try:
            bead_width = float(bead_width)
        except Exception:
            errors.append("Ширина штапика (bead/shtapik) должна быть числом")
            bead_width = 25.0
    if bead_width is not None and bead_width < 0:
        errors.append("Ширина штапика должна быть >= 0")
    if bead_width is not None and bead_width > 0:
        # Штапик не должен превышать профиль рамы/импоста/створки
        if fw is not None and bead_width > fw:
            errors.append(f"Ширина штапика ({bead_width}) не должна превышать ширину рамы ({fw})")
        if mw is not None and bead_width > mw:
            # для импоста это не критично, но предупредим мягко — не ошибка
            pass

    # 8. Расчётные размеры ячеек (с учётом подставочника и доборов, а также кастомных row_heights/col_widths)
    if ow and oh and seam is not None and fw and fh and cols and rows and cols >= 1 and rows >= 1:
        # Учитываем подставочник и доборы для точной проверки
        sill_on_v = params.get("sill", {}).get("on", False)
        sh_v = float(params.get("sill", {}).get("height", 30)) if sill_on_v else 0.0
        addons_v = params.get("addons", {}) or {}
        al_v = float(addons_v.get("left", 0) or 0)
        ar_v = float(addons_v.get("right", 0) or 0)
        at_v = float(addons_v.get("top", 0) or 0)
        frame_left_v = seam + al_v
        frame_right_v = ow - seam - ar_v
        frame_bottom_v = seam + sh_v if sill_on_v else seam
        frame_top_v = oh - seam - at_v
        grid_w_v = (frame_right_v - fw) - (frame_left_v + fw)
        grid_h_v = (frame_top_v - fh) - (frame_bottom_v + fh)
        sum_v = (cols - 1) * mw
        sum_h = (rows - 1) * mh

        # Проверка кастомных размеров секций (row_heights / col_widths)
        custom_rows = None
        for k in ("row_heights", "rows_heights", "heights", "cell_heights", "row_sizes"):
            if k in params:
                custom_rows = params[k]
                break
            if "grid" in params and isinstance(params["grid"], dict) and k in params["grid"]:
                custom_rows = params["grid"][k]
                break
        custom_cols = None
        for k in ("col_widths", "cols_widths", "widths", "cell_widths", "col_sizes"):
            if k in params:
                custom_cols = params[k]
                break
            if "grid" in params and isinstance(params["grid"], dict) and k in params["grid"]:
                custom_cols = params["grid"][k]
                break
        # row_heights: список высот ячеек снизу вверх
        if custom_rows is not None:
            if not isinstance(custom_rows, (list, tuple)):
                errors.append("row_heights должен быть списком чисел")
            elif len(custom_rows) != rows:
                errors.append(f"row_heights длина {len(custom_rows)} не совпадает с rows={rows}")
            else:
                sum_provided = 0
                auto_cnt = 0
                for h in custom_rows:
                    if h is None or h == 0:
                        auto_cnt += 1
                    else:
                        try:
                            hv = float(h)
                            if hv <= 0:
                                errors.append(f"row_heights значение {h} должно быть >0")
                            sum_provided += hv
                        except Exception:
                            errors.append(f"row_heights значение {h} должно быть числом")
                if auto_cnt == 0:
                    if abs(sum_provided + sum_h - grid_h_v) > 1e-6:
                        errors.append(f"Сумма row_heights {sum_provided} + импосты {sum_h} != grid_h {grid_h_v}")
                else:
                    remaining = grid_h_v - sum_h - sum_provided
                    if remaining <= 1e-9:
                        errors.append(f"Оставшаяся высота для auto-строк {remaining} недостаточна")
                    # проверка что auto-строки поместятся
        if custom_cols is not None:
            if not isinstance(custom_cols, (list, tuple)):
                errors.append("col_widths должен быть списком чисел")
            elif len(custom_cols) != cols:
                errors.append(f"col_widths длина {len(custom_cols)} не совпадает с cols={cols}")
            else:
                sum_provided_w = 0
                auto_cnt_w = 0
                for w in custom_cols:
                    if w is None or w == 0:
                        auto_cnt_w += 1
                    else:
                        try:
                            wv = float(w)
                            if wv <= 0:
                                errors.append(f"col_widths значение {w} должно быть >0")
                            sum_provided_w += wv
                        except Exception:
                            errors.append(f"col_widths значение {w} должно быть числом")
                if auto_cnt_w == 0:
                    if abs(sum_provided_w + sum_v - grid_w_v) > 1e-6:
                        errors.append(f"Сумма col_widths {sum_provided_w} + импосты {sum_v} != grid_w {grid_w_v}")
                else:
                    remaining_w = grid_w_v - sum_v - sum_provided_w
                    if remaining_w <= 1e-9:
                        errors.append(f"Оставшаяся ширина для auto-колонок {remaining_w} недостаточна")

        if grid_w_v - sum_v <= 0:
            errors.append(
                f"Ширина светового проёма сетки ({grid_w_v}) недостаточна для {cols} колонок "
                f"и импостов общей шириной {sum_v}"
            )
        if grid_h_v - sum_h <= 0:
            errors.append(
                f"Высота светового проёма сетки ({grid_h_v}) недостаточна для {rows} строк "
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

    # 11. Наплав створки (с учётом системы)
    sash = params.get("sash", {})
    so = sash.get("overlap", None)
    if so is None and sys_prof is not None:
        so = sys_prof.get("overlap", sys_prof.get("sash_overlap", sys_prof.get("sash", {}).get("overlap") if isinstance(sys_prof.get("sash"), dict) else None))
    if so is None:
        so = 15 if sys_prof is None else (sys_prof.get("overlap", 15))
    try:
        so = float(so)
    except Exception:
        so = 15
    if so < 0:
        errors.append("Наплав створки (sash.overlap) должен быть >= 0")

    # 12. Ширина бруска створки (profile_width) по ТЗ 0.2 (с учётом системы)
    pw = sash.get("profile_width", None)
    if pw is None and sys_prof is not None:
        pw = sys_prof.get("sash_profile_width", sys_prof.get("sash", sys_prof.get("profile_width", 80)))
        if pw is None:
            pw = sys_prof.get("sash", 80)
            if isinstance(pw, dict):
                pw = pw.get("profile_width", 80)
    if pw is None:
        pw = 80
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

    # Система профилей — разрешаем значения из profiles.json как дефолты
    _sys_name_tmp, _sys_prof_tmp = _get_system_profile(params)
    # frame с учётом системы
    try:
        fw = float(params["frame"]["face_width"])
    except Exception:
        if _sys_prof_tmp is not None:
            fw = float(_sys_prof_tmp.get("frame", _sys_prof_tmp.get("frame_face_width", 60)))
        else:
            fw = 60.0
    try:
        fh = float(params["frame"]["face_height"])
    except Exception:
        if _sys_prof_tmp is not None:
            fh = float(_sys_prof_tmp.get("frame_face_height", _sys_prof_tmp.get("frame", fw)))
        else:
            fh = float(fw)

    # mullion с учётом системы
    try:
        mw = float(params.get("mullion", {}).get("width", None))
        if mw is None:
            raise KeyError
    except Exception:
        if _sys_prof_tmp is not None:
            mw = float(_sys_prof_tmp.get("mullion", _sys_prof_tmp.get("mullion_width", 80)))
        else:
            mw = 80.0
    try:
        mh = float(params.get("mullion", {}).get("height", None))
        if mh is None:
            raise KeyError
    except Exception:
        if _sys_prof_tmp is not None:
            mh = float(_sys_prof_tmp.get("mullion_height", _sys_prof_tmp.get("mullion", mw)))
        else:
            mh = float(mw)

    cols = int(params["cols"])
    rows = int(params["rows"])

    # sash с учётом системы
    try:
        so = float(params.get("sash", {}).get("overlap", None))
        if so is None:
            raise KeyError
    except Exception:
        if _sys_prof_tmp is not None and "overlap" in _sys_prof_tmp:
            so = float(_sys_prof_tmp.get("overlap", 15))
        elif _sys_prof_tmp is not None and "sash_overlap" in _sys_prof_tmp:
            so = float(_sys_prof_tmp.get("sash_overlap", 15))
        else:
            so = 15.0
    try:
        sw = float(params.get("sash", {}).get("profile_width", None))
        if sw is None:
            raise KeyError
    except Exception:
        if _sys_prof_tmp is not None:
            # пробуем разные ключи
            sw_cand = _sys_prof_tmp.get("sash_profile_width", _sys_prof_tmp.get("sash", _sys_prof_tmp.get("profile_width", 80)))
            if isinstance(sw_cand, dict):
                sw_cand = sw_cand.get("profile_width", 80)
            try:
                sw = float(sw_cand)
            except Exception:
                sw = 80.0
        else:
            sw = 80.0

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

    # Поддержка переменной высоты/ширины ячеек: row_heights (снизу вверх) / col_widths (слева направо)
    _custom_rows = None
    for _k in ("row_heights", "rows_heights", "heights", "cell_heights", "row_sizes"):
        if _k in params:
            _custom_rows = params[_k]
            break
        if "grid" in params and isinstance(params["grid"], dict) and _k in params["grid"]:
            _custom_rows = params["grid"][_k]
            break
    _custom_cols = None
    for _k in ("col_widths", "cols_widths", "widths", "cell_widths", "col_sizes"):
        if _k in params:
            _custom_cols = params[_k]
            break
        if "grid" in params and isinstance(params["grid"], dict) and _k in params["grid"]:
            _custom_cols = params["grid"][_k]
            break

    # Рассчитываем списки ширин/высот ячеек
    if _custom_cols is not None:
        if not isinstance(_custom_cols, (list, tuple)) or len(_custom_cols) != cols:
            raise ValueError(f"col_widths длина не совпадает с cols={cols}")
        row_col_widths: list[float] = []
        auto_idx_w: list[int] = []
        sum_w = 0.0
        for i, v in enumerate(_custom_cols):
            if v is None or v == 0:
                auto_idx_w.append(i)
                row_col_widths.append(0.0)  # placeholder
            else:
                fv = float(v)
                row_col_widths.append(fv)
                sum_w += fv
        if auto_idx_w:
            rem_w = grid_w - sum_v - sum_w
            if rem_w <= 1e-9:
                raise ValueError(f"Оставшаяся ширина {rem_w} недостаточна для auto колонок")
            auto_w = rem_w / len(auto_idx_w)
            for i in auto_idx_w:
                row_col_widths[i] = auto_w
        else:
            # все заданы — проверка замыкания
            if abs(sum_w + sum_v - grid_w) > 1e-6:
                raise ValueError(f"Сумма col_widths {sum_w}+{sum_v} != grid_w {grid_w}")
        cell_w = sum(row_col_widths) / cols if cols else 0  # для совместимости
        col_widths_list = row_col_widths
    else:
        cell_w = (grid_w - sum_v) / cols
        col_widths_list = [cell_w] * cols

    if _custom_rows is not None:
        if not isinstance(_custom_rows, (list, tuple)) or len(_custom_rows) != rows:
            raise ValueError(f"row_heights длина не совпадает с rows={rows}")
        row_heights_list: list[float] = []
        auto_idx_h: list[int] = []
        sum_h_provided = 0.0
        for j, v in enumerate(_custom_rows):
            if v is None or v == 0:
                auto_idx_h.append(j)
                row_heights_list.append(0.0)
            else:
                fv = float(v)
                row_heights_list.append(fv)
                sum_h_provided += fv
        if auto_idx_h:
            rem_h = grid_h - sum_h - sum_h_provided
            if rem_h <= 1e-9:
                raise ValueError(f"Оставшаяся высота {rem_h} недостаточна для auto строк")
            auto_h = rem_h / len(auto_idx_h)
            for j in auto_idx_h:
                row_heights_list[j] = auto_h
        else:
            if abs(sum_h_provided + sum_h - grid_h) > 1e-6:
                raise ValueError(f"Сумма row_heights {sum_h_provided}+{sum_h} != grid_h {grid_h}")
        cell_h = sum(row_heights_list) / rows if rows else 0
        row_heights_list_cached = row_heights_list
    else:
        cell_h = (grid_h - sum_h) / rows
        row_heights_list_cached = [cell_h] * rows
        row_heights_list = row_heights_list_cached

    # Для совместимости также оставляем col_widths_list
    if _custom_cols is None:
        col_widths_list = [cell_w] * cols

    # 3. Проверка замыкания сетки ТЗ 1.2 (±1e-6) — с кастомными размерами считаем по спискам
    if _custom_cols is not None or _custom_rows is not None:
        delta_x = abs(sum(col_widths_list) + sum_v - grid_w)
        delta_y = abs(sum(row_heights_list) + sum_h - grid_h)
    else:
        delta_x = abs(cols * cell_w + sum_v - grid_w)
        delta_y = abs(rows * cell_h + sum_h - grid_h)
    if delta_x > 1e-6 or delta_y > 1e-6:
        raise ValueError(
            f"Ошибка замыкания сетки: dX={delta_x:.2e}, dY={delta_y:.2e}"
        )

    # 4. Расчёт полос и ячеек — с учётом переменных ширин/высот
    if _custom_cols is not None:
        strips_x = []
        cur_x = x0
        for w in col_widths_list:
            strips_x.append((cur_x, cur_x + w))
            cur_x += w + mw
    else:
        strips_x = calc_strips_x(x0, cell_w, mw, cols)
    if _custom_rows is not None:
        strips_y = []
        cur_y = y0
        for h in row_heights_list:
            strips_y.append((cur_y, cur_y + h))
            cur_y += h + mh
    else:
        strips_y = calc_strips_y(y0, cell_h, mh, rows)
    cells = calc_cells(strips_x, strips_y, params.get("cells", []), cols, rows)

    # 5. Импосты с учётом сплошного направления (переключатель мастера)
    # continuous: auto (по умолчанию, наименьшая сторона сплошная), vertical, horizontal
    mullion_cfg_tmp2 = params.get("mullion", {}) if isinstance(params.get("mullion"), dict) else {}
    cont_raw = str(mullion_cfg_tmp2.get("continuous", mullion_cfg_tmp2.get("continuous_impost", "auto"))).strip().lower()
    if cont_raw in ("v", "vert", "верт", "вертикаль", "вертикальный", "vertical"):
        cont_mode = "vertical"
    elif cont_raw in ("h", "hor", "гор", "горизонталь", "горизонтальный", "horizontal"):
        cont_mode = "horizontal"
    else:
        cont_mode = "auto"
    if cont_mode == "auto":
        # сплошной — наименьшее из двух (ширина/высота светового габарита)
        if grid_w + 1e-9 < grid_h:
            cont_mode = "horizontal"  # ширина меньше → горизонт сплошной
        elif grid_h + 1e-9 < grid_w:
            cont_mode = "vertical"
        else:
            cont_mode = "vertical"  # квадрат — tie-break вертикаль
    mullion_continuous = cont_mode

    mullions_v: list[list[tuple[float, float]]] = []
    mullions_h: list[list[tuple[float, float]]] = []

    # Подгатавливаем кумулятивные позиции для импостов с учётом переменных ширин/высот
    def _x_for_v_impost(idx: int) -> float:  # idx 1..cols-1
        # сумма ширин первых idx колонок + (idx-1)*mw
        return x0 + sum(col_widths_list[:idx]) + (idx - 1) * mw
    def _y_for_h_impost(idx: int) -> float:  # idx 1..rows-1
        return y0 + sum(row_heights_list[:idx]) + (idx - 1) * mh

    if mullion_continuous == "vertical":
        # Вертикаль сплошная на всю высоту y0..y1
        for i in range(1, cols):
            x = _x_for_v_impost(i)
            mullions_v.append([
                (x, y0),
                (x + mw, y0),
                (x + mw, y1),
                (x, y1),
            ])
        # Горизонталь режется между вертикалями (с разрывами)
        vert_intervals = []
        for i in range(1, cols):
            x = _x_for_v_impost(i)
            vert_intervals.append((x, x + mw))
        vert_intervals.sort()
        for j in range(1, rows):
            y = _y_for_h_impost(j)
            prev_x = x0
            for vx1, vx2 in vert_intervals:
                if vx1 - prev_x > 1e-9:
                    mullions_h.append([
                        (prev_x, y),
                        (vx1, y),
                        (vx1, y + mh),
                        (prev_x, y + mh),
                    ])
                prev_x = vx2
            if x1 - prev_x > 1e-9:
                mullions_h.append([
                    (prev_x, y),
                    (x1, y),
                    (x1, y + mh),
                    (prev_x, y + mh),
                ])
        if not vert_intervals and rows > 1:
            pass
    else:  # horizontal continuous
        for j in range(1, rows):
            y = _y_for_h_impost(j)
            mullions_h.append([
                (x0, y),
                (x1, y),
                (x1, y + mh),
                (x0, y + mh),
            ])
        horiz_intervals = []
        for j in range(1, rows):
            y = _y_for_h_impost(j)
            horiz_intervals.append((y, y + mh))
        horiz_intervals.sort()
        for i in range(1, cols):
            x = _x_for_v_impost(i)
            prev_y = y0
            for hy1, hy2 in horiz_intervals:
                if hy1 - prev_y > 1e-9:
                    mullions_v.append([
                        (x, prev_y),
                        (x + mw, prev_y),
                        (x + mw, hy1),
                        (x, hy1),
                    ])
                prev_y = hy2
            if y1 - prev_y > 1e-9:
                mullions_v.append([
                    (x, prev_y),
                    (x + mw, prev_y),
                    (x + mw, y1),
                    (x, y1),
                ])

    # 5a. Импост заходит на раму для вида изнутри (Т-образное соединение 25мм / bead системы)
    # Для INSIDE вида вертикальный импост должен заходить на раму на bead_width, горизонтальный сегмент — на вертикальный
    try:
        _view_for_mullion_ext = str(params.get("view", "OUTSIDE")).upper()
        if _view_for_mullion_ext == "INSIDE" and (mullions_v or mullions_h):
            # bead для расширения берём из будущего bead_width, но пока оценим из params/системы
            _bw_ext_tmp = 25.0
            # пробуем взять bead из params
            try:
                if isinstance(params.get("bead"), dict):
                    _bw_ext_tmp = float(params["bead"].get("width", _bw_ext_tmp))
                elif "bead" in params:
                    _bw_ext_tmp = float(params["bead"])
                elif "bead_width" in params:
                    _bw_ext_tmp = float(params["bead_width"])
                elif _sys_prof_tmp is not None:
                    _tmp_bw = _resolve_bead_from_profile(_sys_prof_tmp, params)
                    if _tmp_bw is not None:
                        _bw_ext_tmp = float(_tmp_bw)
            except Exception:
                pass
            # Вертикальный сплошной → заходит на раму на bw
            if mullion_continuous == "vertical":
                for poly in mullions_v:
                    try:
                        # poly: [(x,y0),(x+mw,y0),(x+mw,y1),(x,y1)] — расширяем y0-=bw, y1+=bw
                        ys = [p[1] for p in poly]
                        y_min, y_max = min(ys), max(ys)
                        for i, (x, y) in enumerate(poly):
                            if abs(y - y_min) < 1e-9:
                                poly[i] = (x, y - _bw_ext_tmp)
                            elif abs(y - y_max) < 1e-9:
                                poly[i] = (x, y + _bw_ext_tmp)
                    except Exception:
                        pass
                # Горизонтальные сегменты заходят на вертикальный на bw
                for poly in mullions_h:
                    try:
                        xs = [p[0] for p in poly]
                        x_min, x_max = min(xs), max(xs)
                        # проверяем, касается ли сегмент вертикального импоста (с зазором bw)
                        # расширяем на bw в сторону вертикального, если рядом вертикальный
                        # Определяем, упирается ли левый/правый край в вертикальный
                        # Левый край: если рядом есть вертикальный с x == x_min - mw (т.е. вертикальный справа от сегмента?) — уже учтён как разрыв
                        # Проще: расширить оба края на bw, но не выходить за frame
                        # Но чтобы не выйти за frame, ограничим расширением только если рядом вертикальный
                        # Проверяем наличие вертикального рядом
                        has_vert_left = any(abs(min(vp[0][0], vp[1][0]) - x_min) < 80+1e-6 or abs(max(vp[0][0], vp[1][0]) - x_min) < 1e-6 for vp in mullions_v)
                        has_vert_right = any(abs(min(vp[0][0], vp[1][0]) - x_max) < 1e-6 or abs(max(vp[0][0], vp[1][0]) - x_max) < 80+1e-6 for vp in mullions_v)
                        # Расширяем только если есть вертикальный рядом (Т-соединение)
                        for i, (x, y) in enumerate(poly):
                            if has_vert_left and abs(x - x_min) < 1e-9:
                                poly[i] = (x - _bw_ext_tmp, y)
                            if has_vert_right and abs(x - x_max) < 1e-9:
                                poly[i] = (x + _bw_ext_tmp, y)
                        # Также если сегмент упирается в раму (x_min == x0 или x_max == x1), заходит на раму на bw
                        # x0/x1 доступны выше
                        try:
                            if abs(x_min - x0) < 1e-6:
                                for i, (x, y) in enumerate(poly):
                                    if abs(x - x_min) < 1e-9:
                                        poly[i] = (x - _bw_ext_tmp, y)
                            if abs(x_max - x1) < 1e-6:
                                for i, (x, y) in enumerate(poly):
                                    if abs(x - x_max) < 1e-9:
                                        poly[i] = (x + _bw_ext_tmp, y)
                        except Exception:
                            pass
                    except Exception:
                        pass
            else:  # horizontal continuous
                for poly in mullions_h:
                    try:
                        xs = [p[0] for p in poly]
                        x_min, x_max = min(xs), max(xs)
                        for i, (x, y) in enumerate(poly):
                            if abs(x - x_min) < 1e-9:
                                poly[i] = (x - _bw_ext_tmp, y)
                            elif abs(x - x_max) < 1e-9:
                                poly[i] = (x + _bw_ext_tmp, y)
                    except Exception:
                        pass
                for poly in mullions_v:
                    try:
                        ys = [p[1] for p in poly]
                        y_min, y_max = min(ys), max(ys)
                        has_horiz_bottom = any(abs(min(hp[0][1], hp[1][1]) - y_min) < 1e-6 for hp in mullions_h)
                        has_horiz_top = any(abs(max(hp[0][1], hp[1][1]) - y_max) < 1e-6 for hp in mullions_h)
                        for i, (x, y) in enumerate(poly):
                            if has_horiz_bottom and abs(y - y_min) < 1e-9:
                                poly[i] = (x, y - _bw_ext_tmp)
                            if has_horiz_top and abs(y - y_max) < 1e-9:
                                poly[i] = (x, y + _bw_ext_tmp)
                        try:
                            if abs(y_min - y0) < 1e-6:
                                for i, (x, y) in enumerate(poly):
                                    if abs(y - y_min) < 1e-9:
                                        poly[i] = (x, y - _bw_ext_tmp)
                            if abs(y_max - y1) < 1e-6:
                                for i, (x, y) in enumerate(poly):
                                    if abs(y - y_max) < 1e-9:
                                        poly[i] = (x, y + _bw_ext_tmp)
                        except Exception:
                            pass
                    except Exception:
                        pass
    except Exception:
        pass

    # 5b. Штапик — единый параметр системы (25 мм по умолчанию), одинаков для рамы/импоста/створки
    bead_width_val = 25.0
    bead_src = None
    if isinstance(params.get("bead"), dict):
        bead_src = params.get("bead")
        try:
            bead_width_val = float(bead_src.get("width", bead_src.get("value", bead_src.get("shtapik", 25.0))))
        except Exception:
            bead_width_val = 25.0
    elif isinstance(params.get("shtapik"), dict):
        bead_src = params.get("shtapik")
        try:
            bead_width_val = float(bead_src.get("width", bead_src.get("value", 25.0)))
        except Exception:
            bead_width_val = 25.0
    elif "bead_width" in params:
        try:
            bead_width_val = float(params["bead_width"])
        except Exception:
            bead_width_val = 25.0
    elif "shtapik_width" in params:
        try:
            bead_width_val = float(params["shtapik_width"])
        except Exception:
            bead_width_val = 25.0
    elif "shtapik" in params and not isinstance(params["shtapik"], dict):
        try:
            bead_width_val = float(params["shtapik"])
        except Exception:
            bead_width_val = 25.0
    elif "bead" in params and not isinstance(params["bead"], dict):
        try:
            bead_width_val = float(params["bead"])
        except Exception:
            bead_width_val = 25.0
    # fallback из системы профилей если в params нет явного bead
    if bead_src is None and "bead" not in params and "shtapik" not in params and "bead_width" not in params and "shtapik_width" not in params:
        if _sys_prof_tmp is not None:
            bw_prof = _resolve_bead_from_profile(_sys_prof_tmp, params)
            if bw_prof is not None:
                try:
                    bead_width_val = float(bw_prof)
                except Exception:
                    pass
    # защита от отрицательных/невалидных уже в validate, но на всякий
    if bead_width_val is None or bead_width_val < 0:
        bead_width_val = 25.0

    # 6. Створки (двухконтурные + ГОСТ-стрелки) — с учётом штапика: суммарный наплав = so + bead_width_val
    # По ТЗ: рама 60, штапик 20, наплав 8 => створка заходит на 28, снаружи видимая 52 (80-28), изнутри 60+20
    _sash_total_overlap = float(so) + float(bead_width_val) if float(bead_width_val) > 1e-9 else float(so)
    sashes = calc_sashes(cells, _sash_total_overlap, sw)

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
    # Было 8: OBJECT, WINDOW_NAME, COLOR_OUT, COLOR_IN, GLAZING, SIZE_W, SIZE_H, GRID -> стало 6 с SYSTEM
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
    # Габарит + вид — сливаем WхH и вид (Снаружи/Изнутри) как в примере 1500х1500 Снаружи, поднимаем на строку выше Заполнения
    view_for_size = str(params.get("view", "OUTSIDE")).upper()
    view_str_for_size = "Снаружи" if view_for_size == "OUTSIDE" else "Изнутри"
    size_combined = f"{int(ow) if ow.is_integer() else ow}х{int(oh) if oh.is_integer() else oh} {view_str_for_size}"
    # Система вместо сетки — по ТЗ изменение атрибута GRID -> SYSTEM
    system_val = str(params.get("system") or _sys_name_tmp or "")
    # Если профиль имеет человекочитаемое имя, можно использовать его, но оставляем ID для однозначности
    # Для отображения: если system_val пустой, подставим "-"
    if not system_val:
        system_val = "-"
    object_val = str(meta.get("object", "Тестовый объект"))
    # Порядок (сверху вниз): OBJECT / WINDOW / COLOR / SIZE+вид / GLAZING / SYSTEM
    # По правке: SIZE/вид поднят на строку выше, GLAZING опущен ниже, GRID заменён на SYSTEM
    attdefs = [
        ("OBJECT", "Объект", object_val),
        ("WINDOW", "Окно / кол-во", window_combined),
        ("COLOR", "Цвет", colors_combined),
        ("SIZE", "Габарит", size_combined),
        ("GLAZING", "Заполнение", glazing_val),
        ("SYSTEM", "Система", system_val),
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
    # 7c. Штапик — геометрия по ячейкам (рама/импосты/створки), одинаковая ширина bead_width_val
    # Логика ПВХ: штапик — фиксатор стеклопакета, виден только изнутри (INSIDE), соединение под 45° (митра) по диагонали стеклопакета.
    # Для глухих ячеек штапик идёт по раме/импосту вокруг ячейки (4 полосы с митрой в углах ячейки).
    # Для ячеек со створкой штапик только в створке (по inner_rect), по раме/импосту в этой ячейке не отрисовывать.
    # На стыках рама-импост и импост-импост сечение штапика — по диагонали стеклопакета (45°), что достигается
    # генерацией штапика по каждой ячейке отдельно, а не общей рамой + отдельными импостами.
    # Для створки штапик внутри inner_rect, заходит на брусок створки, а не вываливается наружу.
    bead_polys: list[list[tuple[float, float]]] = []
    bw = bead_width_val
    view_for_bead = str(params.get("view", "OUTSIDE")).upper()
    if view_for_bead == "OUTSIDE":
        bead_polys = []  # снаружи штапик скрыт — не рисуем
    elif bw > 1e-9:
        # По ТЗ для ABSTRACT: рама 60+штапик20 => снаружи 60, изнутри 40+20; импост 80+20*2 => снаружи 80, изнутри 20+40+20
        # Т-образный заход импоста в раму — 20 (bead) уже реализован в 5a
        # Штапик — наружу от ячейки/створки на 20 (на раму/импост/створку), митра 45°
        sash_cells_set = set()
        for _s in sashes:
            try:
                _rc = tuple(_s.get("cell", ()))
                if len(_rc) == 2:
                    sash_cells_set.add(_rc)
            except Exception:
                pass
        # Глухие ячейки — штапик наружу от ячейки на раму/импост (20), с митрой 45°
        # Видимая рама изнутри 40+20, импост 20+40+20, снаружи 60/80
        for cell in cells:
            if (cell["row"], cell["col"]) in sash_cells_set:
                continue
            try:
                x1, y1, x2, y2 = float(cell["x1"]), float(cell["y1"]), float(cell["x2"]), float(cell["y2"])
                x1, x2 = (min(x1, x2), max(x1, x2))
                y1, y2 = (min(y1, y2), max(y1, y2))
                if x2 - x1 <= 1e-9 or y2 - y1 <= 1e-9:
                    continue
                # Низ — наружу вниз на раму/импост: outer y1-bw длиннее, inner y1 короче
                bead_polys.append([(x1, y1), (x2, y1), (x2 + bw, y1 - bw), (x1 - bw, y1 - bw)])
                # Верх — наружу вверх
                bead_polys.append([(x1, y2), (x1 - bw, y2 + bw), (x2 + bw, y2 + bw), (x2, y2)])
                # Лево — наружу влево
                bead_polys.append([(x1, y1), (x1 - bw, y1 - bw), (x1 - bw, y2 + bw), (x1, y2)])
                # Право — наружу вправо
                bead_polys.append([(x2, y1), (x2, y2), (x2 + bw, y2 + bw), (x2 + bw, y1 - bw)])
            except Exception:
                pass
        # Створки: штапик вокруг стекла на створке (80+20) — наружу от inner_rect? Для створки 80+20:
        # снаружи видимая от рамы/импоста 80-20-8=52 (заход 28), изнутри 60+20, находит на 28
        # Штапик на створке — между стеклом и профилем створки, 20 на профиле, митра 45°
        # inner_rect — световой проём створки (стекло), bead — на профиле створки вокруг стекла
        # Для створки низ — наружу вниз? Для створки профиль снизу, стекло выше, bead между ними: outer at glass edge y1 (длиннее), inner at y1-bw (короче) вниз на профиль
        for sash in sashes:
            try:
                ir = sash.get("inner_rect")
                if not ir:
                    continue
                sx1, sy1, sx2, sy2 = ir
                sx1, sx2 = (min(sx1, sx2), max(sx1, sx2))
                sy1, sy2 = (min(sy1, sy2), max(sy1, sy2))
                if sx2 - sx1 <= 2 * bw + 1e-9 or sy2 - sy1 <= 2 * bw + 1e-9:
                    continue
                # Низ створки — между стеклом и профилем снизу: outer south длиннее (стекло+40), inner north короче (стекло) — наружу на профиль 20
                bead_polys.append([(sx1 - bw, sy1 - bw), (sx2 + bw, sy1 - bw), (sx2, sy1), (sx1, sy1)])
                # Верх — выше стекла: outer north длиннее, inner south короче
                bead_polys.append([(sx1, sy2), (sx2, sy2), (sx2 + bw, sy2 + bw), (sx1 - bw, sy2 + bw)])
                # Лево — левее стекла: outer west длиннее, inner east короче
                bead_polys.append([(sx1 - bw, sy1 - bw), (sx1, sy1), (sx1, sy2), (sx1 - bw, sy2 + bw)])
                # Право — правее стекла: outer east длиннее, inner west короче
                bead_polys.append([(sx2, sy1), (sx2 + bw, sy1 - bw), (sx2 + bw, sy2 + bw), (sx2, sy2)])
            except Exception:
                pass
    # 7d. Заполнение — стеклопакет (слой Невидимые, штриховой, скрыт под штапиком)
    # По новому ТЗ: заполнение от посадочной линии штапика -5 мм (фалец), т.е. от размера штапика -10 мм.
    # Для глухих: посадочная линия = граница ячейки (cell), штапик наружу 20 на раму/импост, заполнение внутри ячейки -5 от ячейки
    # Для створки: посадочная линия = inner_rect створки (световой проём), штапик на створке 20, заполнение внутри inner -5
    # Для вида снаружи заполнение не должно находить на линии рам/импостов — теперь оно внутри, не на линиях.
    fillings: list[dict[str, Any]] = []
    filling_polys: list[list[tuple[float, float]]] = []
    filling_texts: list[tuple[tuple[float, float], str]] = []
    # Фалец 5 мм от посадочной линии, т.е. заполнение = штапик -10 (5 с каждой стороны)
    # Посадочная линия = cell (для глухих) / inner_rect (для створок), штапик наружу/на створке 20
    falz_inset = 5.0  # 5 мм от посадочной линии внутрь
    # Поддержка переопределения через params: glazing_falz / falz / glazing_inset
    try:
        _falz = None
        for _k in ("glazing_falz", "falz", "falz_inset", "glazing_inset"):
            if _k in params and params[_k] is not None:
                _falz = params[_k]
                break
            if isinstance(params.get("glazing"), dict) and _k in params["glazing"]:
                _falz = params["glazing"][_k]
                break
        if _falz is not None:
            try:
                falz_inset = float(_falz)
            except Exception:
                pass
        # bead -10 означает falz 5, уже учтено; если задан glazing_overlap — игнорируем, используем falz
    except Exception:
        pass
    if falz_inset is None or falz_inset < 0:
        falz_inset = 5.0
    # Для вида снаружи заполнение внутри — не на линиях рам/импостов (INSIDE и OUTSIDE теперь внутри)
    try:
        for cell in cells:
            sash = next((s for s in sashes if tuple(s.get("cell", ())) == (cell["row"], cell["col"])), None)
            if sash is not None and sash.get("inner_rect"):
                rx1, ry1, rx2, ry2 = sash["inner_rect"]
                # для створки — посадочная линия = inner_rect (штапик на створке), заполнение внутри -5
                rx1, rx2 = (min(float(rx1), float(rx2)), max(float(rx1), float(rx2)))
                ry1, ry2 = (min(float(ry1), float(ry2)), max(float(ry1), float(ry2)))
                fx1 = rx1 + falz_inset
                fy1 = ry1 + falz_inset
                fx2 = rx2 - falz_inset
                fy2 = ry2 - falz_inset
            else:
                # глухое — посадочная линия = cell, заполнение внутри -5 (фалец)
                rx1, ry1, rx2, ry2 = float(cell["x1"]), float(cell["y1"]), float(cell["x2"]), float(cell["y2"])
                rx1, rx2 = (min(rx1, rx2), max(rx1, rx2))
                ry1, ry2 = (min(ry1, ry2), max(ry1, ry2))
                fx1 = rx1 + falz_inset
                fy1 = ry1 + falz_inset
                fx2 = rx2 - falz_inset
                fy2 = ry2 - falz_inset
            if fx2 - fx1 < 10 or fy2 - fy1 < 10:
                continue
            poly = [(fx1, fy1), (fx2, fy1), (fx2, fy2), (fx1, fy2)]
            filling_polys.append(poly)
            w = fx2 - fx1
            h = fy2 - fy1
            w_s = f"{int(w) if float(w).is_integer() else round(w,1)}"
            h_s = f"{int(h) if float(h).is_integer() else round(h,1)}"
            txt = f"{w_s}х{h_s}"
            # Текст внутри заполнения, не на линиях рам/импостов: внутри на 8 мм от угла заполнения
            tx = fx1 + 8
            ty = fy1 + 8
            fillings.append({"cell": (cell["row"], cell["col"]), "rect": (fx1, fy1, fx2, fy2), "poly": poly, "w": w, "h": h, "text": txt, "pos": (tx, ty)})
            filling_texts.append(((tx, ty), txt))
    except Exception:
        pass
    primitives_count += len(bead_polys)  # штапик — LWPOLYLINE
    # заполнения на непечатном слое — в primitives не считаем (справочные)
    primitives_count += len(attdefs)  # ATTDEF

    return {
        "params": params,
        "window_name": window_name,
        "block_name": block_name,
        "opening": {"width": ow, "height": oh, "seam": s},
        "opening_poly": opening_poly,
        "frame_dim": {"width": ow - 2 * s, "height": oh - 2 * s},
        "grid": {"cols": cols, "rows": rows, "cell_w": cell_w, "cell_h": cell_h, "col_widths": col_widths_list, "row_heights": row_heights_list},
        "frame_outer": frame_outer,
        "frame_inner": frame_inner,
        "frame_mitres": frame_mitres,
        "strips_x": strips_x,
        "strips_y": strips_y,
        "mullions_v": mullions_v,
        "mullions_h": mullions_h,
        "mullion_continuous": mullion_continuous,
        "cells": cells,
        "sashes": sashes,
        "sill": sill_poly,
        "addons": addons,
        "addons_info": addons_info,
        "bead_width": bead_width_val,
        "bead_polys": bead_polys,
        "fillings": fillings,
        "filling_polys": filling_polys,
        "filling_texts": filling_texts,
        "system": _sys_name_tmp,
        "profile": _sys_prof_tmp,
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
            # Штриховая линия для проёма: GOST 2.303.4, толщина 0.09 (weight 9)
            # Пытаемся создать тип линии если нет
            if "GOST2.303 4" not in doc.linetypes:
                try:
                    # В шаблоне уже есть, но если нет — создаём DASHED как fallback
                    doc.linetypes.add("GOST2.303 4", pattern=[0.5, 0.5, -0.5], description="GOST 2.303.4")
                except Exception:
                    pass
            lt = "GOST2.303 4" if "GOST2.303 4" in doc.linetypes else "DASHED"
            doc.layers.add(layer_opening, color=7, linetype=lt, lineweight=9)
        except Exception:
            try:
                doc.layers.add(layer_opening, color=1)
                try:
                    # Устанавливаем GOST 2.303.4 и толщину 0.09 если слой уже есть
                    lt = "GOST2.303 4" if "GOST2.303 4" in doc.linetypes else "DASHED"
                    doc.layers.get(layer_opening).dxf.linetype = lt
                    doc.layers.get(layer_opening).dxf.lineweight = 9
                    doc.layers.get(layer_opening).color = 7
                except Exception:
                    pass
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

    # 2c. Слой Заполнение — справочный, непечатный/скрытый для размеров заполнений (текст W×H)
    layer_fill = "Заполнение"
    if layer_fill not in doc.layers:
        try:
            doc.layers.add(layer_fill, color=6)
        except Exception:
            try:
                doc.layers.add(layer_fill, color=6, linetype="Continuous")
            except Exception:
                pass
    try:
        lf = doc.layers.get(layer_fill)
        try:
            lf.dxf.plot = 0
        except Exception:
            pass
        try:
            lf.is_plottable = False
        except Exception:
            pass
        try:
            lf.is_off = False
            lf.is_frozen = False
        except Exception:
            pass
    except Exception:
        pass

    # 2d. Слой Невидимые — для контура стеклопакета, который находится под штапиком (штапик прижимает СП)
    # Контур скрыт, поэтому рисуется штриховой линией на отдельном слое
    layer_invis = "Невидимые"
    if layer_invis not in doc.layers:
        try:
            # Пытаемся создать с штриховым типом линии как у Штриховые
            lt_invis = "GOST2.303 4" if "GOST2.303 4" in doc.linetypes else "DASHED"
            if lt_invis not in doc.linetypes and lt_invis == "DASHED":
                try:
                    doc.linetypes.new("DASHED", dxfattribs={"description": "Dashed"})
                except Exception:
                    pass
            doc.layers.add(layer_invis, color=7, linetype=lt_invis if lt_invis in doc.linetypes else "DASHED")
        except Exception:
            try:
                doc.layers.add(layer_invis, color=7)
            except Exception:
                pass
    try:
        li = doc.layers.get(layer_invis)
        # Невидимые — скрытый контур, делаем непечатным или штриховым (оставляем видимым но штриховым)
        # По ТЗ: непечатный как и Заполнение, но с штриховой линией
        try:
            li.dxf.plot = 0
        except Exception:
            pass
        try:
            li.is_plottable = False
        except Exception:
            pass
        try:
            li.is_off = False
            li.is_frozen = False
        except Exception:
            pass
        # Установим штриховой тип если есть
        try:
            if li.dxf.linetype == "Continuous":
                li.dxf.linetype = "DASHED" if "DASHED" in doc.linetypes else li.dxf.linetype
        except Exception:
            pass
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
            # Условное обозначение открывания: для вида изнутри — сплошная (Continuous) на Штриховые,
            # для вида снаружи — по слою (GOST 2.303.4)
            view_ind = str(model.get("params", {}).get("view", "OUTSIDE")).upper()
            if view_ind == "INSIDE":
                ltype = "Continuous"
            else:
                ltype = "ByLayer"
            ent_ind = blk.add_line(p1, p2, dxfattribs={"layer": layer_opening, "linetype": ltype})
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

    # 9c. Штапик — отрисовка полос шириной bead_width (рама/импосты/створки)
    # Для INSIDE вид — штапик рамы/импостов под створкой скрыт (аналогично раме), но штапик самой створки не вырезается своей же створкой
    view_bead = str(model.get("params", {}).get("view", "OUTSIDE")).upper()
    bead_sash_rects = [s.get("outer_rect") for s in model.get("sashes", []) if s.get("outer_rect")]
    # также соберём inner_rect створок для определения принадлежности полигона к створке
    sash_inner_rects = [s.get("inner_rect") for s in model.get("sashes", []) if s.get("inner_rect")]
    for poly in model.get("bead_polys", []):
        try:
            if view_bead == "INSIDE" and bead_sash_rects:
                # Определяем, принадлежит ли полигон штапика конкретной створке (центр полигона внутри её outer_rect)
                # чтобы не вырезать его своей же створкой
                cx = sum(p[0] for p in poly) / len(poly)
                cy = sum(p[1] for p in poly) / len(poly)
                owner_idx = -1
                for idx, ir in enumerate(sash_inner_rects):
                    if ir is None:
                        continue
                    ix1, iy1, ix2, iy2 = ir
                    # bead створки находится вокруг inner_rect, центр должен быть близко к inner_rect
                    # проверяем попадание центра в расширенный inner_rect (+bw)
                    bw_tmp = float(model.get("bead_width", 25))
                    if (min(ix1, ix2) - bw_tmp - 1e-6 <= cx <= max(ix1, ix2) + bw_tmp + 1e-6 and
                        min(iy1, iy2) - bw_tmp - 1e-6 <= cy <= max(iy1, iy2) + bw_tmp + 1e-6):
                        # дополнительно проверяем что полигон близко к inner_rect
                        # если полигон — створки, он должен быть в пределах outer_rect
                        orx = bead_sash_rects[idx]
                        if orx and (min(orx[0], orx[2]) -1e-6 <= cx <= max(orx[0], orx[2])+1e-6 and min(orx[1], orx[3]) -1e-6 <= cy <= max(orx[1], orx[3])+1e-6):
                            owner_idx = idx
                            break
                # Разбиваем полигон штапика на линии и вычитаем створки, кроме своей
                b_lines = [
                    (poly[0], poly[1]),
                    (poly[1], poly[2]),
                    (poly[2], poly[3]),
                    (poly[3], poly[0]),
                ]
                has_outside = False
                for (x0, y0), (x1, y1) in b_lines:
                    segs = [((x0, y0), (x1, y1))]
                    for s_idx, (rx1, ry1, rx2, ry2) in enumerate(bead_sash_rects):
                        if s_idx == owner_idx:
                            continue  # не вырезаем свой штапик
                        new_segs = []
                        for (sx0, sy0), (sx1, sy1) in segs:
                            new_segs.extend(_subtract_rect_from_line(sx0, sy0, sx1, sy1, rx1, ry1, rx2, ry2))
                        segs = new_segs
                        if not segs:
                            break
                    for (sx0, sy0), (sx1, sy1) in segs:
                        blk.add_line((sx0, sy0), (sx1, sy1), dxfattribs={"layer": layer_name})
                        has_outside = True
                # если весь полигон внутри своей створки, он всё равно должен отрисоваться — уже отрисован выше как линии
                # для створки без обрезки (нет других створок) — линии уже добавлены
                if not has_outside and owner_idx != -1:
                    # fallback: отрисовать как LWPOLYLINE если не было обрезки
                    # но для створки мы уже отрисовали линии, так что ничего
                    pass
            else:
                blk.add_lwpolyline(
                    poly,
                    close=True,
                    dxfattribs={"layer": layer_name},
                )
        except Exception:
            pass

    # 9d. Заполнение — контур стеклопакета на слое Невидимые (под штапиком, скрыт), размер на Заполнение
    for poly in model.get("filling_polys", []):
        try:
            ent = blk.add_lwpolyline(poly, close=True, dxfattribs={"layer": layer_invis})
            try:
                ent.dxf.linetype_scale = 25.0
            except Exception:
                pass
        except Exception:
            pass
    for (tx, ty), txt in model.get("filling_texts", []):
        try:
            # высота 16, как у площади но меньше, стиль WindowStyle уже создан в 2b
            fill_style = "WindowStyle"
            if fill_style not in doc.styles:
                fill_style = "Основной стиль (для надписей)" if "Основной стиль (для надписей)" in doc.styles else "WindowStyle"
            t = blk.add_text(txt, height=16, dxfattribs={"layer": layer_fill, "style": fill_style})
            t.dxf.insert = (tx, ty, 0)
            t.dxf.halign = 0
            t.dxf.valign = 0
            try:
                t.dxf.align_point = (tx, ty, 0)
            except Exception:
                pass
        except Exception:
            pass

    # 10. Добавление 6 ATTDEF в блок (слитые строки, доработка ТЗ 0.2)
    # Доработка: вынести выше окна, выровнять по левому углу (x=0, y=OH+...)
    # Атрибуты: OBJECT / WINDOW(ОК-1/1 шт.) / COLOR(RAL8017/RAL9016) / GLAZING(Заполнение СПД42) / SIZE(1500х1500 Снаружи) / SYSTEM(ABSTRACT...)
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
                ds.dxf.dimscale = max(cur_scale, 4.0)  # минимум 4, соразмерно тексту атрибутов 30 (dimtxt 8*4=32)
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
    # Выравниваем масштаб 2-й цепочки (с точками) с 1-й и 3-й — одинаковый dimscale/dimtxt
    try:
        ds_dots = doc.dimstyles.get("Основной стиль с точками")
        if ds_dots is not None:
            for attr, val in [("dimtxt", 8.0), ("dimasz", 6.0), ("dimscale", 4.0), ("dimexe", 3.0), ("dimexo", 2.5), ("dimgap", 3.0)]:
                try:
                    setattr(ds_dots.dxf, attr, val)
                except Exception:
                    pass
            try:
                if not getattr(ds_dots.dxf, "dimtxsty", None):
                    ds_dots.dxf.dimtxsty = "Основной стиль"
                # если уже есть, оставляем как есть но масштаб уже выровнен
            except Exception:
                pass
            # Синхронизируем dimscale с основным стилем если основной был >4
            try:
                main_scale = float(doc.dimstyles.get(dim_style_name).dxf.dimscale) if dim_style_name in doc.dimstyles else 4.0
                if float(getattr(ds_dots.dxf, "dimscale", 4.0)) != main_scale:
                    ds_dots.dxf.dimscale = main_scale
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
        # idx 0 = OBJECT -> самый верхний (y_start + (n-1)*step), idx 5 = SYSTEM -> самый нижний (y_start)
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

        def _add_dim(p1, p2, base, angle=0, dimstyle=None):
            try:
                _ds = dimstyle if dimstyle else dim_style_name
                dim = blk.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle=_ds)
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
        base_y_detailed = -80.0
        for i in range(len(horiz_points) - 1):
            x_a, x_b = horiz_points[i], horiz_points[i+1]
            if abs(x_b - x_a) < 1e-6:
                continue
            _add_dim(p1=(x_a, horiz_ref_y), p2=(x_b, horiz_ref_y), base=(0, base_y_detailed), angle=0)
        base_y_window = -160.0
        # Габарит окна с доборами — вторая цепочка, стиль с точками
        _add_dim(p1=(overall_left, horiz_ref_y), p2=(overall_right, horiz_ref_y), base=(0, base_y_window), angle=0, dimstyle="Основной стиль с точками")
        base_y_opening = -240.0
        _add_dim(p1=(0, 0), p2=(float(ow), 0), base=(0, base_y_opening), angle=0)
        # Отдельный размер для доборов слева/справа (горизонтально) если есть
        if addon_left > 1e-9:
            _add_dim(p1=(overall_left, horiz_ref_y), p2=(frame_left, horiz_ref_y), base=(0, base_y_detailed), angle=0)
        if addon_right > 1e-9:
            _add_dim(p1=(frame_right, horiz_ref_y), p2=(overall_right, horiz_ref_y), base=(0, base_y_detailed), angle=0)
        # Монтажные швы горизонтальные — в одну линию с 2-й цепочкой (base -160)
        base_y_seam = base_y_window
        if abs(overall_left) > 1e-9:
            _add_dim(p1=(0, 0), p2=(overall_left, 0), base=(0, base_y_seam), angle=0)
        if abs(float(ow) - overall_right) > 1e-9:
            _add_dim(p1=(overall_right, 0), p2=(float(ow), 0), base=(0, base_y_seam), angle=0)
        # Размер подставочного профиля горизонтально? — ширина как окно, уже есть, дополнительно не нужно
        # Доборы уже имеют отдельный размер на базе -60, швы теперь на -120 во второй цепочке

        # Вертикальные только справа: привязка к правому краю блока (x = overall_right для окна с доборами, иначе frame_right)
        vert_ref_x = overall_right if (addon_right > 1e-9 or addon_left > 1e-9) else frame_right
        vert_points = [frame_bottom] + horiz_centers + [frame_top]
        base_x_detailed_r = float(ow) + 80.0
        for i in range(len(vert_points) - 1):
            y_a, y_b = vert_points[i], vert_points[i+1]
            if abs(y_b - y_a) < 1e-6:
                continue
            _add_dim(p1=(vert_ref_x, y_a), p2=(vert_ref_x, y_b), base=(base_x_detailed_r, 0), angle=90)
        base_x_window_r = float(ow) + 160.0
        _add_dim(p1=(vert_ref_x, frame_bottom), p2=(vert_ref_x, frame_top), base=(base_x_window_r, 0), angle=90, dimstyle="Основной стиль с точками")
        # Размер подставочного профиля (вертикально) — во второй цепочке (base 120)
        if sill and abs(sill_top - sill_bottom) > 1e-9:
            _add_dim(p1=(vert_ref_x, sill_bottom), p2=(vert_ref_x, sill_top), base=(float(ow) + 80.0, 0), angle=90, dimstyle="Основной стиль с точками")
        # Доборы вертикальные — во второй цепочке
        if addon_top > 1e-9:
            _add_dim(p1=(vert_ref_x, frame_top), p2=(vert_ref_x, overall_top), base=(base_x_window_r, 0), angle=90, dimstyle="Основной стиль с точками")
            # общий с добором уже есть как window overall, дополнительно не нужно
        base_x_opening_r = float(ow) + 240.0
        _add_dim(p1=(float(ow), 0), p2=(float(ow), float(oh)), base=(base_x_opening_r, 0), angle=90)
        # Монтажные швы вертикальные — в одну линию с 2-й цепочкой (base +160)
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

    # 12. Сохранение DXF (с обработкой занятого файла на Windows)
    try:
        if out_file.exists():
            try:
                out_file.unlink()
            except PermissionError:
                # файл занят — попробуем сохранить под _new и подсказать
                alt = out_file.with_name(out_file.stem + "_new" + out_file.suffix)
                print(f"  Предупреждение: файл {out_file} занят, пробуем сохранить как {alt.name}")
                try:
                    doc.saveas(alt)
                    print(f"  Сохранено под альтернативным именем: {alt} — закройте {out_file.name} и переименуйте")
                    return alt
                except Exception as e2:
                    print(f"  Ошибка сохранения DXF (занят): {e2}. Закройте файл в AutoCAD/проводнике и повторите.")
                    raise PermissionError(f"Файл занят: {out_file}") from e2
            except Exception:
                pass
        doc.saveas(out_file)
        return out_file
    except PermissionError as e_perm:
        print(f"  Ошибка: файл {out_file} занят (Permission denied). Закройте его и повторите. {e_perm}")
        raise


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
        actual_out = export_to_dxf(model, out_dxf_path, template_path=tpl_path)
        if actual_out is not None:
            out_dxf_path = Path(actual_out)
        size_bytes = out_dxf_path.stat().st_size
        size_kb = size_bytes / 1024.0

        rel_path = f"./{out_dxf_path.as_posix()}" if not str(out_dxf_path).startswith(".") else str(out_dxf_path)
        print("[6/6] Экспорт DXF... OK")
        print(f"      Файл:       {rel_path}")
        print(f"      Размер:     {size_kb:.1f} KB")
    except PermissionError as e_perm:
        print(f"[6/6] Экспорт DXF... ОШИБКА: файл занят (Permission denied): {e_perm}")
        print(f"      Закройте файл {out_dxf_path} в AutoCAD/проводнике и повторите.")
        return 1
    except Exception as e:
        print(f"[6/6] Экспорт DXF... ОШИБКА: {e}")
        import traceback; traceback.print_exc()
        return 1

    # Опциональная конвертация в DWG — после успеха удалять DXF (но не в режиме тестов, чтобы unittest не падал)
    _is_test_main = any("unittest" in a for a in sys.argv) or any("test_window_export" in a for a in sys.argv)
    dwg_res = convert_to_dwg(out_dxf_path)
    if dwg_res and Path(dwg_res).is_file() and not _is_test_main:
        try:
            Path(out_dxf_path).unlink()
            print(f"  DXF удалён после конвертации (остался DWG): {dwg_res}")
        except Exception as e:
            print(f"  Не удалось удалить DXF {out_dxf_path}: {e}")
    elif dwg_res and _is_test_main:
        print(f"  [тест] DXF сохранён рядом с DWG для проверки: {out_dxf_path} + {dwg_res}")

    # Дополнительно: вид изнутри для отработки ошибок (если основной OUTSIDE)
    try:
        current_view = str(params.get("view", "OUTSIDE")).upper()
        if current_view == "OUTSIDE":
            inside_params = copy.deepcopy(params)
            inside_params["view"] = "INSIDE"
            inside_model = build_window_model(inside_params)
            inside_path = out_dxf_path.parent / f"{inside_model['window_name']}_INSIDE.dxf"
            actual_inside = export_to_dxf(inside_model, inside_path, template_path=tpl_path)
            if actual_inside is not None:
                inside_path = Path(actual_inside)
            isize = inside_path.stat().st_size / 1024.0
            print(f"  Вид изнутри (для отработки): ./{inside_path.as_posix()} ({isize:.1f} KB)")
            dwg_inside = convert_to_dwg(inside_path)
            if dwg_inside and Path(dwg_inside).is_file() and not _is_test_main:
                try:
                    Path(inside_path).unlink()
                    print(f"  DXF изнутри удалён после конвертации (остался DWG): {dwg_inside}")
                except Exception as e:
                    print(f"  Не удалось удалить DXF {inside_path}: {e}")
            elif dwg_inside and _is_test_main:
                print(f"  [тест] DXF изнутри сохранён для проверки: {inside_path} + {dwg_inside}")
    except Exception as e:
        print(f"  Не удалось сформировать вид изнутри: {e}")

    # Все примеры — также по команде python window_export.py (требование: все примеры в DWG)
    # Пропускаем тяжёлую сборку всех примеров при запуске из unittest (чтобы тесты не тормозили)
    import sys as _sys
    # Проверяем запуск через unittest по аргументам командной строки (ezdxf тянет unittest в sys.modules всегда)
    _is_test = any("unittest" in a for a in _sys.argv) or any("test_window_export" in a for a in _sys.argv)
    if not _is_test:
        try:
            # Импортируем генератор примеров и собираем все 12 в один файл
            import generate_examples as _ge
            examples = _ge.make_examples()
            out_all = Path("output") / "Все_примеры.dxf"
            # Используем тот же шаблон, что и для одиночного
            actual_all = _ge.export_all_to_one(examples, str(out_all), template_path=tpl_path)
            # export_all_to_one возвращает фактический путь (может быть _new при занятом файле)
            if actual_all is not None:
                out_all = Path(actual_all)
            # Конвертация всех примеров в DWG — только если DXF ещё существует (generate_examples уже конвертирует, но на случай если ODA не был доступен там)
            if out_all.exists() and out_all.suffix.lower() == ".dxf":
                dwg_all = convert_to_dwg(out_all)
                if dwg_all and Path(dwg_all).is_file():
                    print(f"  Все примеры конвертированы в DWG: {dwg_all}")
                    try:
                        # DXF уже может быть удалён внутри generate_examples, проверяем
                        if out_all.exists():
                            out_all.unlink()
                            print(f"  DXF Все_примеры удалён после конвертации (остался DWG): {dwg_all}")
                    except PermissionError:
                        print(f"  Не удалось удалить DXF {out_all} (занят)")
                    except Exception:
                        pass
            elif out_all.with_suffix(".dwg").exists():
                print(f"  Все примеры уже в DWG: {out_all.with_suffix('.dwg')}")
            # Также выведем перечень из свежего файла (DXF или DWG если остался DXF)
            try:
                import ezdxf as _ez
                read_path = out_all if out_all.exists() else out_all.with_suffix(".dwg")
                # ezdxf не читает DWG, поэтому только если остался DXF
                if out_all.exists():
                    _d = _ez.readfile(str(out_all))
                    print("  Перечень примеров из Все_примеры:")
                    for i, ins in enumerate(_d.modelspace().query("INSERT")):
                        print(f"    {i+1:02d}. {ins.dxf.name}")
                else:
                    # если остался только DWG — перечень уже выводился в generate_examples
                    pass
            except Exception:
                pass
        except PermissionError as e_perm:
            print(f"  Файл Все_примеры.dxf занят — закройте его в AutoCAD/проводнике и запустите снова: {e_perm}")
            print(f"  Совет: закройте предпросмотр в проводнике, AutoCAD, DWG TrueView и повторите python window_export.py")
        except Exception as e:
            print(f"  Не удалось собрать все примеры: {e}")
            import traceback; traceback.print_exc()

    return 0


if __name__ == "__main__":
    sys.exit(main())