/** @jest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IntegrationActions } from '../IntegrationActions';
import {
  useOAuthAuthorize,
  useReregisterWebhooks,
  useRotateSnipeItWebhookUrl,
  useSnipeItWebhookUrl,
} from '@/lib/api/integrations';

jest.mock('@/lib/api/integrations', () => ({
  useOAuthAuthorize: jest.fn(),
  useReregisterWebhooks: jest.fn(),
  useRotateSnipeItWebhookUrl: jest.fn(),
  useSnipeItWebhookUrl: jest.fn(),
}));

const WEBHOOK_URL = 'https://pms.example/api/integrations/snipeit/webhook/abc';

const mutationResult = { mutate: jest.fn(), isPending: false };
const rotate = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  (useOAuthAuthorize as jest.Mock).mockReturnValue(mutationResult);
  (useReregisterWebhooks as jest.Mock).mockReturnValue(mutationResult);
  (useRotateSnipeItWebhookUrl as jest.Mock).mockReturnValue({
    mutate: rotate,
    isPending: false,
  });
  (useSnipeItWebhookUrl as jest.Mock).mockReturnValue({
    data: {
      data: {
        type: 'webhook-url',
        attributes: { webhook_url: WEBHOOK_URL, message: '' },
      },
    },
  });
});

async function openWebhookUrlDialog() {
  const user = userEvent.setup();
  render(<IntegrationActions integrationId='snipeit' connected />);
  await user.click(screen.getByTestId('get-webhook-url-snipeit'));
  expect(await screen.findByText(WEBHOOK_URL)).toBeInTheDocument();
  return user;
}

describe('IntegrationActions Snipe-IT webhook URL dialog', () => {
  it('asks for confirmation before regenerating the URL', async () => {
    const user = await openWebhookUrlDialog();

    await user.click(screen.getByTestId('regenerate-webhook-url'));

    expect(
      await screen.findByRole('alertdialog', {
        name: 'Regenerate the webhook URL?',
      })
    ).toBeInTheDocument();
    expect(rotate).not.toHaveBeenCalled();
  });

  it('regenerates the URL once confirmed', async () => {
    const user = await openWebhookUrlDialog();

    await user.click(screen.getByTestId('regenerate-webhook-url'));
    await user.click(
      await screen.findByRole('button', { name: 'Regenerate URL' })
    );

    expect(rotate).toHaveBeenCalledTimes(1);
  });

  it('keeps the current URL when cancelled', async () => {
    const user = await openWebhookUrlDialog();

    await user.click(screen.getByTestId('regenerate-webhook-url'));
    await user.click(await screen.findByRole('button', { name: 'Keep URL' }));

    expect(rotate).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByText(WEBHOOK_URL)).toBeInTheDocument();
  });

  it('disables regeneration while a request is in flight', async () => {
    (useRotateSnipeItWebhookUrl as jest.Mock).mockReturnValue({
      mutate: rotate,
      isPending: true,
    });

    await openWebhookUrlDialog();

    expect(screen.getByTestId('regenerate-webhook-url')).toBeDisabled();
  });
});
