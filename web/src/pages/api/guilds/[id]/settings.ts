import type { APIRoute } from 'astro';
import { col } from '../../../../lib/mongo';
import { requireManager } from '../../../../lib/guard';
import { sessionCookie } from '../../../../lib/session';

// POST /api/guilds/:id/settings  form: finance_mode, inventory_mode
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const form = await request.formData();
  const finance_mode = String(form.get('finance_mode') ?? 'everyone');
  const inventory_mode = String(form.get('inventory_mode') ?? 'everyone');
  const ok = (v: string) => (v === 'admins' ? 'admins' : 'everyone');
  let currency = String(form.get('currency') ?? '').trim();
  if (!currency || currency.length > 3) currency = '£';
  const c = await col();
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $set: { settings: { finance_mode: ok(finance_mode), inventory_mode: ok(inventory_mode), currency } } },
    { upsert: true },
  );
  const headers: Record<string, string> = { Location: `/guild/${id}?saved=1` };
  if (gate.ok.refreshed) headers['Set-Cookie'] = sessionCookie(gate.ok.refreshed);
  return new Response(null, { status: 302, headers });
};
