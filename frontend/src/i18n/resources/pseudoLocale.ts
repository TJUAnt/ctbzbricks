const accentMap: Record<string, string> = {
  a: 'á', A: 'Á', e: 'é', E: 'É', i: 'í', I: 'Í', o: 'ó', O: 'Ó',
  u: 'ú', U: 'Ú', y: 'ý', Y: 'Ý', c: 'ç', C: 'Ç', n: 'ñ', N: 'Ñ',
};

const protectedTokenPattern = /(\{\{[^}]+\}\}|<[^>]+>|%\d*\$?[a-zA-Z]|\.[a-zA-Z0-9]+)/g;

export function pseudoLocalizeText(value: string): string {
  const transformed = value
    .split(protectedTokenPattern)
    .map((segment) => {
      if (protectedTokenPattern.test(segment)) {
        protectedTokenPattern.lastIndex = 0;
        return segment;
      }
      protectedTokenPattern.lastIndex = 0;
      return [...segment].map((character) => accentMap[character] ?? character).join('');
    })
    .join('');
  const expansion = '~'.repeat(Math.max(2, Math.ceil(value.length * 0.3)));
  return `[!! ${transformed} ${expansion} !!]`;
}

export function pseudoLocalizeNamespace<T extends Record<string, string>>(source: T): T {
  return Object.fromEntries(
    Object.entries(source).map(([key, value]) => [key, pseudoLocalizeText(value)]),
  ) as T;
}

export function pseudoLocalizeResources<T extends Record<string, Record<string, string>>>(source: T): T {
  return Object.fromEntries(
    Object.entries(source).map(([namespace, values]) => [namespace, pseudoLocalizeNamespace(values)]),
  ) as T;
}
