# API Patterns - REST and MCP Implementation

This document provides detailed examples for implementing REST APIs and MCP tools.

## REST API with JSON API Compliance

### Contact Controller

```typescript
// api/rest/contacts/ContactController.ts
import { Controller, Get, Post, Route, Tags, Body, Path } from 'tsoa';
import { trace } from '@opentelemetry/api';

interface CreateContactRequest {
  name: string;
  email?: string;
  phone?: string;
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
      links: { related: string; };
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

  @Post()
  public async createContact(
    @Body() requestBody: CreateContactRequest
  ): Promise<ContactResponse> {
    return this.tracer.startActiveSpan('api.contacts.create', async (span) => {
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

  @Get('{contactId}')
  public async getContact(@Path() contactId: string): Promise<ContactResponse> {
    const contact = await this.contactService.getContact(ContactId.create(contactId));

    if (!contact) {
      this.setStatus(404);
      throw new Error('Contact not found');
    }

    return this.serializeContact(contact);
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

## Input Validation with Zod

```typescript
// api/rest/shared/validation.ts
import { z } from 'zod';

export const CreateContactSchema = z.object({
  name: z.string().min(1, 'Name is required').max(255),
  email: z.string().email('Invalid email address').optional(),
  phone: z.string().optional(),
  tags: z.array(z.string()).default([])
});

export const UpdateContactSchema = CreateContactSchema.partial().extend({
  id: z.string().uuid()
});

// Middleware for validation
export function validateRequest<T>(schema: z.ZodSchema<T>) {
  return (req: Request, res: Response, next: NextFunction) => {
    const validation = schema.safeParse(req.body);
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
    req.body = validation.data;
    next();
  };
}
```

## Nginx Proxy Middleware

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

export const corsOptions = {
  origin: (origin: string | undefined, callback: Function) => {
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

## MCP Tool Implementation

### Contact Search Tool

```typescript
// api/mcp/contacts/ContactSearchTool.ts
interface McpTool {
  name: string;
  description: string;
  inputSchema: object;
  handler: (params: any) => Promise<any>;
}

export const searchContactsTool: McpTool = {
  name: 'search_contacts',
  description: 'Search contacts by name, email, or tags with AI-friendly responses',
  inputSchema: {
    type: 'object',
    properties: {
      query: {
        type: 'string',
        description: 'Search query for contact name or email'
      },
      tags: {
        type: 'array',
        items: { type: 'string' },
        description: 'Filter by specific tags'
      },
      limit: {
        type: 'number',
        default: 10,
        description: 'Maximum number of results to return'
      }
    },
    required: ['query']
  },
  handler: async (params) => {
    const { query, tags = [], limit = 10 } = params;

    const searchCriteria = ContactSearchCriteria.create({
      query,
      tags,
      limit
    });

    const contacts = await contactService.searchContacts(searchCriteria);

    // AI-friendly response with context and summaries
    return {
      contacts: contacts.map(contact => ({
        id: contact.id,
        name: contact.name,
        email: contact.email,
        phone: contact.phone,
        company: contact.company,
        tags: contact.tags,
        lastInteraction: contact.lastInteraction,
        relationshipStrength: calculateRelationshipStrength(contact),
        summary: generateContactSummary(contact)
      })),
      totalFound: contacts.length,
      searchContext: `Found ${contacts.length} contacts matching "${query}"`,
      suggestions: generateSearchSuggestions(query, contacts)
    };
  }
};
```

### MCP Server Setup

```typescript
// api/mcp/server.ts
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHttpTransport } from '@modelcontextprotocol/sdk/server/http.js';
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const server = new Server(
  {
    name: 'personal-crm-server',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Register tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      searchContactsTool,
      createContactTool,
      getContactInteractionsTool,
      syncGoogleContactsTool
    ].map(tool => ({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.inputSchema
    }))
  };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  const tool = tools.find(t => t.name === name);
  if (!tool) {
    throw new Error(`Unknown tool: ${name}`);
  }

  try {
    const result = await tool.handler(args);
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }
      ]
    };
  } catch (error) {
    throw new Error(`Tool execution failed: ${error.message}`);
  }
});

// Start HTTP server
const transport = new StreamableHttpTransport({
  port: process.env.MCP_PORT || 3001,
  host: process.env.MCP_HOST || 'localhost'
});

await server.connect(transport);
console.log('MCP server running on HTTP transport');
```

## Error Response Formatting

```typescript
// api/rest/shared/error-handler.ts
export interface JsonApiError {
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

export function formatValidationError(zodError: z.ZodError): JsonApiError {
  return {
    errors: zodError.errors.map(err => ({
      status: '400',
      title: 'Validation Error',
      detail: err.message,
      source: { pointer: `/data/attributes/${err.path.join('/')}` }
    }))
  };
}

export function formatDomainError(error: Error): JsonApiError {
  if (error instanceof DuplicateContactError) {
    return {
      errors: [{
        status: '409',
        title: 'Conflict',
        detail: error.message
      }]
    };
  }

  return {
    errors: [{
      status: '500',
      title: 'Internal Server Error',
      detail: 'An unexpected error occurred'
    }]
  };
}
```

## Pagination Implementation

```typescript
// api/rest/shared/pagination.ts
interface PaginationParams {
  page: number;
  limit: number;
}

interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    limit: number;
    totalPages: number;
  };
  links: {
    self: string;
    first: string;
    last: string;
    prev?: string;
    next?: string;
  };
}

export function createPaginatedResponse<T>(
  data: T[],
  total: number,
  params: PaginationParams,
  baseUrl: string
): PaginatedResponse<T> {
  const totalPages = Math.ceil(total / params.limit);

  return {
    data,
    meta: {
      total,
      page: params.page,
      limit: params.limit,
      totalPages
    },
    links: {
      self: `${baseUrl}?page=${params.page}&limit=${params.limit}`,
      first: `${baseUrl}?page=1&limit=${params.limit}`,
      last: `${baseUrl}?page=${totalPages}&limit=${params.limit}`,
      prev: params.page > 1 ? `${baseUrl}?page=${params.page - 1}&limit=${params.limit}` : undefined,
      next: params.page < totalPages ? `${baseUrl}?page=${params.page + 1}&limit=${params.limit}` : undefined
    }
  };
}
```
