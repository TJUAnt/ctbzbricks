import { processPreviewPixels } from './previewProcessing';
import type { PixelArtPreprocessing } from './pixelArtApi';

/** 只执行本地预览计算；通过 transferable buffer 避免在主线程复制像素。 */
self.onmessage = (event: MessageEvent<{ id: number; data: ArrayBuffer; width: number; height: number; preprocessing: PixelArtPreprocessing }>) => {
 const { id, data, width, height, preprocessing } = event.data;
 const pixels = processPreviewPixels(new Uint8ClampedArray(data), width, height, preprocessing);
 self.postMessage({ id, data: pixels.buffer }, { transfer: [pixels.buffer] });
};
