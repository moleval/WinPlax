# Как запустить WinPlax на Windows (PowerShell)

## Ошибки из вашего лога и их решение

### 1. `ModuleNotFoundError: No module named 'ezdxf'`

**Причина:** не установлена библиотека `ezdxf`.

**Решение — выполните в PowerShell в папке `D:\WinPlax`:**

```powershell
# Проверьте, что Python установлен:
python --version
py --version   # альтернативная команда на Windows

# Установите ezdxf (выберите ту команду, где python нашёлся):
python -m pip install ezdxf
# или
py -m pip install ezdxf
# или без прав администратора:
python -m pip install --user ezdxf
# или из файла зависимостей:
python -m pip install -r requirements.txt

# Проверка:
python -m pip show ezdxf
python -c "import ezdxf; print(ezdxf.__version__)"
```

После установки повторно:
```powershell
python window_export.py
python generate_examples.py
```

> Теперь `window_export.py` вместо `Traceback` покажет дружелюбную подсказку, если `ezdxf` всё ещё не установлен.

### 2. `Имя "generate_examples.py" не распознано`

**Причина:** в PowerShell нельзя запускать `.py` файл просто по имени. Это защита оболочки.

**Неправильно:**
```powershell
generate_examples.py
window_export.py
```

**Правильно (всегда пишите `python` впереди):**
```powershell
python window_export.py
python generate_examples.py

# если команда python не найдена, используйте py:
py window_export.py
py generate_examples.py

# с параметрами:
python window_export.py --output output/МоёОкно.dxf
python generate_examples.py --output output/Все_примеры.dxf --template Шаблон.dxf
```

> Подсказка PowerShell `введите ".\generate_examples.py"` тоже **не сработает** без настройки ассоциаций Python — используйте `python generate_examples.py`.

---

## Полный порядок запуска с нуля

```powershell
cd D:\WinPlax

# 1. (один раз) Установка зависимости
python -m pip install ezdxf
# или
python -m pip install -r requirements.txt

# 2. Запуск одного окна из params.json
python window_export.py
# Результат: output\ОК-1.dxf  и  output\ОК-1_INSIDE.dxf

# 3. Запуск всех 12 примеров
python generate_examples.py
# Результат: output\Все_примеры.dxf (12 блоков)

# 4. Проверка
dir output
python test_window_export.py -v   # тесты (если установлен ezdxf)
```

## Если `python` не найден

1. Установите Python 3.10+ с https://www.python.org/downloads/ — **обязательно поставьте галочку `Add python.exe to PATH`** при установке.
2. Перезапустите PowerShell.
3. Попробуйте `py --version` вместо `python --version`.

## Виртуальное окружение (рекомендуется)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python window_export.py
```

После активации `(venv)` появится в приглашении PowerShell.

---

## Что исправлено в репозитории

- `window_export.py` и `generate_examples.py` теперь ловят отсутствие `ezdxf` и выводят инструкцию на русском вместо `Traceback`.
- Добавлен `requirements.txt` (`ezdxf>=1.0`) для `pip install -r requirements.txt`.
- Обновлён `README.md` (§3.1, §5) с инструкциями именно для PowerShell.
- Этот файл `КАК_ЗАПУСТИТЬ_Windows.md` — шпаргалка для Windows.
