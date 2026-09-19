import type { APIRoute } from 'astro';
import { col } from '../../../../lib/mongo';
import { requireManager } from '../../../../lib/guard';
import { sessionCookie } from '../../../../lib/session';

function uid() { return Math.random().toString(36).slice(2, 10); }

function back(id: string, cookie: string | null, err?: string) {
  const headers: Record<string, string> = {
    Location: err ? `/guild/${id}?error=${err}` : `/guild/${id}`,
  };
  if (cookie) headers['Set-Cookie'] = sessionCookie(cookie);
  return new Response(null, { status: 302, headers });
}

// POST /api/guilds/:id/teams  form: name, aliases
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const form = await request.formData();
  const name = String(form.get('name') ?? '').trim();
  const aliases = String(form.get('aliases') ?? '').split(',').map(s => s.trim()).filter(Boolean);
  if (!name) return back(id, gate.ok.refreshed, 'name-required');
  const c = await col();
  const doc: any = await c.findOne({ _type: 'guild', guild_id: id });
  const teams = doc?.teams ?? [];
  if (teams.length >= 3) return back(id, gate.ok.refreshed, 'max-teams');
  const taken = new Set<string>();
  for (const t of teams) {
    taken.add(String(t.name ?? '').toLowerCase());
    for (const a of (t.aliases ?? [])) taken.add(String(a).toLowerCase());
  }
  if (taken.has(name.toLowerCase())) return back(id, gate.ok.refreshed, 'name-taken');
  for (const a of aliases) {
    if (taken.has(a.toLowerCase())) return back(id, gate.ok.refreshed, 'alias-taken');
  }
  // Atomic append (no read-modify-write): concurrent adds can never wipe each other.
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $push: { teams: { id: uid(), name, aliases } } as any },
    { upsert: true },
  );
  return back(id, gate.ok.refreshed);
};
