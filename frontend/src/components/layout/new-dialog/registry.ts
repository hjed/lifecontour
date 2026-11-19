/**
 * The entity types the New dialog offers, in switch order.
 *
 * The order is the specification's (Task, Journal, Contact), and the dialog
 * opens on the first entry.
 */

import { BookOpen, ListTodo, User } from 'lucide-react';

import { CreateContactForm } from '@/components/contacts/CreateContactForm';
import { NewJournalPanel } from '@/components/journals/NewJournalPanel';
import { NewTaskPanel } from '@/components/tasks/NewTaskPanel';

import type { NewEntityType } from './types';

export const NEW_ENTITY_TYPES: readonly NewEntityType[] = [
  {
    id: 'task',
    label: 'Task',
    icon: ListTodo,
    Panel: NewTaskPanel,
    // A task is a line of text first, so the dialog opens ready to type it.
    focusesOnOpen: true,
  },
  {
    id: 'journal',
    label: 'Journal',
    icon: BookOpen,
    Panel: NewJournalPanel,
  },
  {
    id: 'contact',
    label: 'Contact',
    icon: User,
    Panel: CreateContactForm,
  },
];
