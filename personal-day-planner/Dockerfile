FROM python:3.12-alpine
WORKDIR /app
COPY planner.py /app/planner.py
RUN addgroup -g 10002 -S planner && adduser -u 10002 -S planner -G planner
USER planner
EXPOSE 8080
CMD ["python", "/app/planner.py"]
