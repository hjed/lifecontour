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
  it('describes archiving a value', () => {
    expect(
      formatActivityDescription(
        'is_archived',
        'False',
        'True',
        'contact_method'
      )
    ).toBe('Archived method');
  });

  it('describes restoring a value', () => {
    expect(
      formatActivityDescription(
        'is_archived',
        'True',
        'False',
        'contact_address'
      )
    ).toBe('Restored address');
  });

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

describe('ActivityItem — task entries', () => {
  const taskEntry = (
    id: string,
    field_name: string,
    old_value: string | null,
    new_value: string | null,
    source = 'ui'
  ): HistoryResource => ({
    type: 'task_history',
    id,
    attributes: {
      entity_type: 'task',
      entity_id: 42,
      field_name,
      old_value,
      new_value,
      changed_by: source,
      source,
      created_at: '2024-01-15T10:30:00Z',
    },
  });

  const renderItem = (
    activity: HistoryResource,
    entity: 'contact' | 'journal' | 'task' = 'task'
  ) =>
    render(
      <TooltipProvider>
        <ActivityItem activity={activity} entity={entity} />
      </TooltipProvider>
    );

  it('opens a task history with what the task was', () => {
    renderItem(taskEntry('1', '__created__', null, 'Book the venue'));

    expect(
      screen.getByText(/Task created: “Book the venue”/)
    ).toBeInTheDocument();
  });

  it('renders the delete marker as a deletion rather than an empty change', () => {
    renderItem(taskEntry('2', '__deleted__', null, null));

    expect(screen.getByText('Task deleted')).toBeInTheDocument();
  });

  it('renders a status move in the app’s own status wording', () => {
    renderItem(taskEntry('3', 'status', 'not_done', 'done'));

    expect(
      screen.getByText('Status changed from Not done to Done')
    ).toBeInTheDocument();
  });

  it('renders a contact link from the task’s point of view', () => {
    renderItem(taskEntry('4', 'contact:12', null, '12'));

    expect(screen.getByText('Linked a contact')).toBeInTheDocument();
  });

  it('renders the same row from the contact’s point of view', () => {
    renderItem(taskEntry('5', 'contact:12', null, '12'), 'contact');

    expect(screen.getByText('Linked to a task')).toBeInTheDocument();
  });

  it.each([
    ['ui', 'Updated via Web Interface'],
    ['mcp', 'Updated via AI Assistant'],
    ['system', 'Updated by System'],
  ])('carries %s provenance with its hover text', (source, label) => {
    renderItem(taskEntry('6', 'status', 'not_done', 'done', source));

    const trigger = screen.getByTestId(`provenance-trigger-${source}`);
    expect(trigger).toBeInTheDocument();
    expect(getProvenanceLabel(source)).toBe(label);
  });

  it('offers no action on a task entry, on either feed', () => {
    // The specification's *Where tasks appear* allows two working surfaces and
    // says a record of the past is not a third: entries "are not actionable
    // from there". The provenance trigger is a button by necessity (it carries
    // the tooltip), so the assertion is about everything else.
    for (const entity of ['task', 'contact'] as const) {
      const { unmount } = renderItem(
        taskEntry('7', 'contact:12', null, '12'),
        entity
      );

      const actionable = screen
        .queryAllByRole('button')
        .filter(
          button =>
            button.getAttribute('data-testid') !== 'provenance-trigger-ui'
        );
      expect(actionable).toHaveLength(0);
      expect(screen.queryAllByRole('link')).toHaveLength(0);
      expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
      unmount();
    }
  });

  it('leaves a contact’s own entry worded exactly as before', () => {
    // The task wording is gated on entity_type, so widening it must not
    // relabel the rows the contact feed already renders.
    render(
      <TooltipProvider>
        <ActivityItem
          activity={{
            type: 'contact_history',
            id: '8',
            attributes: {
              entity_type: 'contact',
              entity_id: 5,
              field_name: 'status',
              old_value: null,
              new_value: 'created',
              changed_by: 'ui',
              source: 'ui',
              created_at: '2024-01-15T10:30:00Z',
            },
          }}
          entity='contact'
        />
      </TooltipProvider>
    );

    expect(screen.getByText('Added Status: "created"')).toBeInTheDocument();
  });
});
