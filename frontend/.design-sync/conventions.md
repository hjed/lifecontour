## How to build with this system

These are the real components from the Lifecontour app (a self-hosted journal,
people and adventures app): shadcn/ui "new-york" primitives on Radix, styled
with Tailwind CSS v4 and a semantic CSS-variable theme. Australian English and
metric units throughout; dates read like `14 July 2026`.

### Wrap the tree in `DesignSyncProvider`

```jsx
const { DesignSyncProvider, Card, CardHeader, CardTitle, Button } =
  window.Lifecontour;

<DesignSyncProvider>{/* your design here */}</DesignSyncProvider>;
```

The plain form primitives render fine without it, but anything with app chrome
or portal behaviour needs it, and it costs nothing to always use it. It supplies
the Next.js App Router context (`Header`, `Sidebar`, `Breadcrumb`, `UserMenu`
call `usePathname()` / `useSearchParams()` and **throw** without it), a
TanStack Query client, `next-themes`, the app's auth context (previews render as
a signed-in user), and `TooltipProvider` — so `Tooltip` works anywhere.

It takes an optional `pathname` prop (default `/journals`) to set which nav item
the chrome shows as active.

### Styling: Tailwind v4 utilities over semantic tokens

Style your own layout with Tailwind utility classes. **Always prefer the
semantic token classes below over raw palette colours** (`bg-neutral-900`,
`text-gray-500`) — the tokens are what make light and dark mode work.

| Purpose           | Classes                                                                       |
| ----------------- | ----------------------------------------------------------------------------- |
| Page surface      | `bg-background` `text-foreground`                                             |
| Raised surface    | `bg-card` `text-card-foreground` `bg-popover` `text-popover-foreground`       |
| Emphasis / CTA    | `bg-primary` `text-primary-foreground`                                        |
| Quiet fill        | `bg-secondary` `text-secondary-foreground` `bg-muted` `text-muted-foreground` |
| Hover / highlight | `bg-accent` `text-accent-foreground`                                          |
| Danger            | `bg-destructive` `text-destructive`                                           |
| Lines & focus     | `border-border` `border-input` `ring-ring`                                    |
| Nav surface       | `bg-sidebar` `text-sidebar-foreground` `bg-sidebar-accent`                    |
| Data viz          | `bg-chart-1` … `bg-chart-5`                                                   |

Each works with the `bg-` / `text-` / `border-` / `ring-` prefix. Radius follows
`--radius`: `rounded-sm|md|lg|xl`. Spacing, `grid-cols-*`, `max-w-*`,
`text-xs…5xl`, `font-medium|semibold|bold`, `shadow-xs…xl` and the `sm:` `md:`
`lg:` breakpoints are all available.

**Do not use `dark:` variants.** This app toggles dark mode with a `.dark` class,
but no `@custom-variant dark` is defined, so Tailwind compiles `dark:*` to
`@media (prefers-color-scheme: dark)` — it follows the OS, not the app, and will
desync from everything else on the page. The semantic tokens above already
switch correctly under `.dark`, so use them and write no dark-mode CSS at all.
To preview dark mode, put `class="dark"` on a wrapping element.

There is no exported `cn()` helper — pass plain `className` strings.

### Where the truth is

- `_ds/<folder>/styles.css` and the `_ds_bundle.css` it imports — every class and
  token that actually exists. If unsure a utility is available, look here.
- `components/<group>/<Name>/<Name>.prompt.md` — per-component usage.
- `components/<group>/<Name>/<Name>.d.ts` — the real prop contract, including
  variant unions (e.g. `Button` takes
  `variant?: "default" | "secondary" | "destructive" | "outline" | "link" | "ghost"`
  and `size?: "default" | "sm" | "lg" | "icon"`).

Compound components ship all their parts on `window.Lifecontour` even though
only the parent has a card: `Card` + `CardHeader` / `CardTitle` / `CardDescription` /
`CardContent` / `CardFooter`; `Dialog` + `DialogTrigger` / `DialogContent` /
`DialogHeader` / `DialogTitle` / `DialogDescription` / `DialogFooter`; likewise
for `Select`, `DropdownMenu`, `ContextMenu`, `Table`, `Sheet`, `Command`,
`AlertDialog`, `Popover`, `HoverCard`, `Tooltip`, `Collapsible`, `Avatar`,
`Alert`, `RadioGroup`, `ScrollArea` and `Form`.

### Idiomatic example

```jsx
const {
  DesignSyncProvider,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Badge,
  Button,
} = window.Lifecontour;

<DesignSyncProvider>
  <div className='bg-background text-foreground grid gap-4 p-6 sm:grid-cols-2'>
    <Card>
      <CardHeader>
        <CardTitle>Coffee with Priya</CardTitle>
        <CardDescription>Logged 3 days ago</CardDescription>
      </CardHeader>
      <CardContent className='space-y-3'>
        <p className='text-muted-foreground text-sm'>
          Caught up at Patricia. Moving to the Melbourne office in September.
        </p>
        <div className='flex gap-2'>
          <Badge variant='secondary'>catch-up</Badge>
          <Badge variant='secondary'>work</Badge>
        </div>
        <Button size='sm'>Open entry</Button>
      </CardContent>
    </Card>
  </div>
</DesignSyncProvider>;
```
