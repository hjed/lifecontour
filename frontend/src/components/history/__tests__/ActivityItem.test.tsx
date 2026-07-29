/**
 * Tests for the shared (entity-agnostic) ActivityItem component.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import {
  ActivityItem,
  formatFieldName,
  getActivityType,
  formatActivityDescription,
  getProvenanceLabel,
} from '../ActivityItem';
import type { HistoryResource } from '@/types/history';
import { TooltipProvider } from '@/components/ui/tooltip';

// Mock date-fns to have consistent time output
jest.mock('date-fns', () => ({
  formatDistanceToNow: jest.fn(() => 'about 2 hours ago'),
}));

jest.mock('date-fns/locale', () => ({
  enAU: {},
}));

describe('ActivityItem', () => {
  const baseActivity: HistoryResource = {
    type: 'contact_history',
    id: '1',
    attributes: {
      entity_type: 'contact',
      entity_id: 123,
      field_name: 'first_name',
      old_value: 'John',
      new_value: 'Jane',
      changed_by: 'user@example.com',
      source: 'ui',
      created_at: '2024-01-15T10:30:00Z',
    },
  };

  it('renders activity item with correct structure', () => {
    render(
      <TooltipProvider>
        <ActivityItem activity={baseActivity} />
      </TooltipProvider>
    );

    expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    expect(screen.getByText(/Changed First Name/i)).toBeInTheDocument();
    expect(screen.getByText(/about 2 hours ago/i)).toBeInTheDocument();
  });

  it('displays update activity correctly', () => {
    render(
      <TooltipProvider>
        <ActivityItem activity={baseActivity} />
      </TooltipProvider>
    );

    expect(
      screen.getByText(/Changed First Name from "John" to "Jane"/i)
    ).toBeInTheDocument();
  });

  it('displays create activity correctly', () => {
    const createActivity: HistoryResource = {
      ...baseActivity,
      attributes: {
        ...baseActivity.attributes,
        old_value: null,
        new_value: 'JD',
        field_name: 'nick_name',
      },
    };

    render(
      <TooltipProvider>
        <ActivityItem activity={createActivity} />
      </TooltipProvider>
    );

    expect(screen.getByText(/Added Nick Name: "JD"/i)).toBeInTheDocument();
  });

  it('displays delete activity correctly', () => {
    const deleteActivity: HistoryResource = {
      ...baseActivity,
      attributes: {
        ...baseActivity.attributes,
        old_value: 'Smith',
        new_value: null,
        field_name: 'last_name',
      },
    };

    render(
      <TooltipProvider>
        <ActivityItem activity={deleteActivity} />
      </TooltipProvider>
    );

    expect(screen.getByText(/Removed Last Name: "Smith"/i)).toBeInTheDocument();
  });

  // Journal tag assignment/removal history arrives as entity_type 'journal' with
  // field_name 'tags' and the tag name in new_value/old_value. No component change
  // was needed for it to render — these tests pin that contract so a future tweak
  // to the entity-agnostic formatting cannot silently break the journal feed.
  describe('journal tag entries', () => {
    function journalTagActivity(
      oldValue: string | null,
      newValue: string | null,
      overrides: Partial<HistoryResource['attributes']> = {}
    ): HistoryResource {
      return {
        ...baseActivity,
        type: 'journal_history',
        attributes: {
          ...baseActivity.attributes,
          entity_type: 'journal',
          entity_id: 42,
          field_name: 'tags',
          old_value: oldValue,
          new_value: newValue,
          ...overrides,
        },
      };
    }

    it('describes an assignment as an added tag', () => {
      render(
        <TooltipProvider>
          <ActivityItem activity={journalTagActivity(null, 'Hiking')} />
        </TooltipProvider>
      );

      expect(screen.getByText('Added Tags: "Hiking"')).toBeInTheDocument();
      expect(screen.getByTestId('provenance-trigger-ui')).toBeInTheDocument();
    });

    it('describes a removal as a removed tag', () => {
      render(
        <TooltipProvider>
          <ActivityItem activity={journalTagActivity('Hiking', null)} />
        </TooltipProvider>
      );

      expect(screen.getByText('Removed Tags: "Hiking"')).toBeInTheDocument();
    });

    it('shows the AI-assistant provenance for an MCP tag change', () => {
      render(
        <TooltipProvider>
          <ActivityItem
            activity={journalTagActivity(null, 'Hiking', {
              source: 'mcp',
              changed_by: 'mcp',
            })}
          />
        </TooltipProvider>
      );

      expect(screen.getByTestId('provenance-trigger-mcp')).toBeInTheDocument();
    });

    // A tag rename arrives with BOTH values set, which is what makes the shared
    // formatter describe it as a change rather than an add or a remove.
    it('describes a rename as a change from the old name to the new one', () => {
      render(
        <TooltipProvider>
          <ActivityItem activity={journalTagActivity('Hiking', 'Trekking')} />
        </TooltipProvider>
      );

      expect(
        screen.getByText('Changed Tags from "Hiking" to "Trekking"')
      ).toBeInTheDocument();
      expect(screen.getByTestId('provenance-trigger-ui')).toBeInTheDocument();
    });

    it('shows the AI-assistant provenance for an MCP tag rename', () => {
      render(
        <TooltipProvider>
          <ActivityItem
            activity={journalTagActivity('Hiking', 'Trekking', {
              source: 'mcp',
              changed_by: 'mcp',
            })}
          />
        </TooltipProvider>
      );

      expect(
        screen.getByText('Changed Tags from "Hiking" to "Trekking"')
      ).toBeInTheDocument();
      expect(screen.getByTestId('provenance-trigger-mcp')).toBeInTheDocument();
    });
  });

  it('applies custom className', () => {
    render(
      <TooltipProvider>
        <ActivityItem activity={baseActivity} className='custom-class' />
      </TooltipProvider>
    );

    const item = screen.getByTestId('activity-item-1');
    expect(item).toHaveClass('custom-class');
  });

  it('renders summary regeneration abbreviated and collapsible', () => {
    const summaryActivity: HistoryResource = {
      ...baseActivity,
      attributes: {
        ...baseActivity.attributes,
        field_name: 'summary_text',
        source: 'summary_regeneration',
        old_value: 'Old text',
        new_value: 'New summarized text',
      },
    };

    render(
      <TooltipProvider>
        <ActivityItem activity={summaryActivity} />
      </TooltipProvider>
    );

    expect(screen.getByText('AI Summary Regenerated')).toBeInTheDocument();

    // initially hidden
    expect(screen.queryByText('New summarized text')).not.toBeInTheDocument();

    // click expand
    const expandButton = screen.getByRole('button', { name: /expand/i });
    fireEvent.click(expandButton);

    expect(screen.getByText('New summarized text')).toBeInTheDocument();
  });

  describe('provenance sources', () => {
    function renderWithSource(source: string) {
      render(
        <TooltipProvider>
          <ActivityItem
            activity={{
              ...baseActivity,
              attributes: { ...baseActivity.attributes, source },
            }}
          />
        </TooltipProvider>
      );
    }

    // Each known source renders a distinct provenance trigger (icon). The label
    // lives in the Radix tooltip content (rendered on hover), so the label text
    // is verified separately via getProvenanceLabel below.
    it.each([
      'ui',
      'mcp',
      'google_contacts',
      'google_calendar',
      'strava',
      'immich',
      'system',
    ])('renders a provenance trigger for %s', source => {
      renderWithSource(source);

      expect(
        screen.getByTestId(`provenance-trigger-${source}`)
      ).toBeInTheDocument();
    });

    it('falls back to the system provenance trigger for an empty source', () => {
      renderWithSource('');

      expect(
        screen.getByTestId('provenance-trigger-system')
      ).toBeInTheDocument();
    });
  });
});

describe('getProvenanceLabel', () => {
  it.each([
    ['ui', 'Updated via Web Interface'],
    ['mcp', 'Updated via AI Assistant'],
    ['google_contacts', 'Updated via Google Contacts Sync'],
    ['google_calendar', 'Updated via Google Calendar Sync'],
    ['strava', 'Updated via Strava Sync'],
    ['immich', 'Updated via Immich Sync'],
    ['summary_regeneration', 'Generated by AI Summary'],
    ['system', 'Updated by System'],
  ])('maps %s to its label', (source, expectedLabel) => {
    expect(getProvenanceLabel(source)).toBe(expectedLabel);
  });

  it('falls back to the system label for unknown/empty sources', () => {
    expect(getProvenanceLabel('')).toBe('Updated by System');
    expect(getProvenanceLabel('mystery')).toBe('Updated by System');
  });
});

describe('formatFieldName', () => {
  it('converts snake_case to Title Case', () => {
    expect(formatFieldName('first_name')).toBe('First Name');
    expect(formatFieldName('last_name')).toBe('Last Name');
    expect(formatFieldName('nick_name')).toBe('Nick Name');
  });

  it('handles single word fields', () => {
    expect(formatFieldName('email')).toBe('Email');
    expect(formatFieldName('phone')).toBe('Phone');
  });

  it('handles multiple underscores', () => {
    expect(formatFieldName('street_line_1')).toBe('Street Line 1');
  });
});

describe('getActivityType', () => {
  it('returns created when old value is null', () => {
    expect(getActivityType(null, 'new')).toBe('created');
  });

  it('returns deleted when new value is null', () => {
    expect(getActivityType('old', null)).toBe('deleted');
  });

  it('returns updated when both values exist', () => {
    expect(getActivityType('old', 'new')).toBe('updated');
  });

  it('returns updated when both values are null', () => {
    // Edge case - both null means no actual values, treat as update
    expect(getActivityType(null, null)).toBe('updated');
  });
});

describe('formatActivityDescription', () => {
  it('formats update description', () => {
    const result = formatActivityDescription(
      'first_name',
      'John',
      'Jane',
      'contact'
    );
    expect(result).toBe('Changed First Name from "John" to "Jane"');
  });

  it('formats create description', () => {
    const result = formatActivityDescription(
      'nick_name',
      null,
      'JD',
      'contact'
    );
    expect(result).toBe('Added Nick Name: "JD"');
  });

  it('formats delete description', () => {
    const result = formatActivityDescription(
      'last_name',
      'Smith',
      null,
      'contact'
    );
    expect(result).toBe('Removed Last Name: "Smith"');
  });
});
