# Nginx Dockerfile
FROM nginx:1.31.6-alpine

# Copy nginx configuration
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf

# Create SSL directory and set permissions
RUN mkdir -p /etc/nginx/ssl \
    && chown -R nginx:nginx /var/cache/nginx \
    && chown -R nginx:nginx /var/log/nginx \
    && chown -R nginx:nginx /etc/nginx/conf.d

# Copy SSL certificates (if available)
# COPY docker/nginx/ssl/ /etc/nginx/ssl/

# Switch to non-root user
USER nginx

# Expose ports
EXPOSE 80 443

# Copy scripts
COPY docker/nginx/start.sh /start.sh
COPY docker/nginx/healthcheck.sh /healthcheck.sh
RUN chmod +x /start.sh /healthcheck.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD ["/healthcheck.sh"]
CMD ["/start.sh"]
