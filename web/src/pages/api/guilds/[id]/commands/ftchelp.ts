import type { APIRoute } from 'astro';
import { col } from '../../../../../lib/mongo';
import { requireManager } from '../../../../../lib/guard';
import { sessionCookie } from '../../../../../lib/session';

// POST /api/guilds/:id/commands/ftchelp  form: trigger
// Flips the "Add to !ftchelp" flag on a server custom command.
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const form = await request.formData();
  const trigger = String(form.get('trigger') ?? '').trim().toLowerCase();
  const headers: Record<string, string> = { Location: `/guild/${id}` };
  if (gate.ok.refreshed) headers['Set-Cookie'] = sessionCookie(gate.ok.refreshed);
  if (!trigger) {
    headers.Location = `/guild/${id}?error=missing`;
    return new Response(null, { status: 302, headers });
  }
  const c = await col();
  const doc: any = await c.findOne({ _type: 'guild', guild_id: id });
  const cmds = doc?.commands ?? [];
  const entry = cmds.find((x: any) => x.trigger === trigger);
  if (!entry) {
    headers.Location = `/guild/${id}?error=missing`;
    return new Response(null, { status: 302, headers });
  }
  entry.in_ftchelp = !entry.in_ftchelp;
  await c.updateOne({ _type: 'guild', guild_id: id }, { $set: { commands: cmds } });
  return new Response(null, { status: 302, headers });
};
