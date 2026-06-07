/**
 * Jest mock for @tiptap/react.
 *
 * ProseMirror (which Tiptap wraps) relies on contenteditable + real browser
 * selection APIs that jsdom does not implement, so the real editor cannot be
 * exercised in unit tests. This mock provides just enough surface to test the
 * *wiring* of MarkdownEditor: it renders a textarea as the edit surface, fires
 * `onUpdate` (so `onChange` is exercised), forwards `onKeyDown` (so Escape
 * handling works), and exposes a chainable command stub for the toolbar. Live
 * formatting behaviour is covered by Playwright e2e.
 */

import * as React from 'react';

export interface MockEditorOptions {
  content?: string;
  contentType?: string;
  editable?: boolean;
  autofocus?: unknown;
  immediatelyRender?: boolean;
  extensions?: unknown[];
  editorProps?: { attributes?: Record<string, string | undefined> };
  onUpdate?: (props: { editor: { getMarkdown: () => string } }) => void;
}

/** Minimal chainable command stub: every method returns the chain; run() ends it. */
function createChain(): Record<string, () => unknown> {
  const chain: Record<string, () => unknown> = new Proxy(
    {},
    {
      get: (_target, prop) => {
        if (prop === 'run') {
          return () => true;
        }
        return () => chain;
      },
    }
  );
  return chain;
}

export class MockEditor {
  public readonly options: MockEditorOptions;
  public readonly isEmpty: boolean = false;
  public readonly commands = createChain();

  constructor(options: MockEditorOptions) {
    this.options = options;
  }

  getMarkdown(): string {
    return this.options.content ?? '';
  }

  isActive(): boolean {
    return false;
  }

  setEditable(): void {
    // no-op
  }

  chain(): Record<string, () => unknown> {
    return createChain();
  }

  can(): Record<string, () => unknown> {
    return createChain();
  }
}

export function useEditor(options: MockEditorOptions): MockEditor {
  return new MockEditor(options);
}

export interface EditorContentProps {
  editor: MockEditor | null;
  className?: string;
  onKeyDown?: React.KeyboardEventHandler<HTMLTextAreaElement>;
}

export function EditorContent({
  editor,
  className,
  onKeyDown,
}: EditorContentProps) {
  if (!editor) {
    return null;
  }
  const rawAttrs = editor.options.editorProps?.attributes ?? {};
  const attrs = Object.fromEntries(
    Object.entries(rawAttrs).filter(([key]) => key !== 'class')
  );
  return (
    <textarea
      {...attrs}
      className={className}
      defaultValue={editor.options.content}
      disabled={editor.options.editable === false}
      onKeyDown={onKeyDown}
      onChange={e => {
        const value = e.target.value;
        editor.options.onUpdate?.({ editor: { getMarkdown: () => value } });
      }}
    />
  );
}
