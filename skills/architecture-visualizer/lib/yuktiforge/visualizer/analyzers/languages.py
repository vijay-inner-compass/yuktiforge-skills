"""Language detection by file extension. Data only: detecting a language is NOT supporting it."""
from __future__ import annotations

EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".go": "go", ".rs": "rust",
    ".cs": "csharp", ".fs": "fsharp", ".vb": "visualbasic",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".php": "php", ".rb": "ruby", ".swift": "swift", ".m": "objective-c",
    ".dart": "dart", ".lua": "lua", ".r": "r", ".ex": "elixir", ".exs": "elixir",
    ".hs": "haskell", ".clj": "clojure", ".erl": "erlang", ".pl": "perl",
    ".sh": "shell", ".sql": "sql", ".tf": "terraform",
}

SKIP_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
                       "target", ".yuktiforge", ".idea", ".vscode", ".tox", ".mypy_cache", ".pytest_cache",
                       "vendor", "bin", "obj"})


def language_of(filename: str) -> str | None:
    dot = filename.rfind(".")
    return EXT_TO_LANGUAGE.get(filename[dot:].lower()) if dot >= 0 else None
