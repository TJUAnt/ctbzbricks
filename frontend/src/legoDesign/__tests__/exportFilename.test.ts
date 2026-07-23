import { describe, expect, it } from 'vitest';
import { responseFileName } from '../legoDesignApi';

describe('localized export filenames', () => {
  it('prefers the RFC 5987 UTF-8 filename', () => {
    const response = new Response('', {
      headers: {
        'Content-Disposition': [
          'attachment; filename="lego-design-1.json"',
          "filename*=UTF-8''%E4%B9%90%E9%AB%98%E8%AE%BE%E8%AE%A1-1.json",
        ].join('; '),
      },
    });

    expect(responseFileName(response, 'fallback.json')).toBe('乐高设计-1.json');
  });

  it('falls back safely when UTF-8 encoding is invalid', () => {
    const response = new Response('', {
      headers: { 'Content-Disposition': "attachment; filename*=UTF-8''%E0%A4%A" },
    });

    expect(responseFileName(response, 'fallback.json')).toBe('fallback.json');
  });
});
