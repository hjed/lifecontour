# Security & Performance - Lifecontour

This document covers security considerations, performance optimization strategies, and operational best practices for the Python FastAPI backend with Next.js frontend.

## Security Considerations

### Authentication & Authorization

#### OAuth 2.0 Implementation (OAuth-Only Architecture)
- **No Password Storage**: Eliminates password-based authentication entirely for enhanced security
- **Configurable Providers**: Support for generic OAuth2 providers
- **PKCE Flow**: OAuth 2.0 with PKCE flow for enhanced security across all providers
- **Scope Management**: Minimal required scopes for each OAuth provider
- **Token Management**: Secure storage and automatic refresh of OAuth access tokens
- **Session Security**: Session-based authentication post-OAuth login with secure cookies

#### API Security
- **API Key Authentication**: Secure API key generation and rotation for MCP
- **Role-Based Access Control**: Granular permissions for different user roles
- **Request Validation**: Comprehensive input validation using Pydantic models
- **Rate Limiting**: Configurable rate limits per endpoint and user

#### Session Management (Python Backend)
```python
# OAuth2 Configuration with Authlib
from authlib.integrations.fastapi_oauth2 import OAuth2
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from fastapi import Depends, HTTPException, status, Request

# OAuth2 provider configuration
OAUTH_PROVIDERS = {
    "github": {
        "client_id": "your_github_client_id",
        "client_secret": "your_github_client_secret",
        "server_metadata_url": "https://github.com/.well-known/oauth_authorization_server",
        "client_kwargs": {"scope": "user:email"}
    },
    "microsoft": {
        "client_id": "your_microsoft_client_id",
        "client_secret": "your_microsoft_client_secret",
        "server_metadata_url": "https://login.microsoftonline.com/common/v2.0/.well-known/openid_configuration",
        "client_kwargs": {"scope": "openid email profile"}
    }
}

# Session-based authentication (post-OAuth)
async def get_current_user(request: Request):
    """Get current user from session (post-OAuth login)."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id

async def get_current_user_optional(request: Request):
    """Get current user from session, return None if not authenticated."""
    return request.session.get("user_id")
```

### Data Protection

#### Encryption at Rest
- **Database Encryption**: PostgreSQL encryption with encrypted volumes
- **File System**: Encrypted volumes for database and log files
- **Backup Encryption**: Encrypted PostgreSQL backups with separate key management
- **Key Management**: Secure key storage and rotation procedures

#### Encryption in Transit
- **HTTPS Enforcement**: TLS 1.2+ for all communications
- **Certificate Management**: Automated certificate renewal with Let's Encrypt
- **API Communications**: Encrypted connections to external APIs
- **Internal Communications**: TLS for container-to-container communication

#### Input Validation and Sanitization (Python Backend)
```python
# Pydantic validation models
from pydantic import BaseModel, validator, EmailStr
import re

class ContactCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    notes: Optional[str] = None

    @validator('name')
    def validate_name(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Name is required')
        if len(v) > 255:
            raise ValueError('Name too long')
        return v.strip()

    @validator('phone')
    def validate_phone(cls, v):
        if v and not re.match(r'^\+?[\d\s\-\(\)]+$', v):
            raise ValueError('Invalid phone format')
        return v

    @validator('notes')
    def validate_notes(cls, v):
        if v and len(v) > 10000:
            raise ValueError('Notes too long')
        return v

# SQL injection prevention (using parameterized queries)
from sqlalchemy import text

# ✅ Safe - parameterized query
query = text("SELECT * FROM contacts WHERE name = :name")
result = await conn.execute(query, {"name": user_input})
```

#### XSS Protection
- **Content Security Policy**: Strict CSP headers to prevent XSS attacks
- **Output Encoding**: Proper encoding of user-generated content
- **DOM Sanitization**: Client-side sanitization of rich text content
- **Template Security**: Secure templating with automatic escaping

### Privacy and Compliance

#### Data Minimization
- **Local Storage**: PostgreSQL database for controlled data exposure
- **Selective Sync**: User control over which data syncs with external services
- **Data Retention**: Configurable retention policies for different data types
- **Audit Logging**: Comprehensive audit trail for data access and modifications

#### Access Controls (Python Backend)
```python
# Permission-based access control
from enum import Enum
from typing import List

class Permission(Enum):
    READ_CONTACTS = "read:contacts"
    WRITE_CONTACTS = "write:contacts"
    READ_JOURNAL = "read:journal"
    WRITE_JOURNAL = "write:journal"
    ADMIN_SYSTEM = "admin:system"

class User:
    def __init__(self, user_id: str, permissions: List[Permission]):
        self.user_id = user_id
        self.permissions = permissions

def check_permission(user: User, required_permission: Permission) -> bool:
    """Check if user has required permission."""
    return required_permission in user.permissions

# FastAPI dependency for permission checking
from fastapi import Depends, HTTPException, status

def require_permission(permission: Permission):
    """Decorator to require specific permission for endpoint."""
    def permission_checker(current_user: User = Depends(get_current_user)):
        if not check_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {permission.value} required"
            )
        return current_user
    return permission_checker
```

## Performance Considerations

### Database Optimization

#### Query Performance
- **Indexing Strategy**: Comprehensive indexing for frequently queried columns
- **Query Optimization**: Use of EXPLAIN ANALYZE for PostgreSQL performance analysis
- **Prepared Statements**: Parameterized queries for better performance and security
- **Connection Pooling**: Efficient database connection management

#### PostgreSQL Optimization
```sql
-- Performance configuration
-- postgresql.conf settings
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
```

#### Query Patterns (Python)
```python
# Efficient pagination
from sqlalchemy import text

async def get_contacts_paginated(conn, page: int, limit: int):
    offset = (page - 1) * limit
    query = text("""
        SELECT id, name, email, phone, created_at, updated_at
        FROM contacts
        ORDER BY name
        LIMIT :limit OFFSET :offset
    """)
    result = await conn.execute(query, {"limit": limit, "offset": offset})
    return result.fetchall()

# Optimized search with PostgreSQL full-text search
async def search_contacts(conn, search_query: str):
    query = text("""
        SELECT id, name, email, phone,
               ts_rank(search_vector, plainto_tsquery(:query)) as rank
        FROM contacts
        WHERE search_vector @@ plainto_tsquery(:query)
        ORDER BY rank DESC
    """)
    result = await conn.execute(query, {"query": search_query})
    return result.fetchall()
```

### Caching Strategy

#### Application-Level Caching
- **In-Memory Cache**: Redis or Python dict for frequently accessed data
- **Cache Invalidation**: Event-driven cache invalidation on data changes
- **Cache Warming**: Proactive cache population for critical data
- **Cache Metrics**: Monitoring cache hit rates and performance

#### HTTP Caching (FastAPI)
```python
# Cache headers for static content
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Static files with caching
app.mount("/static", StaticFiles(directory="static"), name="static")

# API response caching with custom headers
@app.get("/api/contacts")
async def get_contacts(response: Response):
    # Set cache headers
    response.headers["Cache-Control"] = "public, max-age=300"  # 5 minutes
    response.headers["ETag"] = generate_etag(contacts_data)

    return contacts_data

# Simple in-memory cache
from functools import lru_cache
from typing import List

@lru_cache(maxsize=128)
async def get_cached_contacts() -> List[dict]:
    """Cache frequently accessed contact data."""
    return await fetch_contacts_from_db()
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

#### Resource Optimization (Python)
```python
# Memory management
import psutil
import gc
import logging

logger = logging.getLogger(__name__)

def monitor_memory():
    """Monitor memory usage and trigger cleanup if needed."""
    memory = psutil.virtual_memory()
    if memory.percent > 80:  # 80% threshold
        logger.warning(f"High memory usage detected: {memory.percent}%")
        # Trigger garbage collection
        gc.collect()

    return {
        "memory_percent": memory.percent,
        "available_mb": memory.available // 1024 // 1024
    }

# Background task for monitoring
import asyncio

async def memory_monitor_task():
    """Background task to monitor system resources."""
    while True:
        monitor_memory()
        await asyncio.sleep(60)  # Check every minute
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

#### External Service Integration (Python)
```python
# Optimized Google API client
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import requests
import asyncio

class GoogleAPIClient:
    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self.session = requests.Session()

    async def batch_requests(self, requests_data: list):
        """Batch multiple API requests for efficiency."""
        tasks = []
        for request_data in requests_data:
            task = asyncio.create_task(self._make_request(request_data))
            tasks.append(task)

        return await asyncio.gather(*tasks)

    async def _make_request(self, request_data: dict):
        """Make individual API request with retry logic."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(
                    request_data['url'],
                    headers={'Authorization': f'Bearer {self.credentials.token}'},
                    timeout=30
                )
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

#### Image and Media Optimization
- **Thumbnail Generation**: Automatic thumbnail creation for photos
- **Image Compression**: Optimized image formats and compression
- **Lazy Loading**: Progressive loading of images and media
- **CDN Integration**: Content delivery network for static assets

## Monitoring and Alerting

### Performance Metrics (Python)
```python
# Custom performance metrics with logging
import time
import logging
from functools import wraps
from typing import Dict, Any

logger = logging.getLogger(__name__)

class PerformanceMetrics:
    def __init__(self):
        self.metrics = {
            "api_response_times": [],
            "database_query_times": [],
            "active_connections": 0
        }

    def record_api_response_time(self, method: str, route: str, duration: float, status: int):
        """Record API response time."""
        self.metrics["api_response_times"].append({
            "method": method,
            "route": route,
            "duration": duration,
            "status": status,
            "timestamp": time.time()
        })
        logger.info(f"API {method} {route} - {duration:.3f}s - {status}")

    def record_db_query_time(self, operation: str, table: str, duration: float):
        """Record database query time."""
        self.metrics["database_query_times"].append({
            "operation": operation,
            "table": table,
            "duration": duration,
            "timestamp": time.time()
        })
        logger.debug(f"DB {operation} {table} - {duration:.3f}s")

# Performance monitoring decorator
def monitor_performance(operation_type: str = "api"):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(f"{operation_type} {func.__name__} completed in {duration:.3f}s")
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"{operation_type} {func.__name__} failed after {duration:.3f}s: {e}")
                raise
        return wrapper
    return decorator
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

### Container Security (Python Backend)
```dockerfile
# Security-focused Dockerfile additions
FROM python:3.14.5-slim

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser

# Remove unnecessary packages
RUN apt-get update && apt-get remove -y wget curl && \
    apt-get autoremove -y && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set secure file permissions
COPY --chown=appuser:appuser . .
RUN chmod -R 755 /app && \
    chmod -R 644 /app/app

# Switch to non-root user
USER appuser

# Security scanning
LABEL security.scan="enabled"
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
