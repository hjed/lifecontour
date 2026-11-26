import { render } from '@testing-library/react';

import { TaskIconGlyph } from '@/components/tasks/TaskIconGlyph';

describe('TaskIconGlyph', () => {
  it('draws the icon as decoration, leaving the name to its surroundings', () => {
    const { container } = render(<TaskIconGlyph icon='tent' />);

    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg).toHaveClass('lucide-tent');
  });

  it('takes the caller’s sizing and colour classes', () => {
    const { container } = render(
      <TaskIconGlyph icon='house' className='text-muted-foreground size-4' />
    );

    expect(container.querySelector('svg')).toHaveClass(
      'text-muted-foreground',
      'size-4'
    );
  });
});
