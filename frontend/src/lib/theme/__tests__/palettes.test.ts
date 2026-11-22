/**
 * @jest-environment jsdom
 */

import {
  PALETTE_ATTRIBUTE,
  PALETTE_BOOTSTRAP_SCRIPT,
  PALETTE_STORAGE_KEY,
  applyPalette,
  cachePalette,
  isThemePalette,
  readCachedPalette,
  resetPalette,
} from '../palettes';

const root = document.documentElement;

/** Runs the inline <head> script the way the browser does, before React. */
function runBootstrapScript() {
  new Function(PALETTE_BOOTSTRAP_SCRIPT)();
}

describe('theme palettes', () => {
  beforeEach(() => {
    localStorage.clear();
    root.removeAttribute(PALETTE_ATTRIBUTE);
    jest.restoreAllMocks();
  });

  describe('isThemePalette', () => {
    it.each(['default', 'emerald'])('accepts %s', value => {
      expect(isThemePalette(value)).toBe(true);
    });

    it.each(['Emerald', 'rainbow', '', null, undefined, 3])(
      'rejects %p',
      value => {
        expect(isThemePalette(value)).toBe(false);
      }
    );
  });

  describe('applyPalette', () => {
    it('marks <html> with a non-default palette', () => {
      applyPalette('emerald');

      expect(root.getAttribute(PALETTE_ATTRIBUTE)).toBe('emerald');
    });

    it('removes the attribute for the default palette', () => {
      root.setAttribute(PALETTE_ATTRIBUTE, 'emerald');

      applyPalette('default');

      expect(root.hasAttribute(PALETTE_ATTRIBUTE)).toBe(false);
    });
  });

  describe('the localStorage mirror', () => {
    it('reads back a cached palette', () => {
      cachePalette('emerald');

      expect(readCachedPalette()).toBe('emerald');
    });

    it('does not cache the default palette', () => {
      cachePalette('emerald');
      cachePalette('default');

      expect(localStorage.getItem(PALETTE_STORAGE_KEY)).toBeNull();
    });

    it('ignores a cached value the app does not ship', () => {
      localStorage.setItem(PALETTE_STORAGE_KEY, 'rainbow');

      expect(readCachedPalette()).toBe('default');
    });

    it('answers the default when storage is unavailable', () => {
      jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError');
      });

      expect(readCachedPalette()).toBe('default');
    });

    it('resetPalette clears the cache and the attribute', () => {
      cachePalette('emerald');
      applyPalette('emerald');

      resetPalette();

      expect(localStorage.getItem(PALETTE_STORAGE_KEY)).toBeNull();
      expect(root.hasAttribute(PALETTE_ATTRIBUTE)).toBe(false);
    });
  });

  describe('the blocking <head> script', () => {
    it('applies the cached palette before first paint', () => {
      localStorage.setItem(PALETTE_STORAGE_KEY, 'emerald');

      runBootstrapScript();

      expect(root.getAttribute(PALETTE_ATTRIBUTE)).toBe('emerald');
    });

    it('leaves <html> alone for an unknown cached value', () => {
      localStorage.setItem(PALETTE_STORAGE_KEY, '"><script>');

      runBootstrapScript();

      expect(root.hasAttribute(PALETTE_ATTRIBUTE)).toBe(false);
    });

    it('never throws when storage is unavailable', () => {
      jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('SecurityError');
      });

      expect(runBootstrapScript).not.toThrow();
      expect(root.hasAttribute(PALETTE_ATTRIBUTE)).toBe(false);
    });
  });
});
