/**
 * Deprecated Snipe-IT OAuth callback page.
 *
 * OAuth is no longer used for Snipe-IT authentication.
 * API key authentication is now configured via the integration settings panel.
 * This page redirects users to the integrations page.
 */

import { redirect } from 'next/navigation';

export default function SnipeItCallbackPage() {
  redirect('/integrations');
}
