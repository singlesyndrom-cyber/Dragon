# SSH-туннель до зарубежного сервера: SOCKS5 на :1080 внутри docker-сети, только для бота.
FROM alpine:3.20
RUN apk add --no-cache openssh-client
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 1080
ENTRYPOINT ["/entrypoint.sh"]
