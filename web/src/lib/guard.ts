import { getSessionUser } from './session';
import { discordApi, canManageGuild, botGuildIds, refreshSession } from './discord';
import { guildExists } from './mongo';

const LOGIN = '/api/auth/login';

// Bot owner: full website access on every server, even without Manage Server.
const OWNER_ID = '600411237561663498';

export function isOwner(session: any): boolean {
  return String(session?.id ?? '') === OWNER_ID;
}

export interface Authed {
  user: any;
  /** Non-null when the token was refreshed: re-save the session cookie. */
  refreshed: any | null;
}

type GuardResult = { ok: Authed } | { err: Response };

function loginRedirect(): Response {
  // NB: native Response.redirect() rejects relative URLs — build manually.
  return new Response(null, { status: 302, headers: { Location: LOGIN } });
}

/** Fetch the caller's guilds, refreshing the Discord token once if expired.
 *  One round-trip on the happy path (the fetch itself validates the token). */
async function guildsWithRefresh(
  session: any,
): Promise<{ guilds: any[]; session: any; refreshed: any | null } | null> {
  try {
    const guilds = await discordApi('/users/@me/guilds', session.access_token);
    return { guilds, session, refreshed: null };
  } catch {
    const next = await refreshSession(session);
    if (!next) return null;
    try {
      const guilds = await discordApi('/users/@me/guilds', next.access_token);
      return { guilds, session: next, refreshed: next };
    } catch {
      return null;
    }
  }
}

/** Require the caller to be a manager (admin) of the given guild with the bot present. */
export async function requireManager(guildId: string, request: Request): Promise<GuardResult> {
  const session = getSessionUser(request);
  if (!session?.access_token) return { err: loginRedirect() };
  const loaded = await guildsWithRefresh(session);
  if (!loaded) return { err: loginRedirect() };
  const { guilds, session: s, refreshed } = loaded;
  const g = guilds.find((x: any) => String(x.id) === String(guildId));
  if (!g || (!canManageGuild(g) && !isOwner(session))) {
    return { err: new Response('Forbidden: you must be a server admin.', { status: 403 }) };
  }
  const botIds = await botGuildIds();
  const hasBot = botIds ? botIds.has(String(guildId)) : await guildExists(String(guildId));
  if (!hasBot) {
    return { err: new Response('Bot is not in this server.', { status: 403 }) };
  }
  return { ok: { user: s, refreshed } };
}

/** Guilds the caller can manage that also contain the bot (for the dashboard). */
export async function manageableBotGuilds(
  request: Request,
): Promise<{ ok: { user: any; guilds: any[]; refreshed: any | null } } | { err: Response }> {
  const session = getSessionUser(request);
  if (!session?.access_token) return { err: loginRedirect() };
  const loaded = await guildsWithRefresh(session);
  if (!loaded) return { err: loginRedirect() };
  const { guilds: all, session: s, refreshed } = loaded;
  // Owner sees every server; everyone else only ones they can manage.
  const manageable = isOwner(s) ? all : all.filter(canManageGuild);
  const botIds = await botGuildIds();
  let guilds: any[];
  if (botIds) {
    guilds = manageable.filter((g: any) => botIds.has(String(g.id)));
  } else {
    guilds = [];
    for (const g of manageable) {
      if (await guildExists(String(g.id))) guilds.push(g);
    }
  }
  return { ok: { user: s, guilds, refreshed } };
}
