from __future__ import annotations

from typing import Any


class PathError(ValueError):
    pass


def parts(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PathError(f"path must be a JSON Pointer: {path!r}")
    return [item.replace("~1", "/").replace("~0", "~") for item in path[1:].split("/")]


def get(document: Any, path: str) -> Any:
    current = document
    for part in parts(path):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise PathError(f"missing path {path!r}") from exc
        else:
            raise PathError(f"missing path {path!r}")
    return current


def set_value(document: dict[str, Any], path: str, value: Any) -> None:
    keys = parts(path)
    if not keys:
        raise PathError("the document root cannot be replaced")
    current: Any = document
    for key in keys[:-1]:
        if not isinstance(current, dict):
            raise PathError(f"cannot descend through {key!r} in {path!r}")
        current = current.setdefault(key, {})
    if not isinstance(current, dict):
        raise PathError(f"parent of {path!r} is not an object")
    current[keys[-1]] = value


def delete(document: dict[str, Any], path: str) -> None:
    keys = parts(path)
    if not keys:
        raise PathError("the document root cannot be deleted")
    current: Any = document
    for key in keys[:-1]:
        if not isinstance(current, dict) or key not in current:
            raise PathError(f"missing path {path!r}")
        current = current[key]
    if not isinstance(current, dict) or keys[-1] not in current:
        raise PathError(f"missing path {path!r}")
    del current[keys[-1]]
