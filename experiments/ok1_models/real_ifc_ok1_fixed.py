#!/usr/bin/env python3
import sys
from pathlib import Path
OUT = Path(__file__).parent / "real_output"
OUT.mkdir(parents=True, exist_ok=True)

import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.api.context
import ifcopenshell.util.unit

model = ifcopenshell.file(schema="IFC4")
proj = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="WinPlax OK-1")
# Minimal context
ctx = ifcopenshell.api.context.add_context(model, context_type="Model")
body = ifcopenshell.api.context.add_context(model, context_type="Model", context_identifier="Body", parent=ctx)

# Try correct API
try:
    import inspect
    help_text = inspect.getsource(ifcopenshell.api.geometry.add_window_representation)
    print(help_text[:3000])
except Exception as e:
    print(e)

# Попробуем вызвать с правильными именами
for overall_w, overall_h, part, name in [
    (1440, 1440, "SINGLE_PANEL", "single"),
    (1440, 1440, "DOUBLE_PANEL_VERTICAL", "double_vert"),
    (1440, 1440, "TRIPLE_PANEL_VERTICAL", "triple_vert"),
]:
    try:
        # unit_scale мм? В IFC проект по умолчанию метры, но overall в мм? Проверим
        # В API overall_* ожидается в метрах если unit_scale=1? Давайте попробуем в метрах
        rep = ifcopenshell.api.geometry.add_window_representation(
            model,
            context=body,
            overall_width=overall_w/1000,
            overall_height=overall_h/1000,
            partition_type=part,
            lining_properties={"LiningDepth": 70/1000, "LiningThickness": 60/1000, "MullionThickness": 80/1000, "TransomThickness": 80/1000},
            panel_properties=[{"PanelDepth": 20/1000}]*3,
        )
        print(f"{part} ok rep={rep} id={rep.id()}")
    except Exception as e:
        import traceback
        print(f"{part} failed: {e}")
        traceback.print_exc()

# Попробуем 3x2 через SINGLE + ручные? IFC не умеет 3x2, но посмотрим что SINGLE даёт
# Создадим окно с 3x2 через multiple panels? Попытка с 6 panels
try:
    rep = ifcopenshell.api.geometry.add_window_representation(
        model,
        context=body,
        overall_width=1.44,
        overall_height=1.44,
        partition_type="SINGLE_PANEL",
        lining_properties={"LiningDepth": 0.07, "LiningThickness": 0.06},
        panel_properties=[{"PanelDepth":0.02, "PanelWidth":0.386}] * 1,  # только 1 панель
    )
    print(f"SINGLE with 1 panel ok {rep}")
except Exception as e:
    print(f"single 1 panel fail {e}")

# Сохраним IFC
out = OUT / "ifc_OK1_real_fixed.ifc"
model.write(str(out))
print(f"IFC saved {out} entities={len(list(model))}")
for e in list(model)[-10:]:
    print(e)
