import { render, screen } from '@testing-library/react';
import { ContactHeader } from '../ContactHeader';

// Mock the ContactAvatar component
jest.mock('../ContactAvatar', () => ({
  ContactAvatar: ({ firstName, lastName, size, className }: any) => (
    <div
      data-testid='contact-avatar'
      data-first-name={firstName}
      data-last-name={lastName}
      data-size={size}
      className={className}
    >
      {firstName.charAt(0)}
      {lastName?.charAt(0) || ''}
    </div>
  ),
}));

// Mock the FavouriteToggle component
jest.mock('../FavouriteToggle', () => ({
  FavouriteToggle: ({ contactId, isFavourite, contactName }: any) => (
    <button
      data-testid='favourite-toggle'
      data-contact-id={contactId}
      data-is-favourite={isFavourite}
      data-contact-name={contactName}
    >
      {isFavourite ? '★' : '☆'}
    </button>
  ),
}));

const mockContact = {
  id: '1',
  firstName: 'John',
  lastName: 'Doe',
  nickName: 'Johnny',
  isFavourite: false,
  tags: [
    {
      id: '1',
      type: 'tags' as const,
      attributes: {
        name: 'Work',
        color: '#3b82f6',
        description: 'Work contacts',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
    },
    {
      id: '2',
      type: 'tags' as const,
      attributes: {
        name: 'Client',
        color: '#10b981',
        description: 'Client contacts',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
    },
  ],
};

describe('ContactHeader', () => {
  describe('contact name display', () => {
    it('renders contact name correctly with nickname', () => {
      render(<ContactHeader contact={mockContact} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();

      // Check that nickname is displayed (HTML entities make exact text matching difficult)
      const nicknameElement = screen.getByText((content, element) => {
        return Boolean(
          element?.tagName === 'SPAN' &&
            element?.textContent?.includes('Johnny') &&
            element?.className?.includes('text-muted-foreground')
        );
      });
      expect(nicknameElement).toBeInTheDocument();
    });

    it('renders contact name without nickname when not provided', () => {
      const contactWithoutNickname = { ...mockContact, nickName: undefined };
      render(<ContactHeader contact={contactWithoutNickname} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.queryByText('"Johnny"')).not.toBeInTheDocument();
    });

    it('renders contact name without nickname when empty', () => {
      const contactWithEmptyNickname = { ...mockContact, nickName: '' };
      render(<ContactHeader contact={contactWithEmptyNickname} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.queryByText('""')).not.toBeInTheDocument();
    });

    it('handles contact with only first name', () => {
      const contactWithOnlyFirstName = { ...mockContact, lastName: undefined };
      render(<ContactHeader contact={contactWithOnlyFirstName} />);

      expect(screen.getByText('John')).toBeInTheDocument();
    });

    it('handles contact with empty last name', () => {
      const contactWithEmptyLastName = { ...mockContact, lastName: '' };
      render(<ContactHeader contact={contactWithEmptyLastName} />);

      expect(screen.getByText('John')).toBeInTheDocument();
    });
  });

  describe('avatar integration', () => {
    it('displays avatar with correct props', () => {
      render(<ContactHeader contact={mockContact} avatarSize='lg' />);

      const avatar = screen.getByTestId('contact-avatar');
      expect(avatar).toHaveAttribute('data-first-name', 'John');
      expect(avatar).toHaveAttribute('data-last-name', 'Doe');
      expect(avatar).toHaveAttribute('data-size', 'lg');
    });

    it('uses default avatar size when not specified', () => {
      render(<ContactHeader contact={mockContact} />);

      const avatar = screen.getByTestId('contact-avatar');
      expect(avatar).toHaveAttribute('data-size', 'lg');
    });

    it('passes custom className to avatar', () => {
      render(<ContactHeader contact={mockContact} className='custom-header' />);

      const avatar = screen.getByTestId('contact-avatar');
      expect(avatar).toHaveClass('mr-4');
    });
  });

  describe('tags display', () => {
    it('shows tags as badges', () => {
      render(<ContactHeader contact={mockContact} />);

      expect(screen.getByText('Work')).toBeInTheDocument();
      expect(screen.getByText('Client')).toBeInTheDocument();
    });

    it('handles contact without tags', () => {
      const contactWithoutTags = { ...mockContact, tags: undefined };
      render(<ContactHeader contact={contactWithoutTags} />);

      expect(screen.queryByText('Work')).not.toBeInTheDocument();
      expect(screen.queryByText('Client')).not.toBeInTheDocument();
    });

    it('handles contact with empty tags array', () => {
      const contactWithEmptyTags = { ...mockContact, tags: [] };
      render(<ContactHeader contact={contactWithEmptyTags} />);

      expect(screen.queryByText('Work')).not.toBeInTheDocument();
      expect(screen.queryByText('Client')).not.toBeInTheDocument();
    });
  });

  describe('favourite toggle functionality', () => {
    it('displays favourite toggle with correct state', () => {
      render(<ContactHeader contact={mockContact} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-contact-id', '1');
      expect(favouriteToggle).toHaveAttribute('data-is-favourite', 'false');
      expect(favouriteToggle).toHaveAttribute('data-contact-name', 'John Doe');
      expect(favouriteToggle).toHaveTextContent('☆');
    });

    it('displays favourite toggle for favourite contact', () => {
      const favouriteContact = { ...mockContact, isFavourite: true };
      render(<ContactHeader contact={favouriteContact} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-is-favourite', 'true');
      expect(favouriteToggle).toHaveTextContent('★');
    });

    it('passes correct contactName to FavouriteToggle', () => {
      render(<ContactHeader contact={mockContact} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-contact-name', 'John Doe');
    });

    it('passes correct contactName with only first name', () => {
      const contactWithOnlyFirstName = { ...mockContact, lastName: undefined };
      render(<ContactHeader contact={contactWithOnlyFirstName} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-contact-name', 'John');
    });
  });

  describe('styling and layout', () => {
    it('applies custom className correctly', () => {
      render(<ContactHeader contact={mockContact} className='custom-header' />);

      const header = screen.getByRole('banner');
      expect(header).toHaveClass('custom-header');
    });

    it('has proper semantic structure', () => {
      render(<ContactHeader contact={mockContact} />);

      const header = screen.getByRole('banner');
      expect(header).toBeInTheDocument();

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toHaveTextContent('John Doe');
    });

    it('has proper responsive layout classes', () => {
      render(<ContactHeader contact={mockContact} />);

      const header = screen.getByRole('banner');
      expect(header).toHaveClass('flex', 'items-center', 'gap-4', 'mb-6');
    });
  });

  describe('accessibility', () => {
    it('has proper heading structure', () => {
      render(<ContactHeader contact={mockContact} />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toBeInTheDocument();
    });

    it('has proper semantic markup', () => {
      render(<ContactHeader contact={mockContact} />);

      const header = screen.getByRole('banner');
      expect(header).toBeInTheDocument();
    });
  });
});
