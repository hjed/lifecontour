# Domain Architecture Patterns

This document provides detailed examples of domain-driven design patterns for the Personal CRM & Journal System.

## Domain Entity Pattern

```typescript
// contacts/domain/entities/Contact.ts
export class Contact {
  constructor(
    private readonly id: ContactId,
    private name: string,
    private email?: Email,
    private phone?: PhoneNumber
  ) {}

  public updateEmail(email: Email): void {
    if (!this.canUpdateEmail(email)) {
      throw new Error('Cannot update email: validation failed');
    }
    this.email = email;
  }

  private canUpdateEmail(email: Email): boolean {
    return email.isValid() && !this.isEmailTaken(email);
  }

  public toSnapshot(): ContactSnapshot {
    return {
      id: this.id.value,
      name: this.name,
      email: this.email?.value,
      phone: this.phone?.value
    };
  }

  public static fromSnapshot(snapshot: ContactSnapshot): Contact {
    return new Contact(
      ContactId.create(snapshot.id),
      snapshot.name,
      snapshot.email ? Email.create(snapshot.email) : undefined,
      snapshot.phone ? PhoneNumber.create(snapshot.phone) : undefined
    );
  }
}
```

## Value Object Pattern

```typescript
// contacts/domain/value-objects/Email.ts
export class Email {
  private constructor(private readonly value: string) {}

  public static create(value: string): Email {
    if (!this.isValidEmail(value)) {
      throw new Error(`Invalid email: ${value}`);
    }
    return new Email(value);
  }

  private static isValidEmail(value: string): boolean {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(value);
  }

  public getValue(): string {
    return this.value;
  }

  public equals(other: Email): boolean {
    return this.value === other.value;
  }
}
```

## Repository Interface (Port)

```typescript
// contacts/domain/ports/ContactRepository.ts
export interface ContactRepository {
  save(contact: Contact): Promise<void>;
  findById(id: ContactId): Promise<Contact | null>;
  findByEmail(email: Email): Promise<Contact | null>;
  findAll(criteria?: ContactSearchCriteria): Promise<Contact[]>;
  delete(id: ContactId): Promise<void>;
}
```

## SQL Repository Adapter

```typescript
// contacts/adapters/sql/SqlContactRepository.ts
import { drizzle } from 'drizzle-orm/better-sqlite3';
import { eq, and } from 'drizzle-orm';
import { trace } from '@opentelemetry/api';

@injectable()
export class SqlContactRepository implements ContactRepository {
  private tracer = trace.getTracer('contacts-repository');

  constructor(
    @inject('Database') private db: ReturnType<typeof drizzle>,
    @inject('Logger') private logger: Logger
  ) {}

  async save(contact: Contact): Promise<void> {
    return this.tracer.startActiveSpan('contact.save', async (span) => {
      const snapshot = contact.toSnapshot();
      
      try {
        await this.db.insert(contactsTable)
          .values({
            id: snapshot.id,
            name: snapshot.name,
            email: snapshot.email,
            phone: snapshot.phone,
            updatedAt: new Date()
          })
          .onConflictDoUpdate({
            target: contactsTable.id,
            set: {
              name: snapshot.name,
              email: snapshot.email,
              phone: snapshot.phone,
              updatedAt: new Date()
            }
          });

        this.logger.info('Contact saved', { contactId: snapshot.id });
      } catch (error) {
        span.recordException(error as Error);
        throw new ContactRepositoryError('Failed to save contact', error);
      } finally {
        span.end();
      }
    });
  }

  async findById(id: ContactId): Promise<Contact | null> {
    const rows = await this.db.select()
      .from(contactsTable)
      .where(and(
        eq(contactsTable.id, id.value),
        eq(contactsTable.isDeleted, false)
      ));

    const row = rows[0];
    return row ? this.mapRowToContact(row) : null;
  }

  private mapRowToContact(row: ContactRow): Contact {
    return Contact.fromSnapshot({
      id: row.id,
      name: row.name,
      email: row.email,
      phone: row.phone
    });
  }
}
```

## Application Component Pattern

```typescript
// contacts/application/ContactApplicationService.ts
@injectable()
export class CreateContact {
  constructor(
    @inject('ContactRepository') private contactRepo: ContactRepository,
    @inject('EventBus') private eventBus: EventBus,
    @inject('Logger') private logger: Logger
  ) {}

  async createContact(command: CreateContactCommand): Promise<ContactId> {
    // Input validation
    const validation = CreateContactSchema.safeParse(command);
    if (!validation.success) {
      throw new ValidationError('Invalid contact data', validation.error);
    }

    // Check for duplicates
    if (command.email) {
      const existing = await this.contactRepo.findByEmail(Email.create(command.email));
      if (existing) {
        throw new DuplicateContactError('Contact with this email already exists');
      }
    }

    // Create domain entity
    const contact = new Contact(
      ContactId.generate(),
      command.name,
      command.email ? Email.create(command.email) : undefined,
      command.phone ? PhoneNumber.create(command.phone) : undefined
    );

    // Save to repository
    await this.contactRepo.save(contact);

    // Publish domain event
    await this.eventBus.publish(new ContactCreated(contact.getId(), contact.getName()));

    this.logger.info('Contact created', { contactId: contact.getId().value });
    return contact.getId();
  }
}
```

## External API Adapter

```typescript
// google-integration/adapters/google-api/GoogleContactsAdapter.ts
import { google, people_v1 } from 'googleapis';
import { trace } from '@opentelemetry/api';

@injectable()
export class GoogleContactsAdapter implements GoogleContactsService {
  private tracer = trace.getTracer('google-contacts-adapter');
  private peopleApi: people_v1.People;

  constructor(
    @inject('GoogleAuth') private auth: GoogleAuth,
    @inject('Logger') private logger: Logger
  ) {
    this.peopleApi = google.people({ version: 'v1', auth: this.auth });
  }

  async syncContacts(): Promise<GoogleContact[]> {
    return this.tracer.startActiveSpan('google.contacts.sync', async (span) => {
      try {
        const response = await this.peopleApi.people.connections.list({
          resourceName: 'people/me',
          personFields: 'names,emailAddresses,phoneNumbers,metadata',
          pageSize: 1000,
          sortOrder: 'LAST_MODIFIED_DESCENDING'
        });

        const contacts = response.data.connections?.map(this.mapGoogleContact) || [];
        
        this.logger.info('Google contacts synced', { count: contacts.length });
        return contacts;
      } catch (error) {
        span.recordException(error as Error);
        throw new GoogleContactsError('Failed to sync contacts', error);
      } finally {
        span.end();
      }
    });
  }

  private mapGoogleContact(person: people_v1.Schema$Person): GoogleContact {
    return {
      id: person.resourceName!,
      name: person.names?.[0]?.displayName || '',
      email: person.emailAddresses?.[0]?.value,
      phone: person.phoneNumbers?.[0]?.value,
      etag: person.etag
    };
  }
}
```

## Domain Events

```typescript
// contacts/domain/events/ContactCreated.ts
export class ContactCreated implements DomainEvent {
  public readonly type = 'ContactCreated';
  public readonly occurredAt = new Date();

  constructor(
    public readonly contactId: ContactId,
    public readonly contactName: string
  ) {}
}

// shared/events/EventBus.ts
export interface EventBus {
  publish(event: DomainEvent): Promise<void>;
  subscribe<T extends DomainEvent>(
    eventType: string,
    handler: (event: T) => Promise<void>
  ): void;
}
```

## Error Handling

```typescript
// contacts/domain/errors/ContactErrors.ts
export class ContactRepositoryError extends Error {
  constructor(
    message: string,
    public readonly cause?: Error
  ) {
    super(message);
    this.name = 'ContactRepositoryError';
  }
}

export class DuplicateContactError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DuplicateContactError';
  }
}
```