import type { APIRoute } from 'astro';
import { loginUrl } from '../../../lib/discord';

export const GET: APIRoute = async () => {
  const id = process.env.DISCORD_CLIENT_ID;
  const web = process.env.PUBLIC_WEB_URL;
  if (!id || !web) {
    return new Response(
      'Server misconfigured: DISCORD_CLIENT_ID and PUBLIC_WEB_URL must be set. ' +
      'Local dev: put them in repo-root .env (one KEY=VALUE per line) and restart. ' +
      'Check /api/auth/status for which vars are missing.',
      { status: 500 },
    );
  }
  return Response.redirect(loginUrl(), 302);
};
