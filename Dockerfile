FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Instalacja adaptera Lambda i Playwrighta jako paczki pythonowej
RUN pip install awslambdaric playwright

# Kopiujemy kod do folderu roboczego Lambdy
WORKDIR /var/task
COPY app/ .

# Instalujemy przeglądarkę Chromium ORAZ jej zależności systemowe
RUN python3 -m playwright install chromium
RUN python3 -m playwright install-deps chromium

# Komenda startowa dla Lambdy
ENTRYPOINT [ "/usr/bin/python3", "-m", "awslambdaric" ]
CMD [ "app.handler" ]