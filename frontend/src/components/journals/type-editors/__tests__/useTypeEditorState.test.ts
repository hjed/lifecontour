import { act, renderHook } from '@testing-library/react';
import type { SetStateAction } from 'react';
import { useTypeEditorState } from '../useTypeEditorState';

interface TestData {
  readonly route_id?: string;
  readonly total_length?: number;
}

describe('useTypeEditorState', () => {
  it('supports updater functions and emits the resolved value to onChange', () => {
    const handleChange = jest.fn();
    const { result } = renderHook(() =>
      useTypeEditorState<TestData>({
        initialData: {},
        createMode: true,
        onChange: handleChange,
      })
    );

    handleChange.mockClear();

    act(() => {
      (
        result.current.setEditData as unknown as (
          next: SetStateAction<TestData>
        ) => void
      )(previous => ({
        ...previous,
        route_id: 'route-123',
        total_length: 120,
      }));
    });

    expect(result.current.editData).toEqual({
      route_id: 'route-123',
      total_length: 120,
    });
    expect(handleChange).toHaveBeenLastCalledWith({
      route_id: 'route-123',
      total_length: 120,
    });
  });

  it('resolves sequential updater functions against the latest pending state', () => {
    const handleChange = jest.fn();
    const { result } = renderHook(() =>
      useTypeEditorState<TestData>({
        initialData: {},
        createMode: true,
        onChange: handleChange,
      })
    );

    handleChange.mockClear();

    act(() => {
      const setEditData = result.current.setEditData as unknown as (
        next: SetStateAction<TestData>
      ) => void;

      setEditData(previous => ({ ...previous, route_id: 'route-123' }));
      setEditData(previous => ({ ...previous, total_length: 210 }));
    });

    expect(result.current.editData).toEqual({
      route_id: 'route-123',
      total_length: 210,
    });
    expect(handleChange).toHaveBeenNthCalledWith(1, {
      route_id: 'route-123',
    });
    expect(handleChange).toHaveBeenNthCalledWith(2, {
      route_id: 'route-123',
      total_length: 210,
    });
  });
});
