"""显式迁移 legacy 元数据快照；只读旧数据库，不作为 API/Worker 运行依赖。"""
import argparse
import json
import hashlib
import re
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'backend'))
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.config.db_config import get_db_url
from src.services.lego_design_service import lego_design_metadata, lego_design_colors


def main():
    """把既有真实颜色/Plate 目录导出为 Go 显式导入文件，不包含用户项目或凭据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--ldraw-root', help='Use verified active Go library and local Studio sources instead of removed legacy Part tables')
    args = parser.parse_args()
    engine = create_engine(get_db_url())
    try:
        config = json.loads((root / 'backend/config/lego_design.json').read_text())
        if args.ldraw_root:
            # 旧 public Part 表已退出运行；从 Studio 原始名称确认真实矩形 Plate，再核对 Go 冻结文件哈希及占地。
            source_root = Path(args.ldraw_root)
            candidates = {}
            for path in (source_root / 'parts').glob('*.dat'):
                raw = path.read_bytes()
                first = raw.splitlines()[0].decode('utf-8', errors='replace') if raw else ''
                name = ' '.join(first.removeprefix('0 ').split())
                if re.fullmatch(r'Plate [0-9]+ x [0-9]+', name):
                    candidates[path.name.lower()] = (name, hashlib.sha256(raw).hexdigest())
            if not candidates or len(candidates) > 256:
                raise ValueError('Unexpected rectangular Plate source candidate count')
            with Session(engine) as session:
                colors = lego_design_colors(session, config)
                library = session.execute(text("SELECT id FROM component_repo.part_library_versions WHERE status='active' ORDER BY created_at DESC,id LIMIT 1")).scalar_one()
                # 候选 ID 来自上述有界源目录；按冻结库和 Part 主键读取，不扫描全部几何或 legacy 表。
                rows = session.execute(text("""SELECT p.ldraw_part_num,g.source_file_hash,g.logical_width_stud,g.logical_depth_stud,g.logical_height_plate
                    FROM component_repo.parts p JOIN component_repo.part_geometries g
                    ON g.part_library_version_id=p.part_library_version_id AND g.ldraw_part_num=p.ldraw_part_num
                    WHERE p.part_library_version_id=:library AND p.ldraw_part_num=ANY(:ids) AND g.geometry_status='ready'
                    ORDER BY p.ldraw_part_num"""), {'library': library, 'ids': list(candidates)}).all()
            parts = []
            for number, source_hash, width, depth, bbox_height in rows:
                name, expected_hash = candidates[number]
                if source_hash != expected_hash:
                    raise ValueError('Frozen source hash differs for ' + number)
                # Go 包围盒包含凸点，普通 Plate 总包围高为 1.5 plate；拼接逻辑层高仍为 1。
                if not float(width).is_integer() or not float(depth).is_integer() or not 1 <= width * depth <= 64:
                    continue
                if not 0.99 <= bbox_height <= 1.51:
                    continue
                parts.append(dict(ldrawPartNum=number,rebrickablePartNum=None,legoDesignId=None,name=name,partRole='plate',width=int(width),height=int(depth),logicalHeightPlate=1,area=int(width*depth)))
            metadata = dict(colors=colors,parts=parts,terrainParts=[])
            print('Verified active Part Library:',library)
        else:
            metadata = lego_design_metadata(engine, config)
        if not metadata['parts']:
            raise ValueError('No real Plate candidates; supply --ldraw-root for migrated Go library')
        metadata['terrainParts'] = []
        metadata['contentLocale'] = 'en-US'
        Path(args.output).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        print(f"Exported {len(metadata['colors'])} colors and {len(metadata['parts'])} Plate candidates")
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
