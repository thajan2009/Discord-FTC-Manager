import type { APIRoute } from 'astro';
import { col } from '../../../../../lib/mongo';
import { requireManager } from '../../../../../lib/guard';
import { sessionCookie } from '../../../../../lib/session';

// POST /api/guilds/:id/inventory/edit  form: bucket, oldname, name, qty
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const headers: Record<string, string> = { Location: `/guild/${id}` };
  if (gate.ok.refreshed) headers['Set-Cookie'] = sessionCookie(gate.ok.refreshed);
  const fail = (err: string) => new Response(null, { status: 302, headers: { ...headers, Location: `/guild/${id}?error=${err}` } });
  const form = await request.formData();
  const bucketKey = String(form.get('bucket') ?? '');
  const oldname = String(form.get('oldname') ?? '').trim().toLowerCase();
  const name = String(form.get('name') ?? '').trim();
  const qty = Number(String(form.get('qty') ?? '').trim());
  if (!bucketKey || !oldname) return fail('missing');
  if (!name) return fail('name-required');
  if (!Number.isInteger(qty) || qty < 0) return fail('bad-qty');
  const c = await col();
  const doc: any = await c.findOne({ _type: 'guild', guild_id: id });
  const bucket = doc?.inventory?.teams?.[bucketKey];
  if (!bucket) return fail('missing');
  let touched = false;
  for (const it of (bucket.items ?? [])) {
    if (String(it.name ?? '').toLowerCase() === oldname) {
      it.name = name;
      it.qty = qty;
      touched = true;
    }
  }
  if (!touched) return fail('missing');
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $set: { [`inventory.teams.${bucketKey}`]: bucket } },
  );
  return new Response(null, { status: 302, headers });
};
