/**
 * Tests for ActivityItem component.
 */

import { render, screen } from '@testing-library/react';
import {
  ActivityItem,
  formatFieldName,
  getActivityType,
  formatActivityDescription,
} from '../ActivityItem';
import type { ContactHistoryResource } from '@/types/contacts';

// Mock date-fns to have consistent time output
jest.mock('date-fns', () => ({
  formatDistanceToNow: jest.fn(() => 'about 2 hours ago'),
}));

jest.mock('date-fns/locale', () => ({
  enAU: {},
}));

describe('ActivityItem', () => {
  const baseActivity: ContactHistoryResource = {
    type: 'contact_history',
    id: '1',
    attributes: {
      entity_type: 'contact',
      entity_id: 123,
      field_name: 'first_name',
      old_value: 'John',
      new_value: 'Jane',
      changed_by: 'user@example.com',
      created_at: '2024-01-15T10:30:00Z',
    },
  };

  it('renders activity item with correct structure', () => {
    render(<ActivityItem activity={baseActivity} />);

    expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    expect(screen.getByText(/Changed First Name/i)).toBeInTheDocument();
    expect(screen.getByText(/about 2 hours ago/i)).toBeInTheDocument();
  });

  it('displays update activity correctly', () => {
    render(<ActivityItem activity={baseActivity} />);

    expect(
      screen.getByText(/Changed First Name from "John" to "Jane"/i)
    ).toBeInTheDocument();
  });

  it('displays create activity correctly', () => {
    const createActivity: ContactHistoryResource = {
      ...baseActivity,
      attributes: {
        ...baseActivity.attributes,
        old_value: null,
        new_value: 'JD',
        field_name: 'nick_name',
      },
    };

    render(<ActivityItem activity={createActivity} />);

    expect(screen.getByText(/Added Nick Name: "JD"/i)).toBeInTheDocument();
  });

  it('displays delete activity correctly', () => {
    const deleteActivity: ContactHistoryResource = {
      ...baseActivity,
      attributes: {
        ...baseActivity.attributes,
        old_value: 'Smith',
        new_value: null,
        field_name: 'last_name',
      },
    };

    render(<ActivityItem activity={deleteActivity} />);

    expect(screen.getByText(/Removed Last Name/i)).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(<ActivityItem activity={baseActivity} className='custom-class' />);

    const item = screen.getByTestId('activity-item-1');
    expect(item).toHaveClass('custom-class');
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
    expect(result).toBe('Removed Last Name');
  });
});
