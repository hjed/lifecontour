# Third-Party Notices: Vendored Skills

Most skills in this directory are written for this project and are covered by the repository's
[`LICENSE`](../../LICENSE) (AGPL-3.0-or-later). Two are third-party skills installed with the
[`skills`](https://github.com/vercel-labs/skills) CLI and pinned in
[`skills-lock.json`](../../skills-lock.json). They keep their own licences, listed below.

Their folders are kept exactly as installed, so `npx skills update` can refresh them. Their
notices therefore live in this file rather than inside those folders. Names and logos inside
them, such as the shadcn logo images in `shadcn/assets/`, belong to their owners. They are not
part of this project's work and are not covered by its licence.

| Skill | Source | Licence |
|---|---|---|
| [`playwright-skill/`](./playwright-skill/) | [testdino-hq/playwright-skill](https://github.com/testdino-hq/playwright-skill) | MIT, see [`playwright-skill/LICENSE`](./playwright-skill/LICENSE) |
| [`shadcn/`](./shadcn/) | [shadcn-ui/ui](https://github.com/shadcn-ui/ui) (`skills/shadcn`) | MIT, reproduced below |

## shadcn/ui

The upstream skill folder ships without a licence file. The following is the licence of the
[shadcn/ui repository](https://github.com/shadcn-ui/ui/blob/main/LICENSE.md) it comes from:

```text
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
