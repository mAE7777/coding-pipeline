# Port Registry

Central tracking of dev server port assignments across all active projects. Prevents port conflicts when multiple projects run concurrently in different sessions.

---

## Port Assignments

| Project | Path | Port | Status | Assigned |
|---------|------|------|--------|----------|
| recipeforge | ~/Projects/example/recipeforge | 3000 | active | 2026-02-14 |
| forge | ~/Projects/example/forge | 3001 | active | 2026-02-14 |
| ai-code-reviewer | ~/Projects/example/ai-code-reviewer | 3002 | released | 2026-02-15 |
| seep (Dread Engine) | ~/Projects/lab/seep | 3002 | active | 2026-03-25 |
| compass | ~/Projects/lab/compass | 3003 | active | 2026-04-02 |
| volley | ~/Projects/lab/volley | 3004 | active | 2026-04-10 |
| autumn-in-new-york | ~/Projects/lab/autumn-in-new-york | 3005 | active | 2026-04-12 |

Status values: `active` (in development) | `released` (deploy completed or manually freed)

---

## Assignment Rules

1. **Framework defaults**: Next.js projects start from port 3000, Vite projects from 5173, other frameworks from 3000.
2. **Conflict avoidance**: Read this table before assigning. Skip any port with `active` status.
3. **Lowest available**: Assign the lowest unused port in the framework's range.
4. **Recording**: feat writes both this file AND the pipeline-state.md `Dev Port` header field.
5. **Release**: deploy marks the port as `released` when archiving pipeline-state.md.
6. **Cleanup**: Ports for abandoned projects (no deploy) can be manually released via `/update`.
7. **Runtime check**: dev verifies port availability via `lsof -i :{port}` before starting the server.
