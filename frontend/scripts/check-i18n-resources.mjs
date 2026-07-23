import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const catalogPath = path.join(root, 'src/i18n/catalog.json');
const resourceRoot = path.join(root, 'src/i18n/resources');
const releaseNotesPath = path.resolve(root, '..', 'I18N_RELEASE_NOTES.md');
const catalog = JSON.parse(fs.readFileSync(catalogPath, 'utf8'));
const interpolationPattern = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)[^}]*\}\}/g;
const markupPattern = /<\/?[A-Za-z][^>]*>|javascript\s*:|\bon[A-Za-z]+\s*=/i;
const keyPattern = /^[A-Za-z][A-Za-z0-9_.-]*$/;

validateCatalog();
const source = loadLocale(catalog.sourceLocale);
for (const locale of catalog.productLocales) {
  const labelKey = catalog.localeLabelKeys[locale];
  if (!labelKey) fail(`Missing localeLabelKeys entry: ${locale}`);
  const [namespace, key] = labelKey.split(':', 2);
  if (!source[namespace] || !(key in source[namespace])) fail(`Unknown locale label key: ${labelKey}`);
}
const snapshots = [];
for (const locale of catalog.productLocales) {
  const resources = loadLocale(locale);
  assertSameSet(Object.keys(resources), Object.keys(source), `${locale} namespaces`);
  for (const namespace of Object.keys(source).sort()) {
    const expected = source[namespace];
    const actual = resources[namespace];
    assertSameSet(Object.keys(actual), Object.keys(expected), `${locale}:${namespace} keys`);
    for (const key of Object.keys(expected).sort()) {
      if (!keyPattern.test(key)) fail(`Invalid semantic key: ${namespace}:${key}`);
      validateValue(catalog.sourceLocale, namespace, key, expected[key]);
      validateValue(locale, namespace, key, actual[key]);
      assertSameSet(
        interpolationParameters(actual[key]),
        interpolationParameters(expected[key]),
        `${locale}:${namespace}:${key} interpolation parameters`,
      );
    }
    snapshots.push([locale, namespace, actual]);
  }
}

const contentHash = crypto
  .createHash('sha256')
  .update(JSON.stringify(snapshots))
  .digest('hex');

if (process.argv.includes('--print-hash')) {
  process.stdout.write(`${contentHash}\n`);
  process.exit(0);
}
if (catalog.contentHash !== contentHash) {
  fail(`Catalog contentHash mismatch. Expected ${contentHash}, found ${catalog.contentHash}`);
}
const releaseNotes = fs.existsSync(releaseNotesPath) ? fs.readFileSync(releaseNotesPath, 'utf8') : '';
if (!releaseNotes.includes(catalog.catalogVersion)) {
  fail(`Release notes do not contain catalog version ${catalog.catalogVersion}`);
}
process.stdout.write(
  `Validated ${catalog.productLocales.length} locales, ${Object.keys(source).length} namespaces, catalog ${catalog.catalogVersion}.\n`,
);

function validateCatalog() {
  if (!/^frontend-\d{4}\.\d{2}\.\d{2}\.\d+$/.test(catalog.catalogVersion)) {
    fail(`Invalid catalogVersion: ${catalog.catalogVersion}`);
  }
  if (!catalog.productLocales.includes(catalog.sourceLocale)) fail('sourceLocale must be a product locale');
  if (!catalog.productLocales.includes(catalog.defaultLocale)) fail('defaultLocale must be a product locale');
  assertSameSet(catalog.productLocales, [...new Set(catalog.productLocales)], 'product locale uniqueness');
  for (const locale of catalog.validationLocales) {
    if (catalog.productLocales.includes(locale)) fail(`Validation locale cannot be a product locale: ${locale}`);
  }
}

function loadLocale(locale) {
  const directory = path.join(resourceRoot, locale);
  if (!fs.existsSync(directory)) fail(`Missing locale resource directory: ${locale}`);
  return Object.fromEntries(
    fs.readdirSync(directory)
      .filter((file) => file.endsWith('.json'))
      .sort()
      .map((file) => {
        const namespace = path.basename(file, '.json');
        return [namespace, JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8'))];
      }),
  );
}

function validateValue(locale, namespace, key, value) {
  if (typeof value !== 'string') fail(`Translation must be a string: ${locale}:${namespace}:${key}`);
  if (markupPattern.test(value)) fail(`Unsafe or unsupported HTML in ${locale}:${namespace}:${key}`);
}

function interpolationParameters(value) {
  return [...new Set([...value.matchAll(interpolationPattern)].map((match) => match[1]))].sort();
}

function assertSameSet(actual, expected, label) {
  const left = [...actual].sort();
  const right = [...expected].sort();
  if (JSON.stringify(left) !== JSON.stringify(right)) {
    fail(`${label} differ:\nactual=${JSON.stringify(left)}\nexpected=${JSON.stringify(right)}`);
  }
}

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}
