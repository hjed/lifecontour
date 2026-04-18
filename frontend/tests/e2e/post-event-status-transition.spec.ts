import { test, expect } from './fixtures';
import { TestDataManager } from './data-management';

test.describe('Post-Event Status Transition API', () => {
  test('should allow manual override of contact status via PUT', async ({
    authenticatedPage,
    testCleanup,
  }) => {
    const page = authenticatedPage;
    const dataManager = new TestDataManager(page);

    // 1. Create a Contact and a Journal with a past event date
    const pastDate = new Date();
    pastDate.setDate(pastDate.getDate() - 2);

    const journal = await dataManager.createJournal({
      title: 'Status Override Test',
      content: 'Verifying end-to-end API override of status.',
      event_date_range: {
        start: pastDate.toISOString(),
        end: pastDate.toISOString(),
      },
      types: ['event'],
    });

    const contact = await dataManager.createContact({
      firstName: 'Override',
      lastName: 'Tester',
    });

    // Register cleanup
    testCleanup(async () => await dataManager.cleanup());

    // 2. Add contact to journal via POST with status ATTENDING
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

    // Verify initial POST is successful
    let getResponse = await page.request.get(`/api/journals/${journal.id}`);
    expect(getResponse.ok()).toBe(true);
    let journalData = await getResponse.json();
    let linkedContact = journalData.data.attributes.contacts[0];
    expect(linkedContact.status).toBe('ATTENDING');

    // 3. Update contact status to ATTENDED via PUT
    const updateData = {
      data: {
        type: 'journal-contact-relationships',
        attributes: {
          status: 'ATTENDED',
          role: 'ORGANISER',
        },
      },
    };

    const putResponse = await page.request.put(
      `/api/journals/${journal.id}/relationships/contacts/${contact.id}/PARTICIPANT`,
      { data: updateData }
    );
    expect(putResponse.ok()).toBe(true);

    // 4. GET journal detail and verify the contact relationship is updated
    getResponse = await page.request.get(`/api/journals/${journal.id}`);
    expect(getResponse.ok()).toBe(true);
    journalData = await getResponse.json();

    const contacts = journalData.data.attributes.contacts;
    expect(contacts).toBeDefined();
    expect(contacts.length).toBe(1);

    linkedContact = contacts[0];
    expect(linkedContact.id).toBe(String(contact.id));
    expect(linkedContact.relationship_type).toBe('PARTICIPANT');
    expect(linkedContact.status).toBe('ATTENDED');
    expect(linkedContact.role).toBe('ORGANISER'); // Ensure role wasn't overwritten
  });
});
