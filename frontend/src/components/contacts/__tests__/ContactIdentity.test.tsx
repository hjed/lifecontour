import { render, screen } from '@testing-library/react';
import { ContactIdentity } from '../ContactIdentity';

// Mock the FavouriteToggle component
jest.mock('../FavouriteToggle', () => ({
  FavouriteToggle: ({
    contactId,
    contactName,
    isFavourite,
  }: {
    contactId: string;
    contactName: string;
    isFavourite: boolean;
  }) => (
    <button
      data-testid='favourite-toggle'
      data-contact-id={contactId}
      data-contact-name={contactName}
      data-is-favourite={isFavourite}
    >
      {isFavourite ? '★' : '☆'}
    </button>
  ),
}));

const mockContact = {
  id: '1',
  type: 'contacts' as const,
  attributes: {
    first_name: 'John',
    last_name: 'Doe',
    nick_name: 'Johnny',
    is_favourite: false,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    contact_methods: [],
    addresses: [],
    notes: [],
    relationships: [],
  },
  relationships: {
    tags: {
      data: [
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
    },
  },
};

describe('ContactIdentity', () => {
  describe('contact name display', () => {
    it('renders contact name correctly with nickname', () => {
      render(<ContactIdentity contact={mockContact} />);

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
      const contactWithoutNickname = {
        ...mockContact,
        attributes: { ...mockContact.attributes, nick_name: undefined },
      };
      render(<ContactIdentity contact={contactWithoutNickname} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.queryByText('"Johnny"')).not.toBeInTheDocument();
    });

    it('renders contact name without nickname when empty', () => {
      const contactWithEmptyNickname = {
        ...mockContact,
        attributes: { ...mockContact.attributes, nick_name: '' },
      };
      render(<ContactIdentity contact={contactWithEmptyNickname} />);

      expect(screen.getByText('John Doe')).toBeInTheDocument();
      expect(screen.queryByText('""')).not.toBeInTheDocument();
    });

    it('handles contact with only first name', () => {
      const contactWithOnlyFirstName = {
        ...mockContact,
        attributes: { ...mockContact.attributes, last_name: '' },
      };
      render(<ContactIdentity contact={contactWithOnlyFirstName} />);

      expect(screen.getByText('John')).toBeInTheDocument();
    });

    it('handles contact with empty last name', () => {
      const contactWithEmptyLastName = {
        ...mockContact,
        attributes: { ...mockContact.attributes, last_name: '' },
      };
      render(<ContactIdentity contact={contactWithEmptyLastName} />);

      expect(screen.getByText('John')).toBeInTheDocument();
    });
  });

  describe('favourite toggle functionality', () => {
    it('displays favourite toggle with correct state', () => {
      render(<ContactIdentity contact={mockContact} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toBeInTheDocument();
      expect(favouriteToggle).toHaveAttribute('data-contact-id', '1');
      expect(favouriteToggle).toHaveAttribute('data-contact-name', 'John Doe');
      expect(favouriteToggle).toHaveAttribute('data-is-favourite', 'false');
      expect(favouriteToggle).toHaveTextContent('☆');
    });

    it('displays favourite toggle for favourite contact', () => {
      const favouriteContact = {
        ...mockContact,
        attributes: { ...mockContact.attributes, is_favourite: true },
      };
      render(<ContactIdentity contact={favouriteContact} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-is-favourite', 'true');
      expect(favouriteToggle).toHaveTextContent('★');
    });

    it('passes correct contactName to FavouriteToggle', () => {
      render(<ContactIdentity contact={mockContact} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-contact-name', 'John Doe');
    });

    it('passes correct contactName with only first name', () => {
      const contactWithOnlyFirstName = {
        ...mockContact,
        attributes: { ...mockContact.attributes, last_name: '' },
      };
      render(<ContactIdentity contact={contactWithOnlyFirstName} />);

      const favouriteToggle = screen.getByTestId('favourite-toggle');
      expect(favouriteToggle).toHaveAttribute('data-contact-name', 'John');
    });
  });

  describe('styling and layout', () => {
    it('applies custom className correctly', () => {
      const { container } = render(
        <ContactIdentity contact={mockContact} className='custom-class' />
      );

      const identityElement = container.firstChild as HTMLElement;
      expect(identityElement).toHaveClass('custom-class');
    });

    it('has proper semantic structure', () => {
      render(<ContactIdentity contact={mockContact} />);

      // Check for h1 heading
      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toBeInTheDocument();
      expect(heading).toHaveTextContent('John Doe');
    });
  });

  describe('accessibility', () => {
    it('has proper heading structure', () => {
      render(<ContactIdentity contact={mockContact} />);

      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading).toBeInTheDocument();
      expect(heading).toHaveClass('text-2xl', 'font-bold', 'tracking-tight');
    });

    it('has proper semantic markup', () => {
      render(<ContactIdentity contact={mockContact} />);

      // Verify the heading is properly marked up
      const heading = screen.getByRole('heading', { level: 1 });
      expect(heading.tagName).toBe('H1');
    });
  });
});
