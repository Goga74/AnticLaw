# Импорт чатов Claude в AnticLaw

## Требования
- AnticLaw установлен: `pip install anticlaw` или `pip install -e .`
- Браузер Chrome с открытым и залогиненным claude.ai
- Chrome запущен с remote debugging (для маппинга проектов)

---

## Шаг 1: Экспорт данных из Claude

1. Открой [claude.ai](https://claude.ai) → кликни на аватар (левый нижний угол) → **Settings**
2. Перейди в **Privacy** → **Export Data**
3. Нажми кнопку **Export Data**
4. Жди письмо от Anthropic со ссылкой для скачивания (обычно 1–5 минут)
5. Скачай ZIP-файл, например `data-2026-02-17-15-09-31-batch-0000.zip`
6. Можно распаковать — поддерживается и ZIP и папка

---

## Шаг 2: Инициализация AnticLaw (только первый раз)

```bash
aw init --home C:\AnticlawData        # Windows
aw init --home ~/anticlaw             # Mac/Linux
```

---

## Шаг 3: Импорт без маппинга проектов (быстрый вариант)

Если распределение по проектам не важно — все чаты попадут в `_inbox/`:

```bash
# Windows
aw import claude C:\Downloads\data-2026-02-17-batch-0000.zip --home C:\AnticlawData

# Mac/Linux
aw import claude ~/Downloads/data-2026-02-17-batch-0000.zip --home ~/anticlaw
```

---

## Шаг 4: Получение маппинга проектов (рекомендуется)

Экспорт Claude **не содержит** привязки чатов к проектам. Чтобы чаты попали в правильные
папки, нужно запустить скрапер.

**4а. Запусти Chrome с remote debugging:**

```bash
# Windows (уточни путь к Chrome)
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222

# Mac
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222

# Linux
google-chrome --remote-debugging-port=9222
```

**4б. Войди в claude.ai** в этом окне Chrome (если ещё не залогинен).

**4в. Запусти скрапер:**

```bash
# Windows
aw scrape claude --cdp-url http://localhost:9222 --output C:\AnticlawData\mapping.json --home C:\AnticlawData

# Mac/Linux
aw scrape claude --cdp-url http://localhost:9222 --output ~/anticlaw/mapping.json --home ~/anticlaw
```

Скрапер автоматически получает все чаты и их привязку к проектам. Занимает 10–30 секунд.

---

## Шаг 5: Импорт с маппингом проектов

```bash
# Windows
aw import claude C:\Downloads\data-2026-02-17-batch-0000.zip --mapping C:\AnticlawData\mapping.json --home C:\AnticlawData

# Mac/Linux
aw import claude ~/Downloads/data-2026-02-17-batch-0000.zip --mapping ~/anticlaw/mapping.json --home ~/anticlaw
```

---

## Шаг 6: Проверка результата

```bash
aw list --home C:\AnticlawData        # список проектов
aw search "твой запрос" --home C:\AnticlawData
```

---

## Примечания

- Чаты без проекта в Claude попадают в `_inbox/` — это нормально
- Повторный импорт безопасен: уже импортированные чаты пропускаются
- Скрапер только читает данные, ничего в Claude не изменяет
- `mapping.json` можно переиспользовать для будущих импортов пока структура проектов не меняется
