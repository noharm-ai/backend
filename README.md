# mobile-api
[![Build Status](https://travis-ci.org/noharm-ai/backend.svg?branch=master)](https://travis-ci.org/noharm-ai/backend)

Api for Mobile App

### 1. Install

```
$ python3 -m venv env
$ source env/bin/activate
$ pip3 install -r requirements.txt
```

### 2. Test your Env

```
$ python3 mobile.py
$ curl -X POST -d '{"email":"teste", "password":"1234"}' -H "Content-Type: application/json"  http://127.0.0.1:5000/authenticate
$ curl -X GET http://127.0.0.1:5000/getName/1234
```

### Troubleshooting Tips

For error such as:

- "cannot find -lssl; cannot find -lcrypto” when installing mysql-python?"
- "mysql_config: not found"
- "invalid command 'bdist_wheel'"

```
$ sudo apt install libmysqlclient-dev
$ sudo apt install libssl-dev
$ pip3 install wheel
```

For error such as:

- "ModuleNotFoundError: No module named 'psycopg2'"

```
$ sudo apt install libpq-dev
$ pip install psycopg2
```
