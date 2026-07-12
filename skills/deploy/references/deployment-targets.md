# Deployment Targets

Platform-specific deployment commands, configuration, and post-deploy verification. Load at Stage 4.

---

## Vercel

### Detection
- `vercel.json` exists, OR
- `package.json` has `"vercel"` in devDependencies, OR
- `.vercel/` directory exists

### Pre-Deploy Checks
- Verify Vercel CLI is installed: `vercel --version`
- Verify project is linked: check `.vercel/project.json`
- If not linked: `vercel link` (requires user interaction)

### Deployment Commands
- **Production**: `vercel --prod`
- **Preview**: `vercel`
- **With env vars**: Vercel reads from project settings, not local .env

### Post-Deploy Verification
- Parse deployment URL from command output
- Navigate to URL via Playwright
- Check for common Vercel issues:
  - CORS on API routes (check network requests from browser)
  - Missing env vars (500 errors on serverless functions)
  - Build output mismatch (404 on expected routes)
  - Edge runtime limitations (if using edge functions)

### Common Issues
- `FUNCTION_INVOCATION_FAILED` with no logs: module import error in serverless function
- CORS: Server must include `Origin` header in resumable upload start requests
- tsconfig: API functions need separate tsconfig with CommonJS module

---

## npm

### Detection
- `package.json` with `"publishConfig"`, `"bin"`, `"main"`, or `"exports"` (and not `"private": true`)

### Pre-Publish Checks
- **Name availability**: Run `npm publish --dry-run` (not just `npm view`). npm's similarity check rejects names that look too similar to existing packages (e.g., `reviewkit` rejected because `review-kit` exists). `npm view {name}` returning 404 does NOT guarantee the name is publishable.
- **Auth verification**: Run `npm whoami` to confirm logged in. If not, prompt `npm login`.
- **Version check**: Compare `package.json` version against `npm view {name} version`. If the version already exists, bump first.
- **Files field**: Verify `package.json` has `"files"` array to scope what gets published. Run `npm publish --dry-run` to inspect tarball contents and size.
- **Build output**: Verify dist/ or lib/ is populated and matches `"files"`, `"main"`, `"bin"`, `"exports"` paths.
- **Git clean**: All changes affecting published output must be committed before publishing.

### Authentication (post-Dec 2025)

npm overhauled auth in Dec 2025. Classic tokens were permanently revoked.

**Session-based login** (`npm login`):
- Creates a 2-hour session token
- 2FA is enforced by default for all publish operations on new packages
- Every `npm publish` requires an OTP from authenticator: `npm publish --otp=<code>`

**Granular access tokens** (for OTP-free publishing):
- Created at https://www.npmjs.com/settings/{username}/tokens → "Granular Access Token"
- Enable "Bypass 2FA" checkbox to skip OTP on publish
- Scope to specific packages or all packages, Read+Write permission
- Max 90-day expiration for write tokens

**Using a granular token for publish**:
- `--token` flag does NOT work with `npm publish`
- `NPM_TOKEN` env var does NOT work without `.npmrc` configuration
- The correct approach: write token to project `.npmrc`:
  ```
  echo "//registry.npmjs.org/:_authToken=<token>" > .npmrc
  npm publish
  rm .npmrc   # CRITICAL: clean up immediately, never commit tokens
  ```
- Verify `.npmrc` is in `.gitignore` as a safety net

### Deployment Commands
- **Publish**: `npm publish` (or `npm publish --access public` for scoped packages)
- **With OTP**: `npm publish --otp=<code>`
- **Version bump**: `npm version {patch|minor|major}` (creates git tag)

### Post-Deploy Verification
- `npm view {package}@{version}`: verify package is on the registry
- Create temp directory: `mktemp -d`, `npm init -y`, `npm install {package}@{version}`
- **If CLI** (`bin` field): test `npx {bin} --version`, `npx {bin} --help`, error handling (e.g., missing file → exit 2), and one real command if possible
- **If ESM library**: `node -e "import('{package}').then(m => console.log(Object.keys(m)))"`
- **If CJS library**: `node -e "console.log(Object.keys(require('{package}')))"`
- Clean up temp directory after verification

### Common Issues
- **Name rejected**: npm's typosquatting protection rejects names similar to existing packages. Use `npm publish --dry-run` to catch this before the real attempt.
- **E403 + OTP required**: Account has 2FA enforced. Either provide `--otp` or use a granular token with "Bypass 2FA".
- **E403 + "Forbidden"**: Token doesn't have write permission, or token is scoped to different packages.
- **E404 on publish**: Usually an auth failure masquerading as 404. Check `npm whoami` and token validity.

---

## Docker

### Detection
- `Dockerfile` exists, OR
- `docker-compose.yml` / `compose.yml` exists

### Pre-Deploy Checks
- Docker daemon running: `docker info`
- Base image available: `docker pull {base-image}` (optional, saves time)

### Deployment Commands
- **Build**: `docker build -t {image}:{tag} .`
- **Push**: `docker push {registry}/{image}:{tag}`
- **Compose**: `docker compose up -d`

### Post-Deploy Verification
- `docker ps`: verify container is running
- Health check endpoint if available
- `docker logs {container}`: check for startup errors

---

## Netlify

### Detection
- `netlify.toml` exists

### Deployment Commands
- **Production**: `netlify deploy --prod`
- **Preview**: `netlify deploy`

### Post-Deploy Verification
- Parse deployment URL from command output
- Navigate to URL via Playwright
- Check for redirect configuration (`_redirects` or `netlify.toml` redirects)

---

## Fly.io

### Detection
- `fly.toml` exists

### Deployment Commands
- **Deploy**: `fly deploy`
- **With build args**: `fly deploy --build-arg KEY=VALUE`

### Post-Deploy Verification
- `fly status`: check deployment status
- `fly logs`: check for startup errors
- Navigate to app URL via Playwright

---

## Generic (No Platform Detected)

If no deployment target is detected:

1. Use `AskUserQuestion` to ask:
   ```
   No deployment target detected. How should I deploy?

   A. Vercel
   B. npm publish
   C. Docker
   D. Custom command
   ```

2. If "Custom command", ask for the exact command to run.

3. For custom deployments, post-deploy verification is limited to whatever URL or verification command the user provides.
