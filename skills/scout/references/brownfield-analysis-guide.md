# Brownfield Analysis Guide

Techniques for mapping existing codebases, identifying constraints, and discovering integration points. Load this at Stage 2 for brownfield investigations.

---

## Codebase Mapping Strategy

### Layer 1: Project Structure
1. Read `package.json` / manifest for project metadata, scripts, dependencies
2. Use `ls` on root and key directories to understand file organization
3. Identify the framework from dependencies (React, Next.js, Express, Hono, etc.)
4. Map the directory convention: src/, app/, pages/, api/, lib/, utils/, components/, etc.

### Layer 2: Architecture Patterns
1. Entry points: Find the main entry file(s) — `src/index.ts`, `app/layout.tsx`, `src/main.ts`, etc.
2. Routing: Map how URLs/routes are handled (file-based, config-based, programmatic)
3. State management: Identify how state flows (context, stores, props, URL state)
4. Data layer: How data is fetched, cached, and mutated (API calls, ORM, direct DB)
5. Auth: How authentication/authorization works (middleware, HOCs, route guards)

### Layer 3: Convention Discovery
Use Grep to identify patterns:
- Import style: `import { X } from '@/lib/...'` vs `import { X } from '../../lib/...'`
- Error handling: try/catch patterns, error boundaries, error response formats
- Testing patterns: test file location, naming, assertion library, mocking approach
- Type patterns: strict mode, utility types, shared type files

### Layer 4: Dependency Map
For the feature area being investigated:
1. Identify the core files involved
2. Trace imports outward: what do these files depend on?
3. Trace imports inward: what depends on these files?
4. Map shared abstractions: utilities, hooks, components, types used across the feature

---

## Constraint Identification

### Hard Constraints (cannot change)
- Runtime version (Node.js, Python, etc.) pinned by deployment platform
- Framework version pinned by other dependencies
- Database schema (if shared with other services)
- API contracts (if consumed by external clients)
- Build/deploy pipeline requirements (Vercel, Docker, etc.)

### Soft Constraints (expensive to change)
- Established patterns that would require large-scale refactoring
- Test infrastructure and conventions
- State management approach
- Component library / design system choices

### Compatibility Constraints (must check)
- Peer dependency requirements
- Node.js API availability in the runtime (e.g., edge runtime limitations)
- Browser compatibility targets
- TypeScript version and configuration

---

## Integration Point Discovery

For the feature area being investigated, identify all points where new code must connect to existing code:

1. **Data sources**: Where will new features get their data?
2. **UI mount points**: Where will new UI elements attach to existing layouts?
3. **API surface**: Which existing API endpoints will be consumed or extended?
4. **Shared state**: Which state stores or contexts will new features read/write?
5. **Build pipeline**: Are there custom build steps that affect new code?
6. **Test harness**: How must new tests integrate with existing test infrastructure?

For each integration point, document:
- File path and line number
- Interface/API shape
- Constraints or assumptions the existing code makes
- Whether the integration is stable or likely to change
