/**
 * The entity types the New dialog offers, in switch order.
 */

import { User } from 'lucide-react';

import { CreateContactForm } from '@/components/contacts/CreateContactForm';

import type { NewEntityType } from './types';

export const NEW_ENTITY_TYPES: readonly NewEntityType[] = [
  {
    id: 'contact',
    label: 'Contact',
    icon: User,
    Panel: CreateContactForm,
  },
];
