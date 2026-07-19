import type { AbseilPitch } from '@/types/journals';

export const PITCH_TYPES = [
  { value: 'abseil', label: 'Abseil' },
  { value: 'jump', label: 'Jump' },
  { value: 'down_climb', label: 'Down Climb (DC)' },
] as const;

/** A null/missing pitch_type is treated as an abseil for backward compatibility. */
export function isAbseilPitch(pitch: AbseilPitch): boolean {
  return pitch.pitch_type == null || pitch.pitch_type === 'abseil';
}

/** Count only abseil-type pitches — jumps and down climbs are not abseils. */
export function countAbseils(pitches: readonly AbseilPitch[]): number {
  return pitches.filter(isAbseilPitch).length;
}
