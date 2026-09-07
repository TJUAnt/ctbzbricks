import rawConfig from './pixelArtConfig.json';
import type { PixelArtPreprocessing } from './pixelArtApi';

// 数字算法配置不经过本地化 Proxy，像素循环不执行路径分配或翻译判断。
const pixelArtConfig = rawConfig;
const clamp = (value: number, minimum: number, maximum: number) => Math.min(maximum, Math.max(minimum, value));

/** 在 Web Worker 中处理预览缓冲区；不修改上传原图和服务端算法输入。 */
export function processPreviewPixels(data: Uint8ClampedArray, width: number, height: number, preprocessing: PixelArtPreprocessing): Uint8ClampedArray {
 if (preprocessing.sharpness === 1 && preprocessing.localContrast === 0) return data;
 const source = new Uint8ClampedArray(data);
 for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) applyPreviewPixel(source, data, x, y, width, height, preprocessing);
 return data;
}
function applyPreviewPixel(
  source: Uint8ClampedArray,
  target: Uint8ClampedArray,
  x: number,
  y: number,
  width: number,
  height: number,
  preprocessing: PixelArtPreprocessing,
): void {
  const pixelIndex = previewPixelIndex(x, y, width, height);
  const luminance = previewLuminance(source, pixelIndex);
  const neighborLuminance = previewNeighborLuminance(source, x, y, width, height);
  for (
    let channel = pixelArtConfig.previewProcessing.redChannelIndex;
    channel <= pixelArtConfig.previewProcessing.blueChannelIndex;
    channel += pixelArtConfig.grid.dimensionStep
  ) {
    const sharpened = previewSharpenedChannel(source, x, y, width, height, channel, preprocessing);
    const lightDetailScale = preprocessing.preserveLightDetails
      ? (pixelArtConfig.previewProcessing.rgbMaximum - luminance) / pixelArtConfig.previewProcessing.rgbMaximum
      : pixelArtConfig.previewProcessing.identityValue;
    target[pixelIndex + channel] = clamp(
      sharpened + (luminance - neighborLuminance) * preprocessing.localContrast * lightDetailScale,
      pixelArtConfig.previewProcessing.rgbMinimum,
      pixelArtConfig.previewProcessing.rgbMaximum,
    );
  }
}

function previewSharpenedChannel(
  source: Uint8ClampedArray,
  x: number,
  y: number,
  width: number,
  height: number,
  channel: number,
  preprocessing: PixelArtPreprocessing,
): number {
  const center = previewChannel(source, x, y, width, height, channel);
  const edge =
    center * pixelArtConfig.previewProcessing.sharpnessCenterWeight
    - previewChannel(source, x - pixelArtConfig.grid.dimensionStep, y, width, height, channel)
    - previewChannel(source, x + pixelArtConfig.grid.dimensionStep, y, width, height, channel)
    - previewChannel(source, x, y - pixelArtConfig.grid.dimensionStep, width, height, channel)
    - previewChannel(source, x, y + pixelArtConfig.grid.dimensionStep, width, height, channel);
  return center + ((preprocessing.sharpness - pixelArtConfig.previewProcessing.identityValue) * edge) / pixelArtConfig.previewProcessing.neighborCount;
}

function previewNeighborLuminance(
  source: Uint8ClampedArray,
  x: number,
  y: number,
  width: number,
  height: number,
): number {
  return (
    previewLuminance(source, previewPixelIndex(x - pixelArtConfig.grid.dimensionStep, y, width, height))
    + previewLuminance(source, previewPixelIndex(x + pixelArtConfig.grid.dimensionStep, y, width, height))
    + previewLuminance(source, previewPixelIndex(x, y - pixelArtConfig.grid.dimensionStep, width, height))
    + previewLuminance(source, previewPixelIndex(x, y + pixelArtConfig.grid.dimensionStep, width, height))
  ) / pixelArtConfig.previewProcessing.neighborCount;
}

function previewChannel(
  source: Uint8ClampedArray,
  x: number,
  y: number,
  width: number,
  height: number,
  channel: number,
): number {
  return source[previewPixelIndex(x, y, width, height) + channel];
}

function previewLuminance(source: Uint8ClampedArray, index: number): number {
  return (
    source[index + pixelArtConfig.previewProcessing.redChannelIndex] * pixelArtConfig.previewProcessing.luminanceRedWeight
    + source[index + pixelArtConfig.previewProcessing.greenChannelIndex] * pixelArtConfig.previewProcessing.luminanceGreenWeight
    + source[index + pixelArtConfig.previewProcessing.blueChannelIndex] * pixelArtConfig.previewProcessing.luminanceBlueWeight
  );
}

function previewPixelIndex(x: number, y: number, width: number, height: number): number {
  const boundedX = clamp(x, pixelArtConfig.emptyFileCount, width - pixelArtConfig.grid.dimensionStep);
  const boundedY = clamp(y, pixelArtConfig.emptyFileCount, height - pixelArtConfig.grid.dimensionStep);
  return (boundedY * width + boundedX) * pixelArtConfig.previewProcessing.channelStride;
}

