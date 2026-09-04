# Gatlin (Horizon) markdown briefing viewer.
# nginx serves the SPA; /data/summaries is exposed read-only via the helm chart's
# nginx config (ConfigMap-mounted default.conf). No CDN dependency: marked is vendored.
FROM nginx:1.28-alpine

# Alpine ships without tzdata; needed for the TZ=Asia/Tokyo container env
# (nginx access-log timestamps in Japan time).
RUN apk add --no-cache tzdata

# SPA assets
COPY index.html app.js styles.css /usr/share/nginx/html/
COPY vendor/marked.umd.js /usr/share/nginx/html/

# Data volume — the chart mounts the shared PVC here (readOnly: true).
VOLUME ["/data"]

EXPOSE 80
