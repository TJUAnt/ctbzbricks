import i18n from '../i18n';
import { recordI18nEvent } from '../i18n/telemetry';

export type ApiErrorParams = Record<string, unknown>;
export type StructuredMessage = { code: string; params: ApiErrorParams };

type ApiErrorPayload = {
  error: {
    code: string;
    params: ApiErrorParams;
    traceId: string;
  };
};

export class ApiError extends Error {
  readonly code: string;
  readonly params: ApiErrorParams;
  readonly traceId: string | null;
  readonly status: number;

  constructor(
    code: string,
    params: ApiErrorParams = {},
    traceId: string | null = null,
    status = 0,
    cause?: unknown,
  ) {
    super('');
    this.name = 'ApiError';
    this.code = code;
    this.params = params;
    this.traceId = traceId;
    this.status = status;
    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
    Object.defineProperty(this, 'message', {
      configurable: true,
      enumerable: false,
      get: () => localizeApiError(this),
    });
  }
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  fallbackCode = 'request.failed',
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (cause) {
    throw new ApiError('common.network_error', {}, null, 0, cause);
  }
  return ensureApiResponse(response, fallbackCode);
}

export async function requestJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
  fallbackCode?: string,
): Promise<T> {
  const response = await apiFetch(input, init, fallbackCode);
  try {
    return (await response.json()) as T;
  } catch (cause) {
    throw new ApiError(
      'common.invalid_response',
      {},
      response.headers.get('X-Trace-Id'),
      response.status,
      cause,
    );
  }
}

export async function ensureApiResponse(
  response: Response,
  fallbackCode = 'request.failed',
): Promise<Response> {
  if (response.ok) return response;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  throw apiErrorFromPayload(
    payload,
    response.status,
    response.headers.get('X-Trace-Id'),
    fallbackCode,
  );
}

export function apiErrorFromPayload(
  payload: unknown,
  status: number,
  traceId: string | null = null,
  fallbackCode = 'request.failed',
): ApiError {
  if (isApiErrorPayload(payload)) {
    return new ApiError(
      payload.error.code,
      payload.error.params,
      payload.error.traceId,
      status,
    );
  }
  return new ApiError(fallbackCode, {}, traceId, status);
}

export function localizeApiError(error: ApiError): string {
  const key = `errors:${error.code}`;
  if (i18n.exists(key)) {
    return i18n.t(key, error.params);
  }
  console.error('Unknown API error code', {
    code: error.code,
    traceId: error.traceId,
  });
  recordI18nEvent({
    kind: 'unknown_api_code',
    locale: i18n.resolvedLanguage ?? i18n.language,
    namespace: 'errors',
    code: error.code,
  });
  return i18n.t('errors:common.unknown');
}

export function errorMessage(error: unknown, fallbackCode = 'common.unknown'): string {
  if (error instanceof ApiError) return localizeApiError(error);
  return i18n.t(`errors:${fallbackCode}`);
}

export function localizeStructuredMessage(
  value: StructuredMessage | null,
  namespace: 'errors' | 'tasks' = 'errors',
): string {
  if (!value) return '';
  const key = `${namespace}:${value.code}`;
  if (i18n.exists(key)) return i18n.t(key, value.params);
  console.error('Unknown structured message code', { code: value.code, namespace });
  recordI18nEvent({
    kind: 'unknown_api_code',
    locale: i18n.resolvedLanguage ?? i18n.language,
    namespace,
    code: value.code,
  });
  return i18n.t('errors:common.unknown');
}

function isApiErrorPayload(payload: unknown): payload is ApiErrorPayload {
  if (!isRecord(payload) || !isRecord(payload.error)) return false;
  const { code, params, traceId } = payload.error;
  return typeof code === 'string' && isRecord(params) && typeof traceId === 'string';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
