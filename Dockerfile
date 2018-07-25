FROM python:alpine
ENV FLASK_APP=fastpass.py
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY fastpass.py .
EXPOSE 5000
CMD [ "python", "-m", "flask", "run", "--host=0.0.0.0" ]
