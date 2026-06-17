import { Env } from './types';

/**
 * Verify authentication.
 * Priority:
 * 1. Cloudflare Access (Cf-Access-Authenticated-User-Email header) — set by edge
 * 2. Bearer token (Authorization: Bearer ...) — for programmatic / MCP clients
 * 3. CF-Access-Client-Id + CF-Access-Client-Secret — for Service Tokens
 */
export async function verifyAuth(request: Request, env: Env): Promise<{ ok: boolean; key?: string; error?: string; user?: string }> {
  // Method 1: Cloudflare Access (user login or Service Token, validated at edge)
  const accessUser = request.headers.get('Cf-Access-Authenticated-User-Email');
  if (accessUser) {
    return { ok: true, key: 'cf-access:' + accessUser, user: accessUser };
  }

  // Method 2: Bearer token
  const authHeader = request.headers.get('Authorization') || '';
  let token = '';
  if (authHeader.startsWith('Bearer ')) {
    token = authHeader.slice(7).trim();
  } else {
    const url = new URL(request.url);
    token = url.searchParams.get('token') || '';
  }

  if (token && env.GATEWAY_API_KEY && token === env.GATEWAY_API_KEY) {
    return { ok: true, key: token };
  }

  // Method 3: KV-stored keys (Phase 1+)
  if (token && env.GATEWAY_KV) {
    const kvKey = await env.GATEWAY_KV.get(`apikey:${token}`);
    if (kvKey) {
      return { ok: true, key: token };
    }
  }

  if (accessUser || token) {
    return { ok: false, error: 'Invalid credentials' };
  }

  return { ok: false, error: 'Unauthorized. Use Cloudflare Access login, Bearer token, or Service Token (CF-Access-Client-Id + CF-Access-Client-Secret).' };
}
