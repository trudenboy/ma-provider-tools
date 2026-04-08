[English](#english) | [Русский](#русский)

---

<a name="english"></a>

# ma-provider-tools

Central infrastructure for Music Assistant custom providers.
This repo manages shared CI/CD workflows and distributes standardized files to all provider repos automatically.

## Managed Providers

| Provider | Repository | Type | Docs | Issues | Changelog |
|----------|-----------|------|------|--------|-----------|
| Yandex Music | [ma-provider-yandex-music](https://github.com/trudenboy/ma-provider-yandex-music) | Music | [Docs →](https://trudenboy.github.io/ma-provider-yandex-music/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-music/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-music/blob/dev/CHANGELOG.md) |
| KION Music | [ma-provider-kion-music](https://github.com/trudenboy/ma-provider-kion-music) | Music | [Docs →](https://trudenboy.github.io/ma-provider-kion-music/) | [Issues →](https://github.com/trudenboy/ma-provider-kion-music/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-kion-music/blob/dev/CHANGELOG.md) |
| Zvuk Music | [ma-provider-zvuk-music](https://github.com/trudenboy/ma-provider-zvuk-music) | Music | [Docs →](https://trudenboy.github.io/ma-provider-zvuk-music/) | [Issues →](https://github.com/trudenboy/ma-provider-zvuk-music/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-zvuk-music/blob/dev/CHANGELOG.md) |
| MSX Bridge | [ma-provider-msx-bridge](https://github.com/trudenboy/ma-provider-msx-bridge) | Player | [Docs →](https://trudenboy.github.io/ma-provider-msx-bridge/) | [Issues →](https://github.com/trudenboy/ma-provider-msx-bridge/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-msx-bridge/blob/feat/msx-bridge-player-provider/CHANGELOG.md) |
| Yandex Station | [ma-provider-yandex-station](https://github.com/trudenboy/ma-provider-yandex-station) | Player | [Docs →](https://trudenboy.github.io/ma-provider-yandex-station/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-station/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-station/blob/dev/CHANGELOG.md) |
| Yandex Smart Home | [ma-provider-yandex-smarthome](https://github.com/trudenboy/ma-provider-yandex-smarthome) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-yandex-smarthome/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-smarthome/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-smarthome/blob/dev/CHANGELOG.md) |
| Yandex Music Connect (Ynison) | [ma-provider-yandex-ynison](https://github.com/trudenboy/ma-provider-yandex-ynison) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-yandex-ynison/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-ynison/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-ynison/blob/dev/CHANGELOG.md) |
| DLNA Receiver | [ma-provider-dlna-receiver](https://github.com/trudenboy/ma-provider-dlna-receiver) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-dlna-receiver/) | [Issues →](https://github.com/trudenboy/ma-provider-dlna-receiver/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-dlna-receiver/blob/dev/CHANGELOG.md) |

## How It Works

### Shared CI Workflows

Files in `.github/workflows/reusable-*.yml` contain all CI logic. Provider repos call them via `uses:` — changes take effect instantly across all repos without PRs.

| Workflow | Purpose |
|----------|---------|
| `reusable-test.yml` | Runs pytest + ruff + mypy + codespell |
| `reusable-release.yml` | Creates git tags and GitHub releases |
| `reusable-sync-to-fork.yml` | Syncs provider code into `trudenboy/ma-server` |
| `reusable-report-incident.yml` | Opens a GitHub Issue when CI fails (deduplicated) |
| `reusable-copilot-triage.yml` | Assigns Copilot to triage incident issues |
| `reusable-sync-labels.yml` | Syncs issue labels across provider repos |
| `reusable-security.yml` | Security scanning (CodeQL, dependency audit) |
| `reusable-sync-kion-from-yandex.yml` | Syncs KION provider from Yandex Music codebase |

### Wrapper File Distribution

`scripts/distribute.py` renders Jinja2 templates in `wrappers/` for each provider and creates PRs with the results.
Triggered automatically on push to `main` when `wrappers/` or `providers.yml` changes.

Distributed files include: CI workflows, issue templates, labels, docs, Docker dev environment, MkDocs Pages config.

### Incident Pipeline

CI failures are automatically tracked as GitHub Issues:

```
test.yml fails → reusable-report-incident → Issue (incident:ci + priority:high)
                                                  ↓
                                      issue-project.yml → MA Ecosystem board
                                                  ↓
                        add label "copilot" → copilot-triage → @copilot PR
```

> **File issues in the affected provider's repository, not here.** See the Issues column above.

Issues in this repo are for infrastructure problems only (broken distribution pipeline, shared workflow bugs, etc.).

## Operations

**Update shared CI** (affects all providers immediately):
```bash
# Edit reusable-*.yml, commit, push to main
```

**Update wrapper files** (creates PRs in all provider repos):
```bash
# Edit wrappers/*.j2 or providers.yml, commit, push to main
```

**Run distribute manually**:
```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run   # preview
GH_TOKEN=<your-pat> python3 scripts/distribute.py             # create PRs
```

## Repository Structure

```
.github/workflows/
  reusable-*.yml        ← shared CI logic (changes affect all providers instantly)
  distribute.yml        ← triggers distribute.py on push to main
wrappers/
  *.j2                  ← Jinja2 templates rendered per provider
  docs/*.j2
scripts/
  distribute.py         ← renders templates, creates PRs in provider repos
  validate_templates.py ← checks Jinja2 syntax, whitespace, variables
  generate_dashboard.py ← generates provider dashboard data
  update_changelog.py   ← automates changelog entries for releases
  check_package_safety.py ← dependency safety checks
  parse_manifest_deps.py  ← parses provider manifest dependencies
providers.yml           ← registry: all providers, their repos and config
docs-site/              ← Astro-based documentation site
```

## Further Reading

- **[Provider Dashboard →](https://trudenboy.github.io/ma-provider-tools/dashboard)** — live PRs, CI status, dev activity for all providers

---

<a name="русский"></a>

# ma-provider-tools

Центральная инфраструктура для кастомных провайдеров Music Assistant.
Этот репозиторий управляет общими CI/CD workflow и автоматически распределяет стандартизированные файлы по репозиториям провайдеров.

## Провайдеры

| Провайдер | Репозиторий | Тип | Документация | Задачи | Changelog |
|-----------|------------|-----|--------------|--------|-----------|
| Яндекс Музыка | [ma-provider-yandex-music](https://github.com/trudenboy/ma-provider-yandex-music) | Музыка | [Docs →](https://trudenboy.github.io/ma-provider-yandex-music/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-music/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-music/blob/dev/CHANGELOG.md) |
| KION Музыка | [ma-provider-kion-music](https://github.com/trudenboy/ma-provider-kion-music) | Музыка | [Docs →](https://trudenboy.github.io/ma-provider-kion-music/) | [Issues →](https://github.com/trudenboy/ma-provider-kion-music/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-kion-music/blob/dev/CHANGELOG.md) |
| Звук | [ma-provider-zvuk-music](https://github.com/trudenboy/ma-provider-zvuk-music) | Музыка | [Docs →](https://trudenboy.github.io/ma-provider-zvuk-music/) | [Issues →](https://github.com/trudenboy/ma-provider-zvuk-music/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-zvuk-music/blob/dev/CHANGELOG.md) |
| MSX Bridge | [ma-provider-msx-bridge](https://github.com/trudenboy/ma-provider-msx-bridge) | Плеер | [Docs →](https://trudenboy.github.io/ma-provider-msx-bridge/) | [Issues →](https://github.com/trudenboy/ma-provider-msx-bridge/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-msx-bridge/blob/feat/msx-bridge-player-provider/CHANGELOG.md) |
| Яндекс Станция | [ma-provider-yandex-station](https://github.com/trudenboy/ma-provider-yandex-station) | Плеер | [Docs →](https://trudenboy.github.io/ma-provider-yandex-station/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-station/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-station/blob/dev/CHANGELOG.md) |
| Яндекс Умный Дом | [ma-provider-yandex-smarthome](https://github.com/trudenboy/ma-provider-yandex-smarthome) | Плагин | [Docs →](https://trudenboy.github.io/ma-provider-yandex-smarthome/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-smarthome/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-smarthome/blob/dev/CHANGELOG.md) |
| Yandex Music Connect (Ynison) | [ma-provider-yandex-ynison](https://github.com/trudenboy/ma-provider-yandex-ynison) | Плагин | [Docs →](https://trudenboy.github.io/ma-provider-yandex-ynison/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-ynison/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-ynison/blob/dev/CHANGELOG.md) |
| DLNA Receiver | [ma-provider-dlna-receiver](https://github.com/trudenboy/ma-provider-dlna-receiver) | Плагин | [Docs →](https://trudenboy.github.io/ma-provider-dlna-receiver/) | [Issues →](https://github.com/trudenboy/ma-provider-dlna-receiver/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-dlna-receiver/blob/dev/CHANGELOG.md) |

## Как это работает

### Общие CI Workflow

Файлы в `.github/workflows/reusable-*.yml` содержат всю CI-логику. Репозитории провайдеров вызывают их через `uses:` — изменения применяются мгновенно ко всем репозиториям без PR.

| Workflow | Назначение |
|----------|-----------|
| `reusable-test.yml` | Запускает pytest + ruff + mypy + codespell |
| `reusable-release.yml` | Создаёт git-теги и GitHub-релизы |
| `reusable-sync-to-fork.yml` | Синхронизирует код провайдера в `trudenboy/ma-server` |
| `reusable-report-incident.yml` | Открывает GitHub Issue при падении CI (с дедупликацией) |
| `reusable-copilot-triage.yml` | Назначает Copilot для триажа инцидентов |
| `reusable-sync-labels.yml` | Синхронизирует метки issues по репозиториям провайдеров |
| `reusable-security.yml` | Сканирование безопасности (CodeQL, аудит зависимостей) |
| `reusable-sync-kion-from-yandex.yml` | Синхронизирует KION-провайдер из кодовой базы Яндекс Музыки |

### Распределение файлов-обёрток

`scripts/distribute.py` рендерит Jinja2-шаблоны из `wrappers/` для каждого провайдера и создаёт PR с результатами.
Запускается автоматически при push в `main`, если изменились `wrappers/` или `providers.yml`.

Распределяемые файлы: CI workflow, шаблоны задач, метки, документация, Docker-окружение, конфигурация MkDocs Pages.

### Пайплайн инцидентов

Сбои CI автоматически отслеживаются как GitHub Issues:

```
test.yml падает → reusable-report-incident → Issue (incident:ci + priority:high)
                                                    ↓
                                      issue-project.yml → доска MA Ecosystem
                                                    ↓
                        добавь метку "copilot" → copilot-triage → @copilot PR
```

> **Заводи задачи в репозитории конкретного провайдера, а не здесь.** См. столбец Issues выше.

Задачи в этом репозитории (ma-provider-tools) — только для проблем с инфраструктурой (сбои пайплайна дистрибуции, баги общих workflow и т.д.).

## Операции

**Обновить общий CI** (применяется ко всем провайдерам мгновенно):
```bash
# Отредактируй reusable-*.yml, закоммить, запушь в main
```

**Обновить файлы-обёртки** (создаёт PR во всех репозиториях провайдеров):
```bash
# Отредактируй wrappers/*.j2 или providers.yml, закоммить, запушь в main
```

**Запустить distribute вручную**:
```bash
pip install jinja2 pyyaml
GH_TOKEN=<your-pat> python3 scripts/distribute.py --dry-run   # предпросмотр
GH_TOKEN=<your-pat> python3 scripts/distribute.py             # создать PR
```

## Структура репозитория

```
.github/workflows/
  reusable-*.yml        ← общая CI-логика (изменения применяются ко всем провайдерам мгновенно)
  distribute.yml        ← запускает distribute.py при push в main
wrappers/
  *.j2                  ← Jinja2-шаблоны, рендерятся для каждого провайдера
  docs/*.j2
scripts/
  distribute.py         ← рендерит шаблоны, создаёт PR в репозиториях провайдеров
  validate_templates.py ← проверяет синтаксис Jinja2, пробелы, переменные
  generate_dashboard.py ← генерирует данные для дашборда провайдеров
  update_changelog.py   ← автоматизирует записи changelog при релизах
  check_package_safety.py ← проверка безопасности зависимостей
  parse_manifest_deps.py  ← парсинг зависимостей из манифеста провайдера
providers.yml           ← реестр: все провайдеры, их репозитории и конфигурация
docs-site/              ← сайт документации на Astro
```

## Дополнительно

- **[Дашборд провайдеров →](https://trudenboy.github.io/ma-provider-tools/dashboard)** — live PRs, CI-статус, активность разработки по всем провайдерам
