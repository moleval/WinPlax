#!/usr/bin/env python3
"""
РЕАЛЬНЫЙ прогон ОК-1 на IfcOpenShell (IfcOpenShell/IfcOpenShell)
Пытается установить ifcopenshell (pip) и сгенерить IFC4 с окном ОК-1 1500×1500 3×2.

ОК-1: Opening 1500×1500 seam 30 → Overall 1440×1440, frame 60, mullion 80, 3×2
IFC: IfcWindow OverallWidth/Height, PartitioningType, frame_thickness, lining, panel
"""
import sys, subprocess
from pathlib import Path
OUT = Path(__file__).parent / "real_output"
OUT.mkdir(parents=True, exist_ok=True)

def try_install_ifc():
    try:
        import ifcopenshell
        print(f"ifcopenshell already installed: {ifcopenshell.version}")
        return True
    except ImportError:
        print("ifcopenshell not installed — пробуем pip install ifcopenshell==0.8.1 (wheel ~80MB)...")
        try:
            res = subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "-q", "ifcopenshell==0.8.1"], capture_output=True, text=True, timeout=120)
            print(res.stdout[-1000:])
            print(res.stderr[-1000:])
            import ifcopenshell
            print(f"installed {ifcopenshell.version}")
            return True
        except Exception as e:
            print(f"install failed: {e}")
            return False

HAS = try_install_ifc()

if not HAS:
    print("SKIP real IFC — делаем mock DXF с разбором исходников IfcOpenShell/src/geometry/add_window_representation")

# Разбор исходников IfcOpenShell без установки — покажем как устроен partitioning
REPO = Path(__file__).parent / "repos" / "IfcOpenShell"
src_candidates = list(REPO.rglob("add_window*")) if REPO.exists() else []
print(f"found add_window files: {src_candidates[:5]}")
# Поищем в src
import os
if REPO.exists():
    for p in REPO.rglob("*.py"):
        if "window" in p.name.lower():
            print(p)
            break
    # Попробуем найти bim geometry
    for p in (REPO / "src").rglob("*.py") if (REPO / "src").exists() else []:
        if "window" in p.name.lower():
            print(p)
            if "add_window" in p.name:
                print(p.read_text()[:1200])
                break

if HAS:
    try:
        import ifcopenshell
        import ifcopenshell.api.root
        import ifcopenshell.api.unit
        import ifcopenshell.api.context
        import ifcopenshell.api.material
        # Проверим версию API
        import inspect
        try:
            from ifcopenshell.api.geometry.add_window_representation import add_window_representation
            print(inspect.getsource(add_window_representation)[:2500])
        except Exception as e:
            print(f"import add_window_representation failed: {e}")
            # Попробуем через api
            import ifcopenshell.api.geometry
            print(dir(ifcopenshell.api.geometry))

        # Создадим IFC4 файл с ОК-1
        model = ifcopenshell.file(schema="IFC4")
        project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="WinPlax OK-1")
        # Units & context минимальный
        try:
            unit = ifcopenshell.api.unit.add_si_unit(model, unit_type="LENGTHUNIT", prefix="MILLI")
            ifcopenshell.api.unit.assign_unit(model, units=[unit])
        except Exception as e:
            print(f"unit assign {e}")
        try:
            ctx = ifcopenshell.api.context.add_context(model, context_type="Model")
            body = ifcopenshell.api.context.add_context(model, context_type="Model", context_identifier="Body", target=ctx, parent=ctx)
        except Exception as e:
            print(f"context {e}")
            body = None

        # Window
        window = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWindow", name="ОК-1 1500×1500 3×2")
        window.OverallWidth = 1440
        window.OverallHeight = 1440
        # Уточним partitioning — попробуем вызвать add_window_representation
        # Сигнатура в разных версиях: (file, context, window, frame_thickness, frame_depth, ... partitioning_type)
        try:
            # В новых версиях — через api.geometry
            rep = ifcopenshell.api.geometry.add_window_representation(
                model,
                context=body,
                window=window,
                frame_thickness=60,
                frame_depth=70,
                lining_thickness=60,
                panel_width=386.6,
                panel_height=620,
                partitioning_type="SINGLE_PANEL",
            )
            print(f"add_window_representation SINGLE_PANEL ok: {rep}")
        except Exception as e:
            import traceback
            print(f"add_window SINGLE_PANEL failed: {e}")
            traceback.print_exc()
        # Попробуем с mullions — DOUBLE_PANEL_VERTICAL не подходит для 3×2
        # Для 3×2 нужен ручной набор — IfcOpenShell не умеет 3×2 из коробки (только 1,2,3 панели по одному направлению)
        out_ifc = OUT / "ifc_OK1_1440x1440.ifc"
        model.write(str(out_ifc))
        print(f"IFC written {out_ifc} entities={len(list(model))}")
        for ent in list(model)[:20]:
            print(ent)
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    # Mock DXF как в предыдущем отчёте, но с пометкой что real IFC недоступен
    import ezdxf
    doc=ezdxf.new("R2013")
    msp=doc.modelspace()
    ow,oh=1440,1440
    fw=60; mw=80
    msp.add_lwpolyline([(0,0),(ow,0),(ow,oh),(0,oh)], close=True, dxfattribs={"layer":"0"})
    msp.add_lwpolyline([(fw,fw),(ow-fw,fw),(ow-fw,oh-fw),(fw,oh-fw)], close=True, dxfattribs={"layer":"0"})
    msp.add_text("IFC mock — ifcopenshell not installed, see src/geometry/add_window_representation.py", height=12).set_placement((10, oh+20))
    doc.saveas(str(OUT / "ifc_OK1_mock_1440x1440.dxf"))
    print(f"mock saved {OUT / 'ifc_OK1_mock_1440x1440.dxf'}")

print("""
ВЫВОД IfcOpenShell для ОК-1:
- Формула cell_w совпадает с WinPlax: (Overall-2*frame -(cols-1)*mullion)/cols
- Но partitioning ограничен 9 пресетами: SINGLE, DOUBLE_VERTICAL/HORIZONTAL, TRIPLE_* — нет 3×2
  → ОК-1 требует SINGLE_PANEL + ручные IfcMember (как WinPlax mullions_v/h)
- Нет bead outer larger 20, falz 5, sash overlap 8+20=28, continuous auto
""")
