"""一次性迁移证据生成器：只在验证时调用旧 Python 算法，不参与 Go 运行。"""
import json,sys
from pathlib import Path
from io import BytesIO
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'backend'))
from PIL import Image
from src.api.schemas.pixel_art import PixelArtGenerateSettings
from archive.pixel2d.quantization import create_pixel_art_asset
from src.services.lego_design_service import create_lego_design_result,export_lego_design_ldraw,export_lego_design_plan
out=root/'backend-go/internal/pixel2d/testdata';out.mkdir(exist_ok=True)
config=json.loads((root/'backend/config/pixel_art.json').read_text())
cases=[]
for mode in ['photo_illustration','logo_text','side_mixed_plate_brick_pixel']:
 for pattern in ['blocks','gradient','alpha','preprocessing','enhancement','uneven','large_contrast']:
  size=32 if pattern=='large_contrast' else (13 if pattern=='uneven' else 12)
  img=Image.new('RGBA',(size,size))
  for y in range(size):
   for x in range(size):
    color=((255,0,0,255) if x<6 else (0,0,255,255)) if pattern=='blocks' else (x*20,y*20,(x+y)*10,128 if pattern=='alpha' else 255)
    if pattern=='large_contrast': color=(x*7,y*7,(x+y)*3,255)
    img.putpixel((x,y),color)
  name=mode+'-'+pattern;buf=BytesIO();img.save(buf,format='PNG');(out/(name+'.png')).write_bytes(buf.getvalue())
  settings=dict(algorithm=mode,gridWidth=4,gridHeight=4,colorCount=4,crop=dict(x=0,y=0,width=12,height=12),preprocessing=dict(brightness=1,contrast=1,saturation=1,sharpness=1,localContrast=0,preserveLightDetails=True))
  if pattern in ['preprocessing','enhancement']: settings['preprocessing'].update(brightness=1.15,contrast=1.3,saturation=.8,sharpness=1.4,localContrast=.6)
  if pattern=='large_contrast': settings['crop'].update(width=32,height=32);settings['preprocessing']['localContrast']=.6
  if pattern=='enhancement': settings['preprocessing']['localContrast']=0
  if pattern=='uneven': settings['crop'].update(width=13,height=13);settings.update(gridWidth=5,gridHeight=7)
  asset=create_pixel_art_asset(config,buf.getvalue(),name+'.png','image/png',PixelArtGenerateSettings(**settings));asset.pop('previewBytes');cases.append(dict(name=name,settings=settings,expected=asset))
(out/'quantization.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
# 目录来自测试固定的标准 Plate ID，不作为部署时的生产元数据。
parts=[dict(ldrawPartNum=id,rebrickablePartNum=None,legoDesignId=None,name=f'Plate {w} x {h}',partRole='plate',width=w,height=h,logicalHeightPlate=1,area=w*h) for id,w,h in [('3024.dat',1,1),('3023.dat',1,2),('3022.dat',2,2),('3020.dat',2,4)]]
metadata=dict(colors=[dict(id=4,name='Red',rgb='#FF0000',isTrans=False),dict(id=1,name='Blue',rgb='#0000FF',isTrans=False)],parts=parts,terrainParts=[])
project=dict(gridWidth=8,gridHeight=8,palette=[dict(rgb='#FF0000'),dict(rgb='#0000FF')],pixels=[dict(x=x,y=y,rgb='#FF0000' if x<4 else '#0000FF') for y in range(8) for x in range(8)])
cfg=json.loads((root/'backend/config/lego_design.json').read_text());design=create_lego_design_result(project,metadata,cfg,lambda p:None)
(out/'design.json').write_text(json.dumps(dict(project=project,metadata=metadata,expected=design),indent=2)+'\n')
for locale in ['zh-CN','en-US']:
 for base in [False,True]:
  ctx=dict(locale=locale,timezone='Asia/Shanghai',catalogVersion='brickbuilder-export-2026.07.18.1')
  (out/f'{locale}-{str(base).lower()}.ldr').write_text(export_lego_design_ldraw(design,metadata,base,cfg,ctx))
  (out/f'{locale}-{str(base).lower()}.json').write_text(json.dumps(export_lego_design_plan(design,metadata,base,cfg,ctx),ensure_ascii=False,indent=2)+'\n')
