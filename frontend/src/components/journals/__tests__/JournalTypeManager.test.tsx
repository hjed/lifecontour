import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JournalTypeManager } from '../JournalTypeManager';
import { JournalType } from '@/types/journals';

describe('JournalTypeManager', () => {
  const mockOnTypeAdd = jest.fn();
  const mockOnTypeRemove = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    // Use window.confirm instead of global.confirm, and cast to any to mock it
    (window as any).confirm = jest.fn(() => true);
  });

  const renderComponent = (currentTypes: JournalType[] = []) => {
    render(
      <JournalTypeManager
        currentTypes={currentTypes}
        onTypeAdd={mockOnTypeAdd}
        onTypeRemove={mockOnTypeRemove}
      />
    );
  };

  describe('Rendering', () => {
    it('renders add button when no types present', () => {
      renderComponent();
      expect(screen.getByTestId('add-type-button')).toBeInTheDocument();
    });

    it('renders existing types', () => {
      renderComponent([JournalType.NOTE, JournalType.EVENT]);
      expect(
        screen.getByTestId(`manage-type-${JournalType.NOTE}`)
      ).toBeInTheDocument();
      expect(
        screen.getByTestId(`manage-type-${JournalType.EVENT}`)
      ).toBeInTheDocument();
    });
  });

  describe('Interaction', () => {
    it('shows dropdown menu when clicking add type', async () => {
      const user = userEvent.setup();
      renderComponent();

      await user.click(screen.getByTestId('add-type-button'));
      expect(
        await screen.findByTestId(`add-type-option-${JournalType.NOTE}`)
      ).toBeInTheDocument();
    });

    it('calls onTypeAdd when a new type is selected', async () => {
      const user = userEvent.setup();
      renderComponent();

      await user.click(screen.getByTestId('add-type-button'));
      const option = await screen.findByTestId(
        `add-type-option-${JournalType.EVENT}`
      );
      await user.click(option);

      expect(mockOnTypeAdd).toHaveBeenCalledWith(JournalType.EVENT);
    });

    it('shows remove button when hovering/clicking on existing type', async () => {
      const user = userEvent.setup();
      renderComponent([JournalType.NOTE]);

      // Radix HoverCard opens on hover
      await user.hover(screen.getByTestId(`manage-type-${JournalType.NOTE}`));

      const removeBtn = await screen.findByTestId(
        `remove-type-${JournalType.NOTE}`
      );
      expect(removeBtn).toBeInTheDocument();

      await user.click(removeBtn);

      expect(window.confirm).toHaveBeenCalled();
      expect(mockOnTypeRemove).toHaveBeenCalledWith(JournalType.NOTE);
    });

    it('does not remove type if confirm is cancelled', async () => {
      const user = userEvent.setup();
      (window as any).confirm = jest.fn(() => false);
      renderComponent([JournalType.NOTE]);

      await user.hover(screen.getByTestId(`manage-type-${JournalType.NOTE}`));
      const removeBtn = await screen.findByTestId(
        `remove-type-${JournalType.NOTE}`
      );

      await user.click(removeBtn);

      expect(window.confirm).toHaveBeenCalled();
      expect(mockOnTypeRemove).not.toHaveBeenCalled();
    });
  });

  describe('Error Handling', () => {
    it('handles onTypeAdd errors gracefully', async () => {
      const user = userEvent.setup();
      const consoleSpy = jest
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      mockOnTypeAdd.mockRejectedValueOnce(new Error('API Error'));

      renderComponent();

      // Let's suppress the unhandled promise rejection warning for this specific test
      const originalListeners = process.listeners('unhandledRejection');
      process.removeAllListeners('unhandledRejection');
      process.on('unhandledRejection', () => {});

      await user.click(screen.getByTestId('add-type-button'));

      const option = await screen.findByTestId(
        `add-type-option-${JournalType.EVENT}`
      );
      await user.click(option);

      // The disabled state gets cleared in finally
      await waitFor(() => {
        expect(screen.getByTestId('add-type-button')).not.toBeDisabled();
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to add type:',
        expect.any(Error)
      );

      // Restore listeners
      process.removeAllListeners('unhandledRejection');
      for (const listener of originalListeners) {
        process.on('unhandledRejection', listener);
      }
      consoleSpy.mockRestore();
    });

    it('handles onTypeRemove errors gracefully', async () => {
      const user = userEvent.setup();
      const consoleSpy = jest
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      mockOnTypeRemove.mockRejectedValueOnce(new Error('API Error'));

      renderComponent([JournalType.NOTE]);

      const originalListeners = process.listeners('unhandledRejection');
      process.removeAllListeners('unhandledRejection');
      process.on('unhandledRejection', () => {});

      await user.hover(screen.getByTestId(`manage-type-${JournalType.NOTE}`));
      const removeBtn = await screen.findByTestId(
        `remove-type-${JournalType.NOTE}`
      );

      await user.click(removeBtn);

      expect(window.confirm).toHaveBeenCalled();

      await waitFor(() => {
        expect(
          screen.getByTestId(`manage-type-${JournalType.NOTE}`)
        ).not.toBeDisabled();
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to remove type:',
        expect.any(Error)
      );

      process.removeAllListeners('unhandledRejection');
      for (const listener of originalListeners) {
        process.on('unhandledRejection', listener);
      }
      consoleSpy.mockRestore();
    });
  });
});
