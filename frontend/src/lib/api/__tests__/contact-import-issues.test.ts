/** @jest-environment jsdom */
import React, { type ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  contactImportIssueKeys,
  dismissContactImportIssue,
  fetchContactImportIssues,
  useContactImportIssues,
} from '../contact-import-issues';

globalThis.fetch = jest.fn();
const mockFetch = fetch as jest.MockedFunction<typeof fetch>;

describe('contact import issues API', () => {
  beforeEach(() => mockFetch.mockReset());

  it('lists every pending issue, or one contact’s', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    } as Response);

    await fetchContactImportIssues();
    await fetchContactImportIssues('7');

    expect(mockFetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/integrations/import-issues',
      '/api/integrations/import-issues?contact_id=7',
    ]);
  });

  it('dismisses an issue', async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 204 } as Response);

    await dismissContactImportIssue('3');

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/integrations/import-issues/3/dismiss',
      { credentials: 'include', method: 'POST' }
    );
  });

  it('throws the API error detail', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ errors: [{ detail: 'Import issue not found' }] }),
    } as Response);

    await expect(dismissContactImportIssue('3')).rejects.toThrow(
      'Import issue not found'
    );
  });
});

describe('useContactImportIssues', () => {
  it('keeps an open page current while a sync runs', async () => {
    // No hook fires when a sync job finishes, so the list re-checks on the
    // Google status cadence rather than waiting out the app-wide staleTime.
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    } as Response);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        children
      );

    const { result } = renderHook(() => useContactImportIssues('7'), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const options = queryClient
      .getQueryCache()
      .find({ queryKey: contactImportIssueKeys.list('7') })?.options;
    expect(options).toMatchObject({
      staleTime: 30 * 1000,
      refetchInterval: 60 * 1000,
    });
  });
});
