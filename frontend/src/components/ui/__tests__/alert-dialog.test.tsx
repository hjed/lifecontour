import { render, screen } from '@testing-library/react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

function renderDialog() {
  render(
    <AlertDialog open>
      <AlertDialogContent>
        <AlertDialogTitle>Delete tag</AlertDialogTitle>
        <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
        <AlertDialogFooter>
          <AlertDialogCancel className='bg-muted'>Keep</AlertDialogCancel>
          <AlertDialogAction className='bg-destructive hover:bg-destructive/90'>
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

describe('AlertDialog buttons', () => {
  // Caller classes must go through Button's cn() so they replace the
  // variant's defaults instead of racing them in the stylesheet.
  it('lets a caller colour replace the Action default', () => {
    renderDialog();
    const action = screen.getByRole('button', { name: 'Delete' });
    expect(action).toHaveClass('bg-destructive', 'hover:bg-destructive/90');
    expect(action).not.toHaveClass('bg-primary');
    expect(action.className).not.toContain('hover:bg-primary');
  });

  it('lets a caller colour replace the Cancel default', () => {
    renderDialog();
    const cancel = screen.getByRole('button', { name: 'Keep' });
    expect(cancel).toHaveClass('bg-muted');
    expect(cancel).not.toHaveClass('bg-background');
  });
});
