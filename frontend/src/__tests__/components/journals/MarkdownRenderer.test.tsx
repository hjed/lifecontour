/**
 * Jest unit tests for MarkdownRenderer.
 *
 * Covers GitHub-flavored markdown rendering (headings, emphasis, lists, links,
 * strikethrough, tables, task lists) and XSS safety — raw HTML embedded in the
 * markdown must never be rendered as live DOM nodes. Mirrors the security test
 * pattern in SearchHighlight.test.tsx.
 */

import { render, screen } from '@testing-library/react';
import { MarkdownRenderer } from '@/components/journals/MarkdownRenderer';

describe('MarkdownRenderer', () => {
  describe('GitHub-flavored markdown rendering', () => {
    it('renders a level-1 heading', () => {
      render(<MarkdownRenderer content='# Title' />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent('Title');
    });

    it('renders bold and italic emphasis', () => {
      render(<MarkdownRenderer content='**bold** and *italic*' />);

      expect(screen.getByText('bold').tagName).toBe('STRONG');
      expect(screen.getByText('italic').tagName).toBe('EM');
    });

    it('renders an unordered list with items', () => {
      render(<MarkdownRenderer content={'- one\n- two'} />);

      const items = screen.getAllByRole('listitem');
      expect(items).toHaveLength(2);
      expect(items[0]).toHaveTextContent('one');
      expect(items[1]).toHaveTextContent('two');
    });

    it('renders an ordered list', () => {
      const { container } = render(
        <MarkdownRenderer content={'1. first\n2. second'} />
      );

      expect(container.querySelector('ol')).toBeInTheDocument();
      expect(screen.getAllByRole('listitem')).toHaveLength(2);
    });

    it('renders links with safe target/rel attributes', () => {
      render(<MarkdownRenderer content='[example](https://example.com)' />);

      const link = screen.getByRole('link', { name: 'example' });
      expect(link).toHaveAttribute('href', 'https://example.com');
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
      expect(link).toHaveAttribute(
        'rel',
        expect.stringContaining('noreferrer')
      );
    });

    it('renders GFM strikethrough', () => {
      render(<MarkdownRenderer content='~~gone~~' />);

      expect(screen.getByText('gone').tagName).toBe('DEL');
    });

    it('renders GFM tables', () => {
      const table = ['| a | b |', '| - | - |', '| 1 | 2 |'].join('\n');
      const { container } = render(<MarkdownRenderer content={table} />);

      expect(container.querySelector('table')).toBeInTheDocument();
      expect(screen.getByText('a')).toBeInTheDocument();
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('renders GFM task lists as checkboxes', () => {
      render(<MarkdownRenderer content={'- [x] done\n- [ ] todo'} />);

      const checkboxes = screen.getAllByRole('checkbox');
      expect(checkboxes).toHaveLength(2);
      expect(checkboxes[0]).toBeChecked();
      expect(checkboxes[1]).not.toBeChecked();
    });
  });

  describe('Security - XSS prevention', () => {
    it('does not render raw <script> tags as live nodes', () => {
      render(
        <MarkdownRenderer content={'Hello <script>alert("xss")</script>'} />
      );

      expect(document.querySelector('script')).not.toBeInTheDocument();
    });

    it('does not render <img onerror> as a live node', () => {
      const { container } = render(
        <MarkdownRenderer content={'<img src="x" onerror="alert(1)">'} />
      );

      // No live <img> and no live onerror attribute — the raw HTML is escaped
      // to inert text rather than parsed into DOM.
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
      expect(container.querySelector('img')).not.toBeInTheDocument();
      expect(container.querySelector('[onerror]')).not.toBeInTheDocument();
    });

    it('does not produce live event-handler attributes from raw HTML', () => {
      const { container } = render(
        <MarkdownRenderer content={'<div onclick="alert(1)">click</div>'} />
      );

      // The markup is rendered as escaped text, not a live element with a handler.
      expect(container.querySelector('[onclick]')).not.toBeInTheDocument();
      expect(container.textContent).toContain('onclick');
    });
  });

  describe('Empty / placeholder handling', () => {
    it('renders nothing meaningful for empty content', () => {
      const { container } = render(<MarkdownRenderer content='' />);

      expect(container.textContent).toBe('');
    });

    it('applies a custom className to the wrapper', () => {
      const { container } = render(
        <MarkdownRenderer content='hello' className='custom-class' />
      );

      expect(container.firstChild).toHaveClass('custom-class');
    });
  });
});
