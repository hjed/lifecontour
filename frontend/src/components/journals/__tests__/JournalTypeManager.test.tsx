import { render, screen, waitFor } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { JournalTypeManager } from '../JournalTypeManager';
import { JournalType } from '@/types/journals';

describe('JournalTypeManager', () => {
  const mockOnTypeAdd = jest.fn();
  const mockOnTypeRemove = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    // Use globalThis.confirm instead of global.confirm, and cast to unknown to mock it
    (globalThis as unknown as { confirm: jest.Mock }).confirm = jest.fn(
      () => true
    );
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

    it('shows remove button when clicking an existing type', async () => {
      const user = userEvent.setup();
      renderComponent([JournalType.NOTE]);

      // A click (or tap) opens the manage popover; hover alone is not
      // reachable on touch devices.
      await user.click(screen.getByTestId(`manage-type-${JournalType.NOTE}`));

      const removeBtn = await screen.findByTestId(
        `remove-type-${JournalType.NOTE}`
      );
      expect(removeBtn).toBeInTheDocument();

      await user.click(removeBtn);

      expect(globalThis.confirm).toHaveBeenCalled();
      expect(mockOnTypeRemove).toHaveBeenCalledWith(JournalType.NOTE);
    });

    // A touch tap fires no hover, so a hover-only overlay never opens on a
    // phone; the remove control must be reachable by keyboard and by tap.
    it.each<[string, (user: UserEvent, badge: HTMLElement) => Promise<void>]>([
      [
        'the keyboard',
        async (user, badge) => {
          badge.focus();
          await user.keyboard('{Enter}');
        },
      ],
      [
        'a touch tap',
        (user, badge) => user.pointer({ keys: '[TouchA]', target: badge }),
      ],
    ])('opens the manage controls from %s', async (_, open) => {
      const user = userEvent.setup();
      renderComponent([JournalType.NOTE]);

      await open(user, screen.getByTestId(`manage-type-${JournalType.NOTE}`));

      expect(
        await screen.findByTestId(`remove-type-${JournalType.NOTE}`)
      ).toBeInTheDocument();
    });

    it('does not remove type if confirm is cancelled', async () => {
      const user = userEvent.setup();
      (globalThis as unknown as { confirm: jest.Mock }).confirm = jest.fn(
        () => false
      );
      renderComponent([JournalType.NOTE]);

      await user.click(screen.getByTestId(`manage-type-${JournalType.NOTE}`));
      const removeBtn = await screen.findByTestId(
        `remove-type-${JournalType.NOTE}`
      );

      await user.click(removeBtn);

      expect(globalThis.confirm).toHaveBeenCalled();
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

      consoleSpy.mockRestore();
    });

    it('handles onTypeRemove errors gracefully', async () => {
      const user = userEvent.setup();
      const consoleSpy = jest
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      mockOnTypeRemove.mockRejectedValueOnce(new Error('API Error'));

      renderComponent([JournalType.NOTE]);

      await user.click(screen.getByTestId(`manage-type-${JournalType.NOTE}`));
      const removeBtn = await screen.findByTestId(
        `remove-type-${JournalType.NOTE}`
      );

      await user.click(removeBtn);

      expect(globalThis.confirm).toHaveBeenCalled();

      await waitFor(() => {
        expect(
          screen.getByTestId(`manage-type-${JournalType.NOTE}`)
        ).not.toBeDisabled();
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        'Failed to remove type:',
        expect.any(Error)
      );

      consoleSpy.mockRestore();
    });
  });
});
