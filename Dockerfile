# Baseimage
FROM python:3.12.10-slim-bookworm

# Update Packages
RUN apt update
RUN apt upgrade -y
RUN pip install --upgrade pip
# install git
RUN apt-get install build-essential -y


RUN mkdir /crew-cost-ledger

# Install requirements
COPY ./requirements.txt /crew-cost-ledger/requirements.txt
WORKDIR /crew-cost-ledger
RUN pip install -r requirements.txt

# Copy crew-cost-ledger
COPY ./ /crew-cost-ledger/

# Run app
CMD ["streamlit","run","./app/app.py","--server.headless","true"]
EXPOSE 8501
