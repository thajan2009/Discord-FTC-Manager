import * as cookie from 'cookie';

const NAME = 'ftc_session';

export function getSessionUser(req: Request): any | null {
  const header = req.headers.get('cookie') ?? '';
  const cookies = cookie.parse(header);
  const raw = cookies[NAME];
  if (!raw) return null;
  try {
    return JSON.parse(Buffer.from(raw, 'base64').toString('utf8'));
  } catch {
    return null;
  }
}

export const SESSION_NAME = 'ftc_session';
export const SESSION_MAX_AGE = 60 * 60 * 24 * 7;

// Raw cookie value (base64 JSON) for Astro.cookies.set().
export function sessionValue(user: any): string {
  return Buffer.from(JSON.stringify(user)).toString('base64');
}

export function sessionCookie(user: any): string {
  return cookie.serialize(SESSION_NAME, sessionValue(user), {
    httpOnly: true, secure: true, sameSite: 'lax', path: '/', maxAge: SESSION_MAX_AGE,
  });
}

export function clearCookie(): string {
  return cookie.serialize(NAME, '', { httpOnly: true, path: '/', maxAge: 0 });
}
