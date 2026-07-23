import { resolvedLocale } from '../i18n';

export type TaskContext = {
  locale: string;
  timezone: string;
};

export function currentTaskContext(): TaskContext {
  const locale = resolvedLocale();
  return {
    locale: locale === 'en-XA' ? 'en-US' : locale,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  };
}
