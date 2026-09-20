import type { APIRoute } from 'astro';
import { col } from '../../../../lib/mongo';
import { requireManager } from '../../../../lib/guard';
import { sessionCookie } from '../../../../lib/session';
import { extractSheet } from '../../../../lib/sheets';

// POST /api/guilds/:id/settings  form: finance_mode, inventory_mode,
// outreach_mode, inventory_source (manual|sheet), sheet_url, currency
export const POST: APIRoute = async ({ request, params }) => {
  const id = String(params.id);
  const gate = await requireManager(id, request);
  if ('err' in gate) return gate.err;
  const headers: Record<string, string> = { Location: `/guild/${id}?saved=1` };
  if (gate.ok.refreshed) headers['Set-Cookie'] = sessionCookie(gate.ok.refreshed);
  const fail = (err: string) =>
    new Response(null, { status: 302, headers: { ...headers, Location: `/guild/${id}?error=${err}` } });
  const form = await request.formData();
  const finance_mode = String(form.get('finance_mode') ?? 'everyone');
  const inventory_mode = String(form.get('inventory_mode') ?? 'everyone');
  const outreach_mode = String(form.get('outreach_mode') ?? 'everyone');
  const ok = (v: string) => (v === 'admins' ? 'admins' : 'everyone');
  let currency = String(form.get('currency') ?? '').trim();
  if (!currency || currency.length > 3) currency = '£';
  const inventory_source = String(form.get('inventory_source') ?? 'manual') === 'sheet' ? 'sheet' : 'manual';
  const sheet_url = String(form.get('sheet_url') ?? '').trim();
  if (inventory_source === 'sheet' && !extractSheet(sheet_url)) return fail('bad-sheet-url');
  const c = await col();
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $set: { settings: {
      finance_mode: ok(finance_mode),
      inventory_mode: ok(inventory_mode),
      outreach_mode: ok(outreach_mode),
      inventory_source,
      sheet_url,
      currency,
    } } },
    { upsert: true },
  );
  return new Response(null, { status: 302, headers });
};
