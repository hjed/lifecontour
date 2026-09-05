/**
 * DashboardSectionCard — the shared card shell behind the three evidence
 * sections.
 *
 * One place for the chrome all three share (**W11**, **W21**, **W30** describe
 * the same header in three colours): an icon in a filled chip, a title, a
 * description, and a labelled list container for the entries. The list is
 * rendered whether or not it has any, because **W4** asks for a labelled list
 * per section and the sections' own phases should fill a container that is
 * already there rather than introduce one.
 *
 * The empty line follows **W29** — a centred icon over one muted sentence,
 * reading as a good outcome rather than an error — reusing `WidgetEmptyState`,
 * which is already exactly that shape.
 */

import { Children } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { WidgetEmptyState } from '@/components/journals/WidgetEmptyState';
import { cn } from '@/lib/utils';

/** A lucide icon, rendered decoratively. */
type DecorativeIcon = React.ComponentType<{
  className?: string;
  'aria-hidden'?: boolean | 'true' | 'false';
}>;

interface DashboardSectionCardProps {
  readonly icon: DecorativeIcon;
  /** Chip background, keyed to the section's chart colour. */
  readonly iconChipClassName: string;
  readonly title: string;
  readonly description: string;
  /** Accessible name for the entries list. */
  readonly listLabel: string;
  /** Rendered in place of the entries while the section holds none. */
  readonly emptyIcon: DecorativeIcon;
  readonly emptyMessage: string;
  /**
   * Rendered instead of the empty line while the section holds no entries
   * for a reason *other* than there being none — the query is still in
   * flight, or the section came back unavailable. "Nothing scheduled" would
   * be a false claim about either, so a card passes what is true instead.
   * Ignored once there are entries.
   */
  readonly placeholder?: React.ReactNode;
  /**
   * Hung beneath the entries — under the empty line or the placeholder too,
   * because neither of those says anything about what a footer is for. The
   * agenda's tomorrow disclosure (**W19**) is the first: a real button, so it
   * sits outside the list rather than pretending to be one of its items.
   */
  readonly footer?: React.ReactNode;
  readonly children?: React.ReactNode;
  readonly testId?: string;
}

export function DashboardSectionCard({
  icon: Icon,
  iconChipClassName,
  title,
  description,
  listLabel,
  emptyIcon,
  emptyMessage,
  placeholder,
  footer,
  children,
  testId,
}: DashboardSectionCardProps) {
  // Counted rather than tested for truthiness: a section renders its rows as
  // `entries.map(...)`, and an empty list is `[]` — which is truthy. `!children`
  // would therefore read a *ready but empty* section as populated and suppress
  // the one line W29 asks for, leaving a blank card.
  const isEmpty = Children.count(children) === 0;

  return (
    <Card className='flex flex-col' data-testid={testId}>
      <CardHeader>
        <div className='flex items-center gap-2'>
          <span
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-md',
              iconChipClassName
            )}
          >
            <Icon className='h-4 w-4' aria-hidden='true' />
          </span>
          <CardTitle className='text-lg'>{title}</CardTitle>
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-1 flex-col'>
        {/* `min-w-0` so a long title or tag set inside an entry wraps rather
            than widening the column and pushing the grid off screen (W3).
            Deliberately not `empty:hidden`: a display:none list is out of the
            accessibility tree, and W4 asks for a labelled list per section
            whether or not it has entries yet. Empty, it draws nothing. */}
        <ul aria-label={listLabel} className='min-w-0 space-y-3'>
          {children}
        </ul>
        {isEmpty &&
          (placeholder ?? (
            <WidgetEmptyState icon={emptyIcon} message={emptyMessage} />
          ))}
        {footer}
      </CardContent>
    </Card>
  );
}
