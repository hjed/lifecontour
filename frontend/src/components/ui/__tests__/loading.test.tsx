/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import {
  LoadingSpinner,
  PageLoading,
  Skeleton,
  CardSkeleton,
  ListSkeleton,
  TableSkeleton,
  LoadingOverlay,
  ButtonLoading,
} from '../loading';

describe('LoadingSpinner', () => {
  it('renders spinner with default size', () => {
    render(<LoadingSpinner />);

    const spinner = screen.getByTestId('loading-spinner');
    expect(spinner).toHaveClass('h-6', 'w-6', 'animate-spin');
    expect(screen.getByText('Loading...')).toHaveClass('sr-only');
  });

  it('renders spinner with custom size', () => {
    render(<LoadingSpinner size='lg' />);

    const spinner = screen.getByTestId('loading-spinner');
    expect(spinner).toHaveClass('h-8', 'w-8');
  });

  it('renders spinner with text', () => {
    render(<LoadingSpinner text='Please wait...' />);

    expect(screen.getByText('Please wait...')).toBeInTheDocument();
    expect(screen.getByText('Loading...')).toHaveClass('sr-only');
  });

  it('applies custom className', () => {
    render(<LoadingSpinner className='custom-spinner' />);

    const container = screen.getByText('Loading...').parentElement;
    expect(container).toHaveClass('custom-spinner');
  });
});

describe('PageLoading', () => {
  it('renders page loading with default text', () => {
    const { container } = render(<PageLoading />);

    expect(screen.getAllByText('Loading...')).toHaveLength(2); // One visible, one sr-only
    const pageContainer = container.firstChild as HTMLElement;
    expect(pageContainer).toHaveClass('min-h-[400px]');
  });

  it('renders page loading with custom text', () => {
    render(<PageLoading text='Loading page...' />);

    expect(screen.getByText('Loading page...')).toBeInTheDocument();
    expect(screen.getByText('Loading...')).toHaveClass('sr-only');
  });

  it('applies custom className', () => {
    const { container } = render(
      <PageLoading className='custom-page-loading' />
    );

    const pageContainer = container.firstChild as HTMLElement;
    expect(pageContainer).toHaveClass('custom-page-loading');
  });
});

describe('Skeleton', () => {
  it('renders skeleton with default styling', () => {
    const { container } = render(<Skeleton />);

    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveClass('animate-pulse', 'rounded-md', 'bg-muted');
  });

  it('applies custom className', () => {
    const { container } = render(<Skeleton className='h-4 w-full' />);

    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveClass('h-4', 'w-full');
  });
});

describe('CardSkeleton', () => {
  it('renders card skeleton structure', () => {
    const { container } = render(<CardSkeleton />);

    const skeletons = container.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThan(0);

    const cardContainer = container.firstChild as HTMLElement;
    expect(cardContainer).toHaveClass('rounded-lg', 'border', 'p-4');
  });

  it('applies custom className', () => {
    const { container } = render(<CardSkeleton className='custom-card' />);

    const cardContainer = container.firstChild as HTMLElement;
    expect(cardContainer).toHaveClass('custom-card');
  });
});

describe('ListSkeleton', () => {
  it('renders default number of list items', () => {
    const { container } = render(<ListSkeleton />);

    const skeletons = container.querySelectorAll('.animate-pulse');
    // Each item has multiple skeletons (avatar + text lines)
    expect(skeletons.length).toBeGreaterThan(3);
  });

  it('renders custom number of items', () => {
    const { container } = render(<ListSkeleton itemCount={5} />);

    const skeletons = container.querySelectorAll('.animate-pulse');
    // Should have more skeletons for 5 items vs default 3
    expect(skeletons.length).toBeGreaterThan(5);
  });

  it('applies custom className', () => {
    const { container } = render(<ListSkeleton className='custom-list' />);

    const listContainer = container.firstChild as HTMLElement;
    expect(listContainer).toHaveClass('custom-list');
  });
});

describe('TableSkeleton', () => {
  it('renders default table structure', () => {
    const { container } = render(<TableSkeleton />);

    const skeletons = container.querySelectorAll('.animate-pulse');
    // Should have skeletons for header + rows
    expect(skeletons.length).toBeGreaterThan(10); // 4 columns * (1 header + 5 rows)
  });

  it('renders custom table dimensions', () => {
    const { container } = render(<TableSkeleton rows={3} columns={2} />);

    const skeletons = container.querySelectorAll('.animate-pulse');
    // Should have 2 columns * (1 header + 3 rows) = 8 skeletons
    expect(skeletons).toHaveLength(8);
  });

  it('applies custom className', () => {
    const { container } = render(<TableSkeleton className='custom-table' />);

    const tableContainer = container.firstChild as HTMLElement;
    expect(tableContainer).toHaveClass('custom-table');
  });
});

describe('LoadingOverlay', () => {
  it('renders children when not loading', () => {
    render(
      <LoadingOverlay isLoading={false}>
        <div>Content</div>
      </LoadingOverlay>
    );

    expect(screen.getByText('Content')).toBeInTheDocument();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
  });

  it('shows overlay when loading', () => {
    render(
      <LoadingOverlay isLoading={true}>
        <div>Content</div>
      </LoadingOverlay>
    );

    expect(screen.getByText('Content')).toBeInTheDocument();
    expect(screen.getAllByText('Loading...')).toHaveLength(2); // One visible, one sr-only

    // Check overlay styling using test ID
    const spinner = screen.getByTestId('loading-spinner');
    const overlay = spinner.parentElement?.parentElement;
    expect(overlay).toHaveClass(
      'absolute',
      'inset-0',
      'z-50',
      'bg-background/80',
      'backdrop-blur-sm'
    );
  });

  it('shows custom loading text', () => {
    render(
      <LoadingOverlay isLoading={true} text='Processing...'>
        <div>Content</div>
      </LoadingOverlay>
    );

    expect(screen.getByText('Processing...')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(
      <LoadingOverlay isLoading={false} className='custom-overlay'>
        <div>Content</div>
      </LoadingOverlay>
    );

    const container = screen.getByText('Content').parentElement;
    expect(container).toHaveClass('custom-overlay');
  });
});

describe('ButtonLoading', () => {
  it('renders button loading with default text', () => {
    const { container } = render(<ButtonLoading />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    const spinner = container.querySelector('.animate-spin');
    expect(spinner).toHaveClass('h-4', 'w-4', 'animate-spin');
  });

  it('renders button loading with custom text', () => {
    render(<ButtonLoading text='Saving...' />);

    expect(screen.getByText('Saving...')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    render(<ButtonLoading className='custom-button-loading' />);

    const container = screen.getByText('Loading...').parentElement;
    expect(container).toHaveClass('custom-button-loading');
  });
});

describe('accessibility', () => {
  it('has proper ARIA attributes for loading states', () => {
    render(<LoadingSpinner />);

    expect(screen.getByText('Loading...')).toHaveClass('sr-only');
  });

  it('marks decorative elements as hidden from screen readers', () => {
    const { container } = render(<Skeleton />);

    const skeleton = container.firstChild as HTMLElement;
    expect(skeleton).toHaveAttribute('aria-hidden', 'true');
  });

  it('provides accessible loading overlay', () => {
    render(
      <LoadingOverlay isLoading={true}>
        <div>Content</div>
      </LoadingOverlay>
    );

    // Screen reader should still announce loading
    expect(screen.getAllByText('Loading...')).toHaveLength(2); // One visible, one sr-only
  });
});
