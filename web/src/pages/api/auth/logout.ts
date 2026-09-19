import type { APIRoute } from 'astro';
import { clearCookie } from '../../../lib/session';

export const GET: APIRoute = async () => {
  return new Response(null, { status: 302, headers: { Location: '/', 'Set-Cookie': clearCookie() } });
};
