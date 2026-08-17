FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY html/ /usr/share/nginx/html/

# nginx:alpine ships an unprivileged "nginx" user (uid 101)
RUN touch /var/run/nginx.pid \
 && chown -R 101:101 /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html

USER 101
EXPOSE 8080
