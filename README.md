[English](#english) | [Русский](#русский)

---

<a name="english"></a>

# ma-provider-tools

Central infrastructure for Music Assistant custom providers.
This repo manages shared CI/CD workflows and distributes standardized files to all provider repos automatically.

## Managed Providers

| Provider | Repository | Type |
|----------|-----------|------|
| Yandex Music | [ma-provider-yandex-music](https://github.com/trudenboy/ma-provider-yandex-music) | Music |
| KION Music | [ma-provider-kion-music](https://github.com/trudenboy/ma-provider-kion-music) | Music |
| Zvuk Music | [ma-provider-zvuk-music](https://github.com/trudenboy/ma-provider-zvuk-music) | Music |
| MSX Bridge | [ma-provider-msx-bridge](https://github.com/trudenboy/ma-provider-msx-bridge) | Player |

## How It Works

### Shared CI Workflows

Files in `.github/workflows/reusable-*.yml` contain all CI logic. Provider repos call them via `uses:` — changes take effect instantly across all repos without PRs.

| Workflow | Purpose |
|----------|---------|
| `reusable-test.yml` | Runs pytest + ruff + mypy + codespell |
| `reusable-release.yml` | Creates git tags and GitHub releases |
| `reusable-sync-to-fork.yml` | Syncs provider code into `trudenboy/ma-server` |
| `reusable-report-incident.yml` | Opens a GitHub Issue when CI fails (deduplicated) |

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

## Where to File Incidents

> **File issues in the affected provider's repository, not here.**

| Provider | Issues |
|----------|--------|
| Yandex Music | [Issues →](https://github.com/trudenboy/ma-provider-yandex-music/issues) |
| KION Music | [Issues →](https://github.com/trudenboy/ma-provider-kion-music/issues) |
| Zvuk Music | [Issues →](https://github.com/trudenboy/ma-provider-zvuk-music/issues) |
| MSX Bridge | [Issues →](https://github.com/trudenboy/ma-provider-msx-bridge/issues) |

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
  reusable-*.yml      ← shared CI logic (changes affect all providers instantly)
  distribute.yml      ← triggers distribute.py on push to main
wrappers/
  *.j2                ← Jinja2 templates rendered per provider
  docs/*.j2
scripts/
  distribute.py       ← renders templates, creates PRs in provider repos
providers.yml         ← registry: all providers, their repos and config
docs/
  workflow-overview.md
  adding-provider.md
  github-projects-setup.md
```

## Further Reading

- [Workflow Overview](docs/workflow-overview.md) — full architecture, all workflows, incident pipeline
- [Adding a Provider](docs/adding-provider.md) — step-by-step guide, all `providers.yml` fields
- [GitHub Projects Setup](docs/github-projects-setup.md) — project board configuration

---

<a name="русский"></a>

# ma-provider-tools

Центральная инфраструктура для кастомных провайдеров Music Assistant.
Этот репозиторий управляет общими CI/CD workflow и автоматически распределяет стандартизированные файлы по репозиториям провайдеров.

## Провайдеры

| Провайдер | Репозиторий | Тип |
|-----------|------------|-----|
| Яндекс Музыка | [ma-provider-yandex-music](https://github.com/trudenboy/ma-provider-yandex-music) | Музыкальный |
| KION Музыка | [ma-provider-kion-music](https://github.com/trudenboy/ma-provider-kion-music) | Музыкальный |
| Звук | [ma-provider-zvuk-music](https://github.com/trudenboy/ma-provider-zvuk-music) | Музыкальный |
| MSX Bridge | [ma-provider-msx-bridge](https://github.com/trudenboy/ma-provider-msx-bridge) | Плеер |

## Как это работает

### Общие CI Workflow

Файлы в `.github/workflows/reusable-*.yml` содержат всю CI-логику. Репозитории провайдеров вызывают их через `uses:` — изменения применяются мгновенно ко всем репозиториям без PR.

| Workflow | Назначение |
|----------|-----------|
| `reusable-test.yml` | Запускает pytest + ruff + mypy + codespell |
| `reusable-release.yml` | Создаёт git-теги и GitHub-релизы |
| `reusable-sync-to-fork.yml` | Синхронизирует код провайдера в `trudenboy/ma-server` |
| `reusable-report-incident.yml` | Открывает GitHub Issue при падении CI (с дедупликацией) |

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

## Где заводить инциденты

> **Заводи задачи в репозитории конкретного провайдера, а не здесь.**

| Провайдер | Задачи |
|-----------|--------|
| Яндекс Музыка | [Issues →](https://github.com/trudenboy/ma-provider-yandex-music/issues) |
| KION Музыка | [Issues →](https://github.com/trudenboy/ma-provider-kion-music/issues) |
| Звук | [Issues →](https://github.com/trudenboy/ma-provider-zvuk-music/issues) |
| MSX Bridge | [Issues →](https://github.com/trudenboy/ma-provider-msx-bridge/issues) |

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
  reusable-*.yml      ← общая CI-логика (изменения применяются ко всем провайдерам мгновенно)
  distribute.yml      ← запускает distribute.py при push в main
wrappers/
  *.j2                ← Jinja2-шаблоны, рендерятся для каждого провайдера
  docs/*.j2
scripts/
  distribute.py       ← рендерит шаблоны, создаёт PR в репозиториях провайдеров
providers.yml         ← реестр: все провайдеры, их репозитории и конфигурация
docs/
  workflow-overview.md
  adding-provider.md
  github-projects-setup.md
```

## Дополнительно

- [Обзор архитектуры](docs/workflow-overview.md) — полная архитектура, все workflow, пайплайн инцидентов
- [Добавление провайдера](docs/adding-provider.md) — пошаговое руководство, все поля `providers.yml`
- [Настройка проекта GitHub](docs/github-projects-setup.md) — конфигурация доски проекта
