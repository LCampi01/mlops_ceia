FROM apache/airflow:3.0.2

USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
         git \
  && apt-get autoremove -yqq --purge \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements.txt /requirements.txt

RUN pip install --upgrade pip

RUN pip uninstall -y apache-airflow-providers-google apache-airflow-providers-snowflake \
    snowflake-sqlalchemy snowflake-connector-python
RUN pip install --no-cache-dir apache-airflow[virtualenv]==3.0.2 -r /requirements.txt
RUN pip check
