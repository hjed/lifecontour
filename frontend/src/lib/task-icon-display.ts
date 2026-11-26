/**
 * How the web app shows the fixed task icon set, and how a person searches it.
 *
 * `TASK_ICONS` holds our stored keys; this record maps each to the
 * `lucide-react` component that draws it and the name the picker shows and
 * searches. It is keyed by `TaskIcon`, so a key added to the set does not
 * compile until it has both. The stored key never changes if lucide renames an
 * icon: only the component on the right does.
 */

import {
  Baby,
  Bike,
  BookOpen,
  Bookmark,
  Briefcase,
  Calendar,
  Camera,
  Car,
  ClipboardList,
  Coffee,
  Dumbbell,
  Gift,
  GraduationCap,
  Hammer,
  Heart,
  House,
  Leaf,
  Lightbulb,
  List,
  Luggage,
  Mail,
  Map as MapIcon,
  Mountain,
  Music,
  Package,
  PartyPopper,
  PawPrint,
  Phone,
  Pill,
  Plane,
  Shirt,
  ShoppingCart,
  Star,
  Sun,
  Tent,
  Trophy,
  Users,
  Utensils,
  Wallet,
  Wrench,
  type LucideIcon,
} from 'lucide-react';

import { TASK_ICONS, type TaskIcon } from '@/types/task-icons';

/** The component that draws an icon, and the name a person knows it by. */
export interface TaskIconDisplay {
  readonly Icon: LucideIcon;
  readonly label: string;
}

export const TASK_ICON_DISPLAY: Readonly<Record<TaskIcon, TaskIconDisplay>> = {
  list: { Icon: List, label: 'List' },
  'clipboard-list': { Icon: ClipboardList, label: 'Clipboard list' },
  bookmark: { Icon: Bookmark, label: 'Bookmark' },
  star: { Icon: Star, label: 'Star' },
  heart: { Icon: Heart, label: 'Heart' },
  lightbulb: { Icon: Lightbulb, label: 'Lightbulb' },
  calendar: { Icon: Calendar, label: 'Calendar' },
  house: { Icon: House, label: 'House' },
  briefcase: { Icon: Briefcase, label: 'Briefcase' },
  'shopping-cart': { Icon: ShoppingCart, label: 'Shopping cart' },
  gift: { Icon: Gift, label: 'Gift' },
  package: { Icon: Package, label: 'Package' },
  wallet: { Icon: Wallet, label: 'Wallet' },
  phone: { Icon: Phone, label: 'Phone' },
  mail: { Icon: Mail, label: 'Mail' },
  users: { Icon: Users, label: 'People' },
  baby: { Icon: Baby, label: 'Baby' },
  'paw-print': { Icon: PawPrint, label: 'Paw print' },
  'party-popper': { Icon: PartyPopper, label: 'Party popper' },
  trophy: { Icon: Trophy, label: 'Trophy' },
  plane: { Icon: Plane, label: 'Plane' },
  luggage: { Icon: Luggage, label: 'Luggage' },
  car: { Icon: Car, label: 'Car' },
  bike: { Icon: Bike, label: 'Bike' },
  map: { Icon: MapIcon, label: 'Map' },
  tent: { Icon: Tent, label: 'Tent' },
  mountain: { Icon: Mountain, label: 'Mountain' },
  leaf: { Icon: Leaf, label: 'Leaf' },
  sun: { Icon: Sun, label: 'Sun' },
  dumbbell: { Icon: Dumbbell, label: 'Dumbbell' },
  pill: { Icon: Pill, label: 'Pill' },
  utensils: { Icon: Utensils, label: 'Utensils' },
  coffee: { Icon: Coffee, label: 'Coffee' },
  shirt: { Icon: Shirt, label: 'Shirt' },
  wrench: { Icon: Wrench, label: 'Wrench' },
  hammer: { Icon: Hammer, label: 'Hammer' },
  'book-open': { Icon: BookOpen, label: 'Open book' },
  'graduation-cap': { Icon: GraduationCap, label: 'Graduation cap' },
  music: { Icon: Music, label: 'Music' },
  camera: { Icon: Camera, label: 'Camera' },
};

/**
 * The icons whose name contains `query`, ignoring case and surrounding
 * whitespace, in published order. A blank query offers the whole set.
 */
export function filterTaskIcons(query: string): readonly TaskIcon[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return TASK_ICONS;
  return TASK_ICONS.filter(key =>
    TASK_ICON_DISPLAY[key].label.toLowerCase().includes(needle)
  );
}
