"""
一次性迁移脚本：将现有 Rebrickable 裸表名重命名为 rb_* 表名。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, inspect, text

from src.config.db_config import get_db_url


TABLE_RENAMES = [
    ("themes", "rb_themes"),
    ("sets", "rb_sets"),
    ("part_categories", "rb_part_categories"),
    ("parts", "rb_parts"),
    ("colors", "rb_colors"),
    ("inventories", "rb_inventories"),
    ("inventory_parts", "rb_inventory_parts"),
    ("inventory_sets", "rb_inventory_sets"),
    ("minifigs", "rb_minifigs"),
    ("inventory_minifigs", "rb_inventory_minifigs"),
    ("part_relationships", "rb_part_relationships"),
]


def rename_rebrickable_tables():
    """直接重命名现有 Rebrickable 表；已迁移的表会跳过。"""
    engine = create_engine(get_db_url(), echo=False)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    pending_renames = []
    for old_name, new_name in TABLE_RENAMES:
        if new_name in existing_tables:
            print(f"跳过: {new_name} 已存在")
            continue
        if old_name not in existing_tables:
            print(f"跳过: {old_name} 不存在")
            continue
        pending_renames.append((old_name, new_name))

    if not pending_renames:
        print("没有需要重命名的表")
        return

    with engine.begin() as conn:
        preparer = conn.dialect.identifier_preparer
        for old_name, new_name in pending_renames:
            conn.execute(
                text(
                    f"ALTER TABLE {preparer.quote(old_name)} "
                    f"RENAME TO {preparer.quote(new_name)}"
                )
            )

    for old_name, new_name in pending_renames:
        print(f"已重命名: {old_name} -> {new_name}")


if __name__ == "__main__":
    rename_rebrickable_tables()
