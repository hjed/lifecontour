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

    it('applies default styling classes', () => {
      render(<Card data-testid='card'>Content</Card>);

      const card = screen.getByTestId('card');
      expect(card).toHaveClass('rounded-lg', 'border', 'bg-card');
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

    it('applies default styling classes', () => {
      render(<CardHeader data-testid='card-header'>Content</CardHeader>);

      const header = screen.getByTestId('card-header');
      expect(header).toHaveClass('flex', 'flex-col', 'space-y-1.5', 'p-6');
    });
  });

  describe('CardTitle', () => {
    it('renders as h3 element', () => {
      render(<CardTitle>Test Title</CardTitle>);

      const title = screen.getByRole('heading', { level: 3 });
      expect(title).toBeInTheDocument();
      expect(title).toHaveTextContent('Test Title');
    });

    it('applies default styling classes', () => {
      render(<CardTitle>Test Title</CardTitle>);

      const title = screen.getByRole('heading', { level: 3 });
      expect(title).toHaveClass('text-2xl', 'font-semibold', 'leading-none');
    });
  });

  describe('CardDescription', () => {
    it('renders as paragraph element', () => {
      render(<CardDescription>Test description</CardDescription>);

      const description = screen.getByText('Test description');
      expect(description).toBeInTheDocument();
      expect(description.tagName).toBe('P');
    });

    it('applies default styling classes', () => {
      render(<CardDescription>Test description</CardDescription>);

      const description = screen.getByText('Test description');
      expect(description).toHaveClass('text-sm', 'text-muted-foreground');
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

    it('applies default styling classes', () => {
      render(<CardContent data-testid='card-content'>Content</CardContent>);

      const content = screen.getByTestId('card-content');
      expect(content).toHaveClass('p-6', 'pt-0');
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

    it('applies default styling classes', () => {
      render(<CardFooter data-testid='card-footer'>Content</CardFooter>);

      const footer = screen.getByTestId('card-footer');
      expect(footer).toHaveClass('flex', 'items-center', 'p-6', 'pt-0');
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
