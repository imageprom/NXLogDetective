# NX Log Detective (NXLD) 0.1

Анализ access/error-логов сайта (nginx, Apache) по ТЗ «NX Log Detective 1.0».
Код измеряет, ИИ расследует: движок считает всё, что можно посчитать, а ИИ (Claude, позже ChatGPT) проверяет карту сайта, расследует странное и пишет выводы.

## Состав

| Папка | Что |
|---|---|
| `engine/nxld_run.py` | Запуск: prepare → analyze → report |
| `engine/nxld/` | Модули: ingest, load, recon, visits, blocks, analyze, report |
| `data/` | База IP → сеть и страна (ip-location-db, лицензии рядом) |
| `skill/SKILL.md` | Инструкция для ИИ |
| `signatures/legacy/` | Сигнатуры botsig/1 с example.com (черновик, переход на NXLD-sig/2 — в следующей версии) |

## Быстрый старт

```bash
pip install pandas numpy openpyxl
python3 engine/nxld_run.py --logs ./logs --work ./work --out ./out
```

Параметры: `--blocks overview,errors,load,bots,marketing`, `--check-ips`, `--control-point "ГГГГ-ММ-ДД ЧЧ:ММ"`, `--prev прошлый.snapshot.json`, `--edits edits.json`, `--map-override map.json`, `--stage prepare|analyze|report`.

## Что уже есть в 0.1

- Приём .log/.gz/.zip и папок, автоопределение access/error, сайта, формата, дублей на стыках файлов.
- Разведка: сервер, PHP-FPM, движок (или статический HTML), шаблоны адресов, элементы каталога, цели и признак успеха, подгружаемые блоки, метки, служебные файлы, сотрудники, мониторинги.
- Очистка визитов: двойные загрузки, редиректы, подгружаемые формы и блоки; группы трафика.
- Пять блоков, черновые проблемы с важностью, Excel по блокам, текст Redmine (Textile), снимок, архив, сравнение со снимком, отметки «это норма», правки ИИ.

## Чего пока нет (следующие версии)

- Сигнатуры NXLD-sig/2: проверка по загруженным файлам и выгрузка.
- Склейка визитов при смене IP для статистики людей (для спама форм — есть).
- Вариант для ChatGPT с работой кусками и продолжением после обрыва.
