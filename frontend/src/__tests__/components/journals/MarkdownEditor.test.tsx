/**
 * Jest unit tests for MarkdownEditor (wiring only).
 *
 * Tiptap/ProseMirror cannot run in jsdom, so @tiptap/react is mocked (see
 * src/__mocks__/@tiptap/react.tsx). These tests verify the React wiring:
 * initial value, onChange propagation, an accessible formatting toolbar, and
 * Escape handling. Live WYSIWYG behaviour is covered by Playwright e2e.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MarkdownEditor } from '@/components/journals/MarkdownEditor';

const TOOLBAR_BUTTONS = [
  'Bold',
  'Italic',
  'Heading',
  'Bullet list',
  'Numbered list',
  'Link',
];

describe('MarkdownEditor', () => {
  it('renders the initial markdown value in the edit surface', () => {
    render(
      <MarkdownEditor
        value='# Hi'
        onChange={jest.fn()}
        aria-label='Edit content'
      />
    );

    expect(screen.getByLabelText('Edit content')).toHaveValue('# Hi');
  });

  it('calls onChange with the markdown string when content changes', async () => {
    const user = userEvent.setup();
    const onChange = jest.fn();
    render(
      <MarkdownEditor value='' onChange={onChange} aria-label='Edit content' />
    );

    await user.type(screen.getByLabelText('Edit content'), 'hello');

    expect(onChange).toHaveBeenCalled();
    expect(onChange).toHaveBeenLastCalledWith('hello');
  });

  it('renders an accessible formatting toolbar', () => {
    render(<MarkdownEditor value='' onChange={jest.fn()} />);

    expect(screen.getByRole('toolbar')).toBeInTheDocument();
    for (const label of TOOLBAR_BUTTONS) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('runs a formatting command when a toolbar button is clicked', async () => {
    const user = userEvent.setup();
    render(<MarkdownEditor value='' onChange={jest.fn()} />);

    // The mocked editor command chain is a no-op; this asserts the button is
    // wired and operable without throwing.
    await expect(
      user.click(screen.getByRole('button', { name: 'Bold' }))
    ).resolves.not.toThrow();
  });

  it('calls onEscape when Escape is pressed inside the editor', async () => {
    const user = userEvent.setup();
    const onEscape = jest.fn();
    render(
      <MarkdownEditor
        value=''
        onChange={jest.fn()}
        onEscape={onEscape}
        aria-label='Edit content'
      />
    );

    screen.getByLabelText('Edit content').focus();
    await user.keyboard('{Escape}');

    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it('disables the edit surface when disabled', () => {
    render(
      <MarkdownEditor
        value='x'
        onChange={jest.fn()}
        disabled
        aria-label='Edit content'
      />
    );

    expect(screen.getByLabelText('Edit content')).toBeDisabled();
  });
});
