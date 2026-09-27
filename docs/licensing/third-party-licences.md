# Third-Party Licence Audit

The dependency licence audit required by the
[Open-Source Release & Branding spec, Part 1](../product-specifications/open-source-release-and-branding-product-specification.md#part-1-licensing)
and delivered by
[ITER19-002 Phase 3](../tasks/iteration-19-open-source-release-and-branding.md#iter19-002-licensing--contribution-model).
It records whether every runtime dependency's licence is compatible with this project's
`AGPL-3.0-or-later` licence. An incompatible licence blocks the release (ITER19-005 Phase 2) unless it
is replaced or the owner grants a section 7 exception in [`LICENSE-EXCEPTIONS.md`](../../LICENSE-EXCEPTIONS.md).

**Result: no blocking licence.**

- Every runtime dependency is permissive or weak copyleft, with two exceptions:
  - `react-leaflet` and `@react-leaflet/core` (Hippocratic-2.1) are **not** AGPL-compatible. They
    are combined under the project's
    [section 7 additional permission](../../LICENSE-EXCEPTIONS.md) (owner decision, 2026-09-27).
  - `caniuse-lite` (CC-BY-4.0) is a data licence that is GPLv3-compatible.
- No package has an unknown licence.

| | |
|---|---|
| **Date** | 2026-09-27 |
| **Platform** | linux x86_64 (glibc), Python 3.14, uv 0.11.15, pip-licenses 5.5.5, pnpm 11.7.0 |
| **Commit** | `main` at `52f32d7040` |

## Scope

**In scope:**

- The runtime (non-dev) dependencies of the six Python projects: `backend`, `core_shared` and the
  `google`, `immich`, `snipeit` and `strava` integration workers.
- The frontend's production dependencies.
- The frontend's devDependencies, because `docker/frontend/Dockerfile` runs a full
  `pnpm install` with no prune, so the published image ships them. They are checked for
  redistributability only; see [Frontend devDependencies](#frontend-devdependencies-shipped-in-the-image).

**Out of scope:**

- Python dev extras (pytest, mypy, ruff, …): the production images install `.` without extras.
- `docker/oauth-login-consent` and `docker/oauth-ui`: dev and test OAuth fixtures (the
  compose `dev`/`test` profiles), never deployed.
- OS packages in the Docker base images (Debian/Alpine): these are covered by their
  distributions' own licence notices.
- The project's own packages (`core_shared`, the workers, the backend), which are AGPL.

## Licence families

| Family | Licences seen |
|---|---|
| Permissive | MIT, MIT-CMU, Apache-2.0, BSD-2/3-Clause, ISC, 0BSD, PSF-2.0, Unlicense |
| Weak copyleft | LGPL-2.1/3.0, MPL-2.0 |
| Strong copyleft | none among the runtime dependencies |
| Other | Hippocratic-2.1, CC-BY-4.0 |
| Unknown | none |

- Packages offered under a choice of licences are counted under the one this project uses them
  under: `dompurify` counts as Permissive (Apache-2.0).
- `docutils` also counts as Permissive. Its metadata lists GPL, but the only GPL file is an
  Emacs mode (`tools/editors/emacs/rst.el`) that is not in the wheel. The installed library is
  public domain or BSD-2-Clause.

## Counts

Totals equal the resolved production dependency set of each project, deduplicated by package name.

| Ecosystem | Resolved production set | Permissive | Weak copyleft | Other |
|---|---:|---:|---:|---:|
| `backend` | 147 | 143 | 4 | 0 |
| `core_shared` | 41 | 39 | 2 | 0 |
| `integration_workers/google` | 64 | 62 | 2 | 0 |
| `integration_workers/immich` | 51 | 49 | 2 | 0 |
| `integration_workers/snipeit` | 51 | 49 | 2 | 0 |
| `integration_workers/strava` | 51 | 49 | 2 | 0 |
| Python, unique across projects | 147 | 143 | 4 | 0 |
| `frontend` (production) | 363 | 346 | 14 | 3 |

Notes on the counts:

- **Python:** four backend packages are installed only on other platforms, so `pip-licenses` does
  not see them on Linux. Their licences were read from PyPI:
  - `colorama` (Windows): BSD-3-Clause. Also a dependency of every worker.
  - `pywin32` (Windows): PSF-2.0.
  - `pywin32-ctypes` (Windows): BSD-3-Clause.
  - `httpx2-jsfetch` (emscripten): BSD-3-Clause.
- **Frontend:** the 363 are the distinct `name@version` pairs in the `pnpm list` tree.
  - 330 are installed on linux-x64-gnu, and `pnpm licenses list --prod` reports those.
  - The other 33 are optional per-platform binaries for other platforms (`@img/sharp-*`,
    `@img/sharp-libvips-*`, `@next/swc-*`, `fsevents`, `@emnapi/runtime`). Their licences were
    read with `npm view <pkg>@<version> license`.
  - The production image (`node:26-alpine`) installs the `linuxmusl-x64` / `x64-musl` variants.

## Non-permissive runtime dependencies

| Package | Version | Licence | Used by | Verdict |
|---|---|---|---|---|
| `psycopg2-binary` | 2.9.13 | LGPL-3.0 (with exceptions) | all Python projects | **Compatible.** A dynamically loaded library. LGPLv3 is compatible with GPLv3 and so with AGPLv3. |
| `pycountry` | 26.2.16 | LGPL-2.1-only | backend | **Compatible.** Imported, not modified. LGPL-2.1 section 3 permits applying GPLv2-or-later instead, which is AGPLv3-combinable via GPLv3 section 13. |
| `python-stdnum` | 2.2 | LGPL-2.1-or-later | backend | **Compatible**, for the same reasons. |
| `certifi` | 2025.4.26 – 2026.5.20 | MPL-2.0 | all Python projects | **Compatible.** File-level copyleft, and MPL-2.0 section 3.3 permits combination with GPL-family code. The CA bundle is used unmodified. |
| `docutils` | 0.22.3 | Public domain / BSD-2-Clause (metadata also lists GPL) | backend, via `fastmcp` → `cyclopts` → `rich-rst` | **Compatible.** The GPL-3.0-or-later file (the Emacs mode) is not in the wheel, and it would be compatible anyway. |
| `@img/sharp-libvips-*` (10 platforms) | 1.3.3 | LGPL-3.0-or-later | frontend (server-side Next.js image optimisation) | **Compatible.** A dynamically loaded native library that is never sent to the browser. |
| `@img/sharp-win32-*`, `@img/sharp-wasm32` (4) | 0.35.4 | Apache-2.0 AND LGPL-3.0-or-later (wasm32 also MIT) | frontend (other platforms only) | **Compatible.** These bundle libvips (LGPL). |
| `dompurify` | 3.4.14 | MPL-2.0 OR Apache-2.0 | frontend | **Compatible.** Used under Apache-2.0. |
| `caniuse-lite` | 1.0.30001810 | CC-BY-4.0 | frontend (browser-support data for Next.js/browserslist) | **Compatible.** The FSF lists CC-BY-4.0 as GPLv3-compatible. Attribution is kept in the package. |
| `react-leaflet` | 5.0.0 | Hippocratic-2.1 | frontend: `src/components/journals/GPXTrackMap.tsx` | **Not AGPL-compatible**, because its human-rights use conditions and arbitration clause are "further restrictions" under AGPL section 10. **Combined under the project's section 7 additional permission** in [`LICENSE-EXCEPTIONS.md`](../../LICENSE-EXCEPTIONS.md). The package itself stays under HL-2.1, so anyone who conveys the frontend must also meet its conditions. |
| `@react-leaflet/core` | 3.0.0 | Hippocratic-2.1 | frontend, via `react-leaflet` | As for `react-leaflet`. |

### Non-package assets

- **Inter font** (`next/font/google` in `frontend/src/app/layout.tsx`): SIL OFL-1.1, downloaded
  and self-hosted at build time. OFL permits bundling with software under any licence.
- **OpenStreetMap tiles** (ODbL data): not a code dependency. ODbL requires attribution, and
  both places that render tiles show it. Keep both:
  - the logbook PDF, via `_OSM_ATTRIBUTION` in
    `backend/app/core/journal/adapters/http/osm_tile_source.py`;
  - the frontend map's `TileLayer` attribution in `frontend/src/components/journals/GPXTrackMap.tsx`.

### Frontend devDependencies (shipped in the image)

- There are 589 packages that are devDependencies only (`pnpm licenses list --json` minus the
  production set).
- They are build and test tools (TypeScript, Jest, Playwright, ESLint, Tailwind's
  `lightningcss`, …). They sit alongside the program in the image as **mere aggregation**; they
  are not combined into it. The only requirement is that they may be redistributed.
- The non-permissive ones are listed below. All are redistributable, and each package ships its
  licence file in `node_modules`.

| Package | Version | Licence |
|---|---|---|
| `axe-core` | 4.12.1 | MPL-2.0 |
| `lightningcss`, `lightningcss-linux-x64-gnu` | 1.32.0 | MPL-2.0 |
| `caniuse-lite` | 1.0.30001806 | CC-BY-4.0 |

## Caveats

- **Python images resolve from `pyproject.toml`, not `uv.lock`.** The images run
  `uv pip install --system .` (`docker/backend/Dockerfile`, `docker/python-base/Dockerfile`).
  This audit covers the lockfile versions. A newer release that changes its licence is not caught
  until the audit is re-run.
- **Package metadata only.** The tools read each package's declared licence and do not see
  content bundled inside wheels. The notable bundled content, checked by hand:
  - `psycopg2-binary` ships `libpq` (PostgreSQL), OpenSSL 3 (Apache-2.0), MIT Kerberos,
    OpenLDAP, Cyrus SASL and PCRE (all permissive), plus `libxcrypt` and `keyutils`
    (LGPL-2.1-or-later).
  - `pillow` ships libjpeg, libpng, libtiff, libwebp, libavif, freetype, harfbuzz, lcms2, zstd,
    brotli, xz and openjpeg, all permissive.
  - `reportlab` ships the Bitstream Vera fonts (permissive), Type 1 fonts under ReportLab's own
    BSD licence, and the DarkGarden font, which is GPL-2.0-or-later with a font-embedding exception. That is
    compatible, and this project does not use it.
- **Notices in the browser bundle.** Minified JavaScript drops licence headers.
  - This affects the MIT/BSD notices and the Hippocratic notice in the same way.
  - The image carries every package's licence file under `node_modules`, but the bundle served
    to browsers does not.
  - Follow-up (not a release blocker): serve a generated third-party notices file from the
    frontend. This is scheduled in
    [ITER19-005 Phase 1](../tasks/iteration-19-open-source-release-and-branding.md#iter19-005-repository-rename--go-public).

## Regenerating the audit

Run from the repository root. Scratch environments go in a temporary directory, so the working
virtualenvs are untouched.

```bash
OUT=$(mktemp -d)
for p in backend core_shared integration_workers/{google,immich,snipeit,strava}; do
  n=$(basename "$p")
  # The resolved production set (the count's source of truth)
  (cd "$p" && uv export --no-dev --frozen --no-hashes --no-emit-project > "$OUT/$n.req")
  # Licences, from a --no-dev environment
  (cd "$p" && UV_PROJECT_ENVIRONMENT="$OUT/venv-$n" uv sync --no-dev --frozen -q)
  uv pip install -q --python "$OUT/venv-$n/bin/python" pip-licenses
  "$OUT/venv-$n/bin/pip-licenses" --format=json --with-urls \
    --ignore-packages pip-licenses prettytable wcwidth > "$OUT/$n.json"
done

cd frontend && pnpm install --frozen-lockfile
pnpm list --prod --depth Infinity --json > "$OUT/fe-list.json"   # the resolved production set
pnpm licenses list --prod --json > "$OUT/fe-lic.json"            # installed production licences
pnpm licenses list --json > "$OUT/fe-lic-all.json"               # plus devDependencies
```

Then reconcile and count:

- **Python:** compare the package names in each `.req` file with the names in the matching
  `.json` file. Names missing from the JSON are platform-marker-only packages; look them up on
  PyPI.
- **Frontend:** walk every `dependencies` and `optionalDependencies` node of `fe-list.json`,
  recursing into nodes marked `deduped`, to collect distinct `name@version` pairs. Pairs missing
  from `fe-lic.json` are other-platform binaries; run `npm view <pkg>@<version> license` for each.
- **Families:** assign each licence a family with the table in [Licence families](#licence-families).
  Any Strong copyleft, Other or Unknown result that is not already listed above is a new
  finding, and it goes to the owner before the release.
