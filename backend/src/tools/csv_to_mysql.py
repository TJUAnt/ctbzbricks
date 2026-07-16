"""
CSV 数据导入脚本，支持 MySQL 和 PostgreSQL
使用SQLAlchemy ORM
"""
import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.model.models import (
    Base, Theme, Set, PartCategory, Part, Color,
    Inventory, InventoryPart, PartImage, InventorySet, Minifig,
    InventoryMinifig, PartRelationship
)
from src.resource.file.csv_handler import CSVHandler
from src.config.db_config import get_db_url


REBRICKABLE_TABLES = [
    Theme.__table__,
    Set.__table__,
    PartCategory.__table__,
    Part.__table__,
    Color.__table__,
    Inventory.__table__,
    InventoryPart.__table__,
    PartImage.__table__,
    InventorySet.__table__,
    Minifig.__table__,
    InventoryMinifig.__table__,
    PartRelationship.__table__,
]


class CSVToMySQLImporter:
    """CSV importer retained under its legacy name for CLI compatibility."""

    def __init__(self, db_url: str):
        """
        初始化数据库连接

        :param db_url: 数据库连接URL
                      例如: "postgresql+psycopg://username:password@host/postgres"
        """
        self.engine = create_engine(db_url, echo=False)
        self.Session = sessionmaker(bind=self.engine)
        self.session = None

    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(self.engine, tables=REBRICKABLE_TABLES)
        print("数据库表创建完成")

    def truncate_tables(self):
        """清空所有表数据"""
        with self.engine.begin() as conn:
            # 按依赖顺序反向清空
            conn.execute(text("DELETE FROM rb_part_relationships"))
            conn.execute(text("DELETE FROM rb_inventory_minifigs"))
            conn.execute(text("DELETE FROM rb_inventory_sets"))
            conn.execute(text("DELETE FROM rb_inventory_parts"))
            conn.execute(text("DELETE FROM rb_part_images"))
            conn.execute(text("DELETE FROM rb_inventories"))
            conn.execute(text("DELETE FROM rb_minifigs"))
            conn.execute(text("DELETE FROM rb_colors"))
            conn.execute(text("DELETE FROM rb_parts"))
            conn.execute(text("DELETE FROM rb_part_categories"))
            conn.execute(text("DELETE FROM rb_sets"))
            conn.execute(text("DELETE FROM rb_themes"))
        print("数据表已清空")

    def drop_tables(self):
        """删除所有表"""
        Base.metadata.drop_all(self.engine, tables=REBRICKABLE_TABLES)
        print("数据库表已删除")

    def _process_records(self, df):
        """处理DataFrame中的NaN值和浮点转整型"""
        records = df.to_dict('records')
        for record in records:
            for key, value in record.items():
                if pd.isna(value):
                    record[key] = None
                elif isinstance(value, float) and value.is_integer():
                    record[key] = int(value)
        return records

    def import_themes(self, csv_path: str):
        """导入主题数据"""
        print(f"导入主题数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(Theme, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条主题记录")

    def import_sets(self, csv_path: str):
        """导入套装数据"""
        print(f"导入套装数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(Set, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条套装记录")

    def import_part_categories(self, csv_path: str):
        """导入零件类别数据"""
        print(f"导入零件类别数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(PartCategory, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条零件类别记录")

    def import_parts(self, csv_path: str):
        """导入零件数据"""
        print(f"导入零件数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(Part, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条零件记录")

    def import_colors(self, csv_path: str):
        """导入颜色数据"""
        print(f"导入颜色数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        # 只保留需要的列
        df = df[['id', 'name', 'rgb', 'is_trans']]
        records = self._process_records(df)
        self.session.bulk_insert_mappings(Color, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条颜色记录")

    def import_inventories(self, csv_path: str):
        """导入库存数据"""
        print(f"导入库存数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(Inventory, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条库存记录")

    def import_inventory_parts(self, csv_path: str):
        """导入库存零件数据"""
        print(f"导入库存零件数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        image_df = (
            df.loc[
                df["img_url"].notna() & df["img_url"].ne(""),
                ["id", "part_num", "img_url"],
            ]
            .sort_values("id")
            .drop_duplicates("part_num")
        )
        image_records = self._process_records(image_df[["part_num", "img_url"]])
        self.session.bulk_insert_mappings(PartImage, image_records)
        records = self._process_records(df.drop(columns=["img_url"], errors="ignore"))
        self.session.bulk_insert_mappings(InventoryPart, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条库存零件记录")
        print(f"已导入 {len(image_records)} 条零件图片记录")

    def import_inventory_sets(self, csv_path: str):
        """导入库存套装数据"""
        print(f"导入库存套装数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(InventorySet, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条库存套装记录")

    def import_minifigs(self, csv_path: str):
        """导入小人仔数据"""
        print(f"导入小人仔数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(Minifig, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条小人仔记录")

    def import_inventory_minifigs(self, csv_path: str):
        """导入库存小人仔数据"""
        print(f"导入库存小人仔数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        records = self._process_records(df)
        self.session.bulk_insert_mappings(InventoryMinifig, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条库存小人仔记录")

    def import_part_relationships(self, csv_path: str):
        """导入零件关系数据"""
        print(f"导入零件关系数据: {csv_path}")
        df = CSVHandler.read(csv_path)
        df = df.rename(
            columns={
                "child_part_num": "part_num",
                "parent_part_num": "related_part_num",
            }
        )
        records = self._process_records(df)
        self.session.bulk_insert_mappings(PartRelationship, records)
        self.session.commit()
        print(f"已导入 {len(records)} 条零件关系记录")

    def import_all(self, data_dir: str):
        """
        导入所有CSV数据

        :param data_dir: CSV文件所在目录
        """
        self.session = self.Session()

        # 创建表（如已存在则跳过）
        self.create_tables()

        # 清空已有数据
        self.truncate_tables()

        # 按依赖顺序导入
        self.import_themes(os.path.join(data_dir, 'themes.csv'))
        self.import_sets(os.path.join(data_dir, 'sets.csv'))
        self.import_part_categories(os.path.join(data_dir, 'part_categories.csv'))
        self.import_parts(os.path.join(data_dir, 'parts.csv'))
        self.import_colors(os.path.join(data_dir, 'colors.csv'))
        self.import_inventories(os.path.join(data_dir, 'inventories.csv'))
        self.import_inventory_parts(os.path.join(data_dir, 'inventory_parts.csv'))
        self.import_inventory_sets(os.path.join(data_dir, 'inventory_sets.csv'))
        self.import_minifigs(os.path.join(data_dir, 'minifigs.csv'))
        self.import_inventory_minifigs(os.path.join(data_dir, 'inventory_minifigs.csv'))
        self.import_part_relationships(os.path.join(data_dir, 'part_relationships.csv'))

        self.session.close()
        print("\n所有数据导入完成!")


# 使用示例
if __name__ == '__main__':
    # 数据库连接配置
    DB_URL = get_db_url()

    # 数据目录
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')

    # 创建导入器并导入数据
    importer = CSVToMySQLImporter(DB_URL)
    importer.import_all(DATA_DIR)
