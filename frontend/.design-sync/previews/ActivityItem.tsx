import { useEffect, useRef } from 'react';
import { ActivityItem } from 'personal-management-frontend';
import type { HistoryResource } from '@/types/history';

/**
 * History rows carry a JSON:API resource straight from the API. Timestamps sit
 * just before the capture clock so the relative label reads naturally.
 */
function entry(
  id: string,
  attributes: Partial<HistoryResource['attributes']>
): HistoryResource {
  return {
    type: 'contact_history',
    id,
    attributes: {
      entity_type: 'contact',
      entity_id: 318,
      field_name: 'first_name',
      old_value: null,
      new_value: null,
      changed_by: 'alex.taylor@example.com',
      source: 'ui',
      created_at: '2024-05-15T09:30:00Z',
      ...attributes,
    },
  };
}

/** Both values present — an edit. */
export function Updated() {
  return (
    <div className='max-w-sm'>
      <ActivityItem
        activity={entry('1', {
          field_name: 'last_name',
          old_value: 'Nair',
          new_value: 'Nair-Osei',
          source: 'ui',
        })}
      />
    </div>
  );
}

/** No old value — the field was added, here by the Google Contacts sync. */
export function Added() {
  return (
    <div className='max-w-sm'>
      <ActivityItem
        activity={entry('2', {
          field_name: 'phone_number',
          old_value: null,
          new_value: '+61 412 555 019',
          source: 'google_contacts',
          created_at: '2024-05-14T22:40:00Z',
        })}
      />
    </div>
  );
}

/** No new value — the field was cleared, here by the MCP assistant. */
export function Removed() {
  return (
    <div className='max-w-sm'>
      <ActivityItem
        activity={entry('3', {
          field_name: 'company',
          old_value: 'Ridgeline Outdoors',
          new_value: null,
          source: 'mcp',
          created_at: '2024-05-12T03:15:00Z',
        })}
      />
    </div>
  );
}

/**
 * Summary regenerations get their own expandable row. The expansion is
 * component-private state, so the card clicks the real disclosure button on
 * mount to show the generated text.
 */
export function SummaryRegenerated() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLElement>('[aria-label="Expand summary text"]')
      ?.click();
  }, []);

  return (
    <div ref={ref} className='max-w-sm'>
      <ActivityItem
        activity={entry('4', {
          entity_type: 'journal',
          field_name: 'summary_text',
          old_value: 'Walked the ridge with Priya.',
          new_value:
            'Traversed the Cathedral Ranges southern circuit with Priya over two days, 24 km total.',
          source: 'summary_regeneration',
          created_at: '2024-05-15T11:05:00Z',
        })}
      />
    </div>
  );
}
