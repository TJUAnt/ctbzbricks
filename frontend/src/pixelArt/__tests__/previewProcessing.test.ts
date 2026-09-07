import { expect, it } from 'vitest';
import { processPreviewPixels } from '../previewProcessing';

const settings = { brightness: 1, contrast: 1, saturation: 1, sharpness: 1, localContrast: 0, preserveLightDetails: true };

it('无邻域增强时不分配副本且保留透明像素', () => {
  const data = new Uint8ClampedArray([12, 34, 56, 0, 100, 120, 140, 128]);
  expect(processPreviewPixels(data, 2, 1, settings)).toBe(data);
  expect([...data]).toEqual([12, 34, 56, 0, 100, 120, 140, 128]);
});

it('锐化读取原始邻域，边缘钳位且不改变 alpha', () => {
  const data = new Uint8ClampedArray([50, 50, 50, 128, 150, 150, 150, 255]);
  expect([...processPreviewPixels(data, 2, 1, { ...settings, sharpness: 1.4 })]).toEqual([40, 40, 40, 128, 160, 160, 160, 255]);
});

it('单像素局部对比度不会越界或改变均匀颜色', () => {
  const data = new Uint8ClampedArray([100, 120, 140, 200]);
  expect([...processPreviewPixels(data, 1, 1, { ...settings, sharpness: 1.8, localContrast: 1 })]).toEqual([100, 120, 140, 200]);
});
