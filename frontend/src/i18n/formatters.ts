import { resolvedLocale, type SupportedLocale } from './index';

export function intlLocale(locale: SupportedLocale = resolvedLocale()): string {
  return locale === 'en-XA' ? 'en-US' : locale;
}

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
  locale: SupportedLocale = resolvedLocale(),
): string {
  return new Intl.NumberFormat(intlLocale(locale), options).format(value);
}

export function formatDateTime(
  value: Date | number | string,
  options?: Intl.DateTimeFormatOptions,
  locale: SupportedLocale = resolvedLocale(),
): string {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat(intlLocale(locale), options).format(date);
}

export function formatRelativeTime(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  options?: Intl.RelativeTimeFormatOptions,
  locale: SupportedLocale = resolvedLocale(),
): string {
  return new Intl.RelativeTimeFormat(intlLocale(locale), options).format(value, unit);
}
