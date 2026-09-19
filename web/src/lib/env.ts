// Loads repo-root .env (and web/.env) at RUNTIME for local dev.
// Netlify/host env vars always win (override: false). Never logs values.
import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url)); // web/src/lib
const webDir = path.resolve(here, '..', '..');
const rootDir = path.resolve(webDir, '..');
for (const p of [path.join(webDir, '.env'), path.join(rootDir, '.env')]) {
  dotenv.config({ path: p, override: false });
}

export function envStatus() {
  const check = (v: string | undefined) => !(v === undefined || v === '');
  return {
    DISCORD_CLIENT_ID: check(process.env.DISCORD_CLIENT_ID),
    DISCORD_CLIENT_SECRET: check(process.env.DISCORD_CLIENT_SECRET),
    MONGO_URI: check(process.env.MONGO_URI),
    PUBLIC_WEB_URL: check(process.env.PUBLIC_WEB_URL),
  };
}
