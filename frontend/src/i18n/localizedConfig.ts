import { translateDynamic, type TranslationKey } from './index';

const leafNames = /(label|title|subtitle|description|placeholder|message|action|emptyValue|nullValue|arrayValue|objectValue)$/i;
const translationKeyPattern = /^[a-z][A-Za-z0-9]*:[A-Za-z0-9_.-]+$/;

function isDisplayPath(path: string[]): boolean {
  const normalized = path.map((segment) => segment.toLowerCase());
  const leaf = normalized[normalized.length - 1] ?? '';
  return normalized.includes('texts')
    || normalized.includes('errors')
    || normalized.includes('units')
    || normalized.includes('features')
    || leafNames.test(leaf)
    || leaf === 'defaultprojectname';
}

function pathSegment(value: unknown, fallback: PropertyKey): string {
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    if (typeof record.id === 'string') return record.id;
    if (typeof record.value === 'string') return record.value;
  }
  return String(fallback);
}

export function localizedConfig<T extends object>(source: T): T {
  const cache = new WeakMap<object, object>();

  const wrap = (value: object, path: string[]): object => {
    const cached = cache.get(value);
    if (cached) return cached;

    const proxy = new Proxy(value, {
      get(target, property, receiver) {
        const child = Reflect.get(target, property, receiver) as unknown;
        const childPath = [...path, pathSegment(child, property)];
        if (typeof child === 'string' && isDisplayPath(childPath)) {
          if (!translationKeyPattern.test(child)) {
            throw new Error(`Display config must contain an i18n key at ${childPath.join('.')}`);
          }
          return translateDynamic(child as TranslationKey);
        }
        if (child && typeof child === 'object') {
          return wrap(child, childPath);
        }
        return child;
      },
    });
    cache.set(value, proxy);
    return proxy;
  };

  return wrap(source, []) as T;
}
