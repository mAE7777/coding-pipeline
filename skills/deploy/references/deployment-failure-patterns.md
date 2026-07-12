# Deployment Failure Patterns

Platform-specific failure patterns with symptoms, diagnosis, and resolution. Load at **Stage 5** during post-deploy verification, or at **Stage 2** when checking for known issues.

---

## Pattern Catalog

### 1. Serverless Cold Start Timeout
- **Symptom**: First request after deploy returns 504/timeout; subsequent requests work
- **Diagnosis**: Function needs initialization (importing heavy dependencies, establishing DB connections). Cold start exceeds timeout threshold.
- **Resolution**: Add warm-up request in Stage 5 verification. If persistent: lazy-load heavy imports, increase `maxDuration` in vercel.json, or move initialization to module scope.

### 2. Missing Environment Variable
- **Symptom**: 500 on API routes, 200 on static pages. No build errors.
- **Diagnosis**: Env var exists in local `.env` but not in deployment platform settings. Static pages don't invoke serverless functions, so they load fine.
- **Resolution**: Check function logs (not page load). Compare `process.env.*` references against platform env var dashboard. Common: `DATABASE_URL`, `API_KEY`, `JWT_SECRET`.

### 3. CORS on Resumable Upload
- **Symptom**: Browser shows CORS error on PUT/POST to external API (e.g., Google Cloud). Initial request works, subsequent chunks fail.
- **Diagnosis**: Server-initiated resumable upload didn't include `Origin` header in the start request. External service won't include `Access-Control-Allow-Origin` in responses.
- **Resolution**: Add `Origin: <client-origin>` header to the server-side upload initiation request.

### 4. Serverless tsconfig Conflict
- **Symptom**: `FUNCTION_INVOCATION_FAILED` with no runtime logs.
- **Diagnosis**: Frontend tsconfig (`module: ESNext`, `moduleResolution: bundler`) applied to API functions. Vercel runtime expects CommonJS-compatible output.
- **Resolution**: Add `api/tsconfig.json` with `module: CommonJS`, `moduleResolution: Node`. Ensure Vercel's `functions` config points to the right directory.

### 5. Stale Build Cache
- **Symptom**: Deploy reports success but site shows old version. No errors.
- **Diagnosis**: Platform used cached build output. Common after dependency changes or config modifications that don't trigger cache invalidation.
- **Resolution**: Force clean build: Vercel → redeploy with "Override" or clear build cache in project settings. Docker → `docker build --no-cache`.

### 6. Edge Runtime API Limitation
- **Symptom**: Runtime error: `X is not a function` or `Cannot find module 'fs'`.
- **Diagnosis**: Edge runtime doesn't support full Node.js API. Functions using `fs`, `crypto`, `child_process`, or Node-specific libraries fail silently at build but crash at runtime.
- **Resolution**: Switch to Node.js runtime (`export const runtime = 'nodejs'`) or replace unsupported APIs with edge-compatible alternatives.

### 7. Mixed Content Block
- **Symptom**: Page loads but some resources (images, scripts, API calls) fail. Console shows "Mixed Content" warning.
- **Diagnosis**: HTTPS page loading HTTP resources. Browsers block mixed content by default.
- **Resolution**: Grep for `http://` in production code. Replace with `https://` or protocol-relative `//`. Check API base URLs in environment config.

### 8. Bundle Size Regression
- **Symptom**: Page loads slowly, poor LCP. No functional errors.
- **Diagnosis**: New dependency or unoptimized import bloated the JS bundle. Common after adding a full library when only one function was needed.
- **Resolution**: Check `browser_network_requests` for JS file sizes. Use bundle analyzer. Replace heavy imports with tree-shakeable alternatives or dynamic imports.

### 9. Route Mismatch (SPA vs SSR)
- **Symptom**: Direct URL navigation returns 404. Navigation within the app works fine.
- **Diagnosis**: Server doesn't have catch-all route for client-side routing. SPA needs all routes to serve `index.html`; SSR needs explicit route handlers.
- **Resolution**: Vercel → add `rewrites` in vercel.json. Netlify → add `_redirects`. Docker/nginx → configure `try_files`.

### 10. Package Metadata Inconsistency (npm)
- **Symptom**: Published package shows wrong version in `--version`, wrong tool name in SARIF output, README says wrong license, or changelog doesn't document the installed version.
- **Diagnosis**: After a rename or version bump, not all files referencing the old name/version/license were updated. Common locations: CLI entrypoint `.version()` and `.name()`, output formatter constants, README install/usage examples, CHANGELOG headings, cache/config directory paths in source, test file assertions and temp directory prefixes.
- **Resolution**: Grep for the old name and old version across the entire project. Check README license section against package.json `"license"` field and LICENSE file. Verify CHANGELOG has a heading for the current version. This should be caught by the Package Metadata Consistency checks in the release checklist.

### 11. DNS/SSL Propagation Delay
- **Symptom**: Intermittent 404 or SSL certificate errors immediately after deploy with custom domain.
- **Diagnosis**: DNS changes or SSL certificate provisioning not yet propagated. Can take 5-60 minutes.
- **Resolution**: Wait and retry. Check `dig` or `nslookup` for DNS status. Verify SSL cert status in platform dashboard. Not a code issue — do not redeploy.
