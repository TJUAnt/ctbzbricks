import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlsplit


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = BACKEND_ROOT / ".env"
LEGACY_ENV_FILE_PATH = Path(__file__).resolve().parents[1] / ".env"
DATABASE_URL_ENV_KEY = "DATABASE_URL"
MYSQL_ENV_KEYS = (
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
    "MYSQL_CHARSET",
)


def get_db_url(env_file_path: Path = ENV_FILE_PATH) -> str:
    """Return the configured SQLAlchemy URL.

    ``DATABASE_URL`` is the primary configuration for PostgreSQL/Supabase.
    The legacy MYSQL_* variables remain as a temporary local-development
    fallback while the migration is in progress.
    """
    env_file_path = resolve_env_file_path(env_file_path)
    file_values = read_env_file(env_file_path)
    database_url = os.environ.get(
        DATABASE_URL_ENV_KEY,
        file_values.get(DATABASE_URL_ENV_KEY, ""),
    ).strip()
    if database_url:
        return normalize_database_url(database_url)

    mysql_config = load_mysql_config(env_file_path)
    password = quote_plus(mysql_config["MYSQL_PASSWORD"])
    return (
        f"mysql+pymysql://{mysql_config['MYSQL_USER']}:{password}"
        f"@{mysql_config['MYSQL_HOST']}:{mysql_config['MYSQL_PORT']}/{mysql_config['MYSQL_DATABASE']}"
        f"?charset={mysql_config['MYSQL_CHARSET']}"
    )


def normalize_database_url(database_url: str) -> str:
    """Normalize common Postgres URLs to SQLAlchemy's psycopg driver."""
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return require_supabase_ssl(database_url)


def require_supabase_ssl(database_url: str) -> str:
    """Require TLS for Supabase hosts unless the URL already chooses a mode."""
    parsed = urlsplit(database_url)
    if not parsed.hostname or not parsed.hostname.endswith(".supabase.com"):
        return database_url
    if "sslmode" in parse_qs(parsed.query):
        return database_url
    separator = "&" if parsed.query else "?"
    return f"{database_url}{separator}sslmode=require"


def load_mysql_config(env_file_path: Path) -> dict[str, str | int]:
    env_file_path = resolve_env_file_path(env_file_path)
    file_values = read_env_file(env_file_path)
    mysql_config: dict[str, str | int] = {}
    for key in MYSQL_ENV_KEYS:
        value = os.environ.get(key, file_values.get(key, ""))
        if not value:
            raise RuntimeError(f"Missing database configuration: {key}")
        mysql_config[key] = value
    try:
        mysql_config["MYSQL_PORT"] = int(str(mysql_config["MYSQL_PORT"]))
    except ValueError as error:
        raise RuntimeError("Invalid database configuration: MYSQL_PORT") from error
    return mysql_config


def resolve_env_file_path(env_file_path: Path) -> Path:
    """Keep existing installations using backend/src/.env working."""
    if (
        env_file_path == ENV_FILE_PATH
        and not env_file_path.exists()
        and LEGACY_ENV_FILE_PATH.exists()
    ):
        return LEGACY_ENV_FILE_PATH
    return env_file_path


def read_env_file(env_file_path: Path) -> dict[str, str]:
    if not env_file_path.exists():
        return {}
    env_values: dict[str, str] = {}
    for raw_line in env_file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise RuntimeError(f"Invalid .env line: {key}")
        env_values[key.strip()] = unquoted_env_value(value.strip())
    return env_values


def unquoted_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
