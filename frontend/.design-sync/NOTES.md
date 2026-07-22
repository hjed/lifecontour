# design-sync notes — personal-management-frontend

Repo-specific gotchas for future syncs. Read this before re-running.

## Shape: this is an app, not a library

- `frontend/` is a private Next.js app. There is **no `dist/`** and no library
  build, so the converter runs against a hand-written barrel,
  `.design-sync/ds-entry.ts`, passed via `--entry`. That barrel re-exports the
  repo's real components verbatim — it is scope control, not reimplementation.
- Because there is no shipped `.d.ts` tree, `exportedNames()` finds nothing and
  component discovery comes **entirely** from `cfg.componentSrcMap`. A new
  component is invisible to design-sync until it is added to _all three_ of
  `ds-entry.ts`, `componentSrcMap`, and `.design-sync/docs/<Name>.md`.
- Run everything from `frontend/`, not the repo root.
- Node 26 (`.nvmrc`) — `export PATH="$HOME/.nvm/versions/node/v26.5.0/bin:$PATH"`.
  **Do not then call bare `pnpm`: it hangs forever with no output.** The node 26
  bin dir ships only `node`/`npm`/`npx` (no corepack, no pnpm), so `pnpm`
  resolves to `~/.local/bin/pnpm` → `nvm-wrapper.sh`, which self-execs in a loop.
  Invoke the pinned pnpm from the corepack cache directly instead:

  ```sh
  export PATH="$HOME/.nvm/versions/node/v26.5.0/bin:$PATH"
  export COREPACK_ENABLE_STRICT=0 COREPACK_ENABLE_DOWNLOAD_PROMPT=0
  node ~/.cache/node/corepack/v1/pnpm/11.7.0/bin/pnpm.cjs i --frozen-lockfile
  ```

  11.7.0 is the `packageManager` pin; if that moves, look for the matching
  directory under `~/.cache/node/corepack/v1/pnpm/`.

- `cfg.buildCmd` is `node .design-sync/prepare.mjs`. **Run it before every
  `package-build.mjs`.** It generates two things the repo does not otherwise
  produce (compiled CSS + a `.d.ts` tree) — details below. Nothing runs it for
  you: `buildCmd` is only a config field, never executed by `resync.mjs` or
  `package-build.mjs`.
- **The `.ds-sync/` install needs two deps beyond the skill's default three**
  (`esbuild ts-morph @types/react`), and `prepare.mjs` fails without the first:

  ```sh
  (cd .ds-sync && npm i esbuild ts-morph @types/react \
     @tailwindcss/cli@4.3.3 playwright@1.61.1)
  ```

  - `@tailwindcss/cli` — `prepare.mjs` runs it from
    `.ds-sync/node_modules/@tailwindcss/cli/dist/index.mjs`. Pin it to whatever
    `node_modules/tailwindcss/package.json` reports (see the re-sync risk below).
  - `playwright` — `package-validate.mjs` does a bare `import('playwright')`.
    pnpm's isolated layout only links `@playwright/test` at the top level, never
    `playwright`, so it will **not** resolve from `frontend/node_modules` and the
    render check silently degrades to `[RENDER_SKIPPED]`. Pick the version whose
    `browsers.json` pins a chromium build already in `~/.cache/ms-playwright/`
    (1.61.1 → chromium 1228) so no ~200 MB download is needed. `npm`'s
    `allow-scripts` warning about esbuild's blocked postinstall is harmless —
    the platform binary package still works.

## Scope

- Synced: `ui/` primitives plus shared app chrome (`layout/`, `navigation/`,
  `auth/UserMenu`, `history/`, `shared/`). **47 primary components.**
- Deliberately excluded: the ~130 feature components under `journals/`,
  `contacts/`, `integrations/`, `settings/`, `search/` — app features bound to
  the API and React Query, not design-system parts.
- `auth/AuthGuard` is excluded on purpose: a redirect gate that renders nothing.
- The 40 in-scope files export **158** components (shadcn compounds ship all
  their parts). All 158 are in the bundle and importable from `window.PMS`; only
  the 47 primaries get cards and `.d.ts` contracts, with parts composed into
  their parent's preview.

## The two generated inputs (`prepare.mjs`)

### Compiled CSS — Tailwind v4 source is not a stylesheet

`src/app/globals.css` is a Tailwind v4 **source** file (`@import 'tailwindcss'`).
Using it as `cfg.cssEntry` directly would ship `@import 'tailwindcss'` to the
browser and every component would render unstyled. `.design-sync/preview.css`
wraps it and `prepare.mjs` compiles to `.design-sync/.cache/compiled.css`.

**Re-run `prepare.mjs` after authoring or editing preview cards** — Tailwind only
emits utilities it can see, so classes used solely by a new card don't exist
until recompiled.

`tailwind.config.cjs` at the package root is **dead config** — v4 never loads it.
Plugins come from `@plugin` in `globals.css`.

### The `@source inline(...)` safelist — do not delete it

Scanning `src/` alone yields only the classes this app happens to use today.
`bg-sidebar`, `ring-ring`, `grid-cols-3`, `space-x-2`, `justify-around`,
`self-start` and all `min-h-*` were **absent**, verified independently by three
of the four authoring agents. That's fine for the app but wrong for a design
system: the design agent writes NEW layouts, and any missing utility renders
silently unstyled. `preview.css` therefore force-generates the semantic-token
vocabulary plus the common layout/spacing/typography scales (+29 KB, 138→167 KB).
**Keep it in sync with the class table in `conventions.md`** — that file tells the
agent those names are safe.

### Declaration tree — `.d.ts` prop contracts

The app is `noEmit`, so there was no declaration tree and **every `<Name>Props`
came out as `[key: string]: unknown`** — the design agent would have had no API
contract at all. `prepare.mjs` runs a declaration-only `tsc`
(`.design-sync/tsconfig.types.json`) into `frontend/types/`, which
`findTypesRoot()` discovers by convention.

Deliberately: `exportedNames()` reads only `<pkg>/index.d.ts`, which does not
exist, so this does **not** balloon the component list from 47 to 158.

The tsconfig excludes test helpers (`__tests__`, `__mocks__`, `test-utils/`,
`*test-helpers*`); without those exclusions tsc exits non-zero on missing `jest`
globals (it still emits, but a clean exit is worth having).

## Verified upstream bugs (present in the app, not artefacts of the sync)

1. **`dark:` variants are broken app-wide.** `globals.css:5` says the dark
   `@custom-variant` was "replaced for SonarQube compatibility", but nothing
   replaced it. Tailwind v4 therefore compiles `dark:*` to
   `@media (prefers-color-scheme: dark)` — following the OS — while the app
   toggles dark mode with a `.dark` **class** via next-themes. All 38 `dark:`
   utilities key off the wrong signal. Semantic token classes are unaffected
   (`.dark` redefines the variables), which is why `conventions.md` tells the
   design agent to use tokens and never write `dark:`.
2. **`text-destructive-foreground` does not exist.** `@theme inline` maps
   `--color-destructive` but never `--color-destructive-foreground`, so no
   utility is generated — confirmed absent from the compiled CSS while
   `.text-destructive` is present. **5 files use it**
   (`MergeResolutionDialog`, `ReviewQueueSidebar`, `ReviewSuggestions`,
   `TagManagementDialog`, …). It is a silent no-op in production. The working
   pair, used by `buttonVariants({variant:'destructive'})`, is
   `bg-destructive text-white`.
3. **Duplicate token blocks in `globals.css`.** Tokens are defined twice: an
   HSL-triplet set inside `@layer base { :root }` (~lines 8-51) and an oklch set
   in a plain unlayered `:root` (~lines 105-172). Unlayered beats layered, so
   **the oklch set wins** and the HSL block is dead weight. Same for `.dark`.

## `process` shim — required, keep it first

`.design-sync/process-shim.ts` must stay the **first import** in both
`ds-entry.ts` and `preview-providers.tsx`. The converter's esbuild pass replaces
the literal `process.env.NODE_ENV`, but `next/link` and the App Router internals
also read `process.env.__NEXT_ROUTER_BASEPATH`, `process.env.NEXT_RUNTIME`,
`process.nextTick` and friends. Without the shim the bare `process` identifier
reaches the browser and throws while the bundle is initialising — which leaves
`window.PMS` **undefined and every component unrenderable**. This presented as
`[BUNDLE_EXPORT] 47/47 not a component on window.PMS`.

## `sonner`: `toast` must be re-exported

`ds-entry.ts` exports `toast` from `sonner` deliberately. The bundle inlines its
own sonner copy and previews/designs get only react + this package as externals,
so a consumer's own `import { toast } from 'sonner'` pulls in a **second** sonner
whose store the bundled `<Toaster/>` never subscribes to — calls succeed and
nothing appears. Proven empirically: mounting both Toasters and firing one toast
produced exactly one, from the local copy.

## Preview context harness

`.design-sync/preview-providers.tsx` exports `DesignSyncProvider` (`cfg.provider`),
wrapping every card, because the app chrome reads context that only exists inside
a running Next app:

- `Sidebar` → `useSearchParams()` (null outside the router, then `.get()` throws)
  and `SidebarContext`
- `Breadcrumb` → `usePathname()` (null, then `.split()` throws)
- `Header`, `UserMenu` → `useAuth()`; `Header` also pulls in `GlobalSearch`,
  dragging React Query and the API client into the bundle
- `ActivityFeed` → self-fetches on mount

It supplies Next's `AppRouterContext` / `PathnameContext` / `SearchParamsContext`
/ `PathParamsContext`, a retry-disabled `QueryClient`, `next-themes`, and the
app's own `AuthProvider` + `SidebarProvider` + `TooltipProvider`.

**`AuthContext` is not exported** from `src/lib/auth/AuthProvider.tsx` — only
`AuthProvider` and `useAuth`. The only way to reach an authenticated state is
through the session request the provider makes on mount, so the harness stubs
`fetch` for `/api/auth/status` and returns a fixed preview user (Alex Taylor).
Everything else falls through to the real `fetch`.

## Authoring preview cards — accumulated technique

- **Forcing Radix overlays open is not uniform.** `AlertDialog` is always modal
  (`extends Omit<DialogProps,'modal'>`) so `modal={false}` is a _type error_;
  `HoverCard` has no `modal`; `DropdownMenuContent` has no `onOpenAutoFocus`
  (private to `MenuContentImpl`). `Dialog`/`Sheet`/`Popover` accept all three.
- **`ContextMenu` needs a replayed event.** It has `open`, but Radix anchors to
  the right-click point, which only a real `contextmenu` event populates —
  `open` alone pins the menu to (0,0) and looks broken. The card dispatches
  `new MouseEvent('contextmenu', {bubbles:true, clientX, clientY})` from the
  trigger's rect on mount; the offsets double as framing control.
- **Radix opens on `pointerdown`, not `click`.** `el.click()` opens a Sheet but
  does nothing to a DropdownMenu trigger.
- **`UserMenu` renders `null` until the session query resolves**, so a one-shot
  mount effect finds no trigger — poll until the node exists. Any card driving a
  control inside an auth/query-gated component needs the same.
- **`modal={false}` also removes the scrim** (`DialogOverlay` returns `null` when
  non-modal), so Sheet cards show no dimmed backdrop. Correct behaviour — don't
  "fix" it.
- **`position: fixed` chrome escapes its cell.** `DesktopSidebar` is `md:fixed`;
  a wrapper with `transform: translateZ(0)` makes it the containing block.
- **Capture pins the page clock to 2024-05-15T12:00:00Z**, which is why history
  fixtures sit in May 2024 — otherwise `formatDistanceToNow` reads "2 years ago".
- **`ScrollArea` needs `type='always'`** or a static screenshot shows no
  scrollbar and the card reads as a plain clipped box.
- **`CollapsibleTrigger` is the raw Radix primitive** — wrap it in
  `<Button asChild>` or it renders browser-default.
- **`LoadingOverlay`'s veil is `absolute inset-0` on its wrapper** — put the
  width on the overlay, not the child, or the spinner centres wrong.
- **`AvatarImage` needs a `data:` URI** — capture has no network.
- **`Select` has no `onOpenAutoFocus`**; not needed, Radix highlights the
  selected item, which reads as intentional.
- **Form error states**: `form.setError()` in a `useEffect` is the reliable way
  to render `FormMessage` + `aria-invalid` statically; a resolver needs a submit.
- **`Command`**: use `shouldFilter={false}` — matches the product (MeiliSearch
  ranks server-side) and makes the render deterministic.
- **Grep the compiled CSS with the escaped form.** `grep 'sm:grid-cols-3'`
  returns 0 for a class that IS present — it is stored as `.sm\:grid-cols-3`.

## Known render warns

- `ThemeToggle` can only ever be captured in light theme (the moon glyph is
  behind a `dark:` variant — see upstream bug 1). Its cells are "bare" and
  "in context"; it takes no props.
- `ButtonLoading` hard-codes `h-4` for its spinner, so a size axis only varies
  the surrounding Button — a `variants render identically` warn here is legitimate.

## Grouping

`componentSrcMap` src paths put every `ui/` component in group `general` (the
converter drops `components` and `ui` as generic directory names). Groups come
from stub docs in `.design-sync/docs/<Name>.md` carrying only
`---\ncategory: <Group>\n---`, wired via `cfg.docsMap`. Note the dir-derived
group wins when it is not `general`, which is why the chrome components land in
`layout` / `navigation` / `auth` / `history` / `shared` rather than the
categories their stubs name. Adding a component means adding its stub too.

## LSP noise (ignore)

Editor diagnostics on `.design-sync/previews/*.tsx` — "Cannot find module
'personal-management-frontend'" and "'React' refers to a UMD global" — are
expected. The package specifier is resolved by the converter's shim at
preview-compile time and JSX runtime comes from esbuild; `.design-sync/` is a
dot-directory so `tsc -p` never includes it. `pnpm type-check` is unaffected.

## Repo tooling interactions

- **Prettier scans `.design-sync/`** (it is not in `.prettierignore`), so
  `pnpm format:check` fails if the preview `.tsx` files are unformatted. Keep
  them Prettier-clean. **Formatting a preview changes its source hash and
  therefore clears its grade**, forcing a re-capture and re-grade — so run
  `prettier --write .design-sync` BEFORE grading, not after. That cost a full
  re-grade of 16 components on the first sync.
- **ESLint** ignores `.ds-sync/**`, `ds-bundle/**`, `types/**` and `index.d.ts`
  via `eslint.config.js` — those are generated/staged and would otherwise add
  ~210 errors to `pnpm lint`. The committed `.design-sync/` sources lint clean.
- **Stale Next route types break `pnpm type-check` and the pre-commit hook.**
  With `typedRoutes: true`, `tsc` reads generated definitions from
  `.next/dev/types/`. In a fresh worktree these are missing or predate newer
  routes, producing errors like
  `Type '`/journals/series/${string}`' is not assignable to type
'UrlObject | RouteImpl<…>'` in files you never touched. This is **not** a real
  type error — run `./node_modules/.bin/next typegen` (a few seconds, no full
  build) and it clears. **`next typegen` also rewrites the tracked
  `next-env.d.ts`**, flipping its import from `./.next/dev/types/routes.d.ts` to
  `./.next/types/routes.d.ts` (the dev server writes the `dev/` variant). That
  shows up as a stray modified file with nothing to do with the sync —
  `git checkout -- frontend/next-env.d.ts` once the build is done.

## Reading the re-sync verdict: DS-source-only changes grade nothing

A change to the **app's** component source with no change to
`.design-sync/previews/` yields `changed: []`, `pendingGrade: []` and
`capture: skipped "empty_worklist"` — while `upload.any` is still true. That is
correct, not a broken diff: `sourceKeys` are keyed on the authored previews and
preview-affecting config, so DS source edits re-upload bytes
(`upload.bundle` / `upload.styling`) without re-grading cards.

Worked example — the `ui/loading.tsx` Skeleton collapse (#1177): 47/47
`unchanged`, nothing to grade, `bundleSha12` and `styleSha` both moved. Diffing
the old anchor against the freshly built `ds-bundle/_ds_sync.json` showed **zero
differing `renderHashes`**, which is machine proof that the refactor was visually
a no-op. That diff is the cheapest way to verify a "no visual change" claim:

```sh
python3 -c "
import json; a=json.load(open('.design-sync/.cache/remote-sync.json')); b=json.load(open('ds-bundle/_ds_sync.json'))
print([k for k in b['renderHashes'] if a['renderHashes'].get(k)!=b['renderHashes'][k]])"
```

Also note `scriptsSha`: identical between anchors means the skill scripts have not
moved, which is why `canary` is `null` and no `[SPOT_CHECK]` sheets appear.

## Re-sync risks

- **Next internals.** `preview-providers.tsx` imports
  `next/dist/shared/lib/app-router-context.shared-runtime` and
  `hooks-client-context.shared-runtime` — not public API. If the chrome
  components render blank or throw router errors after a Next major bump, check
  those paths first. Currently Next 16.
- **The session stub is keyed on the literal `/api/auth/status`**, mirroring
  `API_ENDPOINTS.AUTH.SESSION`. If that constant moves, the stub silently stops
  matching and the chrome renders logged-out instead of failing loudly.
- **`process.env.__NEXT_*` names** are Next-internal; a bump could add a new one
  the shim's empty `env` handles fine, but a bare non-`env` `process` member
  would need adding to the shim.
- **The safelist is hand-maintained.** New semantic tokens added to
  `@theme inline` won't reach the design agent until listed in `preview.css`.
- **`prepare.mjs` pins the Tailwind CLI to 4.3.3 in `.ds-sync/`.** If the repo's
  `tailwindcss` version moves, bump the CLI to match or the compiled output can
  drift from what `next build` produces.
- Preview cards that drive real controls (`MobileSidebar`, `UserMenu`,
  `ActivityItem`, `ContextMenu`) depend on current DOM structure and Radix event
  semantics; they are the first to break on a Radix upgrade.
