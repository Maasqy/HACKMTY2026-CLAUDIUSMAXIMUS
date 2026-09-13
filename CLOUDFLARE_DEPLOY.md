# Deploy the Fraud Forensics UI to Cloudflare Pages

The frontend is a static Vite build with no server component. Cloudflare Pages
gives the whole team edit access on the free tier (unlike Vercel Hobby, which
locks projects to a single collaborator).

## One-time setup

1. Sign in at [dash.cloudflare.com](https://dash.cloudflare.com/).
2. Go to **Workers & Pages** → **Create application** → **Pages** → **Connect to
   Git**.
3. Authorize Cloudflare on the GitHub org that owns
   `HACKMTY2026-CLAUDIUSMAXIMUS` and pick the repo.
4. When prompted for build settings, use exactly:

   | Field | Value |
   |-------|-------|
   | Framework preset | `None` (or `Vite` if offered) |
   | Build command | `cd frontend && npm ci && npm run build` |
   | Build output directory | `frontend/dist` |
   | Root directory (advanced) | leave blank (project root) |
   | Node version (env var `NODE_VERSION`) | `20` |

5. Click **Save and Deploy**. First build takes ~90s. Every push to `main`
   redeploys automatically. Preview URLs are created for every branch push.

## What the build does

- `npm ci` installs the pinned deps (sql.js, xlsx, file-saver, papaparse,
  react-router-dom, etc.).
- `npm run build` runs `tsc -b && vite build`. TS strict mode must pass.
- Output is 100% static (`dist/index.html`, `dist/assets/*`). No secrets, no env
  vars needed. Cloudflare will serve it globally from its edge network.

## After deploy

- The default URL is `<project-name>.pages.dev`. Share this in the pitch.
- To add a custom domain (e.g. `forensics.claudiusmaximus.mx`), go to the Pages
  project → **Custom domains** → **Set up a custom domain**.
- Analytics are free and on by default under **Analytics & Logs** → **Web
  Analytics**.

## Custom SPA fallback

React Router uses client-side routing. Cloudflare Pages already rewrites all
paths to `index.html` when no matching file exists, so `/upload`, `/case`,
`/live`, etc. work out of the box. No extra `_redirects` file needed.

## Local preview before push

```powershell
cd frontend
npm ci
npm run build
npm run preview   # serves dist/ on http://localhost:4173
```

If the local preview breaks, Cloudflare will too — fix locally first.

## Common failure modes

| Symptom | Fix |
|---------|-----|
| Build fails with `Cannot find module '@/...'` | Make sure the `tsconfig.json` `paths` alias is unchanged. |
| sql.js WASM 404 in production | The Upload page fetches `sql-wasm.wasm` from `https://sql.js.org/dist/` at runtime — no bundling needed. If corp firewall blocks it, self-host by adding `import wasm from "sql.js/dist/sql-wasm.wasm?url"` and pointing `locateFile` to it. |
| `MOCK_SUBMISSION` still shows Spanish text | Confirm `frontend/src/lib/translate.ts` is present and both `submission.mock.ts` and `events.mock.ts` wrap their raw exports with `translateDeep`. |
| Chunk > 500 kB warning | Cosmetic. Ignore for the hackathon, or add `manualChunks` in `vite.config.ts` if you want a smaller vendor bundle. |

## Manual deploy (no GitHub connection)

If GitHub OAuth is blocked, use Wrangler:

```powershell
npm install -g wrangler
cd frontend
npm ci
npm run build
wrangler pages deploy dist --project-name fraud-forensics
```

Wrangler will open a browser to authenticate the first time.
