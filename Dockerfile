FROM python:alpine
ENV FLASK_APP=fastpass.py
ADD requirements.txt .
RUN pip install -r requirements.txt
ADD fastpass.py .
ADD youtube.py .
ADD slack.py .
ADD .git ./.git
EXPOSE 5000
CMD [ "python", "-m", "flask", "run", "--host=0.0.0.0" ]
