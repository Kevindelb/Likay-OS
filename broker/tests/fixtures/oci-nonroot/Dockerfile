FROM python:3.12-alpine
RUN adduser -D -u 1000 nonroot
COPY src/app.py /app/app.py
USER nonroot
EXPOSE 8000
CMD ["python3", "/app/app.py"]
