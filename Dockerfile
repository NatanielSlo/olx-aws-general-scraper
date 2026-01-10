FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Instalacja adaptera Lambda dla Pythona
RUN pip install awslambdaric

# Kopiujemy kod
WORKDIR /var/task
COPY app/ .

# Instalujemy tylko Chromium (żeby obraz był mniejszy)
RUN playwright install chromium

# Komenda startowa dla Lambdy
ENTRYPOINT [ "/usr/bin/python", "-m", "awslambdaric" ]
CMD [ "app.handler" ]