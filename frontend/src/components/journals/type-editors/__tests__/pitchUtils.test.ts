import { countAbseils, isAbseilPitch, PITCH_TYPES } from '../pitchUtils';
import type { AbseilPitch } from '@/types/journals';

describe('pitchUtils', () => {
  describe('isAbseilPitch', () => {
    it('treats a null or missing pitch_type as an abseil', () => {
      expect(isAbseilPitch({ pitch_number: 1 })).toBe(true);
      expect(isAbseilPitch({ pitch_number: 1, pitch_type: null })).toBe(true);
    });

    it('treats an explicit abseil type as an abseil', () => {
      expect(isAbseilPitch({ pitch_number: 1, pitch_type: 'abseil' })).toBe(
        true
      );
    });

    it('does not treat jumps or down climbs as abseils', () => {
      expect(isAbseilPitch({ pitch_number: 1, pitch_type: 'jump' })).toBe(
        false
      );
      expect(isAbseilPitch({ pitch_number: 1, pitch_type: 'down_climb' })).toBe(
        false
      );
    });
  });

  describe('countAbseils', () => {
    it('counts only abseil-type pitches', () => {
      const pitches: AbseilPitch[] = [
        { pitch_number: 1, height: 20 },
        { pitch_number: 2, height: 25, pitch_type: 'abseil' },
        { pitch_number: 3, height: 5, pitch_type: 'jump' },
        { pitch_number: 4, height: 3, pitch_type: 'down_climb' },
      ];

      expect(countAbseils(pitches)).toBe(2);
    });

    it('returns 0 for an empty list', () => {
      expect(countAbseils([])).toBe(0);
    });
  });

  it('offers abseil, jump, and down climb options', () => {
    expect(PITCH_TYPES.map(t => t.value)).toEqual([
      'abseil',
      'jump',
      'down_climb',
    ]);
  });
});
