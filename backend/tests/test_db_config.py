"""Unit tests for database URL configuration."""

import os
import tempfile
import unittest
from pathlib import Path

from src.config.db_config import (
    get_db_engine_options,
    get_db_url,
    load_mysql_config,
    normalize_database_url,
    require_supabase_ssl,
)


DB_ENV_KEYS = (
    "DATABASE_URL",
    "DATABASE_POOL_SIZE",
    "DATABASE_MAX_OVERFLOW",
    "DATABASE_POOL_TIMEOUT_SECONDS",
    "DATABASE_POOL_RECYCLE_SECONDS",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
    "MYSQL_CHARSET",
)


class DatabaseConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_values = {key: os.environ.get(key) for key in DB_ENV_KEYS}
        for key in DB_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self.original_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_get_db_url_loads_required_values_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "MYSQL_HOST=localhost",
                        "MYSQL_PORT=3306",
                        "MYSQL_USER=test_user",
                        "MYSQL_PASSWORD=p@ss word",
                        "MYSQL_DATABASE=ctbzbricks",
                        "MYSQL_CHARSET=utf8mb4",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                get_db_url(env_file),
                "mysql+pymysql://test_user:p%40ss+word@localhost:3306/ctbzbricks?charset=utf8mb4",
            )

    def test_missing_database_config_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("MYSQL_USER=test_user", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "MYSQL_HOST"):
                load_mysql_config(env_file)

    def test_database_url_takes_priority_over_legacy_mysql_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "DATABASE_URL=postgresql://app:secret@db.example.test:5432/postgres?sslmode=require",
                encoding="utf-8",
            )

            self.assertEqual(
                get_db_url(env_file),
                "postgresql+psycopg://app:secret@db.example.test:5432/postgres?sslmode=require",
            )

    def test_database_pool_uses_bounded_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("", encoding="utf-8")

            self.assertEqual(
                get_db_engine_options(env_file),
                {
                    "pool_pre_ping": True,
                    "pool_size": 10,
                    "max_overflow": 10,
                    "pool_timeout": 30,
                    "pool_recycle": 1800,
                    "pool_use_lifo": True,
                },
            )

    def test_database_pool_settings_can_be_loaded_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "DATABASE_POOL_SIZE=4",
                        "DATABASE_MAX_OVERFLOW=2",
                        "DATABASE_POOL_TIMEOUT_SECONDS=12",
                        "DATABASE_POOL_RECYCLE_SECONDS=900",
                    ]
                ),
                encoding="utf-8",
            )

            options = get_db_engine_options(env_file)

        self.assertEqual(options["pool_size"], 4)
        self.assertEqual(options["max_overflow"], 2)
        self.assertEqual(options["pool_timeout"], 12)
        self.assertEqual(options["pool_recycle"], 900)

    def test_invalid_database_pool_setting_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("DATABASE_POOL_SIZE=0", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "DATABASE_POOL_SIZE"):
                get_db_engine_options(env_file)

    def test_normalize_database_url_preserves_explicit_driver(self) -> None:
        url = "postgresql+psycopg://app:secret@localhost/postgres"
        self.assertEqual(normalize_database_url(url), url)

    def test_supabase_url_requires_ssl_by_default(self) -> None:
        url = "postgresql+psycopg://app:secret@region.pooler.supabase.com/postgres"
        self.assertEqual(require_supabase_ssl(url), f"{url}?sslmode=require")

    def test_supabase_url_preserves_explicit_ssl_mode(self) -> None:
        url = (
            "postgresql+psycopg://app:secret@region.pooler.supabase.com/postgres"
            "?application_name=ctbz&sslmode=verify-full"
        )
        self.assertEqual(require_supabase_ssl(url), url)


if __name__ == "__main__":
    unittest.main()
