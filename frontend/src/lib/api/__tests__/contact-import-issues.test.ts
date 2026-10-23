import {
  dismissContactImportIssue,
  fetchContactImportIssues,
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
