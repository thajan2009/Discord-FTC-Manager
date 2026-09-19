import type { APIRoute } from 'astro';
import { col } from '../../../../../lib/mongo';
import { requireManager } from '../../../../../lib/guard';
import { sessionCookie } from '../../../../../lib/session';

function parseGbp(raw: string): number | null {
  const s = raw.replace(/[£,\s]/g, '');
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(parseFloat(s) * 100);
}

// POST /api/guilds/:id/finance/edit  form: bucket, oldname, name, amount
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
  const pence = parseGbp(String(form.get('amount') ?? ''));
  if (!bucketKey || !oldname) return fail('missing');
  if (!name) return fail('name-required');
  if (pence === null) return fail('bad-amount');
  const c = await col();
  const doc: any = await c.findOne({ _type: 'guild', guild_id: id });
  const bucket = doc?.finance?.teams?.[bucketKey];
  if (!bucket) return fail('missing');
  let touched = false;
  for (const lst of ['debts', 'sources']) {
    for (const e of (bucket[lst] ?? [])) {
      if (String(e.name ?? '').toLowerCase() === oldname) {
        e.name = name;
        e.amount_p = pence;
        touched = true;
      }
    }
  }
  if (!touched) return fail('missing');
  await c.updateOne(
    { _type: 'guild', guild_id: id },
    { $set: { [`finance.teams.${bucketKey}`]: bucket } },
  );
  return new Response(null, { status: 302, headers });
};
