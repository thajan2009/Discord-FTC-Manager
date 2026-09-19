import type { APIRoute } from 'astro';
import { col } from '../../../../../lib/mongo';
import { requireManager } from '../../../../../lib/guard';
import { sessionCookie } from '../../../../../lib/session';

// POST /api/guilds/:id/inventory/delete  form: bucket (team key or _server), name
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const form = await request.formData();
  const bucketKey = String(form.get('bucket') ?? '');
  const name = String(form.get('name') ?? '').trim().toLowerCase();
  const headers: Record<string, string> = { Location: `/guild/${id}` };
  if (gate.ok.refreshed) headers['Set-Cookie'] = sessionCookie(gate.ok.refreshed);
  if (!bucketKey || !name) {
    headers.Location = `/guild/${id}?error=missing`;
    return new Response(null, { status: 302, headers });
  }
  const c = await col();
  const doc: any = await c.findOne({ _type: 'guild', guild_id: id });
  const bucket = doc?.inventory?.teams?.[bucketKey];
  if (bucket) {
    bucket.items = (bucket.items ?? []).filter((it: any) => String(it.name ?? '').toLowerCase() !== name);
    await c.updateOne(
      { _type: 'guild', guild_id: id },
      { $set: { [`inventory.teams.${bucketKey}`]: bucket } },
    );
  }
  return new Response(null, { status: 302, headers });
};
