FROM python

COPY requirements.txt /requirements.txt

RUN python -m venv venv

RUN source venv/bin/activate

RUN pip install -r requirements.txt

ADD ./Monika

WORKDIR /Monika

CMD ["python","/Monika/monika_bot.py"]
