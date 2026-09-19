import type { APIRoute } from 'astro';
import { exchangeCode, discordApi } from '../../../lib/discord';
import { sessionCookie } from '../../../lib/session';

export const GET: APIRoute = async ({ request }) => {
  const url = new URL(request.url);
  const code = url.searchParams.get('code');
  if (!code) return new Response('missing code', { status: 400 });
  const tok: any = await exchangeCode(code);
  const me: any = await discordApi('/users/@me', tok.access_token);
  const session = { id: me.id, username: me.username, access_token: tok.access_token, refresh_token: tok.refresh_token };
  return new Response(null, {
    status: 302,
    headers: { Location: '/dashboard', 'Set-Cookie': sessionCookie(session) },
  });
};
