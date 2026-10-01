// Browser shim for `process`, imported first by both bundle entries.
//
// The converter's esbuild pass replaces the literal `process.env.NODE_ENV`, but
// the app chrome pulls in `next/link` and the App Router internals, which also
// read `process.env.__NEXT_ROUTER_BASEPATH`, `process.env.NEXT_RUNTIME`,
// `process.nextTick` and friends. Next's own build defines those; a plain
// esbuild bundle does not, so the bare `process` identifier reaches the browser
// and throws `ReferenceError: process is not defined` while the bundle is
// initialising — which leaves `window.Lifecontour` undefined and every component
// unrenderable.
//
// Leaving `env` empty is correct: each of those flags is optional, and Next
// treats `undefined` as "not set", which is what we want in a static preview.

interface ProcessShim {
  env: Record<string, string | undefined>;
  nextTick: (fn: (...args: unknown[]) => void, ...args: unknown[]) => void;
  browser: boolean;
  platform: string;
  version: string;
  versions: Record<string, string>;
}

// Cast through `unknown`: intersecting with the real `NodeJS.Process` type from
// @types/node would demand every field of it, which a browser shim can't supply.
const g = globalThis as unknown as { process?: ProcessShim };

if (typeof g.process === 'undefined') {
  g.process = {
    env: {},
    nextTick: (fn, ...args) => {
      void Promise.resolve().then(() => fn(...args));
    },
    browser: true,
    platform: 'browser',
    version: '',
    versions: {},
  };
} else if (typeof g.process.env === 'undefined') {
  g.process.env = {};
}

export {};
