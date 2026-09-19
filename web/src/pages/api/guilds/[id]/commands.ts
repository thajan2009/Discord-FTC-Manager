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
  if (!trigger || !response) return back(id, gate.ok.refreshed, 'command-required');
  if (/\s/.test(trigger)) return back(id, gate.ok.refreshed, 'trigger-spaces');
  const c = await col();
  const doc: any = await c.findOne({ _type: 'guild', guild_id: id });
  const cmds = (doc?.commands ?? []).filter((x: any) => x.trigger !== trigger);
  cmds.push({ trigger, response });
  await c.updateOne({ _type: 'guild', guild_id: id }, { $set: { commands: cmds } }, { upsert: true });
  return back(id, gate.ok.refreshed);
};
