# Сервис backup: pg_dump по расписанию (образ postgres содержит pg_dump, pg_restore и tzdata).
FROM postgres:16.6-alpine
COPY backup.sh /usr/local/bin/backup.sh
# /backup создаётся здесь, чтобы именованный том унаследовал владельца postgres (uid 70).
RUN chmod 0755 /usr/local/bin/backup.sh && mkdir /backup && chown 70:70 /backup
USER 70:70
ENTRYPOINT ["/usr/local/bin/backup.sh"]
CMD ["daemon"]
