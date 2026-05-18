/**
 * Jest unit tests for SearchHighlight component.
 *
 * Tests the SearchHighlight component's functionality including:
 * - Safe HTML sanitization with DOMPurify
 * - XSS prevention
 * - Proper highlighting rendering
 * - Fallback behavior
 */

import { render, screen } from '@testing-library/react';
import {
  SearchHighlight,
  useHighlightedText,
  HighlightedField,
} from '@/components/search/SearchHighlight';
import { renderHook } from '@testing-library/react';

// Test data factory to reduce duplication
const createTestData = {
  plainText: 'John Doe',
  highlightedText: '<mark>John</mark> Doe',
  multipleHighlights: '<mark>John</mark> <mark>Doe</mark>',
  maliciousHtml:
    '<script>alert("xss")</script><mark>John</mark><img src="x" onerror="alert(1)">',
  nestedTags: '<div><mark>John</mark></div>',
  highlightedObject: {
    first_name: '<mark>John</mark>',
    last_name: '<mark>Doe</mark>',
    email: '<mark>john</mark>@example.com',
  },
  emptyHighlightedObject: {},
  nullHighlightedObject: null,
};

// Helper function to check mark element styling
const expectMarkStyling = (element: HTMLElement) => {
  expect(element).toHaveClass('bg-yellow-200');
  expect(element).toHaveClass('dark:bg-yellow-800');
  expect(element).toHaveClass('px-1');
  expect(element).toHaveClass('rounded');
};

describe('SearchHighlight Component', () => {
  describe('Basic Rendering', () => {
    it('renders plain text without highlighting', () => {
      render(<SearchHighlight text={createTestData.plainText} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.queryByRole('mark')).not.toBeInTheDocument();
    });

    it('renders highlighted text with proper styling', () => {
      render(<SearchHighlight text={createTestData.highlightedText} />);

      const markElement = screen.getByText('John');
      expect(markElement.tagName).toBe('MARK');
      expectMarkStyling(markElement);
      expect(screen.getByText('Doe')).toBeInTheDocument();
    });

    it('renders multiple highlights correctly', () => {
      render(<SearchHighlight text={createTestData.multipleHighlights} />);

      const johnMark = screen.getByText('John');
      const doeMark = screen.getByText('Doe');

      expect(johnMark.tagName).toBe('MARK');
      expect(doeMark.tagName).toBe('MARK');
      expectMarkStyling(johnMark);
      expectMarkStyling(doeMark);
    });

    it('applies custom className', () => {
      render(
        <SearchHighlight
          text={createTestData.plainText}
          className='custom-class'
        />
      );

      const span = screen.getByText('John Doe');
      expect(span).toHaveClass('custom-class');
      expect(span).toHaveClass('search-highlight');
    });
  });

  describe('Security - XSS Prevention', () => {
    it('sanitizes malicious HTML and preserves only mark tags', () => {
      render(<SearchHighlight text={createTestData.maliciousHtml} />);

      // Should render the mark tag content
      const johnElement = screen.getByText('John');
      expect(johnElement).toBeInTheDocument();
      expect(johnElement.tagName).toBe('MARK');

      // Should not render script or img tags
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
      expect(document.querySelector('script')).not.toBeInTheDocument();

      // Should not execute any JavaScript - DOMPurify strips everything except mark tags
      const container = johnElement.closest('span');
      expect(container?.innerHTML).not.toContain('<script>');
      expect(container?.innerHTML).not.toContain('<img');
      expect(container?.innerHTML).not.toContain('alert');
    });

    it('removes nested HTML tags but preserves mark content', () => {
      render(<SearchHighlight text={createTestData.nestedTags} />);

      expect(screen.getByText('John')).toBeInTheDocument();
      expect(screen.getByText('John').tagName).toBe('MARK');

      // Should not contain div tags
      const container = screen.getByText('John').closest('span');
      expect(container?.innerHTML).not.toContain('<div>');
    });

    it('handles empty mark tags safely', () => {
      render(<SearchHighlight text='<mark></mark>test' />);

      expect(screen.getByText('test')).toBeInTheDocument();
    });
  });

  describe('Fallback Behavior', () => {
    it('shows fallback when text is empty', () => {
      render(<SearchHighlight text='' fallback='No content available' />);

      expect(screen.getByText('No content available')).toBeInTheDocument();
    });

    it('shows fallback when text is null/undefined', () => {
      render(
        <SearchHighlight text={undefined as never} fallback='Fallback text' />
      );

      expect(screen.getByText('Fallback text')).toBeInTheDocument();
    });

    it('returns null when no text and no fallback', () => {
      const { container } = render(<SearchHighlight text='' />);

      expect(container.firstChild).toBeNull();
    });

    it('returns null when showFallback is false', () => {
      const { container } = render(
        <SearchHighlight
          text=''
          fallback='Should not show'
          showFallback={false}
        />
      );

      expect(container.firstChild).toBeNull();
    });
  });
});

describe('useHighlightedText Hook', () => {
  it('extracts highlighted text from object', () => {
    const { result } = renderHook(() =>
      useHighlightedText(
        createTestData.highlightedObject,
        'first_name',
        'fallback'
      )
    );

    expect(result.current).toBe('<mark>John</mark>');
  });

  it('returns fallback for missing field', () => {
    const { result } = renderHook(() =>
      useHighlightedText(
        createTestData.highlightedObject,
        'missing_field',
        'fallback'
      )
    );

    expect(result.current).toBe('fallback');
  });

  it('returns fallback for null highlighted object', () => {
    const { result } = renderHook(() =>
      useHighlightedText(
        createTestData.nullHighlightedObject,
        'first_name',
        'fallback'
      )
    );

    expect(result.current).toBe('fallback');
  });

  it('returns fallback for empty highlighted object', () => {
    const { result } = renderHook(() =>
      useHighlightedText(
        createTestData.emptyHighlightedObject,
        'first_name',
        'fallback'
      )
    );

    expect(result.current).toBe('fallback');
  });

  it('handles non-string values in highlighted object', () => {
    const highlightedWithNumber = { count: 42 };
    const { result } = renderHook(() =>
      useHighlightedText(highlightedWithNumber, 'count', 'fallback')
    );

    expect(result.current).toBe('fallback');
  });
});

describe('HighlightedField Component', () => {
  it('renders field with highlighting', () => {
    render(
      <HighlightedField
        highlighted={createTestData.highlightedObject}
        field='first_name'
        fallback='John'
        label='Name'
      />
    );

    expect(screen.getByText('Name:')).toBeInTheDocument();
    expect(screen.getByText('John').tagName).toBe('MARK');
  });

  it('renders without label when not provided', () => {
    render(
      <HighlightedField
        highlighted={createTestData.highlightedObject}
        field='first_name'
        fallback='John'
      />
    );

    expect(screen.queryByText(':')).not.toBeInTheDocument();
    expect(screen.getByText('John')).toBeInTheDocument();
  });

  it('returns null when no text and showEmpty is false', () => {
    const { container } = render(
      <HighlightedField
        highlighted={createTestData.emptyHighlightedObject}
        field='missing_field'
        fallback=''
        showEmpty={false}
      />
    );

    expect(container.firstChild).toBeNull();
  });

  it('shows empty field when showEmpty is true', () => {
    render(
      <HighlightedField
        highlighted={createTestData.emptyHighlightedObject}
        field='missing_field'
        fallback=''
        showEmpty={true}
        label='Empty Field'
      />
    );

    expect(screen.getByText('Empty Field:')).toBeInTheDocument();
  });
});
