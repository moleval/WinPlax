#!/usr/bin/env python3
"""
Прогон ОК-1 (1500×1500 3×2) на каждом открытом проекте.
Каждый блок — реальный вызов API проекта (где возможно), иначе — точный разбор исходников + мок DXF.
Результаты: real_output/*.dxf + логи.
"""
import sys, json, pathlib
from pathlib import Path
OUT = Path("real_output")
OUT.mkdir(parents=True, exist_ok=True)
# Загружаем ОК-1
params = json.load(open(Path(__file__).resolve().parents[2] / "params.json", encoding="utf-8"))
print("=== ОК-1 params ===")
print(json.dumps(params, ensure_ascii=False, indent=2)[:800])

