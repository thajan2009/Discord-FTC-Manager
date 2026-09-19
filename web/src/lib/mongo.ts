import './env';
import { MongoClient } from 'mongodb';

let client: MongoClient | null = null;

export async function col() {
  const uri = process.env.MONGO_URI;
  if (!uri) throw new Error('MONGO_URI missing (Netlify env).');
  if (!client) {
    client = new MongoClient(uri);
    await client.connect();
  }
  // DB wilsodc, collection wilsodc (same as bot)
  return client.db('wilsodc').collection('wilsodc');
}

export async function getGuild(guildId: string) {
  const c = await col();
  let doc: any = await c.findOne({ _type: 'guild', guild_id: String(guildId) });
  if (!doc) {
    doc = {
      _type: 'guild', guild_id: String(guildId), teams: [],
      settings: { finance_mode: 'everyone', inventory_mode: 'everyone' },
      finance: { teams: {} }, inventory: { teams: {} }, commands: [],
    };
    await c.insertOne(doc);
  }
  return doc;
}

export async function getGlobals() {
  const c = await col();
  let doc: any = await c.findOne({ _type: 'global_commands' });
  if (!doc) {
    doc = { _type: 'global_commands', entries: {} };
    await c.insertOne(doc);
  }
  return doc.entries ?? {};
}

// Read-only existence check (no auto-create) for dashboard filtering.
export async function guildExists(guildId: string): Promise<boolean> {
  const c = await col();
  const doc = await c.findOne(
    { _type: 'guild', guild_id: String(guildId) },
    { projection: { _id: 1 } },
  );
  return !!doc;
}
