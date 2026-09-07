// 只读对比相同预览算法使用普通数字配置与旧 Proxy 配置的成本，不启动浏览器或访问用户图片。
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(path.join(root, 'src/pixelArt/pixelArtConfig.json'), 'utf8'));
const source = fs.readFileSync(path.join(root, 'src/pixelArt/previewProcessing.ts'), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
function wrap(value, trail = [], cache = new WeakMap()) {
 if (cache.has(value)) return cache.get(value);
 const proxy = new Proxy(value, { get(target, property, receiver) {
  const child = Reflect.get(target, property, receiver);
  const segment = child && typeof child === 'object' ? (child.id ?? child.value ?? String(property)) : String(property);
  const childPath = [...trail, segment];
  if (child && typeof child === 'object') return wrap(child, childPath, cache);
  return child;
 }}); cache.set(value, proxy); return proxy;
}
const input = new Uint8ClampedArray(320 * 240 * 4);
for (let i = 0; i < input.length; i++) input[i] = (i * 17) % 256;
const settings = { brightness: 1, contrast: 1, saturation: 1, sharpness: 1.4, localContrast: 0.6, preserveLightDetails: true };
const results = [];
for (const [name, cfg] of [['plain', config], ['legacyProxy', wrap(config)]]) {
 const module = { exports: {} };
 new Function('require', 'module', 'exports', js)(() => cfg, module, module.exports);
 const start = performance.now();
 const pixels = module.exports.processPreviewPixels(input.slice(), 320, 240, settings);
 results.push({ name, milliseconds: +(performance.now() - start).toFixed(2), pixels });
}
if (!Buffer.from(results[0].pixels).equals(Buffer.from(results[1].pixels))) throw new Error('Preview output changed');
console.log(JSON.stringify(results.map(({ name, milliseconds }) => ({ name, milliseconds })), null, 2));
