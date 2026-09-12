FROM python:3.12-alpine
WORKDIR /app
COPY tracker.py /app/tracker.py
RUN addgroup -g 10001 -S tracker && adduser -u 10001 -S tracker -G tracker && mkdir -p /data && chown -R tracker:tracker /app /data
USER tracker
ENV TRACKER_DB_PATH=/data/tracker.db
EXPOSE 8080
CMD ["python", "/app/tracker.py"]