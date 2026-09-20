#!/usr/bin/env python3
"""
Сборщик шаблона для WinPlax — показывает как использовать ваш DXF/DWG-шаблон
с вашими слоями/стилями для генерации окна.

Использование:
  1. Положите ваш шаблон в репозиторий как один из:
     ./template.dxf
     ./шаблон.dxf
     ./БШАБЛОН.dxf
     ./БШАБЛОН.dwg
     ./template.dwg
     ./output/template.dxf
     или любое другое имя — тогда укажите путь явно.

  2. Запустите:
     python window_export.py --inspect-template template.dxf
        — покажет все слои/стили/размерные стили из шаблона (для сверки)

     python window_export.py --template template.dxf
        — сгенерирует окно с вашими слоями/стилями (берёт цвет/тип линии/шрифт/LTSCALE из шаблона)

     python window_export.py params.json --output output/ОК-1.dxf --template БШАБЛОН.dxf
        — явно указать шаблон + выходной файл

     # через params.json:
     # добавьте в params.json поле:  "template": "БШАБЛОН.dxf"  или  "template": "path/to/шаблон.dwg"

  3. Если шаблон лежит в репозитории, его достаточно просто закоммитить:
     git add БШАБЛОН.dxf && git commit -m "шаблон" && git push

Этот скрипт — просто обёртка для быстрой проверки.
"""
import sys
from pathlib import Path

import ezdxf
from window_export import inspect_template, _copy_template_tables

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nПример: python template_tool.py --inspect БШАБЛОН.dxf")
        print("Пример: python template_tool.py --build БШАБЛОН.dxf")
        return 0
    cmd = sys.argv[1]
    if cmd in ("--inspect", "--inspect-template", "-i"):
        if len(sys.argv) < 3:
            print("Укажите путь к шаблону: python template_tool.py --inspect БШАБЛОН.dxf")
            return 1
        inspect_template(sys.argv[2])
    elif cmd in ("--build", "--with-template", "-b"):
        tpl = sys.argv[2] if len(sys.argv) > 2 else "БШАБЛОН.dxf"
        print(f"Запуск генерации с шаблоном {tpl} ...")
        from window_export import main as win_main
        # передаём --template
        sys.argv = ["window_export.py", "--template", tpl]
        return win_main(sys.argv[1:])
    elif Path(cmd).is_file():
        # если передали просто путь
        inspect_template(cmd)
    else:
        print(f"Неизвестная команда: {cmd}")
        print(__doc__)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
