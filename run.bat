@echo off
REM Запуск WinPlax на Windows — двойной клик или из CMD
REM Требуется: Python 3.10+ и ezdxf (pip install ezdxf)

echo === WinPlax run.bat ===
python --version 2>nul
if errorlevel 1 (
  echo Python 'python' не найден, пробую 'py'...
  py --version
  if errorlevel 1 (
    echo ОШИБКА: Python не найден. Установите с https://www.python.org/downloads/
    pause
    exit /b 1
  )
  echo Установка ezdxf через py...
  py -m pip install ezdxf
  echo Запуск через py...
  py window_export.py
  py generate_examples.py
) else (
  echo Проверка ezdxf...
  python -c "import ezdxf" 2>nul
  if errorlevel 1 (
    echo ezdxf не установлен, устанавливаю...
    python -m pip install ezdxf
  )
  echo Запуск через python...
  python window_export.py
  python generate_examples.py
)

echo.
echo Готово. Результаты в папке output\
pause
