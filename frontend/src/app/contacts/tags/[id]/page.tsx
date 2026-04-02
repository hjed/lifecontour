/**
 * Legacy tag route — redirects to unified contacts page with tag filter.
 *
 * This route previously rendered a standalone tag-filtered contacts page.
 * It now redirects to `/contacts?tag=<id>` so that all contact list experiences
 * (search, favourites, infinite scroll) remain unified.
 */

import { redirect } from 'next/navigation';

interface TagPageProps {
  readonly params: Promise<{ id: string }>;
}

export default async function TagPageRedirect({ params }: TagPageProps) {
  const { id } = await params;
  redirect(`/contacts?tag=${encodeURIComponent(id)}`);
}
