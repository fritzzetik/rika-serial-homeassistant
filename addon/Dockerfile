ARG BUILD_FROM
FROM ${BUILD_FROM}

# Python only: socket, HTTP and JSON are in the standard library.
# No dependency that can break later.
RUN apk add --no-cache python3

COPY rika_gsm.py /opt/rika_gsm.py
CMD ["python3", "-u", "/opt/rika_gsm.py"]
