import json
import os
import re
import sys
import argparse
import random
from pathlib import Path
from datetime import datetime

# Regex for safe tokens in route session ID and project tags
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:-]+$")

def derive_talker_root() -> Path:
    """
    1. Переменная окружения TALKER_ROOT (если задана и непуста)
    2. Иначе: Path(__file__).resolve().parent.parent / "Talker"
    """
    env_root = os.environ.get("TALKER_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent / "Talker"

def derive_app_root() -> Path:
    r"""Parent директории скрипта: Path(__file__).resolve().parent.parent
    Looper/../ == C:\CorrisBot"""
    return Path(__file__).resolve().parent.parent

def get_registry_path(talker_root: Path) -> Path:
    return talker_root / "Temp" / "project_registry.json"

def read_registry(talker_root: Path) -> dict:
    """Прочитать registry. Если файла нет — вернуть пустую структуру
    {"version": 1, "projects": {}}."""
    path = get_registry_path(talker_root)
    if not path.exists():
        return {"version": 1, "projects": {}}
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # According to requirements: Registry-файл повреждён (невалидный JSON) -> Ошибка
        sys.stderr.write(f"project registry is corrupt: {path}\n")
        sys.exit(2)

def write_registry(talker_root: Path, data: dict) -> None:
    """Атомарная запись (tmp + rename). Создать Talker/Temp/ если не существует."""
    path = get_registry_path(talker_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        
        # Atomic replace (os.replace uses MoveFileEx on Windows)
        os.replace(str(tmp_path), str(path))
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        sys.stderr.write(f"failed to write registry: {e}\n")
        sys.exit(2)

def sanitize_for_session_id(raw: str) -> str:
    """Заменить символы, не входящие в SAFE_TOKEN_RE [A-Za-z0-9._:-],
    на '_'. Используется для безопасного включения project_tag в session_id."""
    return "".join(c if SAFE_TOKEN_RE.match(c) else "_" for c in raw)

def generate_session_id(project_tag: str) -> str:
    """Сгенерировать новый route_session_id в формате:
    s-<sanitized_project_tag>-<YYYYMMDD>-<HHMMSS>-<random4hex>
    Результат должен проходить SAFE_TOKEN_RE из route_contract_utils.
    Использовать sanitize_for_session_id для обработки project_tag."""
    sanitized = sanitize_for_session_id(project_tag)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rand = f"{random.randint(0, 0xFFFF):04x}"
    return f"s-{sanitized}-{ts}-{rand}"

def register_project(talker_root: Path, project_root: str, edit_root: str = "") -> dict:
    """Зарегистрировать новый проект. project_tag = Path(project_root).name."""
    project_root_path = Path(project_root).resolve()
    project_tag = project_root_path.name
    
    registry = read_registry(talker_root)
    projects = registry.setdefault("projects", {})
    
    now = datetime.now().isoformat()
    
    if project_tag in projects:
        existing = projects[project_tag]
        if Path(existing["project_root"]).resolve() != project_root_path:
            sys.stderr.write(f"warning: project tag {project_tag} was registered with different project_root, overwriting\n")
        
        # If tag exists, update fields if provided
        if edit_root:
            existing["edit_root"] = str(Path(edit_root).resolve())
        existing["project_root"] = str(project_root_path)
        existing["updated_at"] = now
    else:
        # New registration
        projects[project_tag] = {
            "project_root": str(project_root_path),
            "edit_root": str(Path(edit_root).resolve()) if edit_root else "",
            "route_session_id": "",
            "created_at": now,
            "updated_at": now
        }
    
    write_registry(talker_root, registry)
    return projects[project_tag]

def update_project(talker_root: Path, project_tag: str, **fields) -> dict:
    """Обновить конкретные поля существующего проекта.
    Допустимые поля для обновления: edit_root, route_session_id.
    Всегда обновлять updated_at.
    Вернуть обновлённую запись. Если проект не найден — RuntimeError."""
    registry = read_registry(talker_root)
    projects = registry.get("projects", {})
    
    if project_tag not in projects:
        raise RuntimeError(f"project not found: {project_tag}")
    
    project = projects[project_tag]
    valid_fields = ["edit_root", "route_session_id"]
    
    for key, value in fields.items():
        if key in valid_fields:
            if key == "edit_root" and value:
                project[key] = str(Path(value).resolve())
            else:
                project[key] = value
                
    project["updated_at"] = datetime.now().isoformat()
    
    write_registry(talker_root, registry)
    return project

def lookup_project(talker_root: Path, project_tag: str) -> dict:
    """Найти проект по тегу. Если не найден — RuntimeError с текстом
    'project not registered: <tag>. Use CreateProjectStructure to create it.'"""
    registry = read_registry(talker_root)
    projects = registry.get("projects", {})
    
    if project_tag not in projects:
        raise RuntimeError(f"project not registered: {project_tag}. Use CreateProjectStructure to create it.")
    
    return projects[project_tag]

def remove_project(talker_root: Path, project_tag: str) -> None:
    """Удалить проект из registry по тегу. Если не найден — RuntimeError."""
    registry = read_registry(talker_root)
    projects = registry.get("projects", {})
    
    if project_tag not in projects:
        raise RuntimeError(f"project not found: {project_tag}")
    
    del projects[project_tag]
    write_registry(talker_root, registry)

def list_projects(talker_root: Path) -> dict:
    """Вернуть весь словарь projects из registry."""
    registry = read_registry(talker_root)
    return registry.get("projects", {})

def main():
    parser = argparse.ArgumentParser(description="Talker project registry utility")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # register
    reg_parser = subparsers.add_parser("register")
    reg_parser.add_argument("--project-root", required=True)
    reg_parser.add_argument("--edit-root", default="")
    
    # update
    upd_parser = subparsers.add_parser("update")
    upd_parser.add_argument("--project-tag", required=True)
    upd_parser.add_argument("--edit-root", default=None)
    upd_parser.add_argument("--route-session-id", default=None)
    
    # lookup
    look_parser = subparsers.add_parser("lookup")
    look_parser.add_argument("--project-tag", required=True)
    
    # list
    subparsers.add_parser("list")
    
    # remove
    rem_parser = subparsers.add_parser("remove")
    rem_parser.add_argument("--project-tag", required=True)
    
    args = parser.parse_args()
    
    talker_root = derive_talker_root()
    
    try:
        if args.command == "register":
            project = register_project(talker_root, args.project_root, args.edit_root)
            print(json.dumps(project, indent=2, ensure_ascii=False))
            
        elif args.command == "update":
            fields = {}
            if args.edit_root is not None:
                fields["edit_root"] = args.edit_root
            if args.route_session_id is not None:
                fields["route_session_id"] = args.route_session_id
            
            project = update_project(talker_root, args.project_tag, **fields)
            print(json.dumps(project, indent=2, ensure_ascii=False))
            
        elif args.command == "lookup":
            project = lookup_project(talker_root, args.project_tag)
            print(json.dumps(project, indent=2, ensure_ascii=False))
            
        elif args.command == "list":
            projects = list_projects(talker_root)
            print(json.dumps(projects, indent=2, ensure_ascii=False))
            
        elif args.command == "remove":
            remove_project(talker_root, args.project_tag)
            # No output on success as per plan (exit code 0 is enough)
            
    except RuntimeError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(2)
    except Exception as e:
        sys.stderr.write(f"unexpected error: {e}\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
