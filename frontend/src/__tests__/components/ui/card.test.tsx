import { render, screen } from '@testing-library/react';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

describe('Card Components', () => {
  describe('Card', () => {
    it('renders children correctly', () => {
      render(
        <Card data-testid='card'>
          <div>Card content</div>
        </Card>
      );

      const card = screen.getByTestId('card');
      expect(card).toBeInTheDocument();
      expect(card).toHaveTextContent('Card content');
    });

    it('applies custom className', () => {
      render(
        <Card className='custom-class' data-testid='card'>
          Content
        </Card>
      );

      const card = screen.getByTestId('card');
      expect(card).toHaveClass('custom-class');
    });

    it('marks its slot and theme surface', () => {
      render(<Card data-testid='card'>Content</Card>);

      const card = screen.getByTestId('card');
      expect(card).toHaveAttribute('data-slot', 'card');
      expect(card).toHaveClass('bg-card', 'text-card-foreground');
    });

    // Local to this app: Vega clips the card, which hid dropdowns that render
    // in place rather than in a portal (ContactSearchCombobox inside the
    // Relationships card). Edge-to-edge images still get their rounded
    // corners from the card's own img selectors.
    it('does not clip content that overflows it', () => {
      render(<Card data-testid='card'>Content</Card>);

      expect(screen.getByTestId('card')).not.toHaveClass('overflow-hidden');
    });
  });

  describe('CardHeader', () => {
    it('renders children correctly', () => {
      render(
        <CardHeader data-testid='card-header'>
          <div>Header content</div>
        </CardHeader>
      );

      const header = screen.getByTestId('card-header');
      expect(header).toBeInTheDocument();
      expect(header).toHaveTextContent('Header content');
    });

    it('marks its slot and theme surface', () => {
      render(<CardHeader data-testid='card-header'>Content</CardHeader>);

      const header = screen.getByTestId('card-header');
      expect(header).toHaveAttribute('data-slot', 'card-header');
    });
  });

  describe('CardTitle', () => {
    it('renders as h3 element', () => {
      render(<CardTitle>Test Title</CardTitle>);

      const title = screen.getByRole('heading', { level: 3 });
      expect(title).toBeInTheDocument();
      expect(title).toHaveTextContent('Test Title');
    });

    it('marks its slot and theme surface', () => {
      render(<CardTitle>Test Title</CardTitle>);

      const title = screen.getByRole('heading', { level: 3 });
      // Local to this app, kept across shadcn regenerations: Vega renders a
      // div; ours stays an h3 so every card keeps its heading semantics.
      expect(title.tagName).toBe('H3');
      expect(title).toHaveAttribute('data-slot', 'card-title');
    });
  });

  describe('CardDescription', () => {
    it('renders as paragraph element', () => {
      render(<CardDescription>Test description</CardDescription>);

      const description = screen.getByText('Test description');
      expect(description).toBeInTheDocument();
      expect(description.tagName).toBe('P');
    });

    it('marks its slot and theme surface', () => {
      render(<CardDescription>Test description</CardDescription>);

      const description = screen.getByText('Test description');
      expect(description).toHaveClass('text-muted-foreground');
      expect(description).toHaveAttribute('data-slot', 'card-description');
    });
  });

  describe('CardContent', () => {
    it('renders children correctly', () => {
      render(
        <CardContent data-testid='card-content'>
          <div>Content text</div>
        </CardContent>
      );

      const content = screen.getByTestId('card-content');
      expect(content).toBeInTheDocument();
      expect(content).toHaveTextContent('Content text');
    });

    it('marks its slot and theme surface', () => {
      render(<CardContent data-testid='card-content'>Content</CardContent>);

      const content = screen.getByTestId('card-content');
      expect(content).toHaveAttribute('data-slot', 'card-content');
    });
  });

  describe('CardFooter', () => {
    it('renders children correctly', () => {
      render(
        <CardFooter data-testid='card-footer'>
          <div>Footer content</div>
        </CardFooter>
      );

      const footer = screen.getByTestId('card-footer');
      expect(footer).toBeInTheDocument();
      expect(footer).toHaveTextContent('Footer content');
    });

    it('marks its slot and theme surface', () => {
      render(<CardFooter data-testid='card-footer'>Content</CardFooter>);

      const footer = screen.getByTestId('card-footer');
      expect(footer).toHaveClass('flex', 'items-center');
      expect(footer).toHaveAttribute('data-slot', 'card-footer');
    });
  });

  describe('Complete Card Example', () => {
    it('renders a complete card with all components', () => {
      render(
        <Card data-testid='complete-card'>
          <CardHeader>
            <CardTitle>Card Title</CardTitle>
            <CardDescription>Card description text</CardDescription>
          </CardHeader>
          <CardContent>
            <p>Main card content goes here</p>
          </CardContent>
          <CardFooter>
            <button>Action Button</button>
          </CardFooter>
        </Card>
      );

      const card = screen.getByTestId('complete-card');
      expect(card).toBeInTheDocument();

      expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent(
        'Card Title'
      );
      expect(screen.getByText('Card description text')).toBeInTheDocument();
      expect(
        screen.getByText('Main card content goes here')
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Action Button' })
      ).toBeInTheDocument();
    });
  });
});
