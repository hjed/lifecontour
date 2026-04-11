import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Journal Contact Status & Role API', () => {
  test('should persist and return status and role fields in journal API', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // 1. Create a Contact and a Journal
    const journal = await dataManager.createJournal({
      title: 'Status & Role Test',
      content: 'Verifying end-to-end API persistence of status and role.',
      event_date_range: {
        start: '2026-03-20T10:00:00Z',
        end: '2026-03-20T11:00:00Z',
      },
      types: ['note'],
    });

    const contact = await dataManager.createContact({
      firstName: 'Status',
      lastName: 'Tester',
    });

    // Register cleanup
    testCleanup(async () => await dataManager.cleanup());

    // 2. Add contact to journal via direct API call with status and role
    const relationshipData = {
      data: {
        type: 'journal-contact-relationships',
        attributes: {
          contact_id: String(contact.id),
          relationship_type: 'PARTICIPANT',
          status: 'ATTENDING',
          role: 'ORGANISER',
        },
      },
    };

    const addResponse = await page.request.post(
      `/api/journals/${journal.id}/relationships/contacts`,
      { data: relationshipData }
    );
    expect(addResponse.ok()).toBe(true);

    // 3. GET journal detail and verify the contact relationship includes status and role
    const getResponse = await page.request.get(`/api/journals/${journal.id}`);
    expect(getResponse.ok()).toBe(true);
    const journalData = await getResponse.json();

    const contacts = journalData.data.attributes.contacts;
    expect(contacts).toBeDefined();
    expect(contacts.length).toBe(1);

    const linkedContact = contacts[0];
    expect(linkedContact.id).toBe(String(contact.id));
    expect(linkedContact.relationship_type).toBe('PARTICIPANT');
    expect(linkedContact.status).toBe('ATTENDING');
    expect(linkedContact.role).toBe('ORGANISER');
  });
});
