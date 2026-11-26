/**
 * Radix's Avatar tracks image loading via a detached `new window.Image()` and only
 * renders the <img> once it reports "loaded" (otherwise the initials fallback shows).
 * jsdom never fires load/error events on images, so we mock window.Image to drive the
 * load/error state machine deterministically. URLs containing "broken" simulate an
 * error; any other URL simulates a successful load.
 */
type MockImageListener = (event: { currentTarget: MockImage }) => void;

export class MockImage {
  private listeners: Record<string, MockImageListener[]> = {};
  naturalWidth = 0;
  complete = false;
  referrerPolicy = '';
  crossOrigin: string | null = null;
  private _src = '';

  addEventListener(event: string, cb: MockImageListener): void {
    this.listeners[event] = [...(this.listeners[event] ?? []), cb];
  }

  removeEventListener(event: string, cb: MockImageListener): void {
    this.listeners[event] = (this.listeners[event] ?? []).filter(
      listener => listener !== cb
    );
  }

  private dispatch(event: string): void {
    // Radix's load handler reads `event.currentTarget` to inspect the image's
    // `complete`/`naturalWidth` state, so pass the image itself as the target.
    (this.listeners[event] ?? []).forEach(cb => cb({ currentTarget: this }));
  }

  set src(value: string) {
    this._src = value;
    const shouldFail = value.includes('broken');
    // Defer so React's effects can register listeners before we dispatch.
    queueMicrotask(() => {
      if (shouldFail) {
        this.dispatch('error');
      } else {
        this.naturalWidth = 100;
        this.complete = true;
        this.dispatch('load');
      }
    });
  }

  get src(): string {
    return this._src;
  }
}
