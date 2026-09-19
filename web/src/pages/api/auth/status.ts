import type { APIRoute } from 'astro';
import { envStatus } from '../../../lib/env';

// Safe diagnostics: booleans only, never values.
export const GET: APIRoute = async () => {
  return Response.json(envStatus());
};
