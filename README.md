# backend
![Build](https://github.com/noharm-ai/backend/workflows/Build/badge.svg)
[![Issues](https://img.shields.io/github/issues-raw/tterb/PlayMusic.svg?maxAge=25000)](https://github.com/noharm-ai/backend/issues)  
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Maintainability](https://api.codeclimate.com/v1/badges/a2baa2e03c1661cd70cd/maintainability)](https://codeclimate.com/github/noharm-ai/backend/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/a2baa2e03c1661cd70cd/test_coverage)](https://codeclimate.com/github/noharm-ai/backend/test_coverage)

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
