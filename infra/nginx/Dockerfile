# Build the Cortex edge proxy image with host-based surface routing.

FROM nginx:1.27-alpine

RUN apk add --no-cache gettext

COPY infra/nginx/edge.conf.template /etc/nginx/templates/edge.conf.template
COPY infra/nginx/edge.external-query.conf.template /etc/nginx/templates/edge.external-query.conf.template

ENV CORTEX_EDGE_TEMPLATE_PATH=/etc/nginx/templates/edge.conf.template

CMD ["/bin/sh", "-c", "envsubst '$$CORTEX_CONSOLE_HOST $$CORTEX_QUERY_HOST' < ${CORTEX_EDGE_TEMPLATE_PATH} > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
