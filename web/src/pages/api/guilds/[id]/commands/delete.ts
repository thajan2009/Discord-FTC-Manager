import type { APIRoute } from 'astro';
import { col } from '../../../../../lib/mongo';
import { requireManager } from '../../../../../lib/guard';
import { sessionCookie } from '../../../../../lib/session';

// POST /api/guilds/:id/commands/delete  form: trigger
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const form = await request.formData();
  const trigger = String(form.get('trigger') ?? '').trim().toLowerCase();
  if (!trigger) {
    return new Response(null, { status: 302, headers: { Location: `/guild/${id}?error=missing` } });
  }
  const c = await col();
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $pull: { commands: { trigger } } as any },
  );
  const headers: Record<string, string> = { Location: `/guild/${id}` };
  if (gate.ok.refreshed) headers['Set-Cookie'] = sessionCookie(gate.ok.refreshed);
  return new Response(null, { status: 302, headers });
};
