# Root Cause Diagnostic Catalogs

Loaded at Stage 1 after initial root cause hypothesis. Match the observed symptom to refine the hypothesis before proceeding.

---

## By Symptom

### "Works locally, fails in production"
1. Environment variables: `Grep` for hardcoded `localhost`, missing env vars in deployment config
2. Module format: ESM/CJS mismatch — Vite uses ESM, serverless often expects CJS. Check for separate tsconfig in API directory
3. CORS: Missing `Origin` header on server-initiated requests; browser sees no `Access-Control-Allow-Origin` on subsequent requests
4. Build output: Tree-shaking removed used code; dynamic imports not followed by bundler. Compare local vs production bundle

### "Worked before, now broken"
1. Diff recent changes: `git log --oneline -10` + `git diff HEAD~5` — cause is usually in the last 3 commits
2. Dependency drift: `git diff package-lock.json` — lockfile drift, auto-updates, peer dep conflicts, major version bumps
3. Stale state: Cached values from previous version, stale service workers, browser cache. Hard refresh + clear storage to rule out

### "Works sometimes / intermittent"
1. Race condition: Two async operations sharing mutable state. Log execution order to confirm non-determinism
2. Lifecycle timing: Component mount/unmount ordering. Missing cleanup in `useEffect` return, missing `AbortController` on fetch
3. Network-dependent: Timeout assumptions, retry logic, API rate limits. Check if failure correlates with latency or load

### "Error message doesn't match the bug"
1. Error boundary masking: React error boundary catches real error, shows generic fallback. Check browser console for original
2. try/catch swallowing: Outer catch hides inner error. Add targeted logging at suspected throw point
3. Wrong surface: Error appears in module A but root cause is in module B. Trace through shared state, event bus, or context provider

### "Fix didn't work"
1. Symptom-only patch: Fix addressed the visible output but not the producing condition. Re-read root cause hypothesis
2. Multiple bugs: Two bugs with overlapping symptoms. Fix for one reveals the other. Baseline comparison shows partial improvement
3. Wrong code path: Fix applied to correct file but wrong branch/condition. Trace actual execution with targeted logging

### "Shows old data after changing settings"
1. Stale closure: Event handler or callback captured a value at subscription time. When the value
   changes later, the handler still uses the OLD snapshot. Fix: read the current value at execution
   time, not subscription time. Common in event listeners, setTimeout callbacks, and React useEffect
2. Stale cache: Application caches the old value and doesn't invalidate on update. Check TTL,
   cache key, and invalidation logic
3. Derived state not recomputed: A computed/derived value was calculated once and stored. The source
   changed but the derived value wasn't recalculated. Trace from source → derived → display

---

## Diagnostic Defaults

When root cause is unclear after reading the code path:
- Add targeted `console.log` at decision points (not blanket logging)
- Reproduce with minimal input — strip context until the bug disappears, then add back
- Check BOUNDARIES: function inputs/outputs, API request/response, component props/state
