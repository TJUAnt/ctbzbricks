import catalog from './catalog.json';

export type I18nEvent = {
  kind: 'unknown_key' | 'unknown_api_code' | 'locale_fallback';
  locale: string;
  namespace: string;
  code: string;
};

const sentEvents = new Set<string>();

export function recordI18nEvent(event: I18nEvent): void {
  const fingerprint = JSON.stringify(event);
  if (sentEvents.has(fingerprint)) return;
  sentEvents.add(fingerprint);
  if (typeof fetch !== 'function') return;
  void fetch(catalog.telemetryEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: fingerprint,
    keepalive: true,
  }).catch(() => undefined);
}

export function resetI18nTelemetryForTests(): void {
  sentEvents.clear();
}
