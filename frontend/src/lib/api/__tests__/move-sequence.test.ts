import { QueryClient } from '@tanstack/react-query';
import {
  isNewestMove,
  settleMove,
  startMove,
  takeRereadNeeded,
} from '@/lib/api/move-sequence';

describe('move-sequence', () => {
  it('settles each scope on its own', () => {
    const queryClient = new QueryClient();
    startMove(queryClient, 'a', false);
    startMove(queryClient, 'b', false);

    expect(settleMove(queryClient, 'a')).toBe(true);
    expect(settleMove(queryClient, 'b')).toBe(true);
  });

  it('knows the newest move in a scope', () => {
    const queryClient = new QueryClient();
    const first = startMove(queryClient, 'a', false);
    const second = startMove(queryClient, 'a', false);

    expect(isNewestMove(queryClient, 'a', first)).toBe(false);
    expect(isNewestMove(queryClient, 'a', second)).toBe(true);
  });

  it('needs no re-read for a lone move that cut short no refresh', () => {
    const queryClient = new QueryClient();
    startMove(queryClient, 'a', false);
    settleMove(queryClient, 'a');

    expect(takeRereadNeeded(queryClient, 'a')).toBe(false);
  });

  it('clears every reason at once, so the next lone move needs none', () => {
    // Overlapping moves that also cut short a refresh: both reasons hold, and
    // asking must clear both, or the next lone move re-reads for nothing.
    const queryClient = new QueryClient();
    startMove(queryClient, 'a', true);
    startMove(queryClient, 'a', false);
    settleMove(queryClient, 'a');
    settleMove(queryClient, 'a');
    expect(takeRereadNeeded(queryClient, 'a')).toBe(true);

    startMove(queryClient, 'a', false);
    settleMove(queryClient, 'a');
    expect(takeRereadNeeded(queryClient, 'a')).toBe(false);
  });
});
