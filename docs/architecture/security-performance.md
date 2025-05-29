# Security & Performance - Personal CRM & Journal System

This document covers security considerations, performance optimization strategies, and operational best practices for the Personal CRM & Journal System.

## Security Considerations

### Authentication & Authorization

#### OAuth 2.0 Implementation
- **Google Services**: OAuth 2.0 with PKCE flow for enhanced security
- **Scope Management**: Minimal required scopes for Google APIs
- **Token Management**: Secure storage and automatic refresh of access tokens
- **Session Security**: JWT tokens with short expiration and refresh token rotation

#### API Security
- **API Key Authentication**: Secure API key generation and rotation for MCP
- **Role-Based Access Control**: Granular permissions for different user roles
- **Request Validation**: Comprehensive input validation using Zod schemas
- **Rate Limiting**: Configurable rate limits per endpoint and user

#### Session Management
```typescript
// JWT Configuration
const jwtConfig = {
  accessTokenExpiry: '15m',
  refreshTokenExpiry: '7d',
  algorithm: 'HS256',
  issuer: 'personal-crm',
  audience: 'personal-crm-users'
};

// Secure cookie settings
const cookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'strict' as const,
  maxAge: 7 * 24 * 60 * 60 * 1000 // 7 days
};
```

### Data Protection

#### Encryption at Rest
- **Database Encryption**: SQLite encryption using SQLCipher for sensitive data
- **File System**: Encrypted volumes for database and log files
- **Backup Encryption**: Encrypted backups with separate key management
- **Key Management**: Secure key storage and rotation procedures

#### Encryption in Transit
- **HTTPS Enforcement**: TLS 1.2+ for all communications
- **Certificate Management**: Automated certificate renewal with Let's Encrypt
- **API Communications**: Encrypted connections to external APIs
- **Internal Communications**: TLS for container-to-container communication

#### Input Validation and Sanitization
```typescript
// Input validation schema
const contactSchema = z.object({
  name: z.string().min(1).max(255).trim(),
  email: z.string().email().optional(),
  phone: z.string().regex(/^\+?[\d\s\-\(\)]+$/).optional(),
  notes: z.string().max(10000).optional()
});

// SQL injection prevention
const sanitizeInput = (input: string): string => {
  return input.replace(/[<>\"'%;()&+]/g, '');
};
```

#### XSS Protection
- **Content Security Policy**: Strict CSP headers to prevent XSS attacks
- **Output Encoding**: Proper encoding of user-generated content
- **DOM Sanitization**: Client-side sanitization of rich text content
- **Template Security**: Secure templating with automatic escaping

### Privacy and Compliance

#### Data Minimization
- **Local Storage**: SQLite database for minimal external data exposure
- **Selective Sync**: User control over which data syncs with external services
- **Data Retention**: Configurable retention policies for different data types
- **Audit Logging**: Comprehensive audit trail for data access and modifications

#### Access Controls
```typescript
// Permission-based access control
enum Permission {
  READ_CONTACTS = 'read:contacts',
  WRITE_CONTACTS = 'write:contacts',
  READ_JOURNAL = 'read:journal',
  WRITE_JOURNAL = 'write:journal',
  ADMIN_SYSTEM = 'admin:system'
}

const checkPermission = (user: User, permission: Permission): boolean => {
  return user.permissions.includes(permission);
};
```

## Performance Considerations

### Database Optimization

#### Query Performance
- **Indexing Strategy**: Comprehensive indexing for frequently queried columns
- **Query Optimization**: Use of EXPLAIN QUERY PLAN for performance analysis
- **Prepared Statements**: Parameterized queries for better performance and security
- **Connection Pooling**: Efficient database connection management

#### SQLite Optimization
```sql
-- Performance pragmas
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = 10000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456; -- 256MB
```

#### Query Patterns
```typescript
// Efficient pagination
const getContactsPaginated = async (page: number, limit: number) => {
  const offset = (page - 1) * limit;
  return db.select()
    .from(contacts)
    .limit(limit)
    .offset(offset)
    .orderBy(contacts.name);
};

// Optimized search with FTS
const searchContacts = async (query: string) => {
  return db.select()
    .from(contacts)
    .innerJoin(contactsFts, eq(contacts.id, contactsFts.rowid))
    .where(sql`contacts_fts MATCH ${query}`);
};
```

### Caching Strategy

#### Application-Level Caching
- **In-Memory Cache**: Redis or Node.js Map for frequently accessed data
- **Cache Invalidation**: Event-driven cache invalidation on data changes
- **Cache Warming**: Proactive cache population for critical data
- **Cache Metrics**: Monitoring cache hit rates and performance

#### HTTP Caching
```typescript
// Cache headers for static content
app.use('/static', express.static('public', {
  maxAge: '1y',
  etag: true,
  lastModified: true
}));

// API response caching
app.get('/api/contacts', cache('5 minutes'), getContacts);
```

#### Browser Caching
- **Static Assets**: Long-term caching with versioning
- **API Responses**: Appropriate cache headers for different data types
- **Service Worker**: Offline functionality with cached responses
- **Local Storage**: Client-side caching of user preferences

### Scalability Planning

#### Horizontal Scaling
- **Stateless Design**: Stateless application servers for easy scaling
- **Load Balancing**: Nginx load balancing across multiple instances
- **Session Storage**: External session storage for multi-instance deployments
- **Database Scaling**: Read replicas and connection pooling strategies

#### Resource Optimization
```typescript
// Memory management
const memoryMonitor = () => {
  const usage = process.memoryUsage();
  if (usage.heapUsed > 500 * 1024 * 1024) { // 500MB threshold
    logger.warn('High memory usage detected', { usage });
    // Trigger garbage collection or cleanup
    global.gc?.();
  }
};

setInterval(memoryMonitor, 60000); // Check every minute
```

#### Performance Monitoring
- **Response Time Tracking**: Monitoring API response times
- **Database Performance**: Query execution time monitoring
- **Memory Usage**: Heap usage and garbage collection monitoring
- **CPU Utilization**: Process CPU usage tracking

### Network Performance

#### API Optimization
- **Response Compression**: Gzip compression for API responses
- **Payload Optimization**: Minimal response payloads with field selection
- **Batch Operations**: Bulk operations to reduce API calls
- **Connection Reuse**: HTTP keep-alive for external API calls

#### External Service Integration
```typescript
// Optimized Google API client
const googleClient = new google.auth.OAuth2({
  clientId: config.google.clientId,
  clientSecret: config.google.clientSecret
});

// Request batching for Google APIs
const batchRequests = async (requests: any[]) => {
  const batch = google.batch({
    auth: googleClient
  });

  requests.forEach(request => batch.add(request));
  return batch.exec();
};
```

#### Image and Media Optimization
- **Thumbnail Generation**: Automatic thumbnail creation for photos
- **Image Compression**: Optimized image formats and compression
- **Lazy Loading**: Progressive loading of images and media
- **CDN Integration**: Content delivery network for static assets

## Monitoring and Alerting

### Performance Metrics
```typescript
// Custom performance metrics
const performanceMetrics = {
  apiResponseTime: new Histogram({
    name: 'api_response_time_seconds',
    help: 'API response time in seconds',
    labelNames: ['method', 'route', 'status']
  }),

  databaseQueryTime: new Histogram({
    name: 'database_query_time_seconds',
    help: 'Database query execution time',
    labelNames: ['operation', 'table']
  }),

  activeConnections: new Gauge({
    name: 'active_database_connections',
    help: 'Number of active database connections'
  })
};
```

### Health Monitoring
- **Application Health**: Comprehensive health checks for all components
- **Database Health**: Connection status and query performance monitoring
- **External Service Health**: Monitoring of Google and Immich API availability
- **Resource Health**: Memory, CPU, and disk usage monitoring

### Alerting Strategy
- **Critical Alerts**: Database failures, authentication issues, data corruption
- **Warning Alerts**: High resource usage, slow response times, sync failures
- **Performance Alerts**: Response time degradation, high error rates
- **Security Alerts**: Failed authentication attempts, suspicious activity

## Security Hardening

### Container Security
```dockerfile
# Security-focused Dockerfile additions
FROM node:24-alpine

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001

# Remove unnecessary packages
RUN apk del --purge wget curl

# Set secure file permissions
COPY --chown=nextjs:nodejs . .
RUN chmod -R 755 /app && \
    chmod -R 644 /app/src

USER nextjs
```

### Network Security
- **Firewall Rules**: Restrictive firewall configuration
- **VPN Access**: VPN-only access for administrative functions
- **Network Segmentation**: Isolated networks for different components
- **DDoS Protection**: Rate limiting and traffic analysis

### Operational Security
- **Regular Updates**: Automated security updates for dependencies
- **Vulnerability Scanning**: Regular security scans of containers and code
- **Access Logging**: Comprehensive logging of all access attempts
- **Incident Response**: Documented procedures for security incidents

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Technology Stack](./technology-stack.md) - Security and performance technologies
- [Deployment Guide](./deployment-guide.md) - Production security and monitoring setup
- [Database Design](./database-design.md) - Database security and performance optimization
