FROM python

COPY requirements.txt /requirements.txt

RUN pip install -r requirements.txt

ADD . /Monika

WORKDIR /Monika

CMD ["python","-m venv venv"]

CMD ["python","/Monika/monika_bot.py"]
