import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Integrations | Personal Management System',
  description: 'Manage your external integrations and sync settings',
};

export default function IntegrationsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
