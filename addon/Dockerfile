ARG BUILD_FROM
FROM ${BUILD_FROM}

# Mehr als Python braucht der Dienst nicht: Socket, HTTP und JSON sind in der
# Standardbibliothek. Keine Abhaengigkeit, die spaeter bricht.
RUN apk add --no-cache python3

COPY rika_gsm.py /opt/rika_gsm.py
CMD ["python3", "-u", "/opt/rika_gsm.py"]
