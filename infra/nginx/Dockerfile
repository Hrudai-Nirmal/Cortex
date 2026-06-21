# Build the Cortex edge proxy image with host-based surface routing.

FROM nginx:1.27-alpine

RUN apk add --no-cache gettext

COPY infra/nginx/edge.conf.template /etc/nginx/templates/edge.conf.template

CMD ["/bin/sh", "-c", "envsubst '$$CORTEX_CONSOLE_HOST $$CORTEX_QUERY_HOST' < /etc/nginx/templates/edge.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
