/**
 * Read-only markdown renderer for journal content.
 *
 * Renders a markdown string as GitHub-flavored markdown (headings, emphasis,
 * lists, links, strikethrough, tables, task lists) inside Tailwind `prose`
 * styling. Raw HTML is intentionally NOT parsed (no `rehype-raw`), so embedded
 * markup such as `<script>` or `<img onerror>` can never become live DOM —
 * react-markdown builds a React element tree and never uses
 * `dangerouslySetInnerHTML`.
 */

'use client';

import type { ComponentPropsWithoutRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { cn } from '@/lib/utils';

export interface MarkdownRendererProps {
  /** Markdown source to render. */
  readonly content: string;
  /** Additional CSS classes for the wrapper. */
  readonly className?: string;
  /** Test ID for testing. */
  readonly 'data-testid'?: string;
}

/** Render anchors so external links open safely in a new tab. */
function MarkdownLink({
  href,
  children,
  ...props
}: ComponentPropsWithoutRef<'a'>) {
  return (
    <a href={href} target='_blank' rel='noopener noreferrer' {...props}>
      {children}
    </a>
  );
}

/**
 * Renders a markdown string as styled, sanitized HTML.
 */
export function MarkdownRenderer({
  content,
  className,
  'data-testid': testId,
}: MarkdownRendererProps) {
  return (
    <div
      className={cn('prose prose-sm dark:prose-invert max-w-none', className)}
      data-testid={testId}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ a: MarkdownLink }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
