# План: разделение Workspace bootstrap и Git bootstrap

Дата: 2026-02-19  
Репозиторий: `C:\CorrisBot`  
Назначение: самодостаточный документ для запуска работ в новом чате с чистым контекстом.

## 0) Условия выполнения
1. Все команды в плане предполагают запуск из корня репозитория `C:\CorrisBot`.
2. Если запуск не из корня, использовать абсолютные пути к скриптам.
3. Целевая среда: Windows (`cmd`/PowerShell), `git` и `python` доступны в `PATH`.

## 1) Цель изменений
Устранить смешение двух разных сущностей:
- `Workspace` оркестрации (папка, где живут Orchestrator/Workers и их prompt-обмен),
- `Implementation project` (папка реального разрабатываемого приложения, где нужен Git репозиторий кода).

Результат:
1. `CreateProjectStructure.bat` создает только workspace-структуру.
2. Git инициализируется отдельным скриптом `EnsureRepo.bat` в явном `RepoRoot`.
3. Оркестратор проверяет/готовит Git до делегирования Worker-ам.
4. Worker в shared-режиме не делает `git init` самостоятельно.

## 2) Зафиксированные решения (согласовано)
1. Git bootstrap выносим из `CreateProjectStructure.bat` в отдельный скрипт.
2. Новый скрипт: `Looper/EnsureRepo.bat`.
3. `EnsureRepo.bat` должен:
- работать идемпотентно;
- всегда проверять/обеспечивать наличие repo в целевом `RepoRoot`;
- всегда копировать `.gitignore` из шаблона в `RepoRoot` (с перезаписью существующего файла);
- всегда делать initial commit, если в репозитории еще нет коммитов.
4. Оркестратор при проблеме bootstrap обязан сообщить пользователю и ждать ответа (не продолжать делегирование).
5. Worker в `RepoMode=shared` не имеет права запускать `git init`; при отсутствии repo обязан эскалировать Оркестратору.

## 3) Термины (обязательные для всей реализации)
1. `WorkspaceRoot`:
- пример: `C:\Temp\CorrisBot_TestProject_8`;
- используется для orchestration loopers, prompt inbox/outbox, ролей и планов.
2. `ImplementationRoot`:
- пример: `C:\Temp\TestProject_8`;
- это корень разрабатываемого приложения.
3. `RepoRoot`:
- путь git-репозитория разработки;
- в текущей модели по умолчанию равен `ImplementationRoot`.
4. `RepoMode`:
- `shared`: один общий репозиторий, которым пользуются несколько Worker;
- `isolated`: отдельный репозиторий для конкретного Worker (только по явному указанию Оркестратора).

## 4) Scope изменений
Изменять:
1. `Looper/EnsureRepo.bat` (новый файл)
2. `Looper/CreateProjectStructure.bat`
3. `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
4. `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`
5. `Talker/ROLE_TALKER.md`
6. `Talker/AGENTS.md` (пересборка из шаблона)

Не изменять:
1. Логику gateway/transport.
2. Схему `Reply-To` маршрутизации.
3. Принципы CR/Anti-Hack (кроме нужных уточнений для Git-контракта).

## 5) Этапы выполнения

### Этап 0. Baseline и ветка
1. Создать ветку:
- `git checkout -b chore/git-bootstrap-workspace-split-2026-02-19`
2. Зафиксировать baseline:
- `cmd /c findstr /n "git init" Looper\CreateProjectStructure.bat`
- `cmd /c findstr /n "Initial project structure" Looper\CreateProjectStructure.bat`

Критерий этапа:
- подтверждено, что Git сейчас инициализируется внутри `CreateProjectStructure.bat`.

### Этап 1. Добавить `EnsureRepo.bat`
Создать `Looper/EnsureRepo.bat` с контрактом:
1. Usage:
- `%~nx0 <repo_root_path>`
2. Поведение:
- валидировать входной путь;
- создать папку `RepoRoot`, если отсутствует;
- проверить доступность `git` (`git --version`);
- если `.git` отсутствует: `git init`;
- всегда копировать `.gitignore` из `ProjectFolder_Template\gitignore_template.txt` (через вычисляемый `TEMPLATE_ROOT`) с перезаписью;
- если в repo нет коммитов (`git rev-parse --verify HEAD` неуспешен): `git add .` + `git commit -m "Initial repository bootstrap"`.
3. Идемпотентность:
- повторный запуск не должен ломать существующий репозиторий;
- не должен делать лишний bootstrap commit, если `HEAD` уже существует.
4. Диагностика:
- понятные `echo` сообщения;
- стабильные `exit /b` коды для ошибок.

Проверки:
1. `Looper\EnsureRepo.bat C:\Temp\.EnsureRepo_Test_01` -> успех, создается `.git`, `.gitignore`, первый commit.
2. Повторный запуск по тому же пути -> успех без нового bootstrap commit.
3. `git -C <repo> log --oneline -n 3`.

Коммит:
1. `git add Looper/EnsureRepo.bat`
2. `git commit -m "feat(looper): add EnsureRepo bootstrap script for implementation repositories"`

### Этап 2. Убрать Git-инициализацию из `CreateProjectStructure.bat`
Из `Looper/CreateProjectStructure.bat` удалить блок:
1. проверка `%DEST_ROOT%\.git\`
2. `git init`
3. `git add .`
4. `git commit -m "Initial project structure"`
5. `echo Git repository initialized ...`

Оставить:
1. создание структуры workspace,
2. копирование `.gitignore` в workspace (это допустимо как часть scaffold).

Проверки:
1. создать тестовый workspace:
- `Looper\CreateProjectStructure.bat C:\Temp\.CreateProjectStructure_NoGit_Test`
2. убедиться, что:
- `C:\Temp\.CreateProjectStructure_NoGit_Test\.git` отсутствует,
- структура Orchestrator/Workers создана.

Коммит:
1. `git add Looper/CreateProjectStructure.bat`
2. `git commit -m "refactor(looper): remove git bootstrap from workspace creation script"`

### Этап 3. Обновить роль Оркестратора
Файл: `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`

Добавить/уточнить:
1. Новый обязательный gate перед Worker bootstrap:
- `Git Preflight Gate (MANDATORY)`.
2. Правило входных данных:
- если `ImplementationRoot/RepoRoot` не указан в задаче, Оркестратор обязан запросить путь и остановить делегирование.
3. Команда bootstrap:
- Оркестратор обязан вызвать `EnsureRepo.bat <RepoRoot>` и проверить успех.
  - `EnsureRepo` должен вызываться до первого делегирования Worker в рамках проектной сессии для данного `RepoRoot`.
4. Failure policy:
- если `EnsureRepo` завершился ошибкой, Оркестратор сообщает пользователю и ждет решения.
5. Worker task contract дополнить Git-блоком:
- `RepoRoot`
- `RepoMode` (`shared|isolated`)
- `AllowedPaths`
- `CommitPolicy`
6. Acceptance policy:
- приемка результата Worker только после Git-проверок (`git status`, релевантный commit, отсутствие неожиданных untracked для целевого scope).

Проверка:
1. Поиск ключевых маркеров в роли:
- `Git Preflight Gate`
- `RepoMode`
- `EnsureRepo.bat`
- `stop and ask user` (или эквивалентная формулировка на русском).

Коммит:
1. `git add ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md`
2. `git commit -m "feat(orchestrator-role): enforce git preflight and worker git contract"`

### Этап 4. Обновить роль Worker
Файл: `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`

Добавить/уточнить:
1. `RepoMode=shared`:
- запрет на `git init`;
- при отсутствии repo: немедленная эскалация Оркестратору, без авто-инициализации.
2. `RepoMode=isolated`:
- `git init` разрешен только если это явно указано Оркестратором в task contract.
3. Обязательный Git-отчет в deliverable:
- `git status --short` до/после;
- `commit hash`;
- список файлов последнего commit.

Проверка:
1. В роли присутствуют явные правила `shared`/`isolated`.
2. Нет двусмысленных формулировок, позволяющих самовольный `git init` в shared.

Коммит:
1. `git add ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md`
2. `git commit -m "feat(worker-role): forbid git init in shared mode and require git evidence"`

### Этап 5. Обновить роль Talker
Файл: `Talker/ROLE_TALKER.md`

Уточнить секцию `SKILL CREATE NEW PROJECT`:
1. `CreateProjectStructure.bat` создает только workspace-структуру.
2. Git для implementation проекта не создается на этом шаге.
3. Git bootstrap выполняет Оркестратор после получения `ImplementationRoot`.

Проверка:
1. В `ROLE_TALKER.md` явно разведены `workspace` и `implementation repo`.

Коммит:
1. `git add Talker/ROLE_TALKER.md`
2. `git commit -m "docs(talker-role): clarify workspace-only project creation and orchestrator git bootstrap"`

### Этап 6. Пересборка AGENTS и консистентность
1. Пересобрать Talker AGENTS:
- `py Looper/assemble_agents.py Talker/AGENTS_TEMPLATE.md Talker/AGENTS.md`
2. Проверить сборку шаблонов Orchestrator/Worker (временные файлы в `C:\Temp`):
- `py Looper/assemble_agents.py ProjectFolder_Template/Orchestrator/AGENTS_TEMPLATE.md C:\Temp\Orchestrator_AGENTS_test.md`
- `py Looper/assemble_agents.py ProjectFolder_Template/Workers/Worker_001/AGENTS_TEMPLATE.md C:\Temp\Worker001_AGENTS_test.md`
3. Проверить наличие новых формулировок в `Talker/AGENTS.md`.
4. Убедиться, что нет синтаксических/структурных ошибок в обновленных markdown-файлах.

Коммит:
1. `git add Talker/AGENTS.md`
2. `git commit -m "chore(agents): rebuild Talker AGENTS after role updates"`

### Этап 7. E2E smoke (минимальный сценарий)
Сценарий проверки:
1. Создать workspace:
- `Looper\CreateProjectStructure.bat C:\Temp\Workspace_GitSplit_Test`
2. Убедиться, что `.git` в workspace не создан.
3. Вызвать `EnsureRepo.bat` для implementation path:
- `Looper\EnsureRepo.bat C:\Temp\Implementation_GitSplit_Test`
4. Убедиться, что в implementation path есть:
- `.git`
- `.gitignore`
- минимум один commit.
5. Проверить, что правила ролей содержат новые Git-контракты (`rg`/`findstr` по ключевым фразам).

Done для всей задачи:
1. Git полностью отделен от `CreateProjectStructure.bat`.
2. Git создается через `EnsureRepo.bat` в явном `RepoRoot`.
3. Роли Orchestrator/Worker/Talker синхронизированы с новой моделью.
4. AGENTS Talker пересобран.
5. Сборка шаблонов Orchestrator/Worker проходит без ошибок.
6. Smoke сценарий успешен.

## 6) Обязательный CR по этапам
После этапов 2, 4 и 7 выполнить CR:
1. Findings-first: `High -> Medium -> Low`.
2. Проверить, не возникло ли логических дыр:
- делегирование Worker до `EnsureRepo`,
- самовольный `git init` в shared,
- неоднозначность между `WorkspaceRoot` и `ImplementationRoot`.
3. Если есть `High`, переход к следующему этапу запрещен.

## 7) Риски и меры
1. Риск: частично обновленные роли приведут к конфликту поведения.
- Мера: менять все три роли в одном цикле и проверять маркеры `RepoRoot/RepoMode`.
2. Риск: `EnsureRepo.bat` начнет коммитить лишние файлы.
- Мера: initial commit только при отсутствии `HEAD`; обеспечить `.gitignore` до `git add .`.
3. Риск: повторный запуск `EnsureRepo.bat` перезапишет кастомный `.gitignore`.
- Мера: вызывать `EnsureRepo` один раз до первого делегирования в проектной сессии; дальнейшие изменения `.gitignore` делать осознанно.
4. Риск: операторы продолжат ожидать `.git` после `CreateProjectStructure`.
- Мера: явное обновление текста в `Talker/ROLE_TALKER.md` и плане внедрения.

## 8) Команды для финальной проверки
```bat
cmd /c findstr /n "git init" Looper\CreateProjectStructure.bat
cmd /c findstr /n "EnsureRepo" ProjectFolder_Template\Orchestrator\ROLE_ORCHESTRATOR.md
cmd /c findstr /n "RepoMode" ProjectFolder_Template\Orchestrator\ROLE_ORCHESTRATOR.md
cmd /c findstr /n "shared" ProjectFolder_Template\Workers\Worker_001\ROLE_WORKER.md
cmd /c findstr /n "CreateProjectStructure.bat" Talker\ROLE_TALKER.md
py Looper\assemble_agents.py Talker\AGENTS_TEMPLATE.md Talker\AGENTS.md
py Looper\assemble_agents.py ProjectFolder_Template\Orchestrator\AGENTS_TEMPLATE.md C:\Temp\Orchestrator_AGENTS_test.md
py Looper\assemble_agents.py ProjectFolder_Template\Workers\Worker_001\AGENTS_TEMPLATE.md C:\Temp\Worker001_AGENTS_test.md
```

## 9) Rollback стратегия
Если нужно откатить внедрение:
1. Откатить поэтапно `git revert` последних коммитов в обратном порядке этапов.
2. Минимально критичный rollback:
- вернуть старый `CreateProjectStructure.bat`,
- временно отключить `Git Preflight Gate` в роли Оркестратора.
3. После rollback обязательно повторить smoke.

## 10) Готовый стартовый промпт для нового чата
```md
Контекст: выполняем план `Looper/Plans/GIT_BOOTSTRAP_WORKSPACE_SPLIT_EXECUTION_PLAN_2026_02_19.md`.

Требования:
1) Строго выполнить этапы по порядку.
2) После этапов 2, 4 и 7 сделать CR (findings-first).
3) Не использовать destructive git-команды.
4) Все изменения делать в репозитории `C:\CorrisBot`.
5) В финале предоставить:
   - список измененных файлов;
   - результаты smoke;
   - итоговый CR.
```
