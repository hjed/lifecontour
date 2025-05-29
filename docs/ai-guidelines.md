# AI Development Guidelines - Personal CRM & Journal System

## Project Context

This document provides guidelines for AI assistants working on the Personal CRM & Journal System. The system is a TypeScript/Node.js application that integrates personal data from multiple sources and provides both MCP (Model Context Protocol) and web interfaces. It uses JSON API standard for REST endpoints, Jest for testing, includes contact tags with Google sync, album integration with journal entries and events, name-based person matching, and nginx proxy support.

### Key Principles
1. **Privacy First**: All personal data stays local unless explicitly synced
2. **Type Safety**: Leverage TypeScript's type system for reliability
3. **Domain-Driven Architecture**: Core domains with separate integration sub-domains
4. **Agile Development**: Feature-complete iterations delivering incremental value
5. **Integration Isolation**: External integrations in separate sub-domains
6. **Dependency Inversion**: Domains define interfaces, adapters implement them
7. **AI-Friendly**: Design APIs and data structures for easy AI consumption
8. **Proxy-Ready**: Support deployment behind nginx reverse proxy

## Agile Development Approach

### Feature-Complete Iterations
- Each iteration delivers working, testable functionality end-to-end
- Build domain logic → API endpoints → basic UI for each feature
- Deploy and test after each iteration
- Integration sub-domains are developed separately from core domains

### Iteration Guidelines
1. **Start with core domain logic** - entities, value objects, business rules
2. **Add adapters** - database repositories, external API clients
3. **Create application services** - use cases and orchestration
4. **Build API endpoints** - REST controllers with JSON API compliance
5. **Add basic UI** - functional interface for the feature
6. **Write tests** - unit, integration, and end-to-end tests
7. **Deploy and validate** - ensure feature works in real environment

### Integration Sub-Domain Pattern
```typescript
// google-integration/application/GoogleIntegrationService.ts
@injectable()
export class GoogleIntegrationService {
  constructor(
    // Can access multiple core domains via their application services
    @inject('ContactApplicationService') private contactService: ContactApplicationService,
    @inject('CalendarApplicationService') private calendarService: CalendarApplicationService,
    @inject('GoogleContactsClient') private googleContacts: GoogleContactsClient,
    @inject('GoogleSyncStateRepository') private syncState: GoogleSyncStateRepository
  ) {}

  async syncContactsAndTags(): Promise<void> {
    // Integration logic that coordinates between Google and core domains
    const googleContacts = await this.googleContacts.fetchContacts();
    const googleGroups = await this.googleContacts.fetchContactGroups();

    // Sync tags first
    for (const group of googleGroups) {
      await this.contactService.createOrUpdateTag({
        name: group.name,
        googleId: group.id
      });
    }

    // Then sync contacts
    for (const googleContact of googleContacts) {
      await this.contactService.createOrUpdateContact({
        name: googleContact.name,
        email: googleContact.email,
        googleId: googleContact.id,
        tags: googleContact.groupIds
      });
    }
  }
}
```

## Development Standards

### TypeScript Configuration

**Use strict TypeScript settings:**
```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "noImplicitReturns": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "exactOptionalPropertyTypes": true
  }
}
```

**Always define interfaces for:**
- API request/response objects
- Database entities
- Configuration objects
- External API responses
- MCP tool parameters and results

### Code Organization

**Folder Structure:**
```
src/
├── api/                          # API Adapters (Driving)
│   ├── rest/                     # REST API adapters (nginx proxy compatible)
│   │   ├── contacts/             # Contact REST endpoints
│   │   ├── calendar/             # Calendar REST endpoints
│   │   ├── journal/              # Journal REST endpoints
│   │   ├── photos/               # Photos REST endpoints
│   │   └── shared/               # Shared REST utilities, proxy config
│   └── mcp/                      # MCP adapters
│       ├── contacts/             # Contact MCP tools
│       ├── calendar/             # Calendar MCP tools
│       ├── journal/              # Journal MCP tools
│       ├── photos/               # Photos MCP tools
│       └── server.ts             # MCP server setup
├── contacts/                     # Contacts Core Domain
│   ├── domain/                   # Domain layer
│   │   ├── entities/             # Contact, ContactInteraction, Tag
│   │   ├── value-objects/        # Email, PhoneNumber, Address
│   │   ├── services/             # ContactDuplicationService, TagService
│   │   └── events/               # ContactCreated, TagAssigned, etc.
│   ├── adapters/                 # All external dependencies
│   │   ├── sql/                  # SqlContactRepository, SqlTagRepository
│   │   └── events/               # ContactEventPublisher
│   └── application/              # Use cases and application services
│       ├── use-cases/            # CreateContact, AssignTag, etc.
│       └── ContactApplicationService.ts
├── calendar/                     # Calendar Core Domain
├── journal/                      # Journal Core Domain
├── photos/                       # Photos Core Domain
├── google-integration/           # Google Integration Sub-Domain
│   ├── domain/
│   │   ├── entities/             # GoogleSyncState, GoogleContact, GoogleEvent
│   │   ├── services/             # GoogleSyncService, TagSyncService
│   │   └── events/               # GoogleSyncCompleted, TagSynced, etc.
│   ├── adapters/
│   │   ├── google-api/           # GoogleContactsClient, GoogleCalendarClient
│   │   ├── sql/                  # GoogleSyncStateRepository
│   │   └── events/               # GoogleEventPublisher
│   └── application/
│       ├── use-cases/            # SyncGoogleContacts, SyncTags, etc.
│       └── GoogleIntegrationService.ts
├── immich-integration/           # Immich Integration Sub-Domain
└── shared/                       # Shared Infrastructure
    ├── database/                 # Database connection, migrations
    ├── events/                   # Event infrastructure
    ├── types/                    # Shared types and interfaces
    ├── utils/                    # Utility functions
    ├── config/                   # Configuration management
    └── proxy/                    # Nginx proxy utilities and middleware
```

**File Naming Conventions:**
- Use kebab-case for files: `contact-service.ts`
- Use PascalCase for classes: `ContactService`
- Use camelCase for functions and variables: `getUserContacts`
- Use UPPER_SNAKE_CASE for constants: `MAX_RETRY_ATTEMPTS`

### Domain-Driven Architecture Patterns

**Key Architectural Rules:**
1. **Core domains** (contacts, calendar, journal, photos) contain only business logic
2. **Integration sub-domains** (google-integration, immich-integration) handle external systems
3. **Adapters** within domains can only access their own domain's business logic
4. **Cross-domain communication** happens through application services and events
5. **Integration sub-domains** can access multiple core domains via their application services

**Domain Entity Pattern:**
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
    // Business logic for email validation
    if (!this.canUpdateEmail(email)) {
      throw new Error('Cannot update email: validation failed');
    }
    this.email = email;
  }

  private canUpdateEmail(email: Email): boolean {
    // Domain business rules
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
}
```

**Value Object Pattern:**
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

**Port (Interface) Pattern:**
```typescript
// contacts/ports/ContactRepository.ts
export interface ContactRepository {
  save(contact: Contact): Promise<void>;
  findById(id: ContactId): Promise<Contact | null>;
  findByEmail(email: Email): Promise<Contact | null>;
  findAll(criteria?: ContactSearchCriteria): Promise<Contact[]>;
  delete(id: ContactId): Promise<void>;
}

// contacts/ports/GoogleContactsService.ts
export interface GoogleContactsService {
  syncContacts(): Promise<GoogleContact[]>;
  createContact(contact: Contact): Promise<GoogleContactId>;
  updateContact(id: GoogleContactId, contact: Contact): Promise<void>;
  deleteContact(id: GoogleContactId): Promise<void>;
}
```

**SQL Adapter with ORM Pattern:**
```typescript
// contacts/adapters/sql/SqlContactRepository.ts
import { drizzle } from 'drizzle-orm/better-sqlite3';
import { eq, and } from 'drizzle-orm';
import { trace, context } from '@opentelemetry/api';

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
      span.setAttributes({
        'contact.id': snapshot.id,
        'contact.operation': 'save'
      });

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

        this.logger.info('Contact saved', {
          contactId: snapshot.id,
          traceId: span.spanContext().traceId
        });
        span.setStatus({ code: SpanStatusCode.OK });
      } catch (error) {
        span.recordException(error as Error);
        span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
        this.logger.error('Failed to save contact', {
          error,
          contactId: snapshot.id,
          traceId: span.spanContext().traceId
        });
        throw new ContactRepositoryError('Failed to save contact', error);
      } finally {
        span.end();
      }
    });
  }

  async findById(id: ContactId): Promise<Contact | null> {
    return this.tracer.startActiveSpan('contact.findById', async (span) => {
      span.setAttributes({
        'contact.id': id.value,
        'contact.operation': 'findById'
      });

      try {
        const rows = await this.db.select()
          .from(contactsTable)
          .where(and(
            eq(contactsTable.id, id.value),
            eq(contactsTable.isDeleted, false)
          ));

        const row = rows[0];
        if (!row) {
          span.setStatus({ code: SpanStatusCode.OK });
          return null;
        }

        const contact = this.mapRowToContact(row);
        span.setStatus({ code: SpanStatusCode.OK });
        return contact;
      } catch (error) {
        span.recordException(error as Error);
        span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
        throw new ContactRepositoryError('Failed to find contact', error);
      } finally {
        span.end();
      }
    });
  }

  private mapRowToContact(row: ContactRow): Contact {
    return new Contact(
      ContactId.create(row.id),
      row.name,
      row.email ? Email.create(row.email) : undefined,
      row.phone ? PhoneNumber.create(row.phone) : undefined
    );
  }
}
```

**External API Adapter with Standard Library:**
```typescript
// contacts/adapters/google/GoogleContactsAdapter.ts
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
      span.setAttributes({
        'google.api': 'people',
        'google.operation': 'connections.list'
      });

      try {
        const response = await this.peopleApi.people.connections.list({
          resourceName: 'people/me',
          personFields: 'names,emailAddresses,phoneNumbers,metadata',
          pageSize: 1000,
          sortOrder: 'LAST_MODIFIED_DESCENDING'
        });

        const contacts = response.data.connections?.map(this.mapGoogleContact) || [];

        span.setAttributes({
          'google.contacts.count': contacts.length
        });
        span.setStatus({ code: SpanStatusCode.OK });

        this.logger.info('Google contacts synced', {
          count: contacts.length,
          traceId: span.spanContext().traceId
        });

        return contacts;
      } catch (error) {
        span.recordException(error as Error);
        span.setStatus({ code: SpanStatusCode.ERROR, message: error.message });
        this.logger.error('Failed to sync Google contacts', {
          error,
          traceId: span.spanContext().traceId
        });
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

**Application Service Pattern:**
```typescript
// contacts/application/ContactApplicationService.ts
@injectable()
export class ContactApplicationService {
  constructor(
    @inject('ContactRepository') private contactRepo: ContactRepository,
    @inject('GoogleContactsService') private googleService: GoogleContactsService,
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

  async syncWithGoogle(): Promise<void> {
    // Cross-domain operation - might belong in sync domain
    const googleContacts = await this.googleService.syncContacts();

    for (const googleContact of googleContacts) {
      const existingContact = await this.contactRepo.findByEmail(
        Email.create(googleContact.email)
      );

      if (existingContact) {
        // Update existing contact
        existingContact.updateFromGoogle(googleContact);
        await this.contactRepo.save(existingContact);
      } else {
        // Create new contact
        const newContact = Contact.fromGoogle(googleContact);
        await this.contactRepo.save(newContact);
      }
    }
  }
}
```

### Error Handling

**Create custom error classes:**
```typescript
export class SyncError extends Error {
  constructor(
    message: string,
    public readonly source: string,
    public readonly retryable: boolean = true
  ) {
    super(message);
    this.name = 'SyncError';
  }
}
```

**Always handle errors explicitly:**
```typescript
// Good
try {
  const result = await riskyOperation();
  return { success: true, data: result };
} catch (error) {
  logger.error('Operation failed', { error, context });
  return { success: false, error: error.message };
}

// Bad - letting errors bubble up unhandled
const result = await riskyOperation();
```

### Database Operations

**Use transactions for multi-table operations:**
```typescript
async function createContactWithInteraction(contact: Contact, interaction: Interaction) {
  return db.transaction(() => {
    const contactId = db.prepare('INSERT INTO contacts ...').run(contact).lastInsertRowid;
    db.prepare('INSERT INTO contact_interactions ...').run({
      ...interaction,
      contact_id: contactId
    });
    return contactId;
  });
}
```

**Always use prepared statements:**
```typescript
// Good
const stmt = db.prepare('SELECT * FROM contacts WHERE email = ?');
const contact = stmt.get(email);

// Bad - SQL injection risk
const contact = db.prepare(`SELECT * FROM contacts WHERE email = '${email}'`).get();
```

### API Design

**Nginx Proxy Compatibility:**
```typescript
// api/rest/shared/proxy-middleware.ts
import { Request, Response, NextFunction } from 'express';

export function trustProxyMiddleware(req: Request, res: Response, next: NextFunction) {
  // Trust X-Forwarded-* headers from nginx
  if (req.headers['x-forwarded-for']) {
    req.ip = (req.headers['x-forwarded-for'] as string).split(',')[0].trim();
  }

  if (req.headers['x-forwarded-proto']) {
    req.protocol = req.headers['x-forwarded-proto'] as string;
  }

  if (req.headers['x-forwarded-host']) {
    req.hostname = req.headers['x-forwarded-host'] as string;
  }

  next();
}

// CORS configuration for nginx proxy
export const corsOptions = {
  origin: (origin: string | undefined, callback: Function) => {
    // Allow requests from nginx proxy
    const allowedOrigins = [
      process.env.FRONTEND_URL,
      process.env.NGINX_PROXY_URL,
      'http://localhost:3000', // Development
    ].filter(Boolean);

    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  },
  credentials: true,
  optionsSuccessStatus: 200
};
```

**Follow JSON API specification:**
```typescript
// JSON API compliant response structure
interface JsonApiResponse<T> {
  data: T | T[];
  meta?: {
    total?: number;
    page?: number;
    limit?: number;
  };
  links?: {
    self?: string;
    first?: string;
    last?: string;
    prev?: string;
    next?: string;
  };
  included?: any[];
}

// JSON API error response
interface JsonApiError {
  errors: Array<{
    id?: string;
    status?: string;
    code?: string;
    title?: string;
    detail?: string;
    source?: {
      pointer?: string;
      parameter?: string;
    };
  }>;
}
```

**Validate all inputs:**
```typescript
import { z } from 'zod';

const CreateContactSchema = z.object({
  name: z.string().min(1).max(255),
  email: z.string().email().optional(),
  phone: z.string().optional(),
  tags: z.array(z.string()).default([])
});

export async function createContact(req: Request, res: Response) {
  const validation = CreateContactSchema.safeParse(req.body);
  if (!validation.success) {
    return res.status(400).json({
      errors: validation.error.errors.map(err => ({
        status: '400',
        title: 'Validation Error',
        detail: err.message,
        source: { pointer: `/data/attributes/${err.path.join('/')}` }
      }))
    });
  }
  // ... rest of implementation
}
```

### MCP Implementation

**Structure MCP tools consistently:**
```typescript
interface McpTool {
  name: string;
  description: string;
  inputSchema: object;
  handler: (params: any) => Promise<any>;
}

const searchContactsTool: McpTool = {
  name: 'search_contacts',
  description: 'Search contacts by name, email, or tags',
  inputSchema: {
    type: 'object',
    properties: {
      query: { type: 'string' },
      tags: { type: 'array', items: { type: 'string' } },
      limit: { type: 'number', default: 10 }
    },
    required: ['query']
  },
  handler: async (params) => {
    // Implementation
  }
};
```

**Make MCP responses AI-friendly:**
```typescript
// Good - structured, descriptive response
return {
  contacts: results.map(contact => ({
    id: contact.id,
    name: contact.name,
    email: contact.email,
    lastInteraction: contact.lastInteraction,
    relationshipStrength: calculateRelationshipStrength(contact),
    summary: generateContactSummary(contact)
  })),
  totalFound: results.length,
  searchContext: `Found ${results.length} contacts matching "${params.query}"`
};

// Bad - raw database response
return results;
```

### Testing Requirements (Jest)

**Configure Jest for TypeScript:**
```javascript
// jest.config.js
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src', '<rootDir>/tests'],
  testMatch: ['**/__tests__/**/*.ts', '**/?(*.)+(spec|test).ts'],
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/**/*.d.ts',
    '!src/types/**/*'
  ],
  coverageThreshold: {
    global: {
      branches: 80,
      functions: 80,
      lines: 80,
      statements: 80
    }
  }
};
```

**Write tests for all public functions:**
```typescript
describe('ContactService', () => {
  let contactService: ContactService;
  let mockDb: jest.Mocked<Database>;

  beforeEach(() => {
    mockDb = createMockDatabase();
    contactService = new ContactService(mockDb, mockLogger, mockGoogleApi);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('should create contact with valid data', async () => {
    const contactData = { name: 'John Doe', email: 'john@example.com' };
    mockDb.contacts.create.mockResolvedValue({ id: 1, ...contactData });

    const result = await contactService.create(contactData);

    expect(result.success).toBe(true);
    expect(result.data.name).toBe('John Doe');
    expect(mockDb.contacts.create).toHaveBeenCalledWith(contactData);
  });

  it('should handle duplicate email gracefully', async () => {
    const contactData = { name: 'John Doe', email: 'existing@example.com' };
    mockDb.contacts.create.mockRejectedValue(new Error('UNIQUE constraint failed'));

    const result = await contactService.create(contactData);

    expect(result.success).toBe(false);
    expect(result.error).toContain('already exists');
  });
});
```

**Test external integrations with mocks:**
```typescript
jest.mock('../integrations/google-calendar');

describe('Calendar sync', () => {
  it('should handle API rate limiting', async () => {
    const mockCalendarApi = jest.mocked(googleCalendarApi);
    mockCalendarApi.getEvents.mockRejectedValue(new Error('Rate limit exceeded'));

    const result = await calendarService.sync();
    expect(result.success).toBe(false);
    expect(result.retryAfter).toBeDefined();
  });
});
```

### Logging Standards

**Use structured logging:**
```typescript
import { logger } from '../utils/logger';

// Good
logger.info('Contact created', {
  contactId: contact.id,
  source: 'api',
  userId: req.user.id,
  duration: Date.now() - startTime
});

// Bad
console.log(`Contact ${contact.id} created by user ${req.user.id}`);
```

**Log levels:**
- `error`: System errors, failed operations
- `warn`: Recoverable errors, deprecation warnings
- `info`: Important business events, API calls
- `debug`: Detailed execution flow, variable values

### Security Guidelines

**Never log sensitive data:**
```typescript
// Good
logger.info('User authenticated', { userId: user.id, method: 'oauth' });

// Bad
logger.info('User authenticated', { user }); // May contain tokens/passwords
```

**Validate and sanitize all inputs:**
```typescript
function sanitizeSearchQuery(query: string): string {
  return query
    .trim()
    .replace(/[<>]/g, '') // Remove potential XSS
    .substring(0, 255); // Limit length
}
```

**Use environment variables for secrets:**
```typescript
const config = {
  googleClientId: process.env.GOOGLE_CLIENT_ID!,
  googleClientSecret: process.env.GOOGLE_CLIENT_SECRET!,
  jwtSecret: process.env.JWT_SECRET!
};

// Validate required environment variables at startup
Object.entries(config).forEach(([key, value]) => {
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
});
```

### Performance Guidelines

**Use database indexes:**
```sql
-- Always index foreign keys and frequently queried columns
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contact_interactions_contact_id ON contact_interactions(contact_id);
CREATE INDEX idx_events_start_time ON events(start_time);
```

**Implement pagination for large datasets:**
```typescript
interface PaginationParams {
  page: number;
  limit: number;
}

async function getContacts({ page = 1, limit = 50 }: PaginationParams) {
  const offset = (page - 1) * limit;
  const contacts = db.prepare(`
    SELECT * FROM contacts
    WHERE is_deleted = FALSE
    ORDER BY name
    LIMIT ? OFFSET ?
  `).all(limit, offset);

  const total = db.prepare('SELECT COUNT(*) as count FROM contacts WHERE is_deleted = FALSE').get().count;

  return {
    contacts,
    pagination: {
      page,
      limit,
      total,
      totalPages: Math.ceil(total / limit)
    }
  };
}
```

### Common Patterns

**Service Layer Pattern:**
```typescript
export class ContactService {
  constructor(
    private db: Database,
    private logger: Logger,
    private googleContactsApi: GoogleContactsApi
  ) {}

  async create(data: CreateContactData): Promise<ServiceResult<Contact>> {
    try {
      // Validation
      const validation = CreateContactSchema.safeParse(data);
      if (!validation.success) {
        return { success: false, error: 'Invalid data' };
      }

      // Business logic
      const contact = await this.db.contacts.create(validation.data);

      // Logging
      this.logger.info('Contact created', { contactId: contact.id });

      return { success: true, data: contact };
    } catch (error) {
      this.logger.error('Failed to create contact', { error, data });
      return { success: false, error: 'Failed to create contact' };
    }
  }
}
```

**Configuration Management:**
```typescript
import { z } from 'zod';

const ConfigSchema = z.object({
  port: z.number().default(3000),
  database: z.object({
    path: z.string().default('./data/app.db'),
    enableWAL: z.boolean().default(true)
  }),
  google: z.object({
    clientId: z.string(),
    clientSecret: z.string(),
    redirectUri: z.string()
  }),
  immich: z.object({
    baseUrl: z.string().url(),
    apiKey: z.string()
  })
});

export const config = ConfigSchema.parse({
  port: parseInt(process.env.PORT || '3000'),
  database: {
    path: process.env.DATABASE_PATH || '/app/data/app.db', // Docker-friendly path
    enableWAL: process.env.DATABASE_WAL === 'true'
  },
  google: {
    clientId: process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    redirectUri: process.env.GOOGLE_REDIRECT_URI
  },
  immich: {
    baseUrl: process.env.IMMICH_BASE_URL,
    apiKey: process.env.IMMICH_API_KEY
  }
});
```

### Docker Development Guidelines

**Dockerfile Best Practices:**
```dockerfile
# Use specific Node.js version for reproducibility
FROM node:18.17-alpine AS builder

# Create non-root user for security
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001

# Set working directory
WORKDIR /app

# Copy package files first for better layer caching
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# Copy source code
COPY --chown=nextjs:nodejs . .

# Build application
RUN npm run build

# Production stage
FROM node:18.17-alpine AS runner
WORKDIR /app

# Copy user from builder stage
COPY --from=builder /etc/passwd /etc/passwd
COPY --from=builder /etc/group /etc/group

# Copy built application
COPY --from=builder --chown=nextjs:nodejs /app .

# Create data directory for SQLite
RUN mkdir -p /app/data && chown nextjs:nodejs /app/data

# Switch to non-root user
USER nextjs

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD node healthcheck.js

EXPOSE 3000
CMD ["npm", "start"]
```

**Docker Compose Configuration:**
```yaml
# docker-compose.yml (development)
version: '3.8'
services:
  app:
    build: .
    ports:
      - "3000:3000"
    volumes:
      - ./src:/app/src:ro
      - ./data:/app/data
    environment:
      - NODE_ENV=development
      - DATABASE_PATH=/app/data/app.db
    env_file:
      - .env.local
    restart: unless-stopped

# docker-compose.prod.yml (production)
version: '3.8'
services:
  app:
    image: personal-crm:latest
    ports:
      - "3000:3000"
    volumes:
      - app_data:/app/data
      - app_logs:/app/logs
    environment:
      - NODE_ENV=production
    env_file:
      - .env.production
    restart: always
    healthcheck:
      test: ["CMD", "node", "healthcheck.js"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  app_data:
  app_logs:
```

**Container Health Checks:**
```typescript
// healthcheck.js
const http = require('http');

const options = {
  hostname: 'localhost',
  port: process.env.PORT || 3000,
  path: '/health',
  timeout: 2000
};

const request = http.request(options, (res) => {
  if (res.statusCode === 200) {
    process.exit(0);
  } else {
    process.exit(1);
  }
});

request.on('error', () => {
  process.exit(1);
});

request.end();
```

**Docker Environment Guidelines:**
- Use `.dockerignore` to exclude unnecessary files
- Implement proper health checks for container orchestration
- Use multi-stage builds to minimize image size
- Run containers as non-root users for security
- Use specific version tags, avoid `latest` in production
- Mount volumes for persistent data (SQLite database)
- Use environment variables for configuration
- Implement graceful shutdown handling

### Person Matching Patterns

**Implement confidence-based matching:**
```typescript
interface PersonMatch {
  immichPersonId: string;
  contactId: number;
  confidenceScore: number; // 0.0 to 1.0
  matchMethod: 'manual' | 'facial' | 'name' | 'metadata';
  verified: boolean;
}

class PersonMatchingService {
  async matchPersonToContact(
    immichPerson: ImmichPerson,
    contacts: Contact[]
  ): Promise<PersonMatch[]> {
    const matches: PersonMatch[] = [];

    for (const contact of contacts) {
      // Name-based matching
      const nameScore = this.calculateNameSimilarity(immichPerson.name, contact.name);
      if (nameScore > 0.8) {
        matches.push({
          immichPersonId: immichPerson.id,
          contactId: contact.id,
          confidenceScore: nameScore,
          matchMethod: 'name',
          verified: false
        });
      }

      // Facial recognition matching would go here
      // Metadata matching (dates, locations) would go here
    }

    return matches.sort((a, b) => b.confidenceScore - a.confidenceScore);
  }
}
```

### API Documentation with tsoa

**Controller with automatic OpenAPI generation:**
```typescript
// api/rest/contacts/ContactController.ts
import { Controller, Get, Post, Route, Tags, Body, Path, Query } from 'tsoa';
import { trace } from '@opentelemetry/api';

interface CreateContactRequest {
  /** Contact's full name */
  name: string;
  /** Contact's email address */
  email?: string;
  /** Contact's phone number */
  phone?: string;
  /** Contact tags for categorization */
  tags?: string[];
}

interface ContactResponse {
  type: 'contacts';
  id: string;
  attributes: {
    name: string;
    email?: string;
    phone?: string;
    tags: string[];
    createdAt: string;
    updatedAt: string;
  };
  relationships?: {
    interactions: {
      links: {
        related: string;
      };
    };
  };
}

@Route('api/contacts')
@Tags('Contacts')
export class ContactController extends Controller {
  private tracer = trace.getTracer('contact-controller');

  constructor(
    @inject('ContactApplicationService')
    private contactService: ContactApplicationService
  ) {
    super();
  }

  /**
   * Create a new contact
   * @param requestBody Contact data
   * @returns Created contact
   */
  @Post()
  public async createContact(
    @Body() requestBody: CreateContactRequest
  ): Promise<ContactResponse> {
    return this.tracer.startActiveSpan('api.contacts.create', async (span) => {
      span.setAttributes({
        'http.method': 'POST',
        'http.route': '/api/contacts'
      });

      try {
        const command = CreateContactCommand.from(requestBody);
        const contactId = await this.contactService.createContact(command);
        const contact = await this.contactService.getContact(contactId);

        this.setStatus(201);
        return this.serializeContact(contact);
      } catch (error) {
        span.recordException(error as Error);
        if (error instanceof ValidationError) {
          this.setStatus(400);
          throw error;
        }
        this.setStatus(500);
        throw new Error('Internal server error');
      } finally {
        span.end();
      }
    });
  }

  /**
   * Get contact by ID
   * @param contactId Contact identifier
   * @returns Contact details
   */
  @Get('{contactId}')
  public async getContact(
    @Path() contactId: string
  ): Promise<ContactResponse> {
    return this.tracer.startActiveSpan('api.contacts.get', async (span) => {
      span.setAttributes({
        'http.method': 'GET',
        'http.route': '/api/contacts/{contactId}',
        'contact.id': contactId
      });

      try {
        const contact = await this.contactService.getContact(
          ContactId.create(contactId)
        );

        if (!contact) {
          this.setStatus(404);
          throw new Error('Contact not found');
        }

        return this.serializeContact(contact);
      } catch (error) {
        span.recordException(error as Error);
        this.setStatus(404);
        throw error;
      } finally {
        span.end();
      }
    });
  }

  private serializeContact(contact: Contact): ContactResponse {
    const snapshot = contact.toSnapshot();
    return {
      type: 'contacts',
      id: snapshot.id,
      attributes: {
        name: snapshot.name,
        email: snapshot.email,
        phone: snapshot.phone,
        tags: snapshot.tags || [],
        createdAt: snapshot.createdAt,
        updatedAt: snapshot.updatedAt
      },
      relationships: {
        interactions: {
          links: {
            related: `/api/contacts/${snapshot.id}/interactions`
          }
        }
      }
    };
  }
}
```

### Comprehensive Linting Configuration

**ESLint Configuration (.eslintrc.js):**
```javascript
module.exports = {
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
    project: './tsconfig.json'
  },
  plugins: [
    '@typescript-eslint',
    'import',
    'security',
    'sonarjs'
  ],
  extends: [
    'eslint:recommended',
    '@typescript-eslint/recommended',
    '@typescript-eslint/recommended-requiring-type-checking',
    'plugin:import/typescript',
    'plugin:security/recommended',
    'plugin:sonarjs/recommended'
  ],
  rules: {
    // TypeScript specific rules
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/no-unused-vars': 'error',
    '@typescript-eslint/explicit-function-return-type': 'warn',
    '@typescript-eslint/no-floating-promises': 'error',
    '@typescript-eslint/await-thenable': 'error',
    '@typescript-eslint/no-misused-promises': 'error',

    // Import rules for architectural boundaries
    'import/no-restricted-paths': ['error', {
      zones: [
        // Domain cannot import from adapters
        {
          target: './src/*/domain/**',
          from: './src/*/adapters/**',
          message: 'Domain layer cannot import from adapters'
        },
        // Domain cannot import from other domains
        {
          target: './src/contacts/domain/**',
          from: './src/!(contacts)/**',
          message: 'Domain cannot import from other domains'
        },
        // Adapters can only import from their own domain
        {
          target: './src/contacts/adapters/**',
          from: './src/!(contacts|shared)/**',
          message: 'Adapters can only import from their own domain or shared'
        }
      ]
    }],

    // Security rules
    'security/detect-object-injection': 'error',
    'security/detect-non-literal-regexp': 'error',
    'security/detect-unsafe-regex': 'error',

    // Code quality rules
    'sonarjs/cognitive-complexity': ['error', 15],
    'sonarjs/no-duplicate-string': ['error', 3],
    'sonarjs/no-identical-functions': 'error',

    // General rules
    'no-console': 'warn',
    'prefer-const': 'error',
    'no-var': 'error'
  },
  overrides: [
    {
      files: ['**/*.test.ts', '**/*.spec.ts'],
      rules: {
        '@typescript-eslint/no-explicit-any': 'off',
        'sonarjs/no-duplicate-string': 'off'
      }
    }
  ]
};
```

**Prettier Configuration (.prettierrc):**
```json
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": true,
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false,
  "bracketSpacing": true,
  "arrowParens": "avoid"
}
```

## Common Anti-Patterns to Avoid

1. **Don't use `any` type** - Always define proper interfaces
2. **Don't ignore promise rejections** - Always handle async errors
3. **Don't hardcode configuration** - Use environment variables
4. **Don't expose internal errors to API responses** - Sanitize error messages
5. **Don't skip input validation** - Validate all external inputs
6. **Don't use synchronous database operations** - Use async/await
7. **Don't log sensitive information** - Sanitize logs

## Documentation Requirements

**Document all public APIs:**
```typescript
/**
 * Creates a new contact in the system
 * @param data - Contact data to create
 * @returns Promise resolving to created contact or error
 * @throws {ValidationError} When input data is invalid
 * @example
 * ```typescript
 * const result = await contactService.create({
 *   name: 'John Doe',
 *   email: 'john@example.com'
 * });
 * ```
 */
async create(data: CreateContactData): Promise<ServiceResult<Contact>>
```

**Update README.md for each major feature:**
- Installation instructions
- Configuration requirements
- API documentation
- Usage examples
- Troubleshooting guide

## Task Completion Checklist

Before marking any task as complete, ensure:

- [ ] All TypeScript types are properly defined with strict mode compliance
- [ ] Error handling is implemented with proper error types and OpenTelemetry spans
- [ ] Input validation is in place using Zod schemas
- [ ] Tests are written and passing with Jest and proper mocking
- [ ] Structured logging is implemented with correlation IDs
- [ ] OpenTelemetry instrumentation is added for tracing and metrics
- [ ] Documentation is updated including OpenAPI/Swagger generation
- [ ] Security considerations are addressed with linting rules
- [ ] Performance implications are considered with monitoring
- [ ] Code follows established hexagonal architecture patterns
- [ ] No sensitive data is logged or exposed
- [ ] ESLint rules pass including architectural boundary enforcement
- [ ] Prettier formatting is applied consistently
- [ ] Standard libraries are used instead of raw HTTP clients
- [ ] Docker compatibility is maintained (if applicable)
- [ ] Environment variables are properly configured and validated
- [ ] Health checks work in containerized environment with telemetry
- [ ] API endpoints have proper OpenAPI documentation
- [ ] Cross-cutting concerns (observability, validation) are properly injected

## Getting Help

When stuck on a task:

1. **Check the architecture document** for design decisions
2. **Review similar implementations** in the codebase
3. **Consult the task dependencies** to ensure prerequisites are met
4. **Ask specific questions** about requirements or implementation details
5. **Propose alternative approaches** if the current path seems problematic

Remember: It's better to ask for clarification than to implement something incorrectly!
