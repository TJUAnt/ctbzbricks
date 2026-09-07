"""2D 运行边界：Python 不再暴露图片处理或进程内拼接任务入口。"""
from pathlib import Path


def test_pixel_2d_public_runtime_has_cut_over_to_go():
    root = Path(__file__).resolve().parents[2]
    main = (root / 'backend/src/api/main.py').read_text()
    assert 'create_pixel_art_router' not in main
    assert 'create_lego_design_router' not in main
    assert 'lego_design_jobs_lock' not in main
    assert not (root / 'backend/src/api/routes/pixel_art.py').exists()
    assert not (root / 'backend/src/api/routes/lego_design.py').exists()
    for path in ['pixelArt/pixelArtConfig.json', 'legoDesign/legoDesignConfig.json']:
        config = (root / 'frontend/src' / path).read_text()
        assert '/api/pixel-art/' not in config
        assert '/api/lego/design/' not in config
