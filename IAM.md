# Spyducky IAM Architecture

**Status:** Design phase (public). Implementation roadmap below.

## Overview

Spyducky authentication and authorization supports three concurrent deployment models:

1. **Multi-tenant SaaS** — firms authenticate users via their own OIDC provider (Azure AD, Okta, Ping, etc.)
2. **On-prem single-tenant** — firm deploys on their own H100, uses their company OIDC
3. **IP cameras** — smart cameras authenticate with API keys; survive IdP outages via fallback snapshot

All three models share a **unified IAM system**: one `AuthContext` shape, one RBAC matrix, one audit log.

## Key Design Principles

- **Spyducky mints its own JWT** — OIDC tokens are validated once and exchanged for short-lived internal JWTs (15 min)
- **API-key path has zero dependency on OIDC** — cameras keep streaming during IdP/Redis/Postgres outages via tiered lookup (Redis → Postgres → signed snapshot file)
- **Defense in depth** — 5 independent layers of tenant isolation catch any single-layer breach
- **Unified principals model** — humans and devices share one table, one audit log, one RBAC system
- **Tamper-evident audit** — append-only with SHA256 hash chain; cannot be modified without detection

## Architecture Decisions (ADRs)

### ADR-IAM-1: Spyducky Mints Its Own JWT

Spyducky validates OIDC tokens **once**, then exchanges them for RS256-signed internal JWTs. This avoids:
- Per-request validation against N external JWKS endpoints
- Cross-tenant confusion from misconfigured OIDC `aud` claims
- Dependency on external IdP availability for token refresh

### ADR-IAM-2: Three Token Formats, One Validation Function

| Format | Audience | TTL | Storage |
|---|---|---|---|
| **Access JWT** | humans (browser/mobile/desktop) | 15 min | signed, local verify (~50µs) |
| **Refresh token** | humans | 30 days sliding | Redis-backed, single-use rotation |
| **API key** | IP cameras | 365 days (configurable) | Argon2id hash in Postgres + Redis cache + fallback snapshot |

All decode to the same `AuthContext` at the gateway.

### ADR-IAM-3: Unified Principals Model

One `principals` table with `principal_type ∈ {human, device}` and `device_class ∈ {browser, mobile, ip_camera, desktop}`. Humans and cameras:
- Share one audit log (`actor_principal_id`)
- Use the same RBAC scope system
- Are indistinguishable at the risk-engine layer (unified `session` model)

### ADR-IAM-4: Session Hierarchy

- **Auth session** — represents a human's OIDC login event; holds refresh-token family; one per (principal, device_class, browser instance)
- **Conauth session** — represents a continuous-auth observation; owns N camera devices via `session_devices` join

### ADR-IAM-5: Defense-in-Depth Tenant Isolation

Every cross-tenant access attempt is blocked by **all five** layers (any one is sufficient):

1. **JWT `tid` claim** — cryptographically signed
2. **URL path binding** — `/auth/callback/{tenant_slug}` must match
3. **Postgres RLS** — `SET LOCAL app.tenant_id` on every connection
4. **Redis prefix guard** — wrapper client rejects operations on `t:OTHER_TENANT:*`
5. **Triton routing** — per-tenant rate limits + MIG slice isolation

Cross-tenant attempt = `SEV1 audit event` + immediate paging.

### ADR-IAM-6: API-Key Fallback Path (Zero OIDC Dependency)

Camera key validation follows a **tiered lookup**:

```
1. Redis cache (5 min TTL)      ← fast, ~1ms
2. Postgres query                 ← slower, ~10ms
3. Signed snapshot file (~60s)    ← degraded, ~5ms
```

If Redis + Postgres are both down, cameras authenticate via a cryptographically-signed snapshot file refreshed every 60s by a sidecar. **OIDC code path has no access to this tier**, so IdP outages do not block camera streams.

### ADR-IAM-7: Manual OIDC Registration Per Tenant

Firm admins configure OIDC via the spyducky admin UI: `issuer_url`, `client_id`, `client_secret` (sealed in Postgres), claim mappings. No auto-discovery; we publish per-IdP setup guides (Azure AD, Okta, Ping).

### ADR-IAM-8: Tamper-Evident Audit

Audit events are streamed to Redis then drained to Postgres, with a **hash chain**: each row commits to the previous row's hash. Daily anchor publishes the final hash to an immutable store. Any modification = obvious gap in the chain.

## Authorization (Scopes)

Standard JWT scopes:

| Scope | Granted to | Purpose |
|---|---|---|
| `conauth:session:create` | humans | Create a continuous-auth session |
| `conauth:stream:write` | IP cameras | Push H.264 frames to a session |
| `conauth:command:receive` | humans | Receive LOCK/BLACKOUT commands |
| `conauth:camera:provision` | tenant-admin | Bind camera to session |
| `conauth:apikey:issue` | tenant-admin | Mint an API key |
| `conauth:audit:read` | tenant-admin | View audit log |
| `conauth:risk:configure` | tenant-admin | Adjust risk thresholds |
| `conauth:tenant:admin` | tenant-owner | Manage tenant OIDC config |

## Token Formats

### Access JWT

```json
{
  "iss": "https://app.spyducky.com",
  "aud": "spyducky-gateway",
  "sub": "<principal_id>",
  "tid": "<tenant_id>",
  "pty": "human",
  "dvc": "browser",
  "scp": ["conauth:session:create", "conauth:command:receive"],
  "iat": 1733520000,
  "exp": 1733520900,
  "jti": "<uuid>",
  "kid": "spdk-sign-2026-q2"
}
```

**Algorithm**: RS256 (2048-bit minimum, 4096 preferred). KMS-backed in SaaS, file-backed (0600 permissions) on-prem.

### Refresh Token

Opaque 256-bit random, Redis-backed, single-use rotation, 30-day sliding window. Replay detection triggers family revocation.

### API Key

Format: `spdk_<env>_<tenant_slug>_<key_id>.<secret>`

Example: `spdk_prod_acme_K7QR8.5n3xJ...`

- Stored as Argon2id hash; plaintext returned only at issuance
- Configurable TTL (default 365 days, mandatory expiry)
- Rotation: admin triggers → new key issued → 24h overlap → old auto-revokes
- Revocation: instant via Redis tombstone

## Data Flow

### Login (OIDC)

1. User clicks "Login with Azure AD"
2. Gateway redirects to IdP with PKCE challenge + state
3. IdP redirects back to `/auth/callback/{tenant_slug}?code=...`
4. Gateway exchanges code for ID token (validates against IdP JWKS)
5. Gateway upserts `principal` row (tenant, OIDC sub, issuer)
6. Gateway creates `auth_session` row (refresh-token family)
7. Gateway issues spyducky access JWT + refresh token
8. User now authenticated; subsequent requests send `Authorization: Bearer <access_jwt>`

### IP Camera Stream

1. Admin pre-provisions camera: creates `principal` (type=device), generates API key `spdk_prod_acme_K7QR8.secret`
2. Camera configured with key: `spdk_prod_acme_K7QR8.secret`
3. Camera sends `Authorization: ApiKey spdk_prod_acme_K7QR8.SECRET` to POST `/v2/cameras/stream`
4. Gateway verifies key:
   - Lookup `key_id=K7QR8` in Redis cache → hit → Argon2 verify
   - If miss, query Postgres → Argon2 verify → cache result
   - If both down, read signed snapshot file → Argon2 verify + degrade flag
5. Build `AuthContext` (device principal, ip_camera device_class)
6. WebRTC SDP offer → SRTP stream begins

### Token Refresh

1. Access JWT near expiry; browser sends refresh token
2. Gateway validates refresh token (Redis lookup, check used flag)
3. Validate not replayed (if reused, revoke entire family)
4. Mint new access JWT + new refresh token (rotated secret)
5. Return both; browser stores new refresh token, uses new access JWT

## Fallback & Degradation

| Failure | Access JWT | API Key | Refresh | Recovery |
|---|---|---|---|---|
| IdP down | ✅ (cached 15 min) | ✅ | ❌ | IdP returns |
| Redis down | ✅ (local verify) | ✅ (Postgres) | ❌ | Redis returns |
| Postgres down | ✅ | ✅ (snapshot) | ❌ | Postgres returns |
| Both down | ✅ | ✅ (snapshot) | ❌ | Both return |

**Design principle**: Humans lose refresh ability (will be logged out on JWT expiry); cameras **keep streaming** via snapshot fallback.

## Security

- **Key signing**: KMS-backed (SaaS) or HSM/file (on-prem)
- **Key rotation**: Quarterly for signing key; 365d default for API keys; 30d for refresh tokens; 15min for access JWTs
- **Replay defense**: `jti` cached; refresh tokens single-use with family revocation
- **CSRF**: refresh tokens are `Secure; HttpOnly; SameSite=Strict` cookies; access JWTs in `Authorization` header
- **Secret transport**: API key plaintext returned **once** at issuance; UI shows "copy now, never again"
- **Audit**: append-only hash-chained log; SEV1 alert on any cross-tenant attempt

## Implementation Roadmap

20 tasks, ready to assign to engineers:

1. Add IAM dependencies (`authlib`, `python-jose`, `argon2-cffi`, `httpx`)
2. Define `AuthContext` Pydantic model + scope constants
3. Postgres schema migrations (principals, auth_sessions, api_keys, tenant_oidc_config, auth_audit)
4. Redis wrapper client (prefix guard, contextvar binding)
5. JWT issue/verify, kid rotation, `/.well-known/jwks.json`
6. Principal CRUD (upsert_human, create_device)
7. API-key issue/verify/rotate/revoke, tiered lookup
8. API-key snapshot sidecar (signed, 60s refresh)
9. Auth session lifecycle, refresh-token single-use rotation
10. OIDC relying party (Authorization Code + PKCE, per-tenant JWKS cache)
11. RBAC matrix, authorization decision function
12. Audit emission, hash-chain verification job
13. FastAPI middleware (current_auth, current_tenant, with_tenant wrapper)
14. Gateway auth endpoints (login, callback, refresh, logout, JWKS)
15. Wire session/camera endpoints to RBAC checks
16. Admin API (OIDC config, API-key management, session provisioning)
17. Cross-tenant security regression test suite
18. Degradation integration tests (IdP down, Redis down, Postgres down)
19. OIDC setup runbooks (Azure AD, Okta, Ping)
20. Key rotation runbooks (signing key, API key, refresh token)

See `ARCHITECTURE.md` for the full 20-task breakdown with dependencies and acceptance criteria.

---

**Last updated**: 2026-06-06  
**License**: MIT
