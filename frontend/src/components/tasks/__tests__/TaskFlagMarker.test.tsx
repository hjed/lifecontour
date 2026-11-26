/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { TaskFlagMarker } from '../TaskFlagMarker';

describe('TaskFlagMarker', () => {
  it('is an image named Flagged', () => {
    render(<TaskFlagMarker />);

    expect(screen.getByRole('img', { name: 'Flagged' })).toBeInTheDocument();
  });
});
