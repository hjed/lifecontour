/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { FavouriteToggle } from '../FavouriteToggle';
import { useToggleContactFavourite } from '@/lib/api/contacts';
import { userEvent } from '@/test-utils';

// Mock the API hook
jest.mock('@/lib/api/contacts', () => ({
  useToggleContactFavourite: jest.fn(),
}));

const mockUseToggleContactFavourite =
  useToggleContactFavourite as jest.MockedFunction<
    typeof useToggleContactFavourite
  >;

describe('FavouriteToggle', () => {
  const mockMutate = jest.fn();

  beforeEach(() => {
    mockUseToggleContactFavourite.mockReturnValue({
      mutate: mockMutate,
      isPending: false,
      isError: false,
      error: null,
    } as never);
    mockMutate.mockClear();
  });

  it('should render filled star when contact is favourite', () => {
    render(
      <FavouriteToggle
        contactId='1'
        isFavourite={true}
        contactName='John Doe'
      />
    );

    const button = screen.getByRole('button', {
      name: /remove john doe from favourites/i,
    });
    expect(button).toBeInTheDocument();

    // Check for filled star (should have fill class)
    const starIcon = button.querySelector('svg');
    expect(starIcon).toHaveClass('fill-yellow-400');
  });

  it('should render empty star when contact is not favourite', () => {
    render(
      <FavouriteToggle
        contactId='1'
        isFavourite={false}
        contactName='John Doe'
      />
    );

    const button = screen.getByRole('button', {
      name: /add john doe to favourites/i,
    });
    expect(button).toBeInTheDocument();

    // Check for empty star (should not have fill class)
    const starIcon = button.querySelector('svg');
    expect(starIcon).not.toHaveClass('fill-yellow-400');
  });

  it('should call toggle mutation when clicked', async () => {
    const user = userEvent.setup();

    render(
      <FavouriteToggle
        contactId='1'
        isFavourite={false}
        contactName='John Doe'
      />
    );

    const button = screen.getByRole('button');
    await user.click(button);

    expect(mockMutate).toHaveBeenCalledWith('1');
  });

  it('should be disabled when mutation is pending', () => {
    mockUseToggleContactFavourite.mockReturnValue({
      mutate: mockMutate,
      isPending: true,
      isError: false,
      error: null,
    } as never);

    render(
      <FavouriteToggle
        contactId='1'
        isFavourite={false}
        contactName='John Doe'
      />
    );

    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
  });

  it('should have proper accessibility attributes', () => {
    render(
      <FavouriteToggle
        contactId='1'
        isFavourite={true}
        contactName='John Doe'
      />
    );

    const button = screen.getByRole('button');
    expect(button).toHaveAttribute(
      'aria-label',
      'Remove John Doe from favourites'
    );
    expect(button).toHaveAttribute('type', 'button');
  });

  it('should support custom className', () => {
    render(
      <FavouriteToggle
        contactId='1'
        isFavourite={false}
        contactName='John Doe'
        className='custom-class'
      />
    );

    const button = screen.getByRole('button');
    expect(button).toHaveClass('custom-class');
  });
});
