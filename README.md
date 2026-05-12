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
| Yandex Alice | [ma-provider-yandex-alice](https://github.com/trudenboy/ma-provider-yandex-alice) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-yandex-alice/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-alice/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-alice/blob/dev/CHANGELOG.md) |
| Yandex Music Connect (Ynison) | [ma-provider-yandex-ynison](https://github.com/trudenboy/ma-provider-yandex-ynison) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-yandex-ynison/) | [Issues →](https://github.com/trudenboy/ma-provider-yandex-ynison/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-yandex-ynison/blob/dev/CHANGELOG.md) |
| DLNA Receiver | [ma-provider-dlna-receiver](https://github.com/trudenboy/ma-provider-dlna-receiver) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-dlna-receiver/) | [Issues →](https://github.com/trudenboy/ma-provider-dlna-receiver/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-dlna-receiver/blob/dev/CHANGELOG.md) |
| FastMCP Server | [ma-provider-mcp](https://github.com/trudenboy/ma-provider-mcp) | Plugin | [Docs →](https://trudenboy.github.io/ma-provider-mcp/) | [Issues →](https://github.com/trudenboy/ma-provider-mcp/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-mcp/blob/dev/CHANGELOG.md) |

## How It Works

### Shared CI Workflows

Files in `.github/workflows/reusable-*.yml` contain all CI logic. Provider repos call them via `uses:` — changes take effect instantly across all repos without PRs.

| Workflow | Purpose |
|----------|---------|
| `reusable-test.yml` | Runs pytest + ruff + mypy + codespell |
| `reusable-release.yml` | Creates git tags and GitHub releases |
| `reusable-sync-to-fork.yml` | Syncs provider code into `trudenboy/ma-server` (also copies the provider `VERSION` file alongside `manifest.json` for the dynamic MA badge) |
| `reusable-security.yml` | Security scanning (CodeQL, dependency audit) |
| `reusable-check-config-sync.yml` | Fails a provider PR if `ruff.toml` / `[tool.mypy]` / `[tool.codespell].skip` drifts from the auto-synced template |
| `reusable-check-feature-consistency.yml` | Cross-validates `providers.yml::features[].feature_id` against the provider's `SUPPORTED_FEATURES` set |
| `reusable-report-incident.yml` | Opens a GitHub Issue when CI fails (deduplicated) |
| `reusable-copilot-triage.yml` | Assigns Copilot to triage incident issues |
| `reusable-sync-labels.yml` | Syncs issue labels across provider repos |
| `reusable-sync-kion-from-yandex.yml` | Syncs KION provider from Yandex Music codebase |

### Wrapper File Distribution

`scripts/distribute.py` renders Jinja2 templates in `wrappers/` for each provider and creates PRs with the results.
Triggered automatically on push to `main` when `wrappers/` or `providers.yml` changes.

Distributed files include: CI workflows, issue templates, labels, docs, Docker dev environment, Starlight docs-site config, the auto-synced `CLAUDE.md` development guide, the README header (badges + locale-aware quick-links + cross-provider links via marker injection), the auto-synced `ruff.toml` / `[tool.mypy]` / `[tool.codespell].skip` blocks (kept in sync with upstream `music-assistant/server` weekly), the SDD feature-spec template, and the dynamic Music Assistant version badge JSONs.

### Repository-Level Automation

Three central workflows in this repo (not distributed) keep the ecosystem aligned:

| Workflow | Cadence | Purpose |
|----------|---------|---------|
| `ci.yml` | per PR / branch push | Runs pre-commit, `validate_templates.py`, `validate_providers_yml.py` before merge. |
| `sync-upstream-config.yml` | weekly cron + manual | Pulls upstream `music-assistant/server` `[tool.ruff]` / `[tool.mypy]` / `[tool.codespell].skip` blocks; opens a PR on drift. |
| `sync-repo-settings.yml` | manual `workflow_dispatch` | Pushes `github_description` / `github_topics` / `github_homepage` from `providers.yml` to each provider repo via `gh repo edit` (default dry-run). |
| `update-ma-version-badges.yml` | 4-hourly cron + manual | Refreshes `public/badges/<domain>-{stable,beta}.json` so the Music Assistant badge in each provider's README shows which MA channel ships the provider. |

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
  reusable-*.yml                       ← shared CI logic consumed by provider repos via `uses:`
  ci.yml                               ← PR / push validate gate (pre-commit + validators)
  distribute.yml                       ← runs distribute.py on push to main
  docs.yml                             ← deploys public/ to GitHub Pages
  sync-upstream-config.yml             ← weekly cron: pull MA upstream lint/typing config
  sync-repo-settings.yml               ← manual: push providers.yml metadata via gh repo edit
  update-ma-version-badges.yml         ← 4-hourly cron: refresh MA channel badge JSONs
wrappers/
  *.j2                                 ← Jinja2 templates rendered per provider (top-level)
  docs/*.j2                            ← Starlight docs pages
  feature-spec.md.j2                   ← SDD T-shirt spec template
  readme-header.md.j2                  ← badge + quick-links + cross-link header (marker-injected)
schemas/
  providers.schema.json                ← JSON Schema for providers.yml
scripts/
  distribute.py                        ← renders templates, creates PRs in provider repos
  validate_templates.py                ← checks Jinja2 syntax, whitespace, variables
  validate_providers_yml.py            ← schema-validates providers.yml
  render_for_provider.py               ← renders selected wrappers for one domain
  check_config_sync.py                 ← reusable-check-config-sync.yml worker
  check_feature_consistency.py         ← reusable-check-feature-consistency.yml worker
  sync_upstream_config.py              ← syncs lint/typing config from upstream MA
  sync_repo_settings.py                ← pushes GitHub About + topics via gh repo edit
  update_ma_version_badges.py          ← writes public/badges/<domain>-{stable,beta}.json
  dev-workspace.py                     ← shared dev workspace (multi-provider)
  generate_dashboard.py                ← generates provider dashboard data
  update_changelog.py                  ← automates changelog entries for releases
  check_package_safety.py              ← dependency safety checks
  parse_manifest_deps.py               ← parses provider manifest dependencies
providers.yml                          ← registry: all providers, their repos and config
public/badges/                         ← dynamic MA-version badge JSONs (served via GH Pages)
src/                                   ← Astro Starlight site sources (index, dashboard, …)
docs-site/                             ← additional docs assets (diagrams)
```

## Dev Workspace

Create a shared development workspace with one MA server and all providers:

```bash
# Create workspace with all providers
python3 scripts/dev-workspace.py init --dir ~/ma-workspace --all

# Start MA server with all providers loaded
python3 scripts/dev-workspace.py run --dir ~/ma-workspace

# Update all repos to latest
python3 scripts/dev-workspace.py update --dir ~/ma-workspace
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
| FastMCP Server | [ma-provider-mcp](https://github.com/trudenboy/ma-provider-mcp) | Плагин | [Docs →](https://trudenboy.github.io/ma-provider-mcp/) | [Issues →](https://github.com/trudenboy/ma-provider-mcp/issues) | [Changelog →](https://github.com/trudenboy/ma-provider-mcp/blob/dev/CHANGELOG.md) |

## Как это работает

### Общие CI Workflow

Файлы в `.github/workflows/reusable-*.yml` содержат всю CI-логику. Репозитории провайдеров вызывают их через `uses:` — изменения применяются мгновенно ко всем репозиториям без PR.

| Workflow | Назначение |
|----------|-----------|
| `reusable-test.yml` | Запускает pytest + ruff + mypy + codespell |
| `reusable-release.yml` | Создаёт git-теги и GitHub-релизы |
| `reusable-sync-to-fork.yml` | Синхронизирует код провайдера в `trudenboy/ma-server` (а также копирует файл `VERSION` рядом с `manifest.json` для динамического MA-бейджа) |
| `reusable-security.yml` | Сканирование безопасности (CodeQL, аудит зависимостей) |
| `reusable-check-config-sync.yml` | Падает PR провайдера, если `ruff.toml` / `[tool.mypy]` / `[tool.codespell].skip` разошёлся с авто-синканным шаблоном |
| `reusable-check-feature-consistency.yml` | Кросс-валидация `providers.yml::features[].feature_id` против `SUPPORTED_FEATURES` провайдера |
| `reusable-report-incident.yml` | Открывает GitHub Issue при падении CI (с дедупликацией) |
| `reusable-copilot-triage.yml` | Назначает Copilot для триажа инцидентов |
| `reusable-sync-labels.yml` | Синхронизирует метки issues по репозиториям провайдеров |
| `reusable-sync-kion-from-yandex.yml` | Синхронизирует KION-провайдер из кодовой базы Яндекс Музыки |

### Распределение файлов-обёрток

`scripts/distribute.py` рендерит Jinja2-шаблоны из `wrappers/` для каждого провайдера и создаёт PR с результатами.
Запускается автоматически при push в `main`, если изменились `wrappers/` или `providers.yml`.

Распределяемые файлы: CI workflow, шаблоны задач, метки, документация, Docker-окружение, конфигурация Starlight docs-site, авто-синкаемый гайд `CLAUDE.md`, шапка README (badges + локалезависимые quick-links + cross-link через marker injection), авто-синкаемые блоки `ruff.toml` / `[tool.mypy]` / `[tool.codespell].skip` (еженедельно подтягиваются из upstream `music-assistant/server`), SDD-шаблон спецификации фичи и JSON-файлы динамического Music Assistant бейджа.

### Автоматизация уровня репозитория

Три центральных workflow в этом репо (не распределяются по провайдерам), поддерживающие согласованность экосистемы:

| Workflow | Расписание | Назначение |
|----------|-----------|------------|
| `ci.yml` | на каждый PR / push ветки | Прогоняет pre-commit, `validate_templates.py`, `validate_providers_yml.py` до мерджа. |
| `sync-upstream-config.yml` | еженедельный cron + manual | Подтягивает блоки `[tool.ruff]` / `[tool.mypy]` / `[tool.codespell].skip` из upstream `music-assistant/server`; открывает PR при drift. |
| `sync-repo-settings.yml` | manual `workflow_dispatch` | Отправляет `github_description` / `github_topics` / `github_homepage` из `providers.yml` в каждый провайдер через `gh repo edit` (по умолчанию dry-run). |
| `update-ma-version-badges.yml` | cron каждые 4 часа + manual | Обновляет `public/badges/<domain>-{stable,beta}.json`, чтобы бейдж Music Assistant в README каждого провайдера показывал, в какой канал MA включён провайдер. |

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
  reusable-*.yml                       ← общая CI-логика (вызывается из репозиториев провайдеров через `uses:`)
  ci.yml                               ← PR / push gate (pre-commit + валидаторы)
  distribute.yml                       ← запускает distribute.py при push в main
  docs.yml                             ← деплоит public/ в GitHub Pages
  sync-upstream-config.yml             ← еженедельный cron: подтянуть lint/typing-конфиг из upstream MA
  sync-repo-settings.yml               ← manual: пушит метаданные из providers.yml через gh repo edit
  update-ma-version-badges.yml         ← cron каждые 4 часа: обновление JSON для MA-бейджа
wrappers/
  *.j2                                 ← Jinja2-шаблоны (top-level), рендерятся для каждого провайдера
  docs/*.j2                            ← страницы Starlight
  feature-spec.md.j2                   ← SDD T-shirt-шаблон спеки
  readme-header.md.j2                  ← бейджи + quick-links + cross-links (marker-инжекция)
schemas/
  providers.schema.json                ← JSON Schema для providers.yml
scripts/
  distribute.py                        ← рендерит шаблоны, создаёт PR в репозиториях провайдеров
  validate_templates.py                ← проверяет синтаксис Jinja2, пробелы, переменные
  validate_providers_yml.py            ← schema-валидация providers.yml
  render_for_provider.py               ← рендерит указанные wrappers для одного домена
  check_config_sync.py                 ← worker для reusable-check-config-sync.yml
  check_feature_consistency.py         ← worker для reusable-check-feature-consistency.yml
  sync_upstream_config.py              ← подтягивает lint/typing-конфиг из upstream MA
  sync_repo_settings.py                ← пушит GitHub About + topics через gh repo edit
  update_ma_version_badges.py          ← пишет public/badges/<domain>-{stable,beta}.json
  dev-workspace.py                     ← общее dev-окружение (мульти-провайдер)
  generate_dashboard.py                ← генерирует данные для дашборда провайдеров
  update_changelog.py                  ← автоматизирует записи changelog при релизах
  check_package_safety.py              ← проверка безопасности зависимостей
  parse_manifest_deps.py               ← парсинг зависимостей из манифеста провайдера
providers.yml                          ← реестр: все провайдеры, их репозитории и конфигурация
public/badges/                         ← JSON динамических MA-бейджей (раздаётся через GH Pages)
src/                                   ← исходники Astro Starlight (index, dashboard, …)
docs-site/                             ← дополнительные ассеты документации (diagrams)
```

## Dev Workspace

Создайте общее dev-окружение с одним MA-сервером и всеми провайдерами:

```bash
# Создать workspace со всеми провайдерами
python3 scripts/dev-workspace.py init --dir ~/ma-workspace --all

# Запустить MA-сервер со всеми провайдерами
python3 scripts/dev-workspace.py run --dir ~/ma-workspace

# Обновить все репозитории до последних версий
python3 scripts/dev-workspace.py update --dir ~/ma-workspace
```

## Дополнительно

- **[Дашборд провайдеров →](https://trudenboy.github.io/ma-provider-tools/dashboard)** — live PRs, CI-статус, активность разработки по всем провайдерам
