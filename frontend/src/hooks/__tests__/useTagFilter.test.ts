/**
 * @jest-environment jsdom
 */

import { renderHook, act } from '@testing-library/react';
import { useTagFilter } from '../useTagFilter';
import { useSearchParams, usePathname, useRouter } from 'next/navigation';
// Alias must start with `mock` to be referenced inside the jest.mock factory below.
import { createMockAppRouter as mockCreateAppRouter } from '@/test-utils/mock-router';

jest.mock('next/navigation', () => ({
  useSearchParams: jest.fn(() => new URLSearchParams()),
  usePathname: jest.fn(() => '/contacts'),
  useRouter: jest.fn(() => mockCreateAppRouter()),
}));

const mockUseSearchParams = useSearchParams as jest.MockedFunction<
  typeof useSearchParams
>;
const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseRouter = useRouter as jest.MockedFunction<typeof useRouter>;

describe('useTagFilter', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default: no search params
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams() as ReturnType<typeof useSearchParams>
    );
    mockUsePathname.mockReturnValue('/contacts');
  });

  it('returns null tagId when no tag param is present', () => {
    const { result } = renderHook(() => useTagFilter());
    expect(result.current.tagId).toBeNull();
  });

  it('normalizes empty tag param to null', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=') as ReturnType<typeof useSearchParams>
    );

    const { result } = renderHook(() => useTagFilter());
    expect(result.current.tagId).toBeNull();
  });

  it('returns tagId from URL search params', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=42') as ReturnType<typeof useSearchParams>
    );

    const { result } = renderHook(() => useTagFilter());
    expect(result.current.tagId).toBe('42');
  });

  it('setTag navigates to /contacts with tag param', () => {
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);

    const { result } = renderHook(() => useTagFilter());
    act(() => {
      result.current.setTag('7');
    });

    expect(pushMock).toHaveBeenCalledWith('/contacts?tag=7');
  });

  it('clearTag removes tag param and navigates', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=42') as ReturnType<typeof useSearchParams>
    );
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);

    const { result } = renderHook(() => useTagFilter());
    act(() => {
      result.current.clearTag();
    });

    expect(pushMock).toHaveBeenCalledWith('/contacts');
  });

  it('clearTag preserves pathname when already on /contacts', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=5') as ReturnType<typeof useSearchParams>
    );
    mockUsePathname.mockReturnValue('/contacts');
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);

    const { result } = renderHook(() => useTagFilter());
    act(() => {
      result.current.clearTag();
    });

    expect(pushMock).toHaveBeenCalledWith('/contacts');
  });

  it('setTag navigates to the given base path', () => {
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);
    mockUsePathname.mockReturnValue('/journals');

    const { result } = renderHook(() => useTagFilter('/journals'));
    act(() => {
      result.current.setTag('7');
    });

    expect(pushMock).toHaveBeenCalledWith('/journals?tag=7');
  });

  it('clearTag falls back to the given base path when no params remain', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=42') as ReturnType<typeof useSearchParams>
    );
    mockUsePathname.mockReturnValue('/journals');
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);

    const { result } = renderHook(() => useTagFilter('/journals'));
    act(() => {
      result.current.clearTag();
    });

    expect(pushMock).toHaveBeenCalledWith('/journals');
  });

  it('clearTag preserves other params on the given base path', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=42&view=month') as ReturnType<
        typeof useSearchParams
      >
    );
    mockUsePathname.mockReturnValue('/journals');
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);

    const { result } = renderHook(() => useTagFilter('/journals'));
    act(() => {
      result.current.clearTag();
    });

    expect(pushMock).toHaveBeenCalledWith('/journals?view=month');
  });

  it('setTag replaces existing tag param', () => {
    mockUseSearchParams.mockReturnValue(
      new URLSearchParams('tag=1') as ReturnType<typeof useSearchParams>
    );
    const pushMock = jest.fn();
    mockUseRouter.mockReturnValue({
      push: pushMock,
    } as unknown as ReturnType<typeof useRouter>);

    const { result } = renderHook(() => useTagFilter());
    act(() => {
      result.current.setTag('99');
    });

    expect(pushMock).toHaveBeenCalledWith('/contacts?tag=99');
  });
});
