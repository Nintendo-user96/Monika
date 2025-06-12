FROM python

COPY requirements.txt /requirements.txt

RUN pip install -r requirements.txt

RUN python -m venv venv

ADD ./Monika

WORKDIR /Monika

CMD ["python","/Monika/monika_bot.py"]
