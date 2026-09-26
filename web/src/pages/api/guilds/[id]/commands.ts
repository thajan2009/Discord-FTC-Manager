import type { APIRoute } from 'astro';
import { col } from '../../../../lib/mongo';
import { requireManager } from '../../../../lib/guard';
import { sessionCookie } from '../../../../lib/session';

function back(id: string, cookie: string | null, err?: string) {
  const headers: Record<string, string> = {
    Location: err ? `/guild/${id}?error=${err}` : `/guild/${id}`,
  };
  if (cookie) headers['Set-Cookie'] = sessionCookie(cookie);
  return new Response(null, { status: 302, headers });
}

// POST /api/guilds/:id/commands  form: trigger, response
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const form = await request.formData();
  const trigger = String(form.get('trigger') ?? '').trim().toLowerCase().replace(/^!/, '');
  const response = String(form.get('response') ?? '').trim();
  const in_ftchelp = String(form.get('in_ftchelp') ?? '') === 'on';
  if (!trigger || !response) return back(id, gate.ok.refreshed, 'command-required');
  if (/\s/.test(trigger)) return back(id, gate.ok.refreshed, 'trigger-spaces');
  const c = await col();
  // Atomic replace-by-trigger (no read-modify-write): concurrent adds can't wipe each other.
  await c.updateOne({ _type: 'guild', guild_id: id }, { $pull: { commands: { trigger } } as any });
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $push: { commands: { trigger, response, in_ftchelp } } as any },
    { upsert: true },
  );
  return back(id, gate.ok.refreshed);
};
