/**
 * @jest-environment jsdom
 */

import { renderHook, act } from '@testing-library/react';
import { useDebounce } from '../useDebounce';

// Mock timers
jest.useFakeTimers();

describe('useDebounce', () => {
  afterEach(() => {
    jest.clearAllTimers();
  });

  afterAll(() => {
    jest.useRealTimers();
  });

  it('should return initial value immediately', () => {
    const { result } = renderHook(() => useDebounce('initial', 500));

    expect(result.current).toBe('initial');
  });

  it('should debounce value changes', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: 'initial', delay: 500 },
      }
    );

    expect(result.current).toBe('initial');

    // Change the value
    rerender({ value: 'updated', delay: 500 });

    // Value should not change immediately
    expect(result.current).toBe('initial');

    // Fast-forward time by 250ms (less than delay)
    act(() => {
      jest.advanceTimersByTime(250);
    });

    // Value should still be the old one
    expect(result.current).toBe('initial');

    // Fast-forward time by another 250ms (total 500ms)
    act(() => {
      jest.advanceTimersByTime(250);
    });

    // Now the value should be updated
    expect(result.current).toBe('updated');
  });

  it('should reset timer on rapid value changes', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: 'initial', delay: 500 },
      }
    );

    expect(result.current).toBe('initial');

    // Change the value multiple times rapidly
    rerender({ value: 'first', delay: 500 });

    act(() => {
      jest.advanceTimersByTime(250);
    });

    rerender({ value: 'second', delay: 500 });

    act(() => {
      jest.advanceTimersByTime(250);
    });

    rerender({ value: 'third', delay: 500 });

    // Value should still be initial because timer keeps resetting
    expect(result.current).toBe('initial');

    // Fast-forward by full delay
    act(() => {
      jest.advanceTimersByTime(500);
    });

    // Should now have the latest value
    expect(result.current).toBe('third');
  });

  it('should handle different delay values', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: 'initial', delay: 1000 },
      }
    );

    rerender({ value: 'updated', delay: 1000 });

    // Fast-forward by 500ms (less than 1000ms delay)
    act(() => {
      jest.advanceTimersByTime(500);
    });

    expect(result.current).toBe('initial');

    // Fast-forward by another 500ms (total 1000ms)
    act(() => {
      jest.advanceTimersByTime(500);
    });

    expect(result.current).toBe('updated');
  });

  it('should handle delay changes', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: 'initial', delay: 500 },
      }
    );

    rerender({ value: 'updated', delay: 1000 });

    // Fast-forward by 500ms (original delay)
    act(() => {
      jest.advanceTimersByTime(500);
    });

    // Should still be initial because delay was changed to 1000ms
    expect(result.current).toBe('initial');

    // Fast-forward by another 500ms (total 1000ms)
    act(() => {
      jest.advanceTimersByTime(500);
    });

    expect(result.current).toBe('updated');
  });

  it('should work with different data types', () => {
    // Test with numbers
    const { result: numberResult, rerender: numberRerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: 0, delay: 300 },
      }
    );

    numberRerender({ value: 42, delay: 300 });

    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(numberResult.current).toBe(42);

    // Test with objects
    const { result: objectResult, rerender: objectRerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: { name: 'initial' }, delay: 300 },
      }
    );

    const newObject = { name: 'updated' };
    objectRerender({ value: newObject, delay: 300 });

    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(objectResult.current).toBe(newObject);
  });

  it('should cleanup timeout on unmount', () => {
    const clearTimeoutSpy = jest.spyOn(global, 'clearTimeout');

    const { unmount } = renderHook(() => useDebounce('test', 500));

    unmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();

    clearTimeoutSpy.mockRestore();
  });

  it('should handle zero delay', () => {
    const { result, rerender } = renderHook(
      ({ value, delay }) => useDebounce(value, delay),
      {
        initialProps: { value: 'initial', delay: 0 },
      }
    );

    rerender({ value: 'updated', delay: 0 });

    // With zero delay, should update immediately after next tick
    act(() => {
      jest.advanceTimersByTime(0);
    });

    expect(result.current).toBe('updated');
  });
});
