// Design-system barrel for design-sync.
//
// This repo is a Next.js app, not a published component library, so there is no
// `dist/` entry to bundle. This file is that entry: it re-exports the real,
// unmodified components from `src/components/` — nothing here reimplements
// anything. Scope is the design-system surface (ui/ primitives plus the shared
// app chrome), deliberately excluding the feature components under
// journals/, contacts/, integrations/, settings/ and search/.

// MUST stay first: ESM evaluates imports in order, so this installs the
// `process` global before any Next.js module that reads it initialises.
import './process-shim';

export * from '../src/components/ui/alert-dialog';
export * from '../src/components/ui/alert';
export * from '../src/components/ui/avatar';
export * from '../src/components/ui/badge';
export * from '../src/components/ui/button';
export * from '../src/components/ui/calendar';
export * from '../src/components/ui/card';
export * from '../src/components/ui/checkbox';
export * from '../src/components/ui/collapsible';
export * from '../src/components/ui/command';
export * from '../src/components/ui/context-menu';
export * from '../src/components/ui/dialog';
export * from '../src/components/ui/dropdown-menu';
export * from '../src/components/ui/form';
export * from '../src/components/ui/hover-card';
export * from '../src/components/ui/input';
export * from '../src/components/ui/label';
export * from '../src/components/ui/loading';
export * from '../src/components/ui/popover';
export * from '../src/components/ui/radio-group';
export * from '../src/components/ui/scroll-area';
export * from '../src/components/ui/select';
export * from '../src/components/ui/separator';
export * from '../src/components/ui/sheet';
export * from '../src/components/ui/skeleton';
export * from '../src/components/ui/sonner';
export * from '../src/components/ui/switch';
export * from '../src/components/ui/table';
export * from '../src/components/ui/textarea';
export * from '../src/components/ui/theme-toggle';
export * from '../src/components/ui/toggle';
export * from '../src/components/ui/tooltip';

// The bundle inlines its own copy of sonner, and previews/designs only get
// react + this package as externals. Without re-exporting `toast` here, a
// consumer's own `import { toast } from 'sonner'` pulls in a SECOND sonner whose
// toast store the bundled <Toaster/> never subscribes to — calls succeed and
// nothing ever appears. Re-exporting binds callers to the same instance.
export { toast } from 'sonner';

// Shared app chrome.
export * from '../src/components/shared/ExternalLinksDisplay';
export * from '../src/components/layout/Header';
export * from '../src/components/layout/Sidebar';
export * from '../src/components/navigation/Breadcrumb';
export * from '../src/components/auth/UserMenu';
export * from '../src/components/history/ActivityFeed';
export * from '../src/components/history/ActivityItem';
