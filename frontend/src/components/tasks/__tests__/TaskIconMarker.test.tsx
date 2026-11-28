import { render, screen } from '@testing-library/react';

import { TaskIconMarker } from '@/components/tasks/TaskIconMarker';

describe('TaskIconMarker', () => {
  it('draws the glyph as decoration', () => {
    render(<TaskIconMarker icon='tent' testId='some-row-icon' />);

    const svg = screen.getByTestId('some-row-icon').querySelector('svg');
    expect(svg).toHaveClass('lucide-tent');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('names the icon in visually hidden text', () => {
    render(<TaskIconMarker icon='paw-print' testId='some-row-icon' />);

    const name = screen.getByText('Paw print icon');
    expect(name).toHaveClass('sr-only');
    expect(screen.getByTestId('some-row-icon')).toContainElement(name);
  });
});
