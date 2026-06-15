import { Env } from './types';

export async function verifyAuth(request: Request, env: Env): Promise<{ ok: boolean; key?: string; error?: string }> {
  // 1. Check Authorization header
  const authHeader = request.headers.get('Authorization') || '';
  let token = '';
  if (authHeader.startsWith('Bearer ')) {
    token = authHeader.slice(7).trim();
  } else {
    // Also check ?token= query param
    const url = new URL(request.url);
    token = url.searchParams.get('token') || '';
  }

  if (!token) {
    return { ok: false, error: 'Missing API key. Use Authorization: Bearer <key>' };
  }

  // 2. Phase 0 simple auth: compare with env var
  // In later phases, we'll use KV-based API key management
  if (env.GATEWAY_API_KEY && token === env.GATEWAY_API_KEY) {
    return { ok: true, key: token };
  }

  // 3. Also check KV-stored keys (Phase 1+, optional)
  const kv = env.GATEWAY_KV;
  if (kv) {
    const kvKey = await kv.get(`apikey:${token}`);
    if (kvKey) {
      return { ok: true, key: token };
    }
  }

  return { ok: false, error: 'Invalid API key' };
}
