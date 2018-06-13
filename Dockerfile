FROM python:3-onbuild
ENV FLASK_APP=fastpass.py
RUN pip install -r requirements.txt
EXPOSE 5000
CMD [ "python", "-m", "flask", "run", "--host=0.0.0.0" ]
