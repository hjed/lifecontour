/**
 * Tests for JournalCreateForm component.
 *
 * Tests form rendering, validation, submission, and type selection.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalCreateForm } from '../JournalCreateForm';
import { JournalType } from '@/types/journals';

// Mock the useCreateJournal hook
const mockMutateAsync = jest.fn();
jest.mock('@/lib/api/journals', () => ({
  useCreateJournal: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
  }),
}));

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

describe('JournalCreateForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders all required form fields', () => {
      render(<JournalCreateForm />);

      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/date range/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/content/i)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: /create journal/i })
      ).toBeInTheDocument();
    });

    it('renders type selector checkboxes', () => {
      render(<JournalCreateForm />);

      expect(screen.getByLabelText(/note/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/event/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/mood rating/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/plan/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/travel/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/photo album/i)).toBeInTheDocument();
    });

    it('renders cancel button', () => {
      render(<JournalCreateForm />);

      expect(
        screen.getByRole('button', { name: /cancel/i })
      ).toBeInTheDocument();
    });
  });

  describe('Validation', () => {
    it('shows error when title is empty', async () => {
      const user = userEvent.setup();
      render(<JournalCreateForm />);

      const submitButton = screen.getByRole('button', {
        name: /create journal/i,
      });
      await user.click(submitButton);

      await waitFor(() => {
        expect(screen.getByText(/title is required/i)).toBeInTheDocument();
      });
    });

    it('allows submission with valid title and date range', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '1', type: 'journals', attributes: {} },
      });

      render(<JournalCreateForm />);

      const titleInput = screen.getByLabelText(/title/i);
      await user.type(titleInput, 'Test Journal');

      const submitButton = screen.getByRole('button', {
        name: /create journal/i,
      });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalled();
      });
    });
  });

  describe('Type Selection', () => {
    it('allows selecting multiple types', async () => {
      const user = userEvent.setup();
      render(<JournalCreateForm />);

      const noteCheckbox = screen.getByLabelText(/note/i);
      const eventCheckbox = screen.getByLabelText(/event/i);

      await user.click(noteCheckbox);
      await user.click(eventCheckbox);

      expect(noteCheckbox).toBeChecked();
      expect(eventCheckbox).toBeChecked();
    });

    it('allows deselecting types', async () => {
      const user = userEvent.setup();
      render(<JournalCreateForm />);

      const noteCheckbox = screen.getByLabelText(/note/i);

      await user.click(noteCheckbox);
      expect(noteCheckbox).toBeChecked();

      await user.click(noteCheckbox);
      expect(noteCheckbox).not.toBeChecked();
    });
  });

  describe('Form Submission', () => {
    it('submits form with correct data', async () => {
      const user = userEvent.setup();
      mockMutateAsync.mockResolvedValueOnce({
        data: { id: '1', type: 'journals', attributes: {} },
      });

      render(<JournalCreateForm />);

      const titleInput = screen.getByLabelText(/title/i);
      const contentInput = screen.getByLabelText(/content/i);
      const noteCheckbox = screen.getByLabelText(/note/i);

      await user.type(titleInput, 'Test Journal');
      await user.type(contentInput, 'Test content');
      await user.click(noteCheckbox);

      const submitButton = screen.getByRole('button', {
        name: /create journal/i,
      });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Test Journal',
            content: 'Test content',
            types: [JournalType.NOTE],
          })
        );
      });
    });
  });
});
