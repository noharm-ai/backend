# mobile-api
Api for Mobile App

### 1. Install
```
python3 -m venv env
source env/bin/activate
pip3 install -r requirements.txt
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
