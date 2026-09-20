// Google Sheets inventory source (read-only mirror of bot/utils/sheets.py).
// Expected layout: header row with "Part Name" + "Current Stock" (case-insensitive,
// a few aliases accepted), optional "Vendor" / "Category" sorter columns.
// Sheet must be shared as "Anyone with the link can view".

export interface SheetItem {
  name: string;
  qty: number;
  vendor: string;
  category: string;
}

export interface SheetResult {
  items: SheetItem[];
  hasVendor: boolean;
  hasCategory: boolean;
  error: string | null;
}

const CACHE_TTL = 60_000;
const cache = new Map<string, { at: number; result: SheetResult }>();

const NAME_KEYS = new Set(['part name', 'partname', 'part', 'item', 'item name']);
const STOCK_KEYS = new Set(['current stock', 'stock', 'qty', 'quantity', 'count', 'on hand', 'onhand']);
const VENDOR_KEYS = new Set(['vendor', 'supplier', 'seller', 'store', 'shop']);
const CATEGORY_KEYS = new Set(['category', 'type', 'group', 'class']);

export function extractSheet(url: string): { id: string; gid: string } | null {
  if (!url) return null;
  const m = url.match(/\/spreadsheets\/d\/([A-Za-z0-9-_]+)/);
  if (!m) return null;
  const g = url.match(/[?&#]gid=(\d+)/);
  return { id: m[1], gid: g ? g[1] : '0' };
}

function norm(h: string): string {
  return (h ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else quoted = false;
      } else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (c === '\r') { /* skip */ }
    else field += c;
  }
  row.push(field);
  rows.push(row);
  return rows.filter((r) => r.some((c) => c.trim() !== ''));
}

function parseQty(raw: string): number {
  const m = String(raw ?? '').replace(/,/g, '').match(/-?\d+(\.\d+)?/);
  if (!m) return 0;
  const n = parseInt(m[0], 10);
  return Number.isFinite(n) ? n : 0;
}

export async function fetchSheet(url: string): Promise<SheetResult> {
  const parsed = extractSheet(url ?? '');
  const fail = (error: string): SheetResult => ({ items: [], hasVendor: false, hasCategory: false, error });
  if (!parsed) return fail("That doesn't look like a Google Sheets link.");
  const key = `${parsed.id}/${parsed.gid}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_TTL) return hit.result;

  let text: string;
  try {
    const res = await fetch(
      `https://docs.google.com/spreadsheets/d/${parsed.id}/export?format=csv&gid=${parsed.gid}`,
      { signal: AbortSignal.timeout(10_000), headers: { 'User-Agent': 'FTCManager/1.0' } },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    text = await res.text();
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  } catch {
    return fail("Couldn't open the sheet. Make sure link sharing is on ('Anyone with the link can view').");
  }

  const rows = parseCsv(text);
  if (!rows.length) return fail('The sheet looks empty.');
  const headers = rows[0].map(norm);
  const col = (keys: Set<string>): number => headers.findIndex((h) => keys.has(h));
  const nameI = col(NAME_KEYS);
  const stockI = col(STOCK_KEYS);
  const vendorI = col(VENDOR_KEYS);
  const catI = col(CATEGORY_KEYS);
  if (nameI < 0 || stockI < 0) {
    return fail("Couldn't find the required columns. The first row needs 'Part Name' and 'Current Stock'.");
  }

  const items: SheetItem[] = [];
  for (const r of rows.slice(1)) {
    const name = (r[nameI] ?? '').trim();
    if (!name) continue;
    items.push({
      name,
      qty: parseQty(r[stockI] ?? ''),
      vendor: vendorI >= 0 ? (r[vendorI] ?? '').trim() : '',
      category: catI >= 0 ? (r[catI] ?? '').trim() : '',
    });
  }
  items.sort((a, b) =>
    (a.category || '').localeCompare(b.category || '') ||
    (a.vendor || '').localeCompare(b.vendor || '') ||
    a.name.localeCompare(b.name),
  );
  const result: SheetResult = {
    items,
    hasVendor: vendorI >= 0,
    hasCategory: catI >= 0,
    error: null,
  };
  cache.set(key, { at: Date.now(), result });
  return result;
}
