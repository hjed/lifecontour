/**
 * Shared mock for Next.js' `AppRouterInstance`.
 *
 * Every test that mocks `useRouter()` should build its router from here, so a
 * new member on `AppRouterInstance` is a one-line change rather than a hunt
 * through each test file that hand-rolls the same object.
 */

/**
 * Creates a fresh mock router with one `jest.fn()` per navigation method.
 *
 * Each call returns a new set of mocks, so tests never share call history.
 * Spread the result to override a single method while keeping a handle on it:
 *
 * ```ts
 * const push = jest.fn();
 * const router = { ...createMockAppRouter(), push };
 * ```
 *
 * The return type is deliberately left inferred rather than annotated
 * `: AppRouterInstance`. `bfcacheId` only exists on that interface from Next
 * 16.3 onwards, and annotating would make this object literal fail the excess
 * property check on 16.2.x. Inference satisfies both, since the extra property
 * is accepted when the result is later assigned. Once the 16.3 bump has landed
 * on main, this can be annotated for real type safety.
 */
export const createMockAppRouter = () => ({
  push: jest.fn(),
  replace: jest.fn(),
  prefetch: jest.fn(),
  back: jest.fn(),
  forward: jest.fn(),
  refresh: jest.fn(),
  // Added to AppRouterInstance in Next 16.3: an opaque identifier for the
  // current route segment, intended to be passed to a React `key`.
  bfcacheId: 'test-bfcache-id',
});
