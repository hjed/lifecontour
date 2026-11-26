import { render, screen, waitFor } from '@testing-library/react';
import { ContactAvatar } from '../ContactAvatar';
import { MockImage } from '@/test-utils/mock-image';

describe('ContactAvatar', () => {
  let originalImage: typeof window.Image;

  beforeEach(() => {
    originalImage = window.Image;
    window.Image = MockImage as unknown as typeof window.Image;
  });

  afterEach(() => {
    window.Image = originalImage;
  });

  describe('initials generation', () => {
    it('renders initials correctly for full name', () => {
      render(<ContactAvatar firstName='John' lastName='Doe' />);

      expect(screen.getByText('JD')).toBeInTheDocument();
    });

    it('handles missing last name gracefully', () => {
      render(<ContactAvatar firstName='John' />);

      expect(screen.getByText('J')).toBeInTheDocument();
    });

    it('handles empty first name', () => {
      render(<ContactAvatar firstName='' lastName='Doe' />);

      expect(screen.getByText('D')).toBeInTheDocument();
    });

    it('handles both names empty', () => {
      render(<ContactAvatar firstName='' lastName='' />);

      expect(screen.getByText('?')).toBeInTheDocument();
    });

    it('handles whitespace-only names', () => {
      render(<ContactAvatar firstName='  ' lastName='  ' />);

      expect(screen.getByText('?')).toBeInTheDocument();
    });

    it('handles special characters in names', () => {
      render(<ContactAvatar firstName='José' lastName="O'Connor" />);

      expect(screen.getByText('JO')).toBeInTheDocument();
    });

    it('handles long names correctly', () => {
      render(<ContactAvatar firstName='Alexander' lastName='Montgomery' />);

      expect(screen.getByText('AM')).toBeInTheDocument();
    });
  });

  describe('image display', () => {
    it('displays image when imageUrl provided and loaded', async () => {
      render(
        <ContactAvatar
          firstName='John'
          lastName='Doe'
          imageUrl='https://example.com/avatar.jpg'
        />
      );

      const image = await screen.findByAltText('John Doe');
      expect(image).toHaveAttribute('src', 'https://example.com/avatar.jpg');
      expect(image).toHaveAttribute('alt', 'John Doe');
    });

    it('replaces initials with the image once it has loaded', async () => {
      render(
        <ContactAvatar
          firstName='John'
          lastName='Doe'
          imageUrl='https://example.com/avatar.jpg'
        />
      );

      // Once the image loads, the initials fallback must no longer be rendered
      // (regression: image and initials previously rendered side-by-side).
      await screen.findByAltText('John Doe');
      await waitFor(() =>
        expect(screen.queryByText('JD')).not.toBeInTheDocument()
      );
    });

    it('falls back to initials when image fails to load', async () => {
      render(
        <ContactAvatar
          firstName='John'
          lastName='Doe'
          imageUrl='https://example.com/broken.jpg'
        />
      );

      // The image errors, so only the initials fallback is shown.
      await waitFor(() => expect(screen.getByText('JD')).toBeInTheDocument());
      expect(screen.queryByAltText('John Doe')).not.toBeInTheDocument();
    });

    it('generates correct alt text for image', async () => {
      render(
        <ContactAvatar
          firstName='Jane'
          lastName='Smith'
          imageUrl='https://example.com/avatar.jpg'
        />
      );

      const image = await screen.findByAltText('Jane Smith');
      expect(image).toHaveAttribute('alt', 'Jane Smith');
    });

    it('generates alt text with only first name', async () => {
      render(
        <ContactAvatar
          firstName='Jane'
          imageUrl='https://example.com/avatar.jpg'
        />
      );

      const image = await screen.findByAltText('Jane');
      expect(image).toHaveAttribute('alt', 'Jane');
    });
  });

  describe('sizing', () => {
    it('applies small size classes', () => {
      render(<ContactAvatar firstName='John' lastName='Doe' size='sm' />);

      const avatar = screen
        .getByText('JD')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveClass('h-8', 'w-8');
    });

    it('applies medium size classes (default)', () => {
      render(<ContactAvatar firstName='John' lastName='Doe' />);

      const avatar = screen
        .getByText('JD')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveClass('h-10', 'w-10');
    });

    it('applies large size classes', () => {
      render(<ContactAvatar firstName='John' lastName='Doe' size='lg' />);

      const avatar = screen
        .getByText('JD')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveClass('h-16', 'w-16');
    });
  });

  describe('styling and accessibility', () => {
    it('applies custom className correctly', () => {
      render(
        <ContactAvatar
          firstName='John'
          lastName='Doe'
          className='custom-class'
        />
      );

      const avatar = screen
        .getByText('JD')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveClass('custom-class');
    });

    it('has proper accessibility attributes', () => {
      render(<ContactAvatar firstName='John' lastName='Doe' />);

      const avatar = screen
        .getByText('JD')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveAttribute('role', 'img');
      expect(avatar).toHaveAttribute('aria-label', 'John Doe');
    });

    it('has proper accessibility attributes with only first name', () => {
      render(<ContactAvatar firstName='John' />);

      const avatar = screen
        .getByText('J')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveAttribute('aria-label', 'John');
    });

    it('has proper accessibility attributes for empty names', () => {
      render(<ContactAvatar firstName='' lastName='' />);

      const avatar = screen
        .getByText('?')
        .closest('[data-testid="avatar-contact"]');
      expect(avatar).toHaveAttribute('aria-label', 'Contact avatar');
    });
  });
});
