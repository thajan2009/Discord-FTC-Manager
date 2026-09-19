import './env';

// Normalized site root: no trailing slash, so the callback URL is always
// exactly <root>/api/auth/callback (Discord rejects even a double slash).
export function webBase(): string {
  return (process.env.PUBLIC_WEB_URL ?? '').replace(/\/+$/, '');
}

export function callbackUrl(): string {
  return `${webBase()}/api/auth/callback`;
}

export function loginUrl(): string {
  const id = process.env.DISCORD_CLIENT_ID!;
  const params = new URLSearchParams({
    client_id: id, redirect_uri: callbackUrl(), response_type: 'code', scope: 'identify guilds',
  });
  return `https://discord.com/api/oauth2/authorize?${params}`;
}

export async function exchangeCode(code: string) {
  const res = await fetch('https://discord.com/api/oauth2/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: process.env.DISCORD_CLIENT_ID!,
      client_secret: process.env.DISCORD_CLIENT_SECRET!,
      grant_type: 'authorization_code',
      code,
      redirect_uri: callbackUrl(),
    }),
  });
  if (!res.ok) throw new Error('token exchange failed');
  return res.json();
}

export async function discordApi(path: string, token: string) {
  const res = await fetch(`https://discord.com/api${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`discord api ${path} failed`);
  return res.json();
}

// Exchange a refresh token for a new session. Null when revoked/expired.
export async function refreshSession(session: any): Promise<any | null> {
  try {
    if (!session?.refresh_token) return null;
    const res = await fetch('https://discord.com/api/oauth2/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: process.env.DISCORD_CLIENT_ID!,
        client_secret: process.env.DISCORD_CLIENT_SECRET!,
        grant_type: 'refresh_token',
        refresh_token: session.refresh_token,
      }),
    });
    if (!res.ok) return null;
    const tok: any = await res.json();
    return {
      ...session,
      access_token: tok.access_token,
      refresh_token: tok.refresh_token ?? session.refresh_token,
    };
  } catch {
    return null;
  }
}

export function canManageGuild(g: any): boolean {
  const perms = BigInt(g.permissions ?? 0);
  // ADMINISTRATOR=0x8, MANAGE_GUILD=0x20
  return (perms & 0x8n) === 0x8n || (perms & 0x20n) === 0x20n;
}

// Guild IDs the bot is currently in (via bot token), cached briefly so every
// dashboard/guild load doesn't cost a Discord round-trip. Null if
// DISCORD_TOKEN missing/unreachable — caller falls back to Mongo.
let _botGuildCache: { at: number; ids: Set<string> } | null = null;
const BOT_GUILDS_TTL = 120_000;

export async function botGuildIds(): Promise<Set<string> | null> {
  if (_botGuildCache && Date.now() - _botGuildCache.at < BOT_GUILDS_TTL) {
    return _botGuildCache.ids;
  }
  const token = process.env.DISCORD_TOKEN;
  if (!token) return null;
  try {
    const res = await fetch('https://discord.com/api/users/@me/guilds', {
      headers: { Authorization: `Bot ${token}` },
    });
    if (!res.ok) return _botGuildCache?.ids ?? null;
    const arr: any[] = await res.json();
    _botGuildCache = { at: Date.now(), ids: new Set(arr.map((g) => String(g.id))) };
    return _botGuildCache.ids;
  } catch {
    return _botGuildCache?.ids ?? null;
  }
}
