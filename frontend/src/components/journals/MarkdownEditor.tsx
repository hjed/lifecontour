/**
 * WYSIWYG markdown editor for journal content.
 *
 * Built on Tiptap 3 (ProseMirror). Formatting renders live as you type —
 * StarterKit's input rules turn `**bold**`, `# `, `- ` etc. into formatted
 * content — while the official @tiptap/markdown extension keeps the stored
 * value as a markdown string (loaded via `contentType: 'markdown'`, read back
 * via `editor.getMarkdown()`). This is a controlled input: `value` is markdown
 * in, `onChange` emits markdown out, so it drops into both react-hook-form and
 * the inline `useInlineEdit` flow without changing the save path.
 *
 * Note: Tiptap/ProseMirror rely on contenteditable + real selection APIs that
 * jsdom lacks, so unit tests mock @tiptap/react. Behaviour is covered by e2e.
 */

'use client';

import { useEffect } from 'react';
import {
  Bold,
  Heading2,
  Italic,
  Link as LinkIcon,
  List,
  ListOrdered,
} from 'lucide-react';
import { EditorContent, useEditor, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Markdown } from '@tiptap/markdown';

import { cn } from '@/lib/utils';
import { Toggle } from '@/components/ui/toggle';

export interface MarkdownEditorProps {
  /** Current markdown value. */
  readonly value: string;
  /** Called with the new markdown string on every edit. */
  readonly onChange: (value: string) => void;
  /** Placeholder shown when empty. */
  readonly placeholder?: string;
  /** Whether editing is disabled. */
  readonly disabled?: boolean;
  /** Focus the editor on mount. */
  readonly focusOnMount?: boolean;
  /** Called when Escape is pressed inside the editor (e.g. to cancel). */
  readonly onEscape?: () => void;
  /** Additional CSS classes for the outer container. */
  readonly className?: string;
  /** DOM id for the editing surface (e.g. injected by shadcn FormControl). */
  readonly id?: string;
  /** ARIA label for the editing surface. */
  readonly 'aria-label'?: string;
  /** Marks the editing surface invalid for assistive tech. */
  readonly 'aria-invalid'?: boolean;
  /** Associates the editing surface with a description (e.g. an error message). */
  readonly 'aria-describedby'?: string;
  /** Test ID for testing. */
  readonly 'data-testid'?: string;
}

interface ToolbarAction {
  readonly label: string;
  readonly icon: typeof Bold;
  readonly isActive: (editor: Editor) => boolean;
  readonly run: (editor: Editor) => void;
}

const TOOLBAR_ACTIONS: readonly ToolbarAction[] = [
  {
    label: 'Bold',
    icon: Bold,
    isActive: editor => editor.isActive('bold'),
    run: editor => editor.chain().focus().toggleBold().run(),
  },
  {
    label: 'Italic',
    icon: Italic,
    isActive: editor => editor.isActive('italic'),
    run: editor => editor.chain().focus().toggleItalic().run(),
  },
  {
    label: 'Heading',
    icon: Heading2,
    isActive: editor => editor.isActive('heading', { level: 2 }),
    run: editor => editor.chain().focus().toggleHeading({ level: 2 }).run(),
  },
  {
    label: 'Bullet list',
    icon: List,
    isActive: editor => editor.isActive('bulletList'),
    run: editor => editor.chain().focus().toggleBulletList().run(),
  },
  {
    label: 'Numbered list',
    icon: ListOrdered,
    isActive: editor => editor.isActive('orderedList'),
    run: editor => editor.chain().focus().toggleOrderedList().run(),
  },
  {
    label: 'Link',
    icon: LinkIcon,
    isActive: editor => editor.isActive('link'),
    run: editor => {
      if (editor.isActive('link')) {
        editor.chain().focus().unsetLink().run();
        return;
      }
      const url = window.prompt('Enter URL');
      if (url) {
        editor.chain().focus().setLink({ href: url }).run();
      }
    },
  },
];

/**
 * Markdown WYSIWYG editor. Controlled via `value` / `onChange` (both markdown).
 */
export function MarkdownEditor({
  value,
  onChange,
  placeholder,
  disabled = false,
  focusOnMount = false,
  onEscape,
  className,
  id,
  'aria-label': ariaLabel,
  'aria-invalid': ariaInvalid,
  'aria-describedby': ariaDescribedBy,
  'data-testid': testId,
}: MarkdownEditorProps) {
  const editor = useEditor({
    extensions: [StarterKit, Markdown],
    content: value,
    contentType: 'markdown',
    editable: !disabled,
    autofocus: focusOnMount ? 'end' : false,
    // Avoid SSR hydration mismatches in Next.js (Tiptap renders client-side).
    immediatelyRender: false,
    editorProps: {
      attributes: {
        // contenteditable has no implicit ARIA role; declare textbox so the
        // editor is reachable via role+name for assistive tech and tests.
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-label': ariaLabel ?? 'Markdown editor',
        ...(id ? { id } : {}),
        ...(placeholder ? { 'aria-placeholder': placeholder } : {}),
        ...(ariaInvalid ? { 'aria-invalid': 'true' } : {}),
        ...(ariaDescribedBy ? { 'aria-describedby': ariaDescribedBy } : {}),
        ...(testId ? { 'data-testid': `${testId}-input` } : {}),
        class: 'prose prose-sm max-w-none min-h-[180px] focus:outline-none',
      },
    },
    onUpdate: ({ editor: instance }) => {
      onChange(instance.getMarkdown());
    },
  });

  // Push external value changes (e.g. programmatic reset) into the editor
  // without disturbing the cursor during normal typing — when the change came
  // from the editor itself, value already equals the serialized markdown.
  useEffect(() => {
    if (!editor) {
      return;
    }
    if (value !== editor.getMarkdown()) {
      editor.commands.setContent(value, {
        contentType: 'markdown',
        emitUpdate: false,
      });
    }
  }, [value, editor]);

  // Keep editable in sync if `disabled` toggles after mount.
  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [disabled, editor]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onEscape?.();
    }
  };

  return (
    <div
      className={cn(
        'border-input focus-within:ring-ring/50 rounded-md border focus-within:ring-1',
        disabled && 'opacity-50',
        className
      )}
      data-testid={testId}
    >
      <div
        role='toolbar'
        aria-label='Text formatting'
        className='border-border flex flex-wrap items-center gap-1 border-b p-1'
      >
        {TOOLBAR_ACTIONS.map(action => {
          const Icon = action.icon;
          return (
            <Toggle
              key={action.label}
              size='sm'
              aria-label={action.label}
              pressed={editor ? action.isActive(editor) : false}
              onPressedChange={() => editor && action.run(editor)}
              disabled={disabled || !editor}
            >
              <Icon className='h-4 w-4' />
            </Toggle>
          );
        })}
      </div>

      <EditorContent
        editor={editor}
        onKeyDown={handleKeyDown}
        className='px-3 py-2'
      />
    </div>
  );
}
