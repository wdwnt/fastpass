FROM python:alpine
ENV FLASK_APP=fastpass.py
COPY fastpass.py .
COPY requirements.txt .
RUN pip install -r requirements.txt
EXPOSE 5000
CMD [ "python", "-m", "flask", "run", "--host=0.0.0.0" ]
